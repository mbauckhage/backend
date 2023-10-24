import time
import os
import argparse
import pandas as pd
from ebike_city_tools.optimize.utils import make_fake_od, output_to_dataframe, flow_to_df
from ebike_city_tools.optimize.linear_program import define_IP
from ebike_city_tools.utils import lane_to_street_graph, extend_od_circular, output_lane_graph, filter_by_attribute
from ebike_city_tools.optimize.round_simple import pareto_frontier, rounding_and_splitting
from ebike_city_tools.iterative_algorithms import betweenness_pareto, topdown_betweenness_pareto
from ebike_city_tools.optimize.wrapper import adapt_edge_attributes
import numpy as np
import geopandas as gpd
import networkx as nx
from snman import distribution, street_graph, graph_utils, io, merge_edges, lane_graph
from snman.constants import *

FLOW_CONSTANT = 1  # how much flow to send through a path
algorithm_dict = {
    "betweenness_topdown": (topdown_betweenness_pareto, {}),
    "betweenness_cartime": (betweenness_pareto, {"betweenness_attr": "car_time"}),
    "betweenness_biketime": (betweenness_pareto, {"betweenness_attr": "bike_time"}),
}


def deprecated_table_to_graph(
    edge_table, node_table=None, edge_attributes={"width_total_m": "capacity"}, node_attributes={"geometry": "location"}
):
    """
    DEPRECATED
    edge_table: pd.DataFrame with columns u, v, and the required edge attributes
    node_table (Optional): table with the node id as the index column and the edge id as the
    edge_attributes: Dictionary of the form {columns-name-in-table : desired-attribute_name-in-graph}
    node_attributes: Dictionary of the form {columns-name-in-table : desired-attribute_name-in-graph}
    """
    # init graph
    G = nx.DiGraph()

    # add edge list
    edge_list = []
    for row_ind, edge_row in edge_table.iterrows():
        # extract the edge attributes
        edge_attr = {attr_name: edge_row[col_name] for col_name, attr_name in edge_attributes.items()}
        # add edge with attributes to the list
        edge_list.append([edge_row["u"], edge_row["v"], edge_attr])
        edge_attr["gradient"] = -edge_attr["gradient"]
        edge_list.append([edge_row["v"], edge_row["u"], edge_attr])
    G.add_edges_from(edge_list)

    # set node attributes
    node_attrs = {}
    for row_ind, node_row in node_table.iterrows():
        node_attrs[row_ind] = {attr_name: node_row[col_name] for col_name, attr_name in node_attributes.items()}
    nx.set_node_attributes(G, node_attrs)
    return G


def deprecated_load_graph(path):
    # load nodes and edges
    nodes = gpd.read_file(os.path.join(path, "nodes_all_attributes.gpkg")).set_index("osmid")
    edges = gpd.read_file(os.path.join(path, "edges_all_attributes.gpkg"))
    edges = edges[["u", "v", "width_total_m", "maxspeed", "lanes", "length"]]
    # remove the ones with start and end at the same point
    edges = edges[edges["u"] != edges["v"]]
    # there are many 1.8 and 0.9 wide streets -> transform into 1 and 2 lane streets
    edges["width_total_m"] = edges["width_total_m"].round()  # TODO
    # fill nans of the capacity with 1
    # edges["lanes"] = edges["lanes"].fillna(1)

    # compute gradient
    gradient = []
    for i in range(len(edges)):
        gradient.append(
            100 * (nodes["elevation"][edges.iloc[i, 1]] - nodes["elevation"][edges.iloc[i, 0]]) / edges.iloc[i, 5]
        )
    edges["gradient"] = gradient

    # construct graph
    G = deprecated_table_to_graph(
        edges, nodes, {"width_total_m": "capacity", "length": "distance", "gradient": "gradient"}
    )
    return G


