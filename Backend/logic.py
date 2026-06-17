import osmnx as ox
from functools import lru_cache
import time
import random
import requests

API_URL = "http://127.0.0"

# Завантаження графів доріг
@lru_cache(None)
def get_graph():
    G = ox.graph_from_place("Хмельницький, Україна", network_type="walk")
    return G

G = get_graph()
# Створення списку графів
nodes_list = list(G.nodes)
print(nodes_list)
len_nodes_list = len(nodes_list)
n_points = 2
# Визначення початкових координат
node_index = random.randint(0,len_nodes_list)
points = {}
for i in range(1 , n_points+1):
    point_id = f"{i}"
    node_index = random.randint(0, len_nodes_list)
    node_id = nodes_list[node_index]
    coord_x = G.nodes[node_id]["x"]
    coord_y = G.nodes[node_id]["y"]

    points[point_id] = [coord_x, coord_y, node_index]
print(points)

def choose_next_nodes():
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
        points[id] = [new_coord_x, new_coord_y] , new_node_index
        packet = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [coords[0], coords[1]]
            },
            "properties": {
                "id": id,
            }
        }
        try:
            response = requests.post(API_URL, json=packet, timeout=1)
            print(f"[{id}] Рухнув та відправлений. Статус сервера: {response.status_code}")
        except requests.exceptions.RequestException:
            print(f"[{id}] Помилка з'єднання з сервером")
        time.sleep(0.5)
while True:
    choose_next_nodes()
    print("Всі точки по черзі оновлено. Відпочиваємо 5 секунд...")
    time.sleep(5)

