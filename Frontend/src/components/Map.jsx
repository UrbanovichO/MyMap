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

const Map = () => {
    const city_position = [49.4206, 26.9975]; 
    const [points_list, setPoint_list] = useState([])
    const [new_points_list, setNewPoint_list] = useState([])
    const [loading, setLoading] = useState(true)
    const fetchPoints = () => {
        axios.get('http://127.0.0.1:8000/coordinates').then(r => {
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

    useEffect( () => {
        fetchPoints()    
        const interval = setInterval(() => {
            fetchNewPoints()
        }, 2000);
        return () => clearInterval(interval);
    }, [])
    

    return (
        <MapContainer 
        center={city_position} 
        zoom={13} 
        style={{ height: "100%", width: "100%" }}
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
                duration={1500} // Час плавного переходу в мс
            />
        ))}
        </MapContainer> 
    );
};
export default Map;