def generate_motorized_lane_graph(
    edge_path,
    node_path,
    source_lanes_attribute=KEY_LANES_DESCRIPTION,
    target_lanes_attribute=KEY_LANES_DESCRIPTION_AFTER,
    return_H=False,
):
    G = io.load_street_graph(edge_path, node_path)  # initialize lanes after rebuild
    # need to save the maxspeed attribute here to use it later
    maxspeed = nx.get_edge_attributes(G, "maxspeed")
    nx.set_edge_attributes(G, nx.get_edge_attributes(G, source_lanes_attribute), target_lanes_attribute)
    # ensure consistent edge directions
    street_graph.organize_edge_directions(G)

    distribution.set_given_lanes(G)
    H = street_graph.filter_lanes_by_modes(G, {MODE_PRIVATE_CARS}, lane_description_key=KEY_GIVEN_LANES_DESCRIPTION)

    merge_edges.reset_intermediate_nodes(H)
    merge_edges.merge_consecutive_edges(H, distinction_attributes={KEY_LANES_DESCRIPTION_AFTER})
    # make lane graph
    L = lane_graph.create_lane_graph(H, KEY_GIVEN_LANES_DESCRIPTION)
    # make sure that the graph is strongly connected
    L = graph_utils.keep_only_the_largest_connected_component(L)
    # add some edge attributes that we need for the optimization (e.g. slope)
    L = adapt_edge_attributes(L)
    if return_H:
        return H, L
    return L


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--data_path", default="../street_network_data/zollikerberg", type=str)
    parser.add_argument("-o", "--out_path", default="outputs", type=str)
    parser.add_argument(
        "-p", "--penalty_shared", default=2, type=int, help="penalty factor for driving on a car lane by bike"
    )
    parser.add_argument(
        "-s", "--sp_method", default="od", type=str, help="Compute the shortest path either 'all_pairs' or 'od'"
    )
    parser.add_argument(
        "-a",
        "--algorithm",
        type=str,
        default="optimize",
        help="One of optimize, betweenness_topdown, betweenness_cartime, betweenness_biketime",
    )
    args = parser.parse_args()

    path = args.data_path
    shared_lane_factor = args.penalty_shared  # how much to penalize biking on car lanes
    OUT_PATH = args.out_path
    SP_METHOD = args.sp_method
    ALGORITHM = args.algorithm
    assert ALGORITHM in ["optimize", "betweenness_topdown", "betweenness_cartime", "betweenness_biketime"]
    out_path_ending = "_od" if SP_METHOD == "od" else ""
    WEIGHT_OD_FLOW = False
    os.makedirs(OUT_PATH, exist_ok=True)

    np.random.seed(42)  # random seed for extending the od matrix
    # generate lane graph with snman
    G_lane = generate_motorized_lane_graph(
        os.path.join(path, "edges_all_attributes.gpkg"), os.path.join(path, "nodes_all_attributes.gpkg")
    )

    # load OD
    od = pd.read_csv(os.path.join(path, "od_matrix.csv"))
    od.rename({"osmid_origin": "s", "osmid_destination": "t"}, inplace=True, axis=1)
    od = od[od["s"] != od["t"]]
    # reduce OD matrix to nodes that are in G_lane
    node_list = list(G_lane.nodes())
    od = od[(od["s"].isin(node_list)) & (od["t"].isin(node_list))]

    # extend OD matrix because otherwise we get disconnected car graph
    od = extend_od_circular(od, node_list)

    # # making a subgraph only disconnects the graoh
    # nodes = nodes.sample(200)
    # edges = edges[edges["u"].isin(nodes.index)]
    # edges = edges[edges["v"].isin(nodes.index)]
    # od = od[od["s"].isin(nodes.index)]
    # od = od[od["t"].isin(nodes.index)]

    assert nx.is_strongly_connected(G_lane), "G not connected"

    if "betweenness" in ALGORITHM:
        print(f"Running betweenness algorithm {ALGORITHM}")
        # get algorithm method
        algorithm_func, kwargs = algorithm_dict[ALGORITHM]

        # run betweenness centrality algorithm for comparison
        pareto_between = algorithm_func(
            G_lane.copy(), sp_method=SP_METHOD, od_matrix=od, weight_od_flow=WEIGHT_OD_FLOW, **kwargs
        )
        pareto_between.to_csv(os.path.join(OUT_PATH, f"real_pareto_{ALGORITHM}{out_path_ending}.csv"), index=False)
        exit()

    # other option: Algorithm argumant is "optimize"

    G_street = lane_to_street_graph(G_lane)

    # # the car_weight is an important factor to vary
    # for car_weight in range(15):
    car_weight = 3
    print(f"Running LP for pareto frontier (car weight={car_weight})...")
    tic = time.time()
    ip = define_IP(
        G_street,
        cap_factor=1,
        od_df=od,
        bike_flow_constant=FLOW_CONSTANT,
        car_flow_constant=FLOW_CONSTANT,
        shared_lane_factor=shared_lane_factor,
        weight_od_flow=WEIGHT_OD_FLOW,
        car_weight=car_weight,
    )
    toc = time.time()
    print("Finish init", toc - tic)
    ip.optimize()
    toc2 = time.time()
    print("Finish optimization", toc2 - toc)
    print("OPT VALUE", ip.objective_value)

    # nx.write_gpickle(G, "outputs/real_G.gpickle")
    capacity_values = output_to_dataframe(ip, G_street)
    # capacity_values.to_csv(os.path.join(OUT_PATH, "real_capacities.csv"), index=False)
    del ip
    # flow_df = flow_to_df(ip, list(G_street.edges))
    # flow_df.to_csv(os.path.join(OUT_PATH, "real_flow_solution.csv"), index=False)

    # compute the paretor frontier
    tic = time.time()
    pareto_df = pareto_frontier(
        G_lane,
        capacity_values,
        shared_lane_factor=shared_lane_factor,
        sp_method=SP_METHOD,
        od_matrix=od,
        weight_od_flow=WEIGHT_OD_FLOW,
    )
    print("Time pareto", time.time() - tic)
    pareto_df.to_csv(os.path.join(OUT_PATH, f"real_pareto_optimize{out_path_ending}_{car_weight}.csv"), index=False)
