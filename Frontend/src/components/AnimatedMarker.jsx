import React, { useEffect, useRef } from 'react';
import { Marker } from 'react-leaflet';

// ---------------------------------------------------------------------------
// Один спільний цикл requestAnimationFrame для всіх маркерів
// (замість окремого циклу на кожен із 1000 маркерів).
// ---------------------------------------------------------------------------
const FRAME_MS = 33; // ~30 кадрів/с: для повільного руху це візуально плавно, а DOM навантажується вдвічі менше

const animators = new Set(); // кожен елемент — функція step(now), що повертає true, поки анімація триває
let rafId = null;
let lastFrame = 0;

const tick = (now) => {
    if (now - lastFrame >= FRAME_MS) {
        lastFrame = now;
        for (const step of animators) {
            if (!step(now)) animators.delete(step); // видалення під час обходу Set безпечне
        }
    }
    rafId = animators.size > 0 ? requestAnimationFrame(tick) : null;
};

const startAnimator = (step) => {
    animators.add(step);
    if (rafId === null) rafId = requestAnimationFrame(tick);
};

// ---------------------------------------------------------------------------
// Маркер, що безперервно їде до останньої отриманої точки.
//
// Чому він не зупиняється між оновленнями:
//  1. Рух ЛІНІЙНИЙ (без ease-in/ease-out), тому швидкість не падає до нуля на кінці відрізка.
//  2. Новий відрізок завжди починається з ПОТОЧНОЇ позиції маркера на екрані,
//     а не з попередньої цільової точки — тож стрибків немає.
//  3. Тривалість руху = виміряний інтервал між оновленнями × 1.1. Маркер «доїжджає»
//     трохи пізніше, ніж приходять нові дані, тому до нової цілі він завжди ще в дорозі.
// ---------------------------------------------------------------------------
const AnimatedMarker = ({ lat, lng, icon, duration = 4000 }) => {
    const markerRef = useRef(null);
    const initialPosition = useRef([lat, lng]); // стале значення: react-leaflet не «смикатиме» маркер при рендері
    const shown = useRef({ lat, lng });          // де маркер зараз на екрані
    const motion = useRef({ from: { lat, lng }, to: { lat, lng }, start: 0, duration });
    const lastUpdate = useRef(null);
    const avgInterval = useRef(duration);        // згладжений інтервал між оновленнями, мс
    const stepRef = useRef(null);

    if (stepRef.current === null) {
        stepRef.current = (now) => {
            const m = motion.current;
            const t = Math.min(1, Math.max(0, (now - m.start) / m.duration));
            const pos = {
                lat: m.from.lat + (m.to.lat - m.from.lat) * t,
                lng: m.from.lng + (m.to.lng - m.from.lng) * t,
            };
            shown.current = pos;
            if (markerRef.current) markerRef.current.setLatLng([pos.lat, pos.lng]);
            return t < 1;
        };
    }

    // Надійшла нова ціль -> розпочати новий відрізок з поточної позиції
    useEffect(() => {
        const now = performance.now();
        if (lastUpdate.current !== null) {
            const interval = now - lastUpdate.current;
            avgInterval.current = 0.5 * avgInterval.current + 0.5 * interval;
        }
        lastUpdate.current = now;

        motion.current = {
            from: { ...shown.current },
            to: { lat, lng },
            start: now,
            duration: avgInterval.current * 1.1,
        };
        startAnimator(stepRef.current);
    }, [lat, lng]);

    // При видаленні маркера (наприклад, померла точка) — прибрати його з циклу анімації
    useEffect(() => {
        const step = stepRef.current;
        return () => animators.delete(step);
    }, []);

    return <Marker ref={markerRef} position={initialPosition.current} icon={icon} />;
};

export default AnimatedMarker;
