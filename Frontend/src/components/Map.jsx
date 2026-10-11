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

// Як часто запитувати нові координати та кроки епідемії (мс)
const MOVE_INTERVAL_MS = 1000;
const EPIDEMIC_INTERVAL_MS = 2000;

// Іконки створюються один раз на стан і перевикористовуються.
// Якщо створювати новий L.divIcon при кожному рендері, react-leaflet вважає іконку зміненою
// і перемальовує DOM усіх маркерів — це викликає підлагування й уривчастий рух.
const ICON_CACHE = {};
const getStateIcon = (state) => {
    if (!ICON_CACHE[state]) {
        const color = STATE_COLORS[state] || 'gray';
        ICON_CACHE[state] = L.divIcon({
            html: `<div style="background-color: ${color}; width: 20px; height: 20px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.5);"></div>`,
            className: 'custom-circle-marker',
            iconSize: [20, 20],
            iconAnchor: 10,
        });
    }
    return ICON_CACHE[state];
};

// Опитування «після відповіді»: наступний запит стартує, коли попередній завершився
// (з урахуванням витраченого часу). На відміну від setInterval, запити не накладаються
// й не наздоганяють один одного, якщо сервер відповідає повільніше за інтервал.
const startPolling = (task, intervalMs) => {
    let stopped = false;
    let timer = null;
    const loop = async () => {
        const startedAt = Date.now();
        try {
            await task();
        } catch (err) {
            console.error('Помилка запиту:', err);
        }
        if (stopped) return;
        timer = setTimeout(loop, Math.max(0, intervalMs - (Date.now() - startedAt)));
    };
    loop();
    return () => {
        stopped = true;
        clearTimeout(timer);
    };
};

// Поля панелі налаштувань: key відповідає полю в /params на бекенді,
// default — стандартне значення (збігається з початковими значеннями на бекенді)
const PARAM_FIELDS = [
    { key: 'infection_probability', label: 'Шанс зараження (0–1)', step: 0.05, min: 0, max: 1, default: 0.6 },
    { key: 'death_probability', label: 'Смертність за крок (0–1)', step: 0.01, min: 0, max: 1, default: 0.1 },
    { key: 'recovery_probability', label: 'Шанс одужання за крок (0–1)', step: 0.01, min: 0, max: 1, default: 0.05 },
    { key: 'infection_radius_m', label: 'Радіус зараження (м)', step: 5, min: 1, max: 10000, default: 150 },
    { key: 'movement_step_m', label: 'Швидкість руху (м за крок)', step: 10, min: 1, max: 5000, default: 50 },
    { key: 'gps_error_max_m', label: 'Похибка GPS, макс. (м)', step: 1, min: 0, max: 100, default: 10 },
    { key: 'incubation_min_steps', label: 'Інкубація, мін. (кроків)', step: 1, min: 0, max: 1000, default: 2 },
    { key: 'incubation_max_steps', label: 'Інкубація, макс. (кроків)', step: 1, min: 0, max: 1000, default: 5 },
    { key: 'reinfection_factor', label: 'Вразливість одужалих (0–1)', step: 0.05, min: 0, max: 1, default: 0.3 },
];

const DEFAULT_PARAMS = {
    ...Object.fromEntries(PARAM_FIELDS.map((f) => [f.key, f.default])),
    reinfection_enabled: true,
};

// Стилі панелі параметрів: щільніший шрифт, чорні рамки, крупніший текст
const SETTINGS_FONT = "Verdana, 'Segoe UI', Tahoma, sans-serif";

const settingsInputStyle = {
    width: "84px",
    padding: "5px 8px",
    fontSize: "15px",
    fontWeight: 700,
    fontFamily: SETTINGS_FONT,
    color: "#000",
    background: "#fff",
    border: "2px solid #000",
    borderRadius: "5px",
    textAlign: "right",
};

// CSS кнопок панелі параметрів (потрібен окремо, бо inline-стилі не вміють :hover / :active)
const SETTINGS_BUTTON_CSS = `
.settings-btn {
    padding: 9px 16px;
    font-size: 14px;
    font-weight: 800;
    font-family: ${SETTINGS_FONT};
    color: #000;
    background: #f2f2f2;
    border: 2px solid #000;
    border-radius: 8px;
    box-shadow: 0 3px 0 #000;
    cursor: pointer;
    transition: transform 0.08s, box-shadow 0.08s, filter 0.15s;
}
.settings-btn:hover {
    filter: brightness(1.08);
    transform: translateY(-1px);
    box-shadow: 0 4px 0 #000;
}
.settings-btn:active {
    transform: translateY(3px);
    box-shadow: 0 0 0 #000;
}
.settings-btn--apply {
    background: #2ecc71;
}
.settings-btn--restart {
    background: #d32f2f;
    color: #fff;
}
`;

