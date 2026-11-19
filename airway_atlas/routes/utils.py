import csv
import logging
import math
import random
from pathlib import Path

import networkx as nx

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parent / "data"
DISTANCE = "Distance_km"


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = math.sin((lat2 - lat1) / 2) ** 2
    a += math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


def load_graph():
    graph = nx.Graph()

    with (DATA_DIR / "Airports.csv").open(encoding="utf-8", newline="") as airports:
        for row in csv.DictReader(airports):
            code = row["ID"].strip().upper()
            if len(code) != 3 or not code.isascii() or not code.isalpha():
                continue
            lat, lon = float(row["Latitude"]), float(row["Longitude"])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                graph.add_node(code, name=row["Label"], lat=lat, lon=lon)

    with (DATA_DIR / "Routes.csv").open(encoding="utf-8", newline="") as routes:
        for row in csv.DictReader(routes):
            source = row["Departure"].strip().upper()
            destination = row["Destination"].strip().upper()
            if source != destination and source in graph and destination in graph:
                start = graph.nodes[source]
                end = graph.nodes[destination]
                distance = haversine(start["lat"], start["lon"], end["lat"], end["lon"])
                graph.add_edge(source, destination, **{DISTANCE: distance})

    return graph


try:
    G = load_graph()
except (OSError, ValueError, KeyError):
    logger.exception("Could not load the airport network")
    G = nx.Graph()

connected_airports = sorted(code for code, degree in G.degree if degree > 0)


def route_result(path):
    distance = nx.path_weight(G, path, DISTANCE)
    return {"path": path, "distance": distance}


def get_astar_path(source, destination):
    def heuristic(u, v):
        start, end = G.nodes[u], G.nodes[v]
        return haversine(start["lat"], start["lon"], end["lat"], end["lon"])

    try:
        return route_result(nx.astar_path(G, source, destination, heuristic, DISTANCE))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def get_dijkstra_path(source, destination):
    try:
        return route_result(nx.dijkstra_path(G, source, destination, weight=DISTANCE))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def get_rl_path(source, destination):
    """Train an experimental Q-learning policy with a fixed search budget."""
    if source not in G or destination not in G or not nx.has_path(G, source, destination):
        return None

    alpha, gamma, epsilon = 0.4, 0.9, 1.0
    max_steps = 100
    values = {}
    rng = random.Random(f"{source}:{destination}")
    best_route = None

    for episode in range(50):
        state = source
        path = [source]
        for _ in range(max_steps):
            if state not in values:
                values[state] = dict.fromkeys(G[state], 0.0)
            actions = values[state]
            if rng.random() < epsilon:
                next_state = rng.choice(list(actions))
            else:
                next_state = max(actions, key=actions.get)
            terminal = next_state == destination
            reward = -G[state][next_state][DISTANCE]
            best_future = 0 if terminal else max(values.get(next_state, {}).values(), default=0)
            actions[next_state] += alpha * (reward + gamma * best_future - actions[next_state])
            state = next_state
            if state in path:
                path = path[:path.index(state) + 1]
            else:
                path.append(state)
            if terminal:
                candidate = route_result(path)
                if best_route is None or candidate["distance"] < best_route["distance"]:
                    best_route = candidate
                break

        epsilon = 0.01 + 0.99 * math.exp(-0.005 * (episode + 1))

    return best_route
