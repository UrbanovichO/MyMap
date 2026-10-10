from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
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

def generate_points():
    """(Пере)створює всі n_points точок у випадкових вузлах графа."""
    for i in range(1, n_points + 1):
        point_id = f"{i}"
        node_index = random.randint(0, len_nodes_list-1)
        node_id = nodes_list[node_index]
        coord_x = G.nodes[node_id]["x"]
        coord_y = G.nodes[node_id]["y"]

        points[point_id] = [coord_x, coord_y, node_index]


@app.get("/coordinates")
def get_coordinates():
    generate_points()
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

# Радіус, у межах якого можливий контакт (метри)
INFECTION_RADIUS_M = 150


def get_neighbors_with_distances():
    """Для кожної точки повертає список (id_сусіда, відстань_у_метрах)
    для всіх точок у межах INFECTION_RADIUS_M."""
    ids = list(points.keys())
    if not ids:
        return {}

    lons = np.array([points[pid][0] for pid in ids])  # x = довгота
    lats = np.array([points[pid][1] for pid in ids])  # y = широта

    result = {}
    for i, point_id in enumerate(ids):
        # Відстані від поточної точки до всіх інших (у метрах)
        distances = ox.distance.great_circle(lats[i], lons[i], lats, lons)

        # Виключаємо саму точку
        distances[i] = np.inf

        close_idx = np.where(distances <= INFECTION_RADIUS_M)[0]
        result[point_id] = [(ids[j], float(distances[j])) for j in close_idx]

    return result


@app.get("/neardots")
def get_near_dots():
    """Те саме, що й раніше: {id: [id сусідів у радіусі]} (без відстаней)."""
    neighbors = get_neighbors_with_distances()
    return {pid: [nid for nid, _ in lst] for pid, lst in neighbors.items()}


STATE_HEALTHY = "healthy"
STATE_EXPOSED = "exposed"      # інкубаційний період: заражений, але ще не заразний
STATE_INFECTED = "infected"
STATE_RECOVERED = "recovered"
STATE_DEAD = "dead"

# Тестові параметри (можна підбирати експериментально)
INFECTION_PROBABILITY = 0.6   # максимальний шанс зараження за крок (при відстані 0 м)
RECOVERY_PROBABILITY = 0.05   # шанс одужати за крок
DEATH_PROBABILITY = 0.1       # шанс померти за крок

# Інкубаційний період: випадкова тривалість у кроках симуляції
INCUBATION_MIN_STEPS = 2
INCUBATION_MAX_STEPS = 5

# Реінфекція: одужалі можуть заразитися знову. Вимикається через /reinfection?enabled=false
REINFECTION_ENABLED = True
REINFECTION_FACTOR = 0.3      # наскільки одужалий вразливіший за здорового (0.3 = на 70% менше шансів)


def distance_factor(distance_m):
    """Множник шансу зараження залежно від відстані:
    1.0 при 0 м, лінійно спадає до 0 на межі INFECTION_RADIUS_M."""
    return max(0.0, 1.0 - distance_m / INFECTION_RADIUS_M)


states = {}
incubation_left = {}  # {id: скільки кроків інкубації лишилось}
dead_count = 0  # накопичувальний лічильник, бо мертві видаляються зі states назавжди


def get_epidemic_stats():
    """Рахунок точок по станах. Померлі рахуються окремим лічильником,
    бо вони фізично видаляються з points і states."""
    counts = {
        STATE_HEALTHY: 0,
        STATE_EXPOSED: 0,
        STATE_INFECTED: 0,
        STATE_RECOVERED: 0,
    }
    for state in states.values():
        counts[state] = counts.get(state, 0) + 1
    counts[STATE_DEAD] = dead_count
    return counts


@app.get("/reinfection")
def set_reinfection(enabled: bool):
    """Вмикає/вимикає реінфекцію під час роботи: /reinfection?enabled=false"""
    global REINFECTION_ENABLED
    REINFECTION_ENABLED = enabled
    return {"reinfection_enabled": REINFECTION_ENABLED}


class EpidemicParams(BaseModel):
    infection_probability: float = Field(..., ge=0, le=1)
    death_probability: float = Field(..., ge=0, le=1)
    recovery_probability: float = Field(..., ge=0, le=1)
    infection_radius_m: float = Field(..., gt=0, le=10000)
    incubation_min_steps: int = Field(..., ge=0, le=1000)
    incubation_max_steps: int = Field(..., ge=0, le=1000)
    reinfection_factor: float = Field(..., ge=0, le=1)


