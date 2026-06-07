"""heuristics/nearest_neighbor.py — Heurística de vecino más cercano para el CVRP de Bursan."""
from __future__ import annotations

try:
    from heuristics import Stop, Route, RoutingResult, haversine, construir_matriz_distancias
    from core.instance import BursanInstance
except ImportError:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from heuristics import Stop, Route, RoutingResult, haversine, construir_matriz_distancias
    from core.instance import BursanInstance


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def nearest_neighbor_routing(
    inst: BursanInstance,
    asignacion: list[dict],
    coords: dict[str, tuple[float, float]] | None = None,
    seed: int = 42,
) -> RoutingResult:
    """
    Construye rutas de bus usando la heurística de vecino más cercano.

    Algoritmo:
    1. Identifica guardias aislados (> R_VECINO de todos los demás) → ruta exclusiva.
    2. Para los restantes, construye rutas greedy por turno:
       - Parte del depósito y elige el guardia no visitado más cercano
         que no viole R_VECINO ni R_RUTA.
       - Cierra la ruta cuando no puede agregar más guardias.
    3. Ordena las entregas a empresas por cercanía desde la última recogida.

    Args:
        inst:      Instancia de Bursan con parámetros de flota.
        asignacion: Lista de dicts {guardia_id, empresa, turno, ...}.
        coords:    Coordenadas adicionales {node_id: (lat, lon)} que sobreescriben
                   los valores de la instancia.
        seed:      Semilla para desempates aleatorios (reproducibilidad).

    Returns:
        RoutingResult con todas las rutas construidas.
    """
    import random
    random.seed(seed)

    all_stops = _gather_stops(inst, asignacion, coords)
    dist_matrix = construir_matriz_distancias(list(all_stops.values()))

    valid = [
        a for a in asignacion
        if a["guardia_id"] in all_stops and a["empresa"] in all_stops
    ]

    all_routes: list[Route] = []
    all_exclusivos: list[str] = []

    for turno in sorted({a["turno"] for a in valid}):
        turno_asign = [a for a in valid if a["turno"] == turno]
        routes, exclusivos = _routes_for_turno(turno_asign, all_stops, dist_matrix, inst)
        all_routes.extend(routes)
        all_exclusivos.extend(exclusivos)

    dist_total = round(sum(r.distancia_total_km for r in all_routes), 2)
    costo_total = round(sum(r.costo_clp for r in all_routes), 2)

    return RoutingResult(
        rutas=all_routes,
        distancia_total_sistema=dist_total,
        costo_total_clp=costo_total,
        n_buses_necesarios=len(all_routes),
        guardias_exclusivos=all_exclusivos,
        metodo="nearest_neighbor",
    )


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _gather_stops(
    inst: BursanInstance,
    asignacion: list[dict],
    coords: dict[str, tuple[float, float]] | None,
) -> dict[str, Stop]:
    """Construye el diccionario de paradas a partir de la instancia y los overrides de coords."""
    stops: dict[str, Stop] = {
        "deposito": Stop(
            node_id="deposito",
            node_type="deposito",
            lat=inst.deposito_lat,
            lon=inst.deposito_lon,
        )
    }

    guard_map = {g.id: g for g in inst.guardias}
    for a in asignacion:
        gid = a["guardia_id"]
        if gid in stops:
            continue
        lat, lon = _resolve_coords(gid, coords, guard_map.get(gid))
        if lat is not None:
            stops[gid] = Stop(node_id=gid, node_type="guardia", lat=lat, lon=lon, carga=1)

    empresa_map = {e.nombre: e for e in inst.empresas}
    for a in asignacion:
        ename = a["empresa"]
        if ename in stops:
            continue
        lat, lon = _resolve_coords(ename, coords, empresa_map.get(ename))
        if lat is not None:
            stops[ename] = Stop(node_id=ename, node_type="empresa", lat=lat, lon=lon)

    return stops


def _resolve_coords(node_id: str, coords, entity) -> tuple[float | None, float | None]:
    """Devuelve (lat, lon) usando override primero, luego atributos de la entidad."""
    if coords and node_id in coords:
        return coords[node_id]
    if entity is not None:
        lat = getattr(entity, "lat", None)
        lon = getattr(entity, "lon", None)
        if lat is not None and lon is not None:
            return lat, lon
    return None, None


