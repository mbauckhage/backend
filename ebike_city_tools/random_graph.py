import networkx as nx
import numpy as np
import pandas as pd


def generate_base_graph(n=20, min_neighbors=2):
    """Random graph where the neighbors of each node are sampled proportinally to their inverse distance"""
    # init graph
    G = nx.MultiDiGraph()

    # define node coordinates
    coords = np.random.rand(n, 2)
    node_inds = np.arange(n)

    # add edge list
    edge_list = []
    for i, node_coords in enumerate(coords):
        neighbor_distances = np.linalg.norm(coords - node_coords, axis=1)
        neighbor_distances[i] = 1000000
        neighbor_probs = 1 / neighbor_distances**2
        neighbor_probs = neighbor_probs / np.sum(neighbor_probs)
        nr_neighbors = max(min_neighbors, round(np.random.normal(2.5, 2)))
        sampled_neighbors = np.random.choice(node_inds, p=neighbor_probs, replace=True, size=nr_neighbors)
        for neigh in sampled_neighbors:
            dist = neighbor_distances[neigh]
            edge_list.append([i, neigh, {"weight": np.random.rand(), "distance": dist}])
    #             edge_list.append([neigh, i, {"weight": np.random.rand()}])
    G.add_edges_from(edge_list)

    # set attributes
    attrs = {i: {"loc": coords[i]} for i in range(n)}
    nx.set_node_attributes(G, attrs)

    return G


def base_graph_doppelspur(n=20, min_neighbors=2):
    """
    Graph where each lane has also a corresponding lane in the opposite direction
    (no multigraph!)
    """
    # init graph
    G = nx.DiGraph()

    # define node coordinates
    coords = np.random.rand(n, 2)
    node_inds = np.arange(n)

    # add edge list
    edge_list = []
    for i, node_coords in enumerate(coords):
        neighbor_distances = np.linalg.norm(coords - node_coords, axis=1)
        neighbor_distances[i] = 1000000
        neighbor_probs = 1 / neighbor_distances**2
        neighbor_probs = neighbor_probs / np.sum(neighbor_probs)
        nr_neighbors = max(min_neighbors, round(np.random.normal(2, 2)))
        sampled_neighbors = np.random.choice(node_inds, p=neighbor_probs, replace=False, size=nr_neighbors)
        for neigh in sampled_neighbors:
            dist = neighbor_distances[neigh]
            edge_list.append([i, neigh, {"weight": 1, "distance": dist}])
            edge_list.append([neigh, i, {"weight": 1, "distance": dist}])
    G.add_edges_from(edge_list)

    # set attributes
    attrs = {i: {"loc": coords[i]} for i in range(n)}
    nx.set_node_attributes(G, attrs)

    return nx.MultiDiGraph(G)


def deprecated_aureliens_base_graph(n=20, min_neighbors=2):
    """
    Graph where each lane has also a corresponding lane in the opposite direction
    (no multigraph!)
    """
    # init graph
    G = nx.DiGraph()

    # define node coordinates
    coords = np.random.rand(n, 2)
    node_inds = np.arange(n)

    # add edge list
    edge_list = []
    for i, node_coords in enumerate(coords):
        neighbor_distances = np.linalg.norm(coords - node_coords, axis=1)
        neighbor_distances[i] = 1000000
        neighbor_probs = 1 / neighbor_distances**2
        neighbor_probs = neighbor_probs / np.sum(neighbor_probs)
        nr_neighbors = max(min_neighbors, round(np.random.normal(2, 2)))
        sampled_neighbors = np.random.choice(node_inds, p=neighbor_probs, replace=False, size=nr_neighbors)
        for neigh in sampled_neighbors:
            dist = neighbor_distances[neigh]
            cap = 10  # round(np.random.rand()*5) # TODO
            grad = np.random.rand() * 5  # Add to edges --> this is also done in the other one
            # they have the same capacity, so basically they are just virtual edges for the same edge
            edge_list.append([i, neigh, {"capacity": cap, "distance": dist, "gradient": grad}])
            edge_list.append([neigh, i, {"capacity": cap, "distance": dist, "gradient": -grad}])
    G.add_edges_from(edge_list)

    # set attributes
    attrs = {i: {"loc": coords[i]} for i in range(n)}
    nx.set_node_attributes(G, attrs)

    return nx.DiGraph(G)


