import time
import numpy as np
import networkx as nx
import pandas as pd
from ebike_city_tools.random_graph import city_graph, lane_to_street_graph
from ebike_city_tools.optimize.utils import output_to_dataframe, flow_to_df, make_fake_od
from ebike_city_tools.optimize.linear_program import initialize_IP
from ebike_city_tools.optimize.round_simple import *
from ebike_city_tools.metrics import sp_length

shared_lane_factor = 2
n = 20
nr_trials = 10

G_city = city_graph(n)
G = lane_to_street_graph(G_city)
# full od matrix
od_full = pd.DataFrame(np.array([[i, j] for i in range(n) for j in range(n)]), columns=["s", "t"])

# run several times to remove different parts from the OD matrix
res_df = []
for trial in range(nr_trials):
    for od_reduction in np.arange(1, 0, -0.1):
        new_od_size = int(len(od_full) * od_reduction)
        od = od_full.sample(new_od_size, replace=False)

        # initialize and optimize with this od matrix
        tic = time.time()
        ip = initialize_IP(G, cap_factor=1, od_df=od, shared_lane_factor=shared_lane_factor)
        toc = time.time()
        ip.optimize()
        toc2 = time.time()

        flow_df = flow_to_df(ip, list(G.edges))
        flow_df = flow_df[flow_df["flow"] > 0]

        # # writing and reading for debugging
        # flow_df.to_csv("outputs/test_flow_solution.csv", index=False)
        # nx.write_gpickle(G, "outputs/test_G.gpickle")
        # flow_df = pd.read_csv("bike_lane_optimization/outputs/test_flow_solution.csv")
        # G = nx.read_gpickle("bike_lane_optimization/outputs/test_G.gpickle")

        car_flows = flow_df[flow_df["var_type"] == "c"].groupby(["edge_u", "edge_v"])["flow"].max().to_dict()
        flow_edges = [tuple(t) for t in flow_df[["edge_u", "edge_v"]].values]
        for e in list(G.edges):
            if e not in flow_edges:
                car_flows[e] = 1
        #     else:
        #         print("IN", e)
        bike_flows = flow_df[flow_df["var_type"] == "b"].groupby(["edge_u", "edge_v"])["flow"].max().to_dict()

        existing_car_edges = car_flows.keys()
        existing_bike_edges = bike_flows.keys()

        weight_sp_dict = {}
        for u, v, data in G.edges(data=True):
            inner_dict = {}
            if (u, v) in existing_car_edges:
                inner_dict["car_sp_weight"] = data["cartime"] / car_flows[(u, v)]
            else:
                inner_dict["car_sp_weight"] = np.inf
            if (u, v) in existing_bike_edges and bike_flows[(u, v)] > 1 / shared_lane_factor:
                inner_dict["bike_sp_weight"] = data["biketime"] / bike_flows[(u, v)]
            else:
                # treat as a shared edge
                inner_dict["bike_sp_weight"] = data["biketime"] * shared_lane_factor
            weight_sp_dict[(u, v)] = inner_dict
        #     print(u, v, data["biketime"])
        nx.set_edge_attributes(G, weight_sp_dict)

        car_sp = sp_length(G, "car_sp_weight", return_matrix=True)
        bike_sp = sp_length(G, "bike_sp_weight", return_matrix=True)

        res_dict = {
            "car sp lengths": np.mean(car_sp[car_sp < np.inf]),
            "car sp reachable": len(np.where(car_sp == np.inf)[0]),
            "bike sp lengths": np.mean(bike_sp[bike_sp < np.inf]),
            "bike sp reachable": len(np.where(bike_sp == np.inf)[0]),
            "od reduction": od_reduction,
            "nr_trial": trial,
            "runtime_init": toc - tic,
            "runtime_optim": toc2 - toc,
        }
        res_df.append(res_dict)
    pd.DataFrame(res_df).to_csv("outputs/od_dependency.csv")