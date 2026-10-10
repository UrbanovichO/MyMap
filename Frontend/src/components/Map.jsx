import React, { useEffect, useState , useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import axios, { Axios } from 'axios';
import AnimatedMarker from './AnimatedMarker';



delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
    iconRetinaUrl: 'https://cloudflare.com',
    iconUrl: 'https://cloudflare.com',
    shadowUrl: 'https://cloudflare.com',
});

const STATE_COLORS = {
    healthy: 'green',
    exposed: 'orange',
    infected: 'red',
    recovered: 'blue',
    dead: 'black',
};

// Поля панелі налаштувань: ключ відповідає полю в /params на бекенді
const PARAM_FIELDS = [
    { key: 'infection_probability', label: 'Шанс зараження (0–1)', step: 0.05, min: 0, max: 1 },
    { key: 'death_probability', label: 'Смертність за крок (0–1)', step: 0.01, min: 0, max: 1 },
    { key: 'recovery_probability', label: 'Шанс одужання за крок (0–1)', step: 0.01, min: 0, max: 1 },
    { key: 'infection_radius_m', label: 'Радіус зараження (м)', step: 5, min: 1, max: 10000 },
    { key: 'incubation_min_steps', label: 'Інкубація, мін. (кроків)', step: 1, min: 0, max: 1000 },
    { key: 'incubation_max_steps', label: 'Інкубація, макс. (кроків)', step: 1, min: 0, max: 1000 },
    { key: 'reinfection_factor', label: 'Вразливість одужалих (0–1)', step: 0.05, min: 0, max: 1 },
];