def get_city_coords(n=20):
    coords = np.random.rand(n, 3)  # with elevation
    coords[:, :2] *= 5000  # positions vary between 0 and 5000m --> city of 5km quadtric side length
    coords[:, 2] *= 50  # make the altitude differ by at most 100m
    # --> NOTE: it is not ensured that nearby nodes have similar altitude, so we leave it like it is
    return coords.astype(int)


def make_fake_od(n, nr_routes, nodes=None):
    od = pd.DataFrame()
    od["s"] = (np.random.rand(nr_routes) * n).astype(int)
    od["t"] = (np.random.rand(nr_routes) * n).astype(int)
    od["trips_per_day"] = (np.random.rand(nr_routes) * 5).astype(int)
    od = od[od["s"] != od["t"]].drop_duplicates(subset=["s", "t"])

    if nodes is not None:
        # transform into the correct node names
        node_list = np.array(sorted(list(nodes)))
        as_inds = od[["s", "t"]].values
        trips_per_day = od["trips_per_day"].values  # save flow column here
        # use as index
        od = pd.DataFrame(node_list[as_inds], columns=["s", "t"])
        od["trips_per_day"] = trips_per_day
    return od


def random_lane_graph(n=20, neighbor_choices=[2, 3, 4], neighbor_p=[0.6, 0.3, 0.1]):
    """
    Create realistic city graph with coordinates, elevation, etc
    Returns: MultiDiGraph with attributes width, distance, gradient -> one edge per lane!
    """
    # init graph
    G_lane = nx.MultiDiGraph()

    # define node coordinates
    coords = get_city_coords(n)
    node_inds = np.arange(n)
    node_ids = np.arange(n)  # * 10 # to test whether it works also for other node IDs

    # add edge list
    edge_list = []
    for i, node_coords in enumerate(coords):
        neighbor_distances = np.linalg.norm(coords[:, :2] - node_coords[:2], axis=1)
        neighbor_distances[i] = 1000000
        neighbor_probs = 1 / neighbor_distances**2
        neighbor_probs = neighbor_probs / np.sum(neighbor_probs)
        # nr_neighbors = max(min_neighbors, round(np.random.normal(2, 2)))
        nr_neighbors = np.random.choice(neighbor_choices, p=neighbor_p)
        sampled_neighbors = np.random.choice(node_inds, p=neighbor_probs, replace=True, size=nr_neighbors)
        for neigh in sampled_neighbors:
            dist = neighbor_distances[neigh] / 1000  # we want the distance in km
            gradient = (coords[neigh, 2] - node_coords[2]) / (dist * 10)  # meter of height per 100m
            # gradient is given in percent
            # (From paper: for every additional 1% of uphill gradient,
            # the mean speed is reduced by 0.4002 m/s (1.44 kph))
            # --> meters in height / (dist * 1000) * 100
            edge_list.append(
                [
                    node_ids[i],
                    node_ids[neigh],
                    {"capacity": 1, "distance": dist, "gradient": gradient, "speed_limit": 30},
                ]
            )
            edge_list.append(
                [
                    node_ids[neigh],
                    node_ids[i],
                    {"capacity": 1, "distance": dist, "gradient": -gradient, "speed_limit": 30},
                ]
            )
    G_lane.add_edges_from(edge_list)

    # set attributes
    attrs = {node_ids[i]: {"loc": coords[i]} for i in range(n)}
    nx.set_node_attributes(G_lane, attrs)

    if not nx.is_strongly_connected(G_lane):
        return random_lane_graph(n=n, neighbor_choices=neighbor_choices, neighbor_p=neighbor_p)

    return nx.MultiDiGraph(G_lane)