const Map = () => {
    const city_position = [49.4206, 26.9975]; 
    const [points_list, setPoint_list] = useState([])
    const [new_points_list, setNewPoint_list] = useState([])
    const [loading, setLoading] = useState(true)
    const [states_list, setStates_list] = useState({})
    const [stats, setStats] = useState({ healthy: 0, exposed: 0, infected: 0, recovered: 0, dead: 0 })
    const [params_draft, setParamsDraft] = useState(DEFAULT_PARAMS)
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

    const fetchNewPoints = () => {
        return axios.get('http://127.0.0.1:8000/newcoordinates').then(r => {
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
            console.log('patient_zero:', initResponce.patient_zero)
        })
    }

    // Отримання інформації про заражені точки (один крок симуляції)
    const fetchEpidemicStep = () => {
        return axios.get('http://127.0.0.1:8000/step_epidemic').then(r => {
            const stepResponce = r.data
            const newStates = stepResponce.states
            setStates_list(newStates)
            setStats(stepResponce.stats)
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
        payload.reinfection_enabled = Boolean(params_draft.reinfection_enabled)
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

    // Початкове завантаження: точки, параметри і стани. Рух та епідемія ще не йдуть.
    useEffect( () => {
        // initEpidemic потребує, щоб бекенд уже створив точки, тому чекаємо на /coordinates
        fetchPoints().then(() => initEpidemic())
        fetchParams()
    }, [])

    // Цикл симуляції: працює лише поки running === true
    useEffect( () => {
        if (!running) return
        const stopMoving = startPolling(fetchNewPoints, MOVE_INTERVAL_MS)
        const stopEpidemic = startPolling(fetchEpidemicStep, EPIDEMIC_INTERVAL_MS)
        return () => {
            stopMoving()
            stopEpidemic()
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
                    duration={MOVE_INTERVAL_MS} // Початкова оцінка тривалості переходу в мс (далі уточнюється за реальним інтервалом)
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
                    background: "rgba(255, 255, 255, 0.96)",
                    borderRadius: "10px",
                    padding: "14px 18px",
                    boxShadow: "0 2px 10px rgba(0,0,0,0.4)",
                    fontFamily: SETTINGS_FONT,
                    fontSize: "15px",
                    fontWeight: 600,
                    color: "#000",
                    width: "380px",
                    maxWidth: "calc(100% - 40px)",
                    boxSizing: "border-box",
                }}
            >
                <div
                    style={{ fontWeight: 800, fontSize: "17px", cursor: "pointer" }}
                    onClick={() => setSettingsOpen(!settingsOpen)}
                >
                    ⚙ Параметри {settingsOpen ? '▲' : '▼'}
                </div>
                {settingsOpen && (
                    <div style={{ marginTop: "12px" }}>
                        {PARAM_FIELDS.map((field) => (
                            <label
                                key={field.key}
                                style={{
                                    display: "flex",
                                    justifyContent: "space-between",
                                    alignItems: "center",
                                    gap: "10px",
                                    marginBottom: "10px",
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
                                    disabled={field.key === 'reinfection_factor' && !params_draft.reinfection_enabled}
                                    style={{
                                        ...settingsInputStyle,
                                        opacity: field.key === 'reinfection_factor' && !params_draft.reinfection_enabled ? 0.4 : 1,
                                    }}
                                />
                            </label>
                        ))}
                        <label
                            style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                gap: "10px",
                                marginBottom: "10px",
                                cursor: "pointer",
                            }}
                        >
                            <span>Реінфекція (повторне зараження)</span>
                            <input
                                type="checkbox"
                                checked={Boolean(params_draft.reinfection_enabled)}
                                onChange={(e) =>
                                    setParamsDraft({ ...params_draft, reinfection_enabled: e.target.checked })
                                }
                                style={{ width: "22px", height: "22px", accentColor: "#000", cursor: "pointer" }}
                            />
                        </label>
                        <style>{SETTINGS_BUTTON_CSS}</style>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", marginTop: "16px" }}>
                            <button className="settings-btn settings-btn--apply" onClick={applyParams}>
                                ✔ Застосувати
                            </button>
                            <button className="settings-btn" onClick={() => setParamsDraft(DEFAULT_PARAMS)}>
                                Стандартні значення
                            </button>
                            <button className="settings-btn settings-btn--restart" onClick={restartEpidemic}>
                                ↻ Перезапустити епідемію
                            </button>
                        </div>
                        {paramsMessage && (
                            <div style={{ marginTop: "10px", fontWeight: 700, color: paramsMessage.ok ? '#1e7e34' : '#c00' }}>
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
            </div>
        </div>
    );
};
export default Map;