def _routes_for_turno(
    assignments: list[dict],
    all_stops: dict[str, Stop],
    dist_matrix: dict[str, dict[str, float]],
    inst: BursanInstance,
) -> tuple[list[Route], list[str]]:
    """Construye rutas NN para un turno dado."""
    R_VEC = inst.max_distancia_vecino
    R_RUT = inst.max_distancia_ruta
    CAP = inst.capacidad_bus
    depot = all_stops["deposito"]

    isolated, candidates = _split_isolated(assignments, dist_matrix, R_VEC)

    routes: list[Route] = []
    exclusivos: list[str] = []

    for a in isolated:
        routes.append(_exclusive_route(a, all_stops, dist_matrix, inst))
        exclusivos.append(a["guardia_id"])

    unrouted = list(candidates)
    while unrouted:
        current = depot
        route_asign: list[dict] = []
        pickup_dist = 0.0

        while unrouted and len(route_asign) < CAP:
            best, best_d = _nearest_feasible(
                current, unrouted, route_asign, all_stops, dist_matrix, R_VEC, R_RUT, pickup_dist
            )
            if best is None:
                break
            pickup_dist += best_d
            route_asign.append(best)
            current = all_stops[best["guardia_id"]]
            unrouted.remove(best)

        if not route_asign:
            # Guards left without feasible neighbors: give them exclusive routes
            for a in unrouted:
                routes.append(_exclusive_route(a, all_stops, dist_matrix, inst))
                exclusivos.append(a["guardia_id"])
            break

        routes.append(_close_route(route_asign, pickup_dist, all_stops, dist_matrix, inst, depot))

    return routes, exclusivos


def _split_isolated(
    assignments: list[dict],
    dist_matrix: dict[str, dict[str, float]],
    R_VEC: float,
) -> tuple[list[dict], list[dict]]:
    """Separa guardias aislados (> R_VEC de todos los demás) de los candidatos normales."""
    if len(assignments) <= 1:
        return list(assignments), []

    isolated, candidates = [], []
    for a in assignments:
        gid = a["guardia_id"]
        min_d = min(
            dist_matrix.get(gid, {}).get(b["guardia_id"], float("inf"))
            for b in assignments if b["guardia_id"] != gid
        )
        (isolated if min_d > R_VEC else candidates).append(a)
    return isolated, candidates


def _nearest_feasible(
    current: Stop,
    unrouted: list[dict],
    route_asign: list[dict],
    all_stops: dict[str, Stop],
    dist_matrix: dict[str, dict[str, float]],
    R_VEC: float,
    R_RUT: float,
    pickup_dist: float,
) -> tuple[dict | None, float]:
    """Encuentra el guardia no visitado más cercano que no viole R_VEC ni R_RUT."""
    best: dict | None = None
    best_d = float("inf")

    for a in unrouted:
        gid = a["guardia_id"]
        d = dist_matrix.get(current.node_id, {}).get(gid, float("inf"))
        if d > R_VEC or d >= best_d:
            continue
        # Estimate completion: d_to_company + d_company_to_depot
        ename = a["empresa"]
        d_co = dist_matrix.get(gid, {}).get(ename, 0.0)
        d_ret = dist_matrix.get(ename, {}).get("deposito", 0.0)
        if pickup_dist + d + d_co + d_ret <= R_RUT:
            best = a
            best_d = d

    return best, best_d


def _close_route(
    route_asign: list[dict],
    pickup_dist: float,
    all_stops: dict[str, Stop],
    dist_matrix: dict[str, dict[str, float]],
    inst: BursanInstance,
    depot: Stop,
) -> Route:
    """Cierra una ruta añadiendo las entregas en orden NN y el retorno al depósito."""
    companies: dict[str, list[str]] = {}
    for a in route_asign:
        companies.setdefault(a["empresa"], []).append(a["guardia_id"])

    current = all_stops[route_asign[-1]["guardia_id"]]
    remaining = list(companies.keys())
    delivery_order: list[str] = []
    delivery_dist = 0.0

    while remaining:
        nearest = min(
            remaining,
            key=lambda c: dist_matrix.get(current.node_id, {}).get(c, float("inf")),
        )
        delivery_dist += dist_matrix.get(current.node_id, {}).get(nearest, 0.0)
        current = all_stops[nearest]
        delivery_order.append(nearest)
        remaining.remove(nearest)

    d_return = dist_matrix.get(current.node_id, {}).get("deposito", 0.0)
    total_dist = round(pickup_dist + delivery_dist + d_return, 2)

    paradas = [depot]
    for a in route_asign:
        paradas.append(all_stops[a["guardia_id"]])
    for ename in delivery_order:
        paradas.append(all_stops[ename])
    paradas.append(depot)

    return Route(
        paradas=paradas,
        guardias=[a["guardia_id"] for a in route_asign],
        distancia_total_km=total_dist,
        costo_clp=round(inst.costo_clp(total_dist), 2),
    )


