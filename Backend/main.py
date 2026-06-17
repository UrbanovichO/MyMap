from fastapi import FastAPI
import random
import osmnx as ox
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_graph():
    G = ox.graph_from_place("Хмельницький, Україна", network_type="walk")
    return G

G = get_graph()
# Створення списку графів
nodes_list = list(G.nodes)
len_nodes_list = len(nodes_list)
n_points = 10
points = {}

@app.get("/coordinates")
def get_coordinates():
    for i in range(1, n_points + 1):
        point_id = f"{i}"
        node_index = random.randint(0, len_nodes_list)
        node_id = nodes_list[node_index]
        coord_x = G.nodes[node_id]["x"]
        coord_y = G.nodes[node_id]["y"]

        points[point_id] = [coord_x, coord_y, node_index]
    return points
@app.get("/newcoordinates")
def get_new_coordinates():
    for id,coords in points.items():
        node_index = coords[2]
        direction = 0
        choice_weights = [5, 5, 90]
        # Рух - назад, на місці , вперед
        option = [-1, 0, 1]
        # Визначення напрямку руху
        if direction == -1:
            choice_weights = [90, 5, 5]
        # Вибір напрямку руху
        direction = random.choices(option, weights=choice_weights, k=1)[0]
        if 0 <= node_index <= len_nodes_list:
            new_node_index = node_index + direction
        elif node_index < 0:
            node_index += 1
        elif node_index >= len_nodes_list:
            node_index -= 1
        new_node_id = nodes_list[new_node_index]

        new_coord_x = G.nodes[new_node_id]["x"]
        new_coord_y = G.nodes[new_node_id]["y"]
        points[id] = [new_coord_x, new_coord_y,new_node_index]
    return points