const Map = () => {
    const city_position = [49.4206, 26.9975]; 
    const [points_list, setPoint_list] = useState([])
    const [new_points_list, setNewPoint_list] = useState([])
    const [loading, setLoading] = useState(true)
    const [states_list, setStates_list] = useState({})
    const [stats, setStats] = useState({ healthy: 0, exposed: 0, infected: 0, recovered: 0, dead: 0 })
    const [reinfectionEnabled, setReinfectionEnabled] = useState(true)
    const [params_draft, setParamsDraft] = useState({})
    const [settingsOpen, setSettingsOpen] = useState(false)
    const [paramsMessage, setParamsMessage] = useState(null)
    const [running, setRunning] = useState(false)  // симуляція стартує тільки після натискання кнопки
    const fetchPoints = () => {
        return axios.get('http://127.0.0.1:8000/coordinates').then(r => {
            const pointsResponce = r.data 
            const coordinate_data = []
            for(const [id, coordinate] of Object.entries(pointsResponce)){
                const x = coordinate[1]
                const y = coordinate[0]
                coordinate_data.push({id : id , lat : x , lng : y})
            }
            setPoint_list(coordinate_data);
            setLoading(false);
            console.log(points_list)     
        })
    }
    const redCircleIcon = L.divIcon({
  // HTML-структура з CSS для створення кола
        html: '<div style="background-color: red; width: 20px; height: 20px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.5);"></div>',
        className: 'custom-circle-marker', // Обов'язково вкажіть клас (можна порожній), щоб скинути стандартні стилі Leaflet
        iconSize:[20,20],               // Розмір всього контейнера іконки [ширина, висота]
        iconAnchor:10,             // Центр кола (половина від iconSize), щоб маркер стояв точно на координаті
    });
     // Іконка, що будується динамічно за станом точки (колір змінюється залежно від стану)
    const getStateIcon = (state) => {
        const color = STATE_COLORS[state];
        return L.divIcon({
            html: `<div style="background-color: ${color}; width: 20px; height: 20px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.5);"></div>`,
            className: 'custom-circle-marker',
            iconSize: [20, 20],
            iconAnchor: 10,
        });
    }

    const fetchNewPoints = () => {
        axios.get('http://127.0.0.1:8000/newcoordinates').then(r => {
            const newPointsResponce = r.data
            const newCoordinate_data = []
            for(const [id, coordinate] of Object.entries(newPointsResponce)){
                const x = coordinate[1]
                const y = coordinate[0]
                const direction = coordinate[2]
                newCoordinate_data.push({id : id , lat : x , lng : y, direction: direction})
            }
            setPoint_list(newCoordinate_data)
            console.log(new_points_list) 
        })
    }

    const initEpidemic = () => {
        axios.get('http://127.0.0.1:8000/init_epidemic').then(r => {
            const initResponce = r.data
            setStates_list(initResponce.states)
            setStats(initResponce.stats)
            setReinfectionEnabled(initResponce.reinfection_enabled)
            console.log('patient_zero:', initResponce.patient_zero)
        })
    }

    // Отримання інформації про заражені точки (один крок симуляції)
    const fetchEpidemicStep = () => {
        axios.get('http://127.0.0.1:8000/step_epidemic').then(r => {
            const stepResponce = r.data
            const newStates = stepResponce.states
            setStates_list(newStates)
            setStats(stepResponce.stats)
            setReinfectionEnabled(stepResponce.reinfection_enabled)
            setPoint_list(prev => prev.filter(point => newStates.hasOwnProperty(point.id)))
        })
    }

    // Завантаження поточних параметрів симуляції з бекенду
    const fetchParams = () => {
        axios.get('http://127.0.0.1:8000/params').then(r => {
            setParamsDraft(r.data)
        })
    }

    // Відправка змінених параметрів на бекенд (діють з наступного кроку симуляції)
    const applyParams = () => {
        const payload = {}
        for (const field of PARAM_FIELDS) {
            payload[field.key] = Number(params_draft[field.key])
        }
        axios.post('http://127.0.0.1:8000/params', payload).then(r => {
            setParamsDraft(r.data)
            setParamsMessage({ ok: true, text: 'Застосовано' })
        }).catch(err => {
            const detail = err.response?.data?.detail
            // 422 від FastAPI повертає масив помилок, 400 — рядок
            const text = typeof detail === 'string'
                ? detail
                : 'Значення поза допустимим діапазоном'
            setParamsMessage({ ok: false, text })
        })
    }

    // Повний перезапуск: заново створюємо точки (померлі видаляються з бекенду назавжди),
    // і лише потім запускаємо епідемію
    const restartEpidemic = () => {
        fetchPoints().then(() => initEpidemic())
    }

    // Вмикання/вимикання реінфекції на бекенді
    const toggleReinfection = () => {
        axios.get(`http://127.0.0.1:8000/reinfection?enabled=${!reinfectionEnabled}`).then(r => {
            setReinfectionEnabled(r.data.reinfection_enabled)
        })
    }

    // Початкове завантаження: точки, параметри і стани. Рух та епідемія ще не йдуть.
    useEffect( () => {
        // initEpidemic потребує, щоб бекенд уже створив точки, тому чекаємо на /coordinates
        fetchPoints().then(() => initEpidemic())
        fetchParams()
    }, [])

    // Цикл симуляції: працює лише поки running === true
    useEffect( () => {
        if (!running) return
        const interval = setInterval(() => {
            fetchNewPoints()
        }, 4000);
        const epidemicInterval = setInterval(() => {
            fetchEpidemicStep()
        }, 2000);
        return () => {
            clearInterval(interval)
            clearInterval(epidemicInterval)
        };
    }, [running])
    

    return (
        <div style={{ position: "relative", height: "100%", width: "100%" }}>
            <MapContainer 
            center={city_position} 
            zoom={13} 
            style={{ height: "100%", width: "100%" }}
            fadeAnimation={false}
            >
            {/* 5. Підключаємо безкоштовні тайли OpenStreetMap */}
                <TileLayer
                    attribution='&copy; <a href="https://openstreetmap.org">OpenStreetMap</a> contributors'
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
          
            {points_list.map((point) => (
                <AnimatedMarker 
                    key={String(point.id)} // Ключ за ID — критично важливо для React!
                    id={point.id}
                    lat={point.lat}
                    lng={point.lng}
                    duration={4000} // Час плавного переходу в мс
                    icon={getStateIcon(states_list[point.id])}
                />
            ))}
            </MapContainer>

            {/* Кнопка запуску / паузи симуляції */}
            <button
                onClick={() => setRunning(!running)}
                style={{
                    position: "absolute",
                    top: "20px",
                    left: "50%",
                    transform: "translateX(-50%)",
                    zIndex: 1000,
                    padding: "10px 22px",
                    fontSize: "15px",
                    fontWeight: "bold",
                    color: "white",
                    background: running ? "#e67e22" : "#27ae60",
                    border: "none",
                    borderRadius: "8px",
                    boxShadow: "0 2px 8px rgba(0,0,0,0.3)",
                    cursor: "pointer",
                }}
            >
                {running ? "⏸ Пауза" : "▶ Запустити симуляцію"}
            </button>

            {/* Панель налаштувань у правому верхньому куті */}
            <div
                style={{
                    position: "absolute",
                    top: "20px",
                    right: "20px",
                    zIndex: 1000,
                    background: "rgba(255, 255, 255, 0.9)",
                    borderRadius: "8px",
                    padding: "10px 14px",
                    boxShadow: "0 2px 8px rgba(0,0,0,0.3)",
                    fontFamily: "sans-serif",
                    fontSize: "13px",
                    width: "250px",
                }}
            >
                <div
                    style={{ fontWeight: "bold", cursor: "pointer" }}
                    onClick={() => setSettingsOpen(!settingsOpen)}
                >
                    ⚙ Параметри {settingsOpen ? '▲' : '▼'}
                </div>
                {settingsOpen && (
                    <div style={{ marginTop: "8px" }}>
                        {PARAM_FIELDS.map((field) => (
                            <label
                                key={field.key}
                                style={{
                                    display: "flex",
                                    justifyContent: "space-between",
                                    alignItems: "center",
                                    marginBottom: "6px",
                                }}
                            >
                                <span>{field.label}</span>
                                <input
                                    type="number"
                                    step={field.step}
                                    min={field.min}
                                    max={field.max}
                                    value={params_draft[field.key] ?? ''}
                                    onChange={(e) =>
                                        setParamsDraft({ ...params_draft, [field.key]: e.target.value })
                                    }
                                    style={{ width: "70px" }}
                                />
                            </label>
                        ))}
                        <button onClick={applyParams} style={{ marginRight: "6px" }}>
                            Застосувати
                        </button>
                        <button onClick={restartEpidemic}>Перезапустити епідемію</button>
                        {paramsMessage && (
                            <div style={{ marginTop: "6px", color: paramsMessage.ok ? 'green' : 'red' }}>
                                {paramsMessage.text}
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Панель статистики в лівому нижньому куті */}
            <div
                style={{
                    position: "absolute",
                    bottom: "20px",
                    left: "20px",
                    zIndex: 1000,
                    background: "rgba(255, 255, 255, 0.9)",
                    borderRadius: "8px",
                    padding: "12px 16px",
                    boxShadow: "0 2px 8px rgba(0,0,0,0.3)",
                    fontFamily: "sans-serif",
                    fontSize: "14px",
                    lineHeight: "1.6",
                    minWidth: "140px",
                }}
            >
                <div style={{ fontWeight: "bold", marginBottom: "6px" }}>Статистика</div>
                <div><span style={{ color: STATE_COLORS.healthy }}>●</span> Здорові: {stats.healthy || 0}</div>
                <div><span style={{ color: STATE_COLORS.exposed }}>●</span> Інкубація: {stats.exposed || 0}</div>
                <div><span style={{ color: STATE_COLORS.infected }}>●</span> Заражені: {stats.infected || 0}</div>
                <div><span style={{ color: STATE_COLORS.recovered }}>●</span> Одужалі: {stats.recovered || 0}</div>
                <div><span style={{ color: STATE_COLORS.dead }}>●</span> Померлі: {stats.dead || 0}</div>
                <label style={{ display: "block", marginTop: "8px", cursor: "pointer" }}>
                    <input
                        type="checkbox"
                        checked={reinfectionEnabled}
                        onChange={toggleReinfection}
                        style={{ marginRight: "6px" }}
                    />
                    Реінфекція
                </label>
            </div>
        </div>
    );
};
export default Map;