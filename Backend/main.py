from fastapi import FastAPI
import random
import osmnx as ox
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
import math

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
nodes_list.sort()
len_nodes_list = len(nodes_list)
n_points = 1000
points = {}

@app.get("/coordinates")
def get_coordinates():
    for i in range(1, n_points + 1):
        point_id = f"{i}"
        node_index = random.randint(0, len_nodes_list-1)
        node_id = nodes_list[node_index]
        coord_x = G.nodes[node_id]["x"]
        coord_y = G.nodes[node_id]["y"]

        points[point_id] = [coord_x, coord_y, node_index]
    return points


def add_gps_error(lon, lat, min_error_m=1, max_error_m=10):
    """
    Зміщує координату (lon, lat) на випадкову відстань
    у діапазоні [min_error_m, max_error_m] метрів у випадковому напрямку.
    """
    error_distance = random.uniform(min_error_m, max_error_m)
    angle = random.uniform(0, 2 * math.pi)

    # Зміщення вздовж широти (1 градус широти ≈ 111320 метрів, майже постійно)
    delta_lat = (error_distance * math.cos(angle)) / 111320

    # Зміщення вздовж довготи (довжина градуса довготи залежить від широти)
    delta_lon = (error_distance * math.sin(angle)) / (111320 * math.cos(math.radians(lat)))

    new_lon = lon + delta_lon
    new_lat = lat + delta_lat
    return new_lon, new_lat

@app.get("/newcoordinates")
def get_new_coordinates():
    global new_node_index
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
        if 0 <= node_index <= len_nodes_list-2:
            new_node_index = node_index + direction
            if new_node_index < 0:
                new_node_index = 0
            elif new_node_index >= len_nodes_list-1:
                new_node_index -= len_nodes_list-1

        new_node_id = nodes_list[new_node_index]

        new_coord_x = G.nodes[new_node_id]["x"]
        new_coord_y = G.nodes[new_node_id]["y"]

        new_coord_x, new_coord_y = add_gps_error(new_coord_x, new_coord_y)

        points[id] = [new_coord_x, new_coord_y,new_node_index]
    return points

@app.get("/neardots")
def get_near_dots():
    ids = list(points.keys())
    lons = np.array([points[pid][0] for pid in ids])  # x = довгота
    lats = np.array([points[pid][1] for pid in ids])  # y = широта

    radius_meters = 150

    nearest_points = {}

    for i, point_id in enumerate(ids):
        # Відстані від поточної точки до всіх інших (у метрах)
        distances = ox.distance.great_circle(
            lats[i], lons[i], lats, lons
        )

        # Виключаємо саму точку
        distances[i] = np.inf

        # Індекси точок, що потрапляють у радіус
        close_idx = np.where(distances <= radius_meters)[0]

        nearest_points[point_id] = [ids[j] for j in close_idx]

    return nearest_points

STATE_HEALTHY = "healthy"
STATE_INFECTED = "infected"
STATE_RECOVERED = "recovered"
STATE_DEAD = "dead"

# Тестові параметри (можна підбирати експериментально)
INFECTION_PROBABILITY = 0.6   # шанс заразити здорового сусіда за один крок
RECOVERY_PROBABILITY = 0   # шанс одужати за крок (якщо не помер)
DEATH_PROBABILITY = 0.1      # шанс померти за крок

states = {}
dead_count = 0  # накопичувальний лічильник, бо мертві видаляються зі states назавжди

def get_epidemic_stats():
    """Рахунок точок по станах. Померлі рахуються окремим лічильником,
    бо вони фізично видаляються з points і states."""
    counts = {STATE_HEALTHY: 0, STATE_INFECTED: 0, STATE_RECOVERED: 0}
    for state in states.values():
        counts[state] = counts.get(state, 0) + 1
    counts[STATE_DEAD] = dead_count
    return counts

@app.get("/init_epidemic")
def init_epidemic():
    """Ініціалізація: усі здорові, крім одного випадкового 'нульового пацієнта'."""
    global states, dead_count
    states = {pid: STATE_HEALTHY for pid in points.keys()}
    dead_count = 0

    patient_zero = random.choice(list(points.keys()))
    states[patient_zero] = STATE_INFECTED

    return {"patient_zero": patient_zero, "states": states, "stats": get_epidemic_stats()}

@app.get("/step_epidemic")
def step_epidemic():
    """Один крок симуляції: зараження сусідів + перехід інфікованих у одужалі/померлі."""
    global points, states, dead_count

    near_points = get_near_dots()  # {"1": ["3", "7"], ...}
    new_states = states.copy()
    dead_ids = []

    for point_id, state in states.items():
        if state != STATE_INFECTED:
            continue

        # 1. Спроба зараження здорових сусідів у радіусі
        for neighbor_id in near_points.get(point_id, []):
            if states.get(neighbor_id) == STATE_HEALTHY:
                if random.random() < INFECTION_PROBABILITY:
                    new_states[neighbor_id] = STATE_INFECTED

        # 2. Визначення долі самої зараженої точки (смерть / одужання / залишається хворою)
        outcome_roll = random.random()
        if outcome_roll < DEATH_PROBABILITY:
            new_states[point_id] = STATE_DEAD
            dead_ids.append(point_id)
        elif outcome_roll < DEATH_PROBABILITY + RECOVERY_PROBABILITY:
            new_states[point_id] = STATE_RECOVERED
        # інакше — залишається "infected" ще на один крок

    states = new_states

    # 3. Видаляємо померлих з points і states, рахунок зберігаємо в dead_count
    dead_count += len(dead_ids)
    for pid in dead_ids:
        points.pop(pid, None)
        states.pop(pid, None)

    return {"states": states, "stats": get_epidemic_stats()}