def current_params():
    return {
        "infection_probability": INFECTION_PROBABILITY,
        "death_probability": DEATH_PROBABILITY,
        "recovery_probability": RECOVERY_PROBABILITY,
        "infection_radius_m": INFECTION_RADIUS_M,
        "incubation_min_steps": INCUBATION_MIN_STEPS,
        "incubation_max_steps": INCUBATION_MAX_STEPS,
        "reinfection_factor": REINFECTION_FACTOR,
    }


@app.get("/params")
def get_params():
    """Поточні параметри симуляції."""
    return current_params()


@app.post("/params")
def set_params(p: EpidemicParams):
    """Змінює параметри симуляції під час роботи. Діють з наступного кроку."""
    global INFECTION_PROBABILITY, DEATH_PROBABILITY, RECOVERY_PROBABILITY
    global INFECTION_RADIUS_M, INCUBATION_MIN_STEPS, INCUBATION_MAX_STEPS
    global REINFECTION_FACTOR

    if p.death_probability + p.recovery_probability > 1:
        raise HTTPException(
            status_code=400,
            detail="Смертність + шанс одужання не можуть разом перевищувати 1",
        )
    if p.incubation_min_steps > p.incubation_max_steps:
        raise HTTPException(
            status_code=400,
            detail="Мінімальна інкубація не може бути більшою за максимальну",
        )

    INFECTION_PROBABILITY = p.infection_probability
    DEATH_PROBABILITY = p.death_probability
    RECOVERY_PROBABILITY = p.recovery_probability
    INFECTION_RADIUS_M = p.infection_radius_m
    INCUBATION_MIN_STEPS = p.incubation_min_steps
    INCUBATION_MAX_STEPS = p.incubation_max_steps
    REINFECTION_FACTOR = p.reinfection_factor
    return current_params()


@app.get("/init_epidemic")
def init_epidemic():
    """Ініціалізація: усі здорові, крім одного випадкового 'нульового пацієнта'."""
    global states, dead_count

    # Якщо всі точки вже померли (або сервер перезапустили), points порожній —
    # створюємо їх заново, інакше нема з кого обрати нульового пацієнта
    if not points:
        generate_points()

    states = {pid: STATE_HEALTHY for pid in points.keys()}
    incubation_left.clear()
    dead_count = 0

    patient_zero = random.choice(list(points.keys()))
    states[patient_zero] = STATE_INFECTED

    return {
        "patient_zero": patient_zero,
        "states": states,
        "stats": get_epidemic_stats(),
        "reinfection_enabled": REINFECTION_ENABLED,
    }


@app.get("/step_epidemic")
def step_epidemic():
    """Один крок симуляції: інкубація -> зараження сусідів (з урахуванням відстані)
    -> одужання/смерть. Оновлення синхронне: читаємо states, пишемо в new_states."""
    global points, states, dead_count

    neighbors = get_neighbors_with_distances()  # {"1": [("3", 12.4), ("7", 80.1)], ...}
    new_states = states.copy()
    dead_ids = []
    newly_exposed = set()

    for point_id, state in states.items():

        # 0. Інкубація: відлік кроків, після чого точка стає заразною
        if state == STATE_EXPOSED:
            incubation_left[point_id] = incubation_left.get(point_id, 0) - 1
            if incubation_left[point_id] <= 0:
                new_states[point_id] = STATE_INFECTED
                incubation_left.pop(point_id, None)
            continue

        # Заразні тільки заражені (exposed ще не заразні)
        if state != STATE_INFECTED:
            continue

        # 1. Спроба зараження сусідів у радіусі, шанс залежить від відстані
        for neighbor_id, dist in neighbors.get(point_id, []):
            if neighbor_id in newly_exposed:
                continue

            neighbor_state = states.get(neighbor_id)
            if neighbor_state == STATE_HEALTHY:
                susceptibility = 1.0
            elif neighbor_state == STATE_RECOVERED and REINFECTION_ENABLED:
                susceptibility = REINFECTION_FACTOR
            else:
                continue

            p = INFECTION_PROBABILITY * distance_factor(dist) * susceptibility
            if random.random() < p:
                new_states[neighbor_id] = STATE_EXPOSED
                incubation_left[neighbor_id] = random.randint(
                    INCUBATION_MIN_STEPS, INCUBATION_MAX_STEPS
                )
                newly_exposed.add(neighbor_id)

        # 2. Доля самої зараженої точки (смерть / одужання / залишається хворою)
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
        incubation_left.pop(pid, None)

    return {
        "states": states,
        "stats": get_epidemic_stats(),
        "reinfection_enabled": REINFECTION_ENABLED,
    }