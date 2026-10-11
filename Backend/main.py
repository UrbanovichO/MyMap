from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import random
import osmnx as ox
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
import math
import threading
import functools

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

# FastAPI виконує звичайні (не async) ендпоінти паралельно в різних потоках.
# Без блокування /newcoordinates (перебирає points) і /step_epidemic (видаляє мертвих з points)
# можуть працювати одночасно: це дає помилку "dictionary changed size during iteration"
# (тоді точки перестають рухатись) або "воскрешає" щойно померлу точку.
sim_lock = threading.RLock()

def locked(fn):
    """Декоратор: ендпоінти, що чіпають points/states, виконуються по одному."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with sim_lock:
            return fn(*args, **kwargs)
    return wrapper


def get_graph():
    G = ox.graph_from_place("Хмельницький, Україна", network_type="walk")
    return G

G = get_graph()
# Список вузлів графа (перехрестя та повороти вулиць)
nodes_list = list(G.nodes)
len_nodes_list = len(nodes_list)

def edge_length_m(u, v):
    """Довжина ребра u->v у метрах (атрибут 'length' графа osmnx)."""
    data = G.get_edge_data(u, v) or {}
    lengths = [d["length"] for d in data.values() if d.get("length")]
    if lengths:
        return max(0.5, float(min(lengths)))
    # запасний варіант: відстань по прямій між вузлами
    a, b = G.nodes[u], G.nodes[v]
    return max(0.5, float(ox.distance.great_circle(a["y"], a["x"], b["y"], b["x"])))

# Для кожного вузла — вузли, до яких з нього можна дійти вулицею (одне ребро),
# та довжини цих ребер. Рахуємо один раз при старті.
neighbors_map = {
    node_id: [v for v in G.successors(node_id) if v != node_id]
    for node_id in nodes_list
}
edge_len_map = {
    (u, v): edge_length_m(u, v)
    for u, targets in neighbors_map.items()
    for v in targets
}

# Параметри руху (змінюються через /params)
MOVEMENT_STEP_M = 50   # скільки метрів проходить точка за один крок
GPS_ERROR_MAX_M = 10   # макс. випадкова похибка позиції, м (0 = без похибки)

# Стартувати можна лише з вузлів, з яких є куди йти
movable_nodes = [node_id for node_id in nodes_list if neighbors_map[node_id]]
n_points = 1000
points = {}

def generate_points():
    """(Пере)створює всі n_points точок у випадкових вузлах графа."""
    for i in range(1, n_points + 1):
        point_id = f"{i}"
        from_id = random.choice(movable_nodes)
        to_id = random.choice(neighbors_map[from_id])
        coord_x = G.nodes[from_id]["x"]
        coord_y = G.nodes[from_id]["y"]

        # [довгота, широта, вузол звідки, вузол куди, пройдено по ребру (м)]
        points[point_id] = [coord_x, coord_y, from_id, to_id, 0.0]


@app.get("/coordinates")
@locked
def get_coordinates():
    generate_points()
    return points


def add_gps_error(lon, lat, min_error_m=1, max_error_m=10):
    """
    Зміщує координату (lon, lat) на випадкову відстань
    у діапазоні [min_error_m, max_error_m] метрів у випадковому напрямку.
    """
    if max_error_m <= 0:
        return lon, lat
    error_distance = random.uniform(min(min_error_m, max_error_m), max_error_m)
    angle = random.uniform(0, 2 * math.pi)

    # Зміщення вздовж широти (1 градус широти ≈ 111320 метрів, майже постійно)
    delta_lat = (error_distance * math.cos(angle)) / 111320

    # Зміщення вздовж довготи (довжина градуса довготи залежить від широти)
    delta_lon = (error_distance * math.sin(angle)) / (111320 * math.cos(math.radians(lat)))

    new_lon = lon + delta_lon
    new_lat = lat + delta_lat
    return new_lon, new_lat

def advance_along_graph(from_id, to_id, offset, distance):
    """Проходить distance метрів вздовж вулиць, починаючи з позиції offset на ребрі from->to.
    На перехрестях обирає випадкове ребро без розвороту (назад — лише в глухому куті)."""
    remaining = distance
    while True:
        left_on_edge = edge_len_map[(from_id, to_id)] - offset
        if remaining < left_on_edge:
            return from_id, to_id, offset + remaining

        remaining -= left_on_edge
        options = neighbors_map.get(to_id, [])
        if not options:
            # вузол без виходу (рідкість): відроджуємо точку в іншому місці
            from_id = random.choice(movable_nodes)
            return from_id, random.choice(neighbors_map[from_id]), 0.0

        forward = [n for n in options if n != from_id]
        next_id = random.choice(forward if forward else options)
        from_id, to_id, offset = to_id, next_id, 0.0


def position_on_edge(from_id, to_id, offset):
    """Координати точки на відстані offset метрів від from_id вздовж ребра до to_id."""
    t = offset / edge_len_map[(from_id, to_id)]
    a, b = G.nodes[from_id], G.nodes[to_id]
    return a["x"] + (b["x"] - a["x"]) * t, a["y"] + (b["y"] - a["y"]) * t


@app.get("/newcoordinates")
@locked
def get_new_coordinates():
    """Кожна точка проходить MOVEMENT_STEP_M метрів вулицями (рівномірна швидкість,
    можливо через кілька ребер за крок)."""
    for point_id in list(points.keys()):
        _, _, from_id, to_id, offset = points[point_id]

        from_id, to_id, offset = advance_along_graph(from_id, to_id, offset, MOVEMENT_STEP_M)
        x, y = position_on_edge(from_id, to_id, offset)

        # Похибка додається лише до відображуваної позиції, "справжній" стан лишається точним
        x, y = add_gps_error(x, y, 1, GPS_ERROR_MAX_M)

        points[point_id] = [x, y, from_id, to_id, offset]
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
@locked
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

# Реінфекція: одужалі можуть заразитися знову. Вмикається/вимикається через /params
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


class EpidemicParams(BaseModel):
    infection_probability: float = Field(..., ge=0, le=1)
    death_probability: float = Field(..., ge=0, le=1)
    recovery_probability: float = Field(..., ge=0, le=1)
    infection_radius_m: float = Field(..., gt=0, le=10000)
    incubation_min_steps: int = Field(..., ge=0, le=1000)
    incubation_max_steps: int = Field(..., ge=0, le=1000)
    reinfection_factor: float = Field(..., ge=0, le=1)
    reinfection_enabled: bool
    movement_step_m: float = Field(..., gt=0, le=5000)
    gps_error_max_m: float = Field(..., ge=0, le=100)


def current_params():
    return {
        "infection_probability": INFECTION_PROBABILITY,
        "death_probability": DEATH_PROBABILITY,
        "recovery_probability": RECOVERY_PROBABILITY,
        "infection_radius_m": INFECTION_RADIUS_M,
        "incubation_min_steps": INCUBATION_MIN_STEPS,
        "incubation_max_steps": INCUBATION_MAX_STEPS,
        "reinfection_factor": REINFECTION_FACTOR,
        "reinfection_enabled": REINFECTION_ENABLED,
        "movement_step_m": MOVEMENT_STEP_M,
        "gps_error_max_m": GPS_ERROR_MAX_M,
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
    global REINFECTION_FACTOR, REINFECTION_ENABLED
    global MOVEMENT_STEP_M, GPS_ERROR_MAX_M

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
    REINFECTION_ENABLED = p.reinfection_enabled
    MOVEMENT_STEP_M = p.movement_step_m
    GPS_ERROR_MAX_M = p.gps_error_max_m
    return current_params()


@app.get("/init_epidemic")
@locked
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
    }


@app.get("/step_epidemic")
@locked
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
    }