def _exclusive_route(
    a: dict,
    all_stops: dict[str, Stop],
    dist_matrix: dict[str, dict[str, float]],
    inst: BursanInstance,
) -> Route:
    """Crea una ruta exclusiva para un guardia aislado."""
    depot = all_stops["deposito"]
    gid, ename = a["guardia_id"], a["empresa"]

    d1 = dist_matrix.get("deposito", {}).get(gid, 0.0)
    d2 = dist_matrix.get(gid, {}).get(ename, 0.0)
    d3 = dist_matrix.get(ename, {}).get("deposito", 0.0)
    total = round(d1 + d2 + d3, 2)

    return Route(
        paradas=[depot, all_stops[gid], all_stops[ename], depot],
        guardias=[gid],
        distancia_total_km=total,
        costo_clp=round(inst.costo_clp(total), 2),
        es_exclusiva=True,
    )


# ---------------------------------------------------------------------------
# Prueba mínima
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os, sys
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from core.instance import BursanInstance, Guard, Company

    _g = [
        Guard("TG1", "Test1", "Dir1", False, "activo", -36.820, -73.044),
        Guard("TG2", "Test2", "Dir2", False, "activo", -36.835, -73.060),
        Guard("TG3", "Test3", "Dir3", False, "activo", -36.850, -73.074),
        Guard("TG4", "Test4", "Dir4", False, "activo", -36.865, -73.088),
    ]
    _e = [
        Company("TE1", "CorpA", "DirA", 2, 0, False, "activo", -36.960, -73.090),
        Company("TE2", "CorpB", "DirB", 2, 0, False, "activo", -36.880, -73.020),
    ]
    _d = {
        "TG1": {"CorpA": 16.0, "CorpB": 7.0},
        "TG2": {"CorpA": 14.0, "CorpB": 6.0},
        "TG3": {"CorpA": 12.0, "CorpB": 5.5},
        "TG4": {"CorpA": 10.5, "CorpB": 6.3},
    }
    _inst = BursanInstance(guardias=_g, empresas=_e, distancias=_d)
    _asign = [
        {"guardia_id": "TG1", "empresa": "CorpA", "turno": "D", "distancia_km": 16.0, "costo_clp": 0},
        {"guardia_id": "TG2", "empresa": "CorpA", "turno": "D", "distancia_km": 14.0, "costo_clp": 0},
        {"guardia_id": "TG3", "empresa": "CorpB", "turno": "D", "distancia_km": 5.5,  "costo_clp": 0},
        {"guardia_id": "TG4", "empresa": "CorpB", "turno": "D", "distancia_km": 6.3,  "costo_clp": 0},
    ]

    res = nearest_neighbor_routing(_inst, _asign)

    assert len(res.rutas) >= 1, "Debe haber al menos una ruta"
    assert res.n_buses_necesarios == len(res.rutas)
    assert res.distancia_total_sistema > 0

    all_guards_covered = sorted(g for r in res.rutas for g in r.guardias)
    assert all_guards_covered == ["TG1", "TG2", "TG3", "TG4"], (
        f"Guardias cubiertos: {all_guards_covered}"
    )
    for r in res.rutas:
        assert r.paradas[0].node_id == "deposito"
        assert r.paradas[-1].node_id == "deposito"
        assert r.distancia_total_km > 0

    print(f"OK nearest_neighbor.py: {len(res.rutas)} ruta(s), "
          f"{res.distancia_total_sistema:.1f} km total")
    for i, r in enumerate(res.rutas, 1):
        print(f"  Ruta {i}: {r.guardias} -> {r.distancia_total_km:.1f} km"
              f"{'  [EXCLUSIVA]' if r.es_exclusiva else ''}")
