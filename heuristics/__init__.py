"""heuristics/__init__.py — Dataclasses compartidos y utilidades geográficas."""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Dataclasses compartidos
# ---------------------------------------------------------------------------

@dataclass
class Stop:
    """Parada en una ruta de bus (guardia, empresa o depósito)."""

    node_id: str    # "G1", "Noramco", "deposito"
    node_type: str  # "guardia" | "empresa" | "deposito"
    lat: float
    lon: float
    carga: int = 0  # pasajeros a recoger en esta parada (1 para guardias, 0 para el resto)


@dataclass
class Route:
    """Ruta completa de un bus: depósito → recogidas → entregas → depósito."""

    paradas: list[Stop]
    guardias: list[str]           # IDs de guardias en esta ruta
    distancia_total_km: float
    costo_clp: float
    n_viajes: int = 1
    es_exclusiva: bool = False    # True cuando se generó por violación de R_VECINO


@dataclass
class RoutingResult:
    """Resultado agregado de un algoritmo de ruteo."""

    rutas: list[Route]
    distancia_total_sistema: float
    costo_total_clp: float
    n_buses_necesarios: int
    guardias_exclusivos: list[str]  # guardias que requirieron ruta exclusiva
    metodo: str


# ---------------------------------------------------------------------------
# Utilidades geográficas
# ---------------------------------------------------------------------------

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en km entre dos puntos geográficos (fórmula haversine)."""
    R = 6_371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2.0 * R * math.asin(math.sqrt(min(a, 1.0)))


def construir_matriz_distancias(stops: list[Stop]) -> dict[str, dict[str, float]]:
    """Construye la matriz de distancias haversine completa para una lista de paradas."""
    matrix: dict[str, dict[str, float]] = {}
    for s1 in stops:
        matrix[s1.node_id] = {}
        for s2 in stops:
            if s1.node_id == s2.node_id:
                matrix[s1.node_id][s2.node_id] = 0.0
            else:
                matrix[s1.node_id][s2.node_id] = haversine(
                    s1.lat, s1.lon, s2.lat, s2.lon
                )
    return matrix
