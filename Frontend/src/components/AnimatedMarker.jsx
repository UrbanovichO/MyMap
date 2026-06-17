import React, { useEffect, useRef, useState } from 'react';
import { Marker } from 'react-leaflet';

const AnimatedMarker = ({ lat, lng, duration = 3000, ...props }) => {
  const markerRef = useRef(null);
  const animationRef = useRef(null);

  // Примусово перетворюємо в числа для захисту від рядкових даних
  const targetLat = Number(lat);
  const targetLng = Number(lng);

  // Зберігаємо поточну позицію в рефі (числа)
  const currentPosRef = useRef([targetLat, targetLng]);
  
  // Стейт потрібен тільки для ініціалізації та фіксації кінця анімації
  const [displayPosition, setDisplayPosition] = useState([targetLat, targetLng]);

  useEffect(() => {
    // Скасовуємо попередню анімацію, якщо вона активна
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current);
    }

    const startPos = [...currentPosRef.current];
    const endPos = [targetLat, targetLng];

    // Якщо координати взагалі не змінилися — нічого не анімуємо
    if (startPos[0] === endPos[0] && startPos[1] === endPos[1]) return;

    let startTimestamp = null;

    const animate = (timestamp) => {
      if (!startTimestamp) startTimestamp = timestamp;
      const elapsed = timestamp - startTimestamp;
      const progress = Math.min(elapsed / duration, 1);

      // Формула лінійної інтерполяції (LERP)
      const currentLat = startPos[0] + (endPos[0] - startPos[0]) * progress;
      const currentLng = startPos[1] + (endPos[1] - startPos[1]) * progress;
      const newPos = [currentLat, currentLng];

      // Оновлюємо реф, щоб наступний крок/анімація стартували звідси
      currentPosRef.current = newPos;

      // Рухаємо маркер на карті в обхід React (прямо через Leaflet для плавности)
      if (markerRef.current) {
        markerRef.current.setLatLng(newPos);
      }

      if (progress < 1) {
        animationRef.current = requestAnimationFrame(animate);
      } else {
        setDisplayPosition(endPos); // Синхронізуємо стейт в кінці шляху
      }
    };

    animationRef.current = requestAnimationFrame(animate);

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [targetLat, targetLng, duration]); // Ефект чітко стежить за зміною координат

  return <Marker position={displayPosition} ref={markerRef} {...props} />;
};

export default AnimatedMarker;