"""core/distances.py — Matriz de distancias ORS/Haversine con caché en disco."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

# ── SSL: usa el almacén de certificados del sistema en Windows ───────────────
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

# ── Carga opcional de variables de entorno desde .env ────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_ROOT       = Path(__file__).parent.parent          # bursan_rutas/
_CACHE_FILE = _ROOT / "data" / "distance_cache.json"


# ---------------------------------------------------------------------------
# Haversine — función reutilizable (fuente de verdad para el fallback)
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en km entre dos puntos geográficos (fórmula haversine)."""
    R = 6_371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2.0 * R * math.asin(math.sqrt(min(a, 1.0)))


# ---------------------------------------------------------------------------
# Cliente ORS — construido bajo demanda
# ---------------------------------------------------------------------------

def _get_ors_client():
    """Devuelve cliente ORS configurado, o None si no hay API key disponible."""
    api_key = os.getenv("ORS_API_KEY")
    if not api_key or api_key == "tu_api_key_aqui":
        return None
    try:
        import openrouteservice
        return openrouteservice.Client(key=api_key)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Caché en disco — data/distance_cache.json
# ---------------------------------------------------------------------------

def _cache_key(coords: list[tuple[float, float]]) -> str:
    """Clave estable basada en coordenadas redondeadas a 4 decimales."""
    rounded = [[round(lat, 4), round(lon, 4)] for lat, lon in coords]
    return json.dumps(rounded, separators=(",", ":"))


def _load_cache() -> dict:
    try:
        if _CACHE_FILE.exists():
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False),
                               encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def get_distance_matrix(
    coords: list[tuple[float, float]],
    use_cache: bool = True,
) -> tuple[list[list[float]], list[list[float]], str]:
    """
    Calcula la matriz de distancias y duraciones entre todos los puntos.

    Parámetros
    ----------
    coords : lista de (lat, lon)  — convención de todo el sistema.
    use_cache : busca / escribe en data/distance_cache.json.

    Retorna
    -------
    distancias_km  : matriz NxN en km
    duraciones_min : matriz NxN en minutos  (0.0 en fallback haversine)
    metodo         : "ors_road" | "ors_road_cached" | "haversine_fallback"

    Nota: ORS espera (lon, lat) — la inversión se hace solo aquí,
    el resto del sistema siempre trabaja con (lat, lon).
    """
    key = _cache_key(coords)

    # 1) Caché en disco
    if use_cache:
        cache = _load_cache()
        if key in cache:
            entry = cache[key]
            return entry["distances"], entry["durations"], "ors_road_cached"

    # 2) OpenRouteService
    client = _get_ors_client()
    if client is not None:
        try:
            ors_locs = [(lon, lat) for lat, lon in coords]  # ORS quiere (lon, lat)
            result = client.distance_matrix(
                locations=ors_locs,
                profile="driving-car",
                metrics=["distance", "duration"],
                units="km",
            )
            distances: list[list[float]] = result["distances"]
            durations: list[list[float]] = [
                [s / 60.0 for s in row] for row in result["durations"]
            ]
            if use_cache:
                cache = _load_cache()
                cache[key] = {"distances": distances, "durations": durations}
                _save_cache(cache)
            return distances, durations, "ors_road"
        except Exception:
            pass  # ORS no disponible → haversine

    # 3) Fallback haversine (sin datos de duración)
    n = len(coords)
    distances = [
        [
            0.0 if i == j else haversine_km(
                coords[i][0], coords[i][1], coords[j][0], coords[j][1]
            )
            for j in range(n)
        ]
        for i in range(n)
    ]
    durations = [[0.0] * n for _ in range(n)]
    return distances, durations, "haversine_fallback"


def get_route_geometry(
    waypoints: list[tuple[float, float]],
) -> list[tuple[float, float]] | None:
    """
    Obtiene el trazado real por carretera entre los waypoints usando ORS directions.

    Parámetros
    ----------
    waypoints : lista de (lat, lon) — convención del sistema.

    Retorna
    -------
    Lista de (lat, lon) del polilínea real, o None si ORS no está disponible.

    Nota: ORS GeoJSON devuelve coordenadas en [lon, lat] — se invierten aquí.
    """
    client = _get_ors_client()
    if client is None:
        return None
    try:
        ors_coords = [(lon, lat) for lat, lon in waypoints]  # ORS quiere (lon, lat)
        result = client.directions(
            coordinates=ors_coords,
            profile="driving-car",
            format="geojson",
        )
        # GeoJSON LineString: cada punto es [lon, lat] o [lon, lat, elevation]
        geom_coords = result["features"][0]["geometry"]["coordinates"]
        return [(lat, lon) for lon, lat, *_ in geom_coords]
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

    coords = [(-36.820, -73.044), (-37.052, -73.138)]  # depósito, Noramco
    dist, dur, metodo = get_distance_matrix(coords)
    print(f"metodo={metodo}, deposito->Noramco={dist[0][1]:.1f} km")

    if metodo == "haversine_fallback":
        print("Configura ORS_API_KEY en .env para distancias reales")
    else:
        assert 35 <= dist[0][1] <= 50, (
            f"Distancia fuera de rango 35-50 km: {dist[0][1]:.1f} km"
        )
        # Segunda llamada debe venir del caché
        _, _, metodo2 = get_distance_matrix(coords)
        assert metodo2 == "ors_road_cached", f"Esperado cache, got {metodo2}"
        print(f"Cache OK: segunda llamada = {metodo2}")
        print("Criterio OK: distancia por carretera dentro de rango 35-50 km")
