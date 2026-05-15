"""Mock tools the agent can call.

All tools return plain dicts/lists so the agent loop can serialize them
straight back into the conversation as tool results.

Three destinations are supported with hand-crafted POI data: Kyoto, Paris,
Goa. For anything else, search_pois returns an empty list - which is a
useful path to exercise the agent's fallback behavior.
"""

from __future__ import annotations

import math
import random
from datetime import date as _date
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration toggles (set from the UI for demos)
# ---------------------------------------------------------------------------

# When True, get_weather randomly returns an error to demo fallback behavior.
SIMULATE_WEATHER_FAILURE = False


# ---------------------------------------------------------------------------
# Hardcoded POI database
# ---------------------------------------------------------------------------

POIS: dict[str, dict[str, dict[str, Any]]] = {
    "kyoto": {
        "fushimi_inari_shrine": {
            "id": "fushimi_inari_shrine",
            "name": "Fushimi Inari Shrine",
            "category": "temple",
            "est_cost_per_person": 0,
            "currency": "JPY",
            "est_duration_min": 120,
            "rating": 4.8,
            "opening_hours": "00:00-24:00",
            "tags": ["iconic", "outdoor", "photo", "hike-light"],
            "lat": 34.9671,
            "lon": 135.7727,
        },
        "kinkakuji": {
            "id": "kinkakuji",
            "name": "Kinkaku-ji (Golden Pavilion)",
            "category": "temple",
            "est_cost_per_person": 500,
            "currency": "JPY",
            "est_duration_min": 60,
            "rating": 4.6,
            "opening_hours": "09:00-17:00",
            "tags": ["iconic", "garden", "photo"],
            "lat": 35.0394,
            "lon": 135.7292,
        },
        "arashiyama_bamboo": {
            "id": "arashiyama_bamboo",
            "name": "Arashiyama Bamboo Grove",
            "category": "nature",
            "est_cost_per_person": 0,
            "currency": "JPY",
            "est_duration_min": 90,
            "rating": 4.5,
            "opening_hours": "00:00-24:00",
            "tags": ["nature", "photo", "walk"],
            "lat": 35.0094,
            "lon": 135.6722,
        },
        "gion_district": {
            "id": "gion_district",
            "name": "Gion District (geisha quarter)",
            "category": "culture",
            "est_cost_per_person": 0,
            "currency": "JPY",
            "est_duration_min": 120,
            "rating": 4.4,
            "opening_hours": "17:00-23:00",
            "tags": ["evening", "walk", "atmospheric"],
            "lat": 35.0036,
            "lon": 135.7780,
        },
        "nishiki_market": {
            "id": "nishiki_market",
            "name": "Nishiki Market",
            "category": "food",
            "est_cost_per_person": 2500,
            "currency": "JPY",
            "est_duration_min": 90,
            "rating": 4.4,
            "opening_hours": "09:30-18:00",
            "tags": ["food", "tasting", "covered"],
            "lat": 35.0050,
            "lon": 135.7647,
        },
        "kiyomizu_dera": {
            "id": "kiyomizu_dera",
            "name": "Kiyomizu-dera",
            "category": "temple",
            "est_cost_per_person": 400,
            "currency": "JPY",
            "est_duration_min": 90,
            "rating": 4.7,
            "opening_hours": "06:00-18:00",
            "tags": ["iconic", "view", "photo"],
            "lat": 34.9949,
            "lon": 135.7850,
        },
        "ryoanji": {
            "id": "ryoanji",
            "name": "Ryoan-ji (Zen rock garden)",
            "category": "temple",
            "est_cost_per_person": 600,
            "currency": "JPY",
            "est_duration_min": 60,
            "rating": 4.4,
            "opening_hours": "08:00-17:00",
            "tags": ["zen", "garden", "quiet"],
            "lat": 35.0344,
            "lon": 135.7183,
        },
        "philosophers_path": {
            "id": "philosophers_path",
            "name": "Philosopher's Path",
            "category": "nature",
            "est_cost_per_person": 0,
            "currency": "JPY",
            "est_duration_min": 60,
            "rating": 4.3,
            "opening_hours": "00:00-24:00",
            "tags": ["walk", "scenic", "spring-cherry"],
            "lat": 35.0270,
            "lon": 135.7944,
        },
        "nijo_castle": {
            "id": "nijo_castle",
            "name": "Nijo Castle",
            "category": "history",
            "est_cost_per_person": 1300,
            "currency": "JPY",
            "est_duration_min": 90,
            "rating": 4.4,
            "opening_hours": "08:45-16:00",
            "tags": ["history", "indoor", "shogun"],
            "lat": 35.0142,
            "lon": 135.7481,
        },
        "pontocho_dinner": {
            "id": "pontocho_dinner",
            "name": "Pontocho Alley Dinner",
            "category": "food",
            "est_cost_per_person": 4500,
            "currency": "JPY",
            "est_duration_min": 90,
            "rating": 4.5,
            "opening_hours": "17:00-23:00",
            "tags": ["dinner", "atmospheric", "kaiseki"],
            "lat": 35.0050,
            "lon": 135.7710,
        },
    },
    "paris": {
        "eiffel_tower": {
            "id": "eiffel_tower",
            "name": "Eiffel Tower",
            "category": "landmark",
            "est_cost_per_person": 29,
            "currency": "EUR",
            "est_duration_min": 120,
            "rating": 4.6,
            "opening_hours": "09:00-23:45",
            "tags": ["iconic", "view"],
            "lat": 48.8584,
            "lon": 2.2945,
        },
        "louvre": {
            "id": "louvre",
            "name": "Louvre Museum",
            "category": "museum",
            "est_cost_per_person": 22,
            "currency": "EUR",
            "est_duration_min": 180,
            "rating": 4.7,
            "opening_hours": "09:00-18:00",
            "tags": ["art", "indoor"],
            "lat": 48.8606,
            "lon": 2.3376,
        },
        "notre_dame": {
            "id": "notre_dame",
            "name": "Notre-Dame Cathedral (exterior)",
            "category": "landmark",
            "est_cost_per_person": 0,
            "currency": "EUR",
            "est_duration_min": 45,
            "rating": 4.5,
            "opening_hours": "00:00-24:00",
            "tags": ["history", "exterior"],
            "lat": 48.8530,
            "lon": 2.3499,
        },
        "sacre_coeur": {
            "id": "sacre_coeur",
            "name": "Sacré-Cœur & Montmartre",
            "category": "landmark",
            "est_cost_per_person": 0,
            "currency": "EUR",
            "est_duration_min": 120,
            "rating": 4.6,
            "opening_hours": "06:00-22:30",
            "tags": ["view", "walk", "evening"],
            "lat": 48.8867,
            "lon": 2.3431,
        },
        "musee_dorsay": {
            "id": "musee_dorsay",
            "name": "Musée d'Orsay",
            "category": "museum",
            "est_cost_per_person": 16,
            "currency": "EUR",
            "est_duration_min": 150,
            "rating": 4.7,
            "opening_hours": "09:30-18:00",
            "tags": ["art", "indoor", "impressionist"],
            "lat": 48.8600,
            "lon": 2.3266,
        },
        "seine_cruise": {
            "id": "seine_cruise",
            "name": "Seine River Cruise",
            "category": "experience",
            "est_cost_per_person": 18,
            "currency": "EUR",
            "est_duration_min": 60,
            "rating": 4.3,
            "opening_hours": "10:00-22:00",
            "tags": ["water", "view", "evening-option"],
            "lat": 48.8606,
            "lon": 2.3290,
        },
        "le_marais_dinner": {
            "id": "le_marais_dinner",
            "name": "Le Marais Bistro Dinner",
            "category": "food",
            "est_cost_per_person": 45,
            "currency": "EUR",
            "est_duration_min": 90,
            "rating": 4.4,
            "opening_hours": "18:30-23:00",
            "tags": ["dinner", "bistro"],
            "lat": 48.8566,
            "lon": 2.3622,
        },
        "versailles": {
            "id": "versailles",
            "name": "Palace of Versailles (day trip)",
            "category": "history",
            "est_cost_per_person": 27,
            "currency": "EUR",
            "est_duration_min": 360,
            "rating": 4.6,
            "opening_hours": "09:00-17:30",
            "tags": ["day-trip", "garden", "indoor-outdoor"],
            "lat": 48.8049,
            "lon": 2.1204,
        },
    },
    "goa": {
        "baga_beach": {
            "id": "baga_beach",
            "name": "Baga Beach",
            "category": "beach",
            "est_cost_per_person": 0,
            "currency": "INR",
            "est_duration_min": 180,
            "rating": 4.3,
            "opening_hours": "00:00-24:00",
            "tags": ["beach", "lively", "water-sports"],
            "lat": 15.5563,
            "lon": 73.7517,
        },
        "anjuna_flea_market": {
            "id": "anjuna_flea_market",
            "name": "Anjuna Flea Market (Wed)",
            "category": "shopping",
            "est_cost_per_person": 1500,
            "currency": "INR",
            "est_duration_min": 120,
            "rating": 4.2,
            "opening_hours": "08:00-18:00",
            "tags": ["market", "shopping", "weekly"],
            "lat": 15.5736,
            "lon": 73.7456,
        },
        "old_goa_churches": {
            "id": "old_goa_churches",
            "name": "Old Goa Churches (Basilica of Bom Jesus)",
            "category": "history",
            "est_cost_per_person": 0,
            "currency": "INR",
            "est_duration_min": 120,
            "rating": 4.5,
            "opening_hours": "09:00-18:30",
            "tags": ["history", "unesco", "indoor"],
            "lat": 15.5009,
            "lon": 73.9116,
        },
        "dudhsagar_falls": {
            "id": "dudhsagar_falls",
            "name": "Dudhsagar Falls (jeep tour)",
            "category": "nature",
            "est_cost_per_person": 2500,
            "currency": "INR",
            "est_duration_min": 360,
            "rating": 4.6,
            "opening_hours": "08:00-17:00",
            "tags": ["day-trip", "nature", "monsoon-spectacular"],
            "lat": 15.3144,
            "lon": 74.3144,
        },
        "spice_plantation": {
            "id": "spice_plantation",
            "name": "Sahakari Spice Plantation Tour",
            "category": "experience",
            "est_cost_per_person": 1200,
            "currency": "INR",
            "est_duration_min": 180,
            "rating": 4.4,
            "opening_hours": "09:00-16:00",
            "tags": ["tour", "lunch-included", "cultural"],
            "lat": 15.4116,
            "lon": 74.0394,
        },
        "fontainhas": {
            "id": "fontainhas",
            "name": "Fontainhas (Latin Quarter)",
            "category": "culture",
            "est_cost_per_person": 0,
            "currency": "INR",
            "est_duration_min": 90,
            "rating": 4.4,
            "opening_hours": "00:00-24:00",
            "tags": ["walk", "colonial", "photo"],
            "lat": 15.4969,
            "lon": 73.8330,
        },
        "chapora_fort": {
            "id": "chapora_fort",
            "name": "Chapora Fort (sunset)",
            "category": "history",
            "est_cost_per_person": 0,
            "currency": "INR",
            "est_duration_min": 60,
            "rating": 4.3,
            "opening_hours": "09:00-18:00",
            "tags": ["sunset", "view", "ruins"],
            "lat": 15.6053,
            "lon": 73.7367,
        },
        "panjim_dinner": {
            "id": "panjim_dinner",
            "name": "Panjim Goan Dinner",
            "category": "food",
            "est_cost_per_person": 1500,
            "currency": "INR",
            "est_duration_min": 90,
            "rating": 4.5,
            "opening_hours": "19:00-23:00",
            "tags": ["dinner", "goan-cuisine"],
            "lat": 15.4989,
            "lon": 73.8278,
        },
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_location(location: str) -> str:
    """Map a free-form location name to a city key in POIS."""
    loc = location.lower().strip()
    for key in POIS.keys():
        if key in loc or loc in key:
            return key
    return loc  # unknown - will yield empty results


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _find_poi(poi_ref: str) -> Optional[dict]:
    """Look up a POI by id or by name match across all cities."""
    ref = poi_ref.lower().strip()
    for city in POIS.values():
        if ref in city:
            return city[ref]
        for poi in city.values():
            if poi["name"].lower() == ref or ref in poi["name"].lower():
                return poi
    return None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def get_weather(location: str, date: str) -> dict:
    """Return mock weather for a location/date.

    Args:
        location: free-form city name ("Kyoto", "kyoto japan", ...)
        date: ISO date "YYYY-MM-DD"
    """
    if SIMULATE_WEATHER_FAILURE and random.random() < 0.5:
        return {"error": "service_unavailable", "detail": "Mock weather API timed out."}

    # Deterministic-ish mock by month
    try:
        month = int(date.split("-")[1])
    except Exception:
        month = 5

    city_climate = {
        "kyoto": {
            (3, 4, 5): ("partly_cloudy", 16, 0.25),
            (6, 7, 8): ("hot_humid", 30, 0.45),
            (9, 10, 11): ("clear", 18, 0.20),
            (12, 1, 2): ("cold_clear", 6, 0.15),
        },
        "paris": {
            (3, 4, 5): ("mild_cloudy", 14, 0.35),
            (6, 7, 8): ("warm", 23, 0.20),
            (9, 10, 11): ("cool_rain", 13, 0.45),
            (12, 1, 2): ("cold_wet", 6, 0.50),
        },
        "goa": {
            (3, 4, 5): ("hot_clear", 32, 0.10),
            (6, 7, 8): ("monsoon_heavy", 27, 0.85),
            (9, 10, 11): ("warm_humid", 29, 0.30),
            (12, 1, 2): ("warm_clear", 28, 0.05),
        },
    }
    loc = _normalize_location(location)
    climate = city_climate.get(loc, {(3, 4, 5): ("mild", 20, 0.2)})
    for months, (cond, temp, precip) in climate.items():
        if month in months:
            return {
                "location": location,
                "date": date,
                "condition": cond,
                "temp_c": temp,
                "precipitation_chance": precip,
            }
    return {
        "location": location,
        "date": date,
        "condition": "mild",
        "temp_c": 20,
        "precipitation_chance": 0.2,
    }


def get_distance(from_poi: str, to_poi: str, mode: str) -> dict:
    """Travel time/distance between two POIs.

    mode: 'walk' | 'transit' | 'taxi'
    """
    a = _find_poi(from_poi)
    b = _find_poi(to_poi)
    if a is None or b is None:
        return {
            "error": "unknown_poi",
            "detail": f"Could not resolve one of: {from_poi!r}, {to_poi!r}",
        }
    km = _haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
    speed_kmh = {"walk": 4.5, "transit": 20.0, "taxi": 28.0}.get(mode, 20.0)
    minutes = int(round((km / speed_kmh) * 60 + (5 if mode == "transit" else 0)))
    return {
        "from": a["name"],
        "to": b["name"],
        "mode": mode,
        "km": round(km, 2),
        "minutes": max(minutes, 1),
    }


def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Mock FX. Rates fixed against INR for reproducibility."""
    # Approx rates as of mid-2025 (mock; do not trust)
    to_inr = {
        "INR": 1.0,
        "JPY": 0.55,
        "EUR": 92.0,
        "USD": 84.0,
        "GBP": 108.0,
    }
    f, t = from_currency.upper(), to_currency.upper()
    if f not in to_inr or t not in to_inr:
        return {"error": "unknown_currency", "detail": f"{f} or {t} not supported."}
    rate = to_inr[f] / to_inr[t]
    return {
        "amount": amount,
        "from": f,
        "to": t,
        "rate": round(rate, 6),
        "converted": round(amount * rate, 2),
        "as_of": _date.today().isoformat(),
    }


def search_pois(location: str, category: str, limit: int = 5) -> list[dict]:
    """Find POIs in a city by category.

    category examples: 'temple', 'food', 'beach', 'museum', 'nature',
    'history', 'shopping', 'landmark', 'experience', 'culture'.
    """
    loc = _normalize_location(location)
    city = POIS.get(loc, {})
    cat = category.lower().strip()
    matches = [p for p in city.values() if cat == p["category"] or cat in p["tags"]]
    matches.sort(key=lambda p: -p["rating"])
    return matches[:limit]


def get_poi_details(poi_id: str) -> dict:
    """Return enriched detail for one POI."""
    poi = _find_poi(poi_id)
    if poi is None:
        return {"error": "unknown_poi", "detail": f"No POI matching {poi_id!r}."}
    return dict(poi)  # already has the relevant fields in our mock


# ---------------------------------------------------------------------------
# Registry used by the agent loop
# ---------------------------------------------------------------------------

TOOLS = {
    "get_weather": get_weather,
    "get_distance": get_distance,
    "convert_currency": convert_currency,
    "search_pois": search_pois,
    "get_poi_details": get_poi_details,
}


def execute_tool(name: str, args: dict) -> dict | list:
    """Dispatch a tool call. Returns the raw tool result (dict or list)."""
    if name not in TOOLS:
        return {"error": "unknown_tool", "detail": f"Tool {name!r} does not exist."}
    fn = TOOLS[name]
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": "bad_arguments", "detail": str(e)}
    except Exception as e:  # pragma: no cover - defensive
        return {"error": "tool_exception", "detail": f"{type(e).__name__}: {e}"}
