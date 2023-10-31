import os
import time
import numpy as np
import networkx as nx
import pandas as pd
from ebike_city_tools.random_graph import random_lane_graph
from ebike_city_tools.optimize.utils import make_fake_od
from ebike_city_tools.metrics import compute_travel_times
from ebike_city_tools.optimize.optimizer import Optimizer
from ebike_city_tools.utils import lane_to_street_graph, extend_od_circular
from ebike_city_tools.optimize.round_simple import ceiled_car_graph, pareto_frontier, graph_from_integer_solution

OUT_PATH = "outputs"
os.makedirs(OUT_PATH, exist_ok=True)
NR_ITERS = 5
shared_lane_factor = 2
SP_METHOD = "od"
WEIGHT_OD_FLOW = False

if __name__ == "__main__":
    np.random.seed(20)
    res_df = []
    for i in range(NR_ITERS):
        # test different number of nodes
        for size in np.arange(40, 70, 10):
            G_lane = random_lane_graph(size)
            G = lane_to_street_graph(G_lane)
            # test for graphs with OD matrix of 2 times, 3 times, or 4 times as many entries as the number of nodes
            for od_factor in [1, 2, 3]:
                # define graph
                od = make_fake_od(size, od_factor * size, nodes=G.nodes)
                od = extend_od_circular(od, list(G_lane.nodes()))

                # run for several car weights to get a pareto frontier also for the integer problem
                for car_weight in [0.1, 0.5, 0.75, 1, 2, 3, 4, 5, 10]:
                    for integer_problem, name in zip([True, False], ["integer", "linear"]):
                        optim = Optimizer(
                            graph=G.copy(),
                            od_matrix=od,
                            integer_problem=integer_problem,
                            shared_lane_factor=shared_lane_factor,  # factor how much worse it is to bike on a car lane
                            car_weight=car_weight,
                            weight_od_flow=WEIGHT_OD_FLOW,
                        )
                        tic = time.time()
                        optim.init_lp()
                        toc = time.time()
                        obj_value = optim.optimize()
                        toc_finished = time.time()

                        # first check whether car graph is strongly connected
                        capacity_values = optim.get_solution()
                        car_G_init = ceiled_car_graph(capacity_values.copy())
                        if not nx.is_strongly_connected(car_G_init):
                            continue

                        # transform the graph layout into travel times, including gradient and penalty factor for using
                        if integer_problem:
                            bike_G, car_G = graph_from_integer_solution(capacity_values)
                            res_dict_list = [
                                compute_travel_times(
                                    G_lane,
                                    bike_G,
                                    car_G,
                                    od_matrix=od,
                                    sp_method=SP_METHOD,
                                    shared_lane_factor=shared_lane_factor,
                                    weight_od_flow=WEIGHT_OD_FLOW,
                                )
                            ]
                        else:
                            # for linear, we have to compute the paretor frontier
                            res_dict_list = pareto_frontier(
                                G_lane,
                                capacity_values,
                                od_matrix=od,
                                shared_lane_factor=shared_lane_factor,
                                sp_method=SP_METHOD,
                                return_list=True,
                                weight_od_flow=WEIGHT_OD_FLOW,
                            )
                        # add general infos to integer or linear (pareto) solution
                        for r in res_dict_list:
                            r.update(
                                {
                                    "iter": i,
                                    "name": name,
                                    "nodes": size,
                                    "edges": G.number_of_edges(),
                                    "od_size": len(od),
                                    "car_weight": car_weight,
                                    "opt_value": obj_value,
                                    "time init": toc - tic,
                                    "time optimize": toc_finished - toc,
                                }
                            )
                        res_df.extend(res_dict_list)
                        print("----------")
                        print(res_df[-1])
                        print("----------")
                # save updated df in every iteration
                pd.DataFrame(res_df).to_csv(os.path.join(OUT_PATH, "integer_vs_linear.csv"), index=False)
