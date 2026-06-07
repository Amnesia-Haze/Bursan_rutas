"""heuristics/two_opt.py — Mejora de rutas mediante 2-opt para el CVRP de Bursan."""
from __future__ import annotations

try:
    from heuristics import Stop, Route
except ImportError:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from heuristics import Stop, Route


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def improve_route_2opt(
    route: Route,
    dist_matrix: dict[str, dict[str, float]],
    R_RUTA: float = 50.0,
    R_VECINO: float = 25.0,
    max_iter: int = 1000,
) -> Route:
    """
    Mejora una ruta aplicando 2-opt estándar.

    Para cada par de arcos (i→i+1) y (j→j+1), evalúa si invertir el segmento
    interior [i+1 .. j] reduce la distancia total sin violar R_RUTA ni R_VECINO.
    Itera hasta que no haya mejora o se alcance max_iter.

    Args:
        route:       Ruta a mejorar. Sus paradas incluyen depósito al inicio y al final.
        dist_matrix: Matriz de distancias {node_id: {node_id: km}}.
        R_RUTA:      Distancia total máxima permitida (km).
        R_VECINO:    Distancia máxima entre paradas consecutivas (km).
        max_iter:    Límite de iteraciones para evitar ciclos largos.

    Returns:
        Nueva Route con distancia mejorada (o la ruta original si no hubo mejora).
    """
    paradas = list(route.paradas)
    n = len(paradas)

    if n < 4:  # depósito + al menos 2 paradas internas + depósito
        return route

    # Inferir tasa de costo por km a partir de la ruta original
    clp_per_km = (
        route.costo_clp / route.distancia_total_km
        if route.distancia_total_km > 0
        else 1560.0 / 7.0
    )

    current_dist = _route_dist(paradas, dist_matrix)
    improved = True
    iteration = 0

    while improved and iteration < max_iter:
        improved = False
        iteration += 1

        for i in range(1, n - 2):
            for j in range(i + 1, n - 1):
                # Proponer inversión del segmento [i .. j]
                candidate = paradas[:i] + list(reversed(paradas[i : j + 1])) + paradas[j + 1 :]
                new_dist = _route_dist(candidate, dist_matrix)

                if new_dist < current_dist - 1e-6:
                    if new_dist <= R_RUTA and _max_leg(candidate, dist_matrix) <= R_VECINO:
                        paradas = candidate
                        current_dist = new_dist
                        improved = True
                        break  # Reiniciar búsqueda desde el inicio

            if improved:
                break

    return Route(
        paradas=paradas,
        guardias=route.guardias,
        distancia_total_km=round(current_dist, 2),
        costo_clp=round(current_dist * clp_per_km, 2),
        n_viajes=route.n_viajes,
        es_exclusiva=route.es_exclusiva,
    )


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _route_dist(paradas: list[Stop], dist_matrix: dict[str, dict[str, float]]) -> float:
    """Suma de distancias de todos los tramos de la ruta."""
    return sum(
        dist_matrix.get(paradas[i].node_id, {}).get(paradas[i + 1].node_id, 0.0)
        for i in range(len(paradas) - 1)
    )


def _max_leg(paradas: list[Stop], dist_matrix: dict[str, dict[str, float]]) -> float:
    """Distancia máxima entre paradas consecutivas de la ruta."""
    return max(
        dist_matrix.get(paradas[i].node_id, {}).get(paradas[i + 1].node_id, 0.0)
        for i in range(len(paradas) - 1)
    )


# ---------------------------------------------------------------------------
# Prueba mínima
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os, sys, math
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from heuristics import construir_matriz_distancias  # type: ignore[import]

    # Ruta artificial con 4 paradas internas en orden sub-óptimo
    # Óptimo: depósito → A → B → C → D → depósito (circulo)
    # Inicial: depósito → A → C → B → D → depósito (con un cruce)

    def _mk_stop(nid, ntype, lat, lon):
        return Stop(node_id=nid, node_type=ntype, lat=lat, lon=lon)

    depot = _mk_stop("deposito", "deposito", -36.820, -73.044)
    A = _mk_stop("G1", "guardia", -36.830, -73.044)
    B = _mk_stop("G2", "guardia", -36.830, -73.054)
    C = _mk_stop("G3", "guardia", -36.820, -73.054)
    D = _mk_stop("EmpA", "empresa", -36.840, -73.060)

    # Ruta sub-óptima con cruce A→C→B en lugar de A→B→C
    paradas_init = [depot, A, C, B, D, depot]
    dist_matrix = construir_matriz_distancias([depot, A, B, C, D])

    d_init = sum(
        dist_matrix[paradas_init[i].node_id][paradas_init[i+1].node_id]
        for i in range(len(paradas_init)-1)
    )

    ruta_init = Route(
        paradas=paradas_init,
        guardias=["G1", "G3", "G2"],
        distancia_total_km=round(d_init, 2),
        costo_clp=round(d_init * (1560 / 7), 2),
    )

    ruta_opt = improve_route_2opt(ruta_init, dist_matrix)

    assert ruta_opt.distancia_total_km <= ruta_init.distancia_total_km, (
        f"2-opt empeoró la ruta: {ruta_opt.distancia_total_km:.3f} > {ruta_init.distancia_total_km:.3f}"
    )
    assert ruta_opt.paradas[0].node_id == "deposito"
    assert ruta_opt.paradas[-1].node_id == "deposito"

    mejora = ruta_init.distancia_total_km - ruta_opt.distancia_total_km
    print(
        f"OK two_opt.py: {ruta_init.distancia_total_km:.3f} km -> "
        f"{ruta_opt.distancia_total_km:.3f} km  (mejora {mejora:.3f} km)"
    )
