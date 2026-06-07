"""heuristics/clarke_wright.py — Algoritmo Clarke-Wright Savings para el CVRP de Bursan."""
from __future__ import annotations

try:
    from heuristics import Stop, Route, RoutingResult, haversine, construir_matriz_distancias
    from heuristics.two_opt import improve_route_2opt
    from core.instance import BursanInstance
except ImportError:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from heuristics import Stop, Route, RoutingResult, haversine, construir_matriz_distancias
    from heuristics.two_opt import improve_route_2opt
    from core.instance import BursanInstance


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def clarke_wright_routing(
    inst: BursanInstance,
    asignacion: list[dict],
    coords: dict[str, tuple[float, float]] | None = None,
    seed: int = 42,
) -> RoutingResult:
    """
    Construye rutas de bus usando el algoritmo Clarke-Wright Savings con mejora 2-opt.

    Algoritmo:
    1. Inicializa una ruta individual para cada guardia (depósito → guardia → empresa → depósito).
    2. Calcula el ahorro s(i,j) = d(depósito,i) + d(depósito,j) - d(i,j) para todo par.
    3. Fusiona rutas en orden descendente de ahorro mientras se respeten capacidad,
       R_RUTA y R_VECINO.
    4. Aplica mejora 2-opt a cada ruta resultante.

    Args:
        inst:       Instancia de Bursan con parámetros de flota.
        asignacion: Lista de dicts {guardia_id, empresa, turno, ...}.
        coords:     Coordenadas adicionales {node_id: (lat, lon)}.
        seed:       Semilla para reproducibilidad.

    Returns:
        RoutingResult con rutas mejoradas por 2-opt.
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

    for turno in sorted({a["turno"] for a in valid}):
        turno_asign = [a for a in valid if a["turno"] == turno]
        routes = _cw_for_turno(turno_asign, all_stops, dist_matrix, inst)
        # Aplicar 2-opt a cada ruta
        routes = [
            improve_route_2opt(
                r, dist_matrix,
                R_RUTA=inst.max_distancia_ruta,
                R_VECINO=inst.max_distancia_vecino,
            )
            for r in routes
        ]
        all_routes.extend(routes)

    dist_total = round(sum(r.distancia_total_km for r in all_routes), 2)
    costo_total = round(sum(r.costo_clp for r in all_routes), 2)

    return RoutingResult(
        rutas=all_routes,
        distancia_total_sistema=dist_total,
        costo_total_clp=costo_total,
        n_buses_necesarios=len(all_routes),
        guardias_exclusivos=[],  # C-W no genera rutas exclusivas por aislamiento
        metodo="clarke_wright",
    )


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _gather_stops(
    inst: BursanInstance,
    asignacion: list[dict],
    coords: dict[str, tuple[float, float]] | None,
) -> dict[str, Stop]:
    """Igual que en nearest_neighbor — construye el dict de paradas."""
    stops: dict[str, Stop] = {
        "deposito": Stop(
            node_id="deposito", node_type="deposito",
            lat=inst.deposito_lat, lon=inst.deposito_lon,
        )
    }

    guard_map = {g.id: g for g in inst.guardias}
    empresa_map = {e.nombre: e for e in inst.empresas}

    for a in asignacion:
        gid = a["guardia_id"]
        if gid not in stops:
            lat, lon = _resolve_coords(gid, coords, guard_map.get(gid))
            if lat is not None:
                stops[gid] = Stop(node_id=gid, node_type="guardia", lat=lat, lon=lon, carga=1)

        ename = a["empresa"]
        if ename not in stops:
            lat, lon = _resolve_coords(ename, coords, empresa_map.get(ename))
            if lat is not None:
                stops[ename] = Stop(node_id=ename, node_type="empresa", lat=lat, lon=lon)

    return stops


def _resolve_coords(node_id: str, coords, entity) -> tuple[float | None, float | None]:
    if coords and node_id in coords:
        return coords[node_id]
    if entity is not None:
        lat = getattr(entity, "lat", None)
        lon = getattr(entity, "lon", None)
        if lat is not None and lon is not None:
            return lat, lon
    return None, None


def _cw_for_turno(
    assignments: list[dict],
    all_stops: dict[str, Stop],
    dist_matrix: dict[str, dict[str, float]],
    inst: BursanInstance,
) -> list[Route]:
    """Ejecuta Clarke-Wright Savings para los guardias de un turno."""
    if not assignments:
        return []

    depot = all_stops["deposito"]
    R_VEC = inst.max_distancia_vecino
    R_RUT = inst.max_distancia_ruta
    CAP = inst.capacidad_bus

    # Calcular ahorros para todos los pares de guardias
    savings = _compute_savings(assignments, dist_matrix)

    # Estado inicial: cada guardia en su propia ruta
    # route_chains[route_id] = lista ordenada de dicts
    route_chains: dict[int, list[dict]] = {i: [a] for i, a in enumerate(assignments)}
    # Extremos de cada ruta (primer y último guardia) → para verificar fusión válida
    # En C-W clásico solo se puede fusionar el final de una ruta con el inicio de otra
    route_of: dict[str, int] = {a["guardia_id"]: i for i, a in enumerate(assignments)}
    next_id = len(assignments)

    for s_val, idx_i, idx_j in savings:
        gi = assignments[idx_i]["guardia_id"]
        gj = assignments[idx_j]["guardia_id"]

        ri_id = route_of.get(gi)
        rj_id = route_of.get(gj)

        if ri_id is None or rj_id is None or ri_id == rj_id:
            continue

        ri = route_chains.get(ri_id)
        rj = route_chains.get(rj_id)

        if not ri or not rj:
            continue

        # En C-W clásico: gi debe ser el último de ri y gj el primero de rj
        # (o viceversa). Aquí aceptamos ambas orientaciones.
        merged = _try_merge(ri, rj, gi, gj, dist_matrix, R_VEC, R_RUT, CAP,
                            all_stops, depot)
        if merged is None:
            continue

        # Actualizar estructuras
        route_chains[next_id] = merged
        del route_chains[ri_id]
        del route_chains[rj_id]
        for a in merged:
            route_of[a["guardia_id"]] = next_id
        next_id += 1

    # Construir objetos Route
    return [
        _finalize_route(chain, all_stops, dist_matrix, inst, depot)
        for chain in route_chains.values()
    ]


def _compute_savings(
    assignments: list[dict],
    dist_matrix: dict[str, dict[str, float]],
) -> list[tuple[float, int, int]]:
    """Calcula y ordena ahorros s(i,j) = d(depot,i) + d(depot,j) - d(i,j)."""
    savings: list[tuple[float, int, int]] = []
    for i in range(len(assignments)):
        for j in range(i + 1, len(assignments)):
            gi = assignments[i]["guardia_id"]
            gj = assignments[j]["guardia_id"]
            s = (
                dist_matrix.get("deposito", {}).get(gi, 0.0)
                + dist_matrix.get("deposito", {}).get(gj, 0.0)
                - dist_matrix.get(gi, {}).get(gj, float("inf"))
            )
            if s > 0:
                savings.append((s, i, j))
    savings.sort(key=lambda x: -x[0])
    return savings


def _try_merge(
    ri: list[dict],
    rj: list[dict],
    gi: str,
    gj: str,
    dist_matrix: dict[str, dict[str, float]],
    R_VEC: float,
    R_RUT: float,
    CAP: int,
    all_stops: dict[str, Stop],
    depot: Stop,
) -> list[dict] | None:
    """
    Intenta fusionar ri y rj en el punto (gi, gj).
    gi debe ser el extremo final de ri y gj el extremo inicial de rj,
    o la orientación inversa. Retorna la fusión si es factible, None si no.
    """
    # Determinar orientación
    if ri[-1]["guardia_id"] == gi and rj[0]["guardia_id"] == gj:
        merged = ri + rj
    elif ri[0]["guardia_id"] == gi and rj[-1]["guardia_id"] == gj:
        merged = list(reversed(ri)) + rj
    elif ri[-1]["guardia_id"] == gj and rj[0]["guardia_id"] == gi:
        merged = rj + ri
    elif ri[0]["guardia_id"] == gj and rj[-1]["guardia_id"] == gi:
        merged = list(reversed(rj)) + ri
    else:
        return None  # No hay extremo compatible

    if len(merged) > CAP:
        return None

    # Verificar R_VECINO en el punto de unión
    split_g1 = merged[len(ri) - 1]["guardia_id"]
    split_g2 = merged[len(ri)]["guardia_id"]
    d_join = dist_matrix.get(split_g1, {}).get(split_g2, float("inf"))
    if d_join > R_VEC:
        return None

    # Verificar R_RUTA estimada
    est = _estimate_dist(merged, all_stops, dist_matrix, depot)
    if est > R_RUT:
        return None

    return merged


def _estimate_dist(
    chain: list[dict],
    all_stops: dict[str, Stop],
    dist_matrix: dict[str, dict[str, float]],
    depot: Stop,
) -> float:
    """Estimación de la distancia total de una ruta (pickup NN + delivery NN + retorno)."""
    if not chain:
        return 0.0
    dist = 0.0
    current_id = depot.node_id
    for a in chain:
        gid = a["guardia_id"]
        dist += dist_matrix.get(current_id, {}).get(gid, 0.0)
        current_id = gid

    remaining_cos = list({a["empresa"] for a in chain})
    while remaining_cos:
        nearest = min(
            remaining_cos,
            key=lambda c: dist_matrix.get(current_id, {}).get(c, float("inf")),
        )
        dist += dist_matrix.get(current_id, {}).get(nearest, 0.0)
        current_id = nearest
        remaining_cos.remove(nearest)

    dist += dist_matrix.get(current_id, {}).get(depot.node_id, 0.0)
    return dist


def _finalize_route(
    chain: list[dict],
    all_stops: dict[str, Stop],
    dist_matrix: dict[str, dict[str, float]],
    inst: BursanInstance,
    depot: Stop,
) -> Route:
    """Construye un objeto Route completo desde una secuencia de asignaciones."""
    dist = 0.0
    current = depot
    pickup_seq: list[str] = []

    for a in chain:
        gid = a["guardia_id"]
        dist += dist_matrix.get(current.node_id, {}).get(gid, 0.0)
        current = all_stops[gid]
        pickup_seq.append(gid)

    companies: dict[str, list[str]] = {}
    for a in chain:
        companies.setdefault(a["empresa"], []).append(a["guardia_id"])

    remaining_cos = list(companies.keys())
    delivery_order: list[str] = []
    while remaining_cos:
        nearest = min(
            remaining_cos,
            key=lambda c: dist_matrix.get(current.node_id, {}).get(c, float("inf")),
        )
        dist += dist_matrix.get(current.node_id, {}).get(nearest, 0.0)
        current = all_stops[nearest]
        delivery_order.append(nearest)
        remaining_cos.remove(nearest)

    dist += dist_matrix.get(current.node_id, {}).get(depot.node_id, 0.0)

    paradas: list[Stop] = [depot]
    for gid in pickup_seq:
        paradas.append(all_stops[gid])
    for ename in delivery_order:
        paradas.append(all_stops[ename])
    paradas.append(depot)

    return Route(
        paradas=paradas,
        guardias=pickup_seq,
        distancia_total_km=round(dist, 2),
        costo_clp=round(inst.costo_clp(dist), 2),
    )


# ---------------------------------------------------------------------------
# Prueba mínima
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os, sys
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from core.instance import BursanInstance, Guard, Company  # type: ignore[import]

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

    res_nn_import = None
    try:
        from heuristics.nearest_neighbor import nearest_neighbor_routing  # type: ignore[import]
        res_nn = nearest_neighbor_routing(_inst, _asign)
        res_nn_dist = res_nn.distancia_total_sistema
    except Exception:
        res_nn_dist = None

    res = clarke_wright_routing(_inst, _asign)

    assert len(res.rutas) >= 1, "Debe haber al menos una ruta"
    assert res.n_buses_necesarios == len(res.rutas)
    assert res.distancia_total_sistema > 0

    all_guards = sorted(g for r in res.rutas for g in r.guardias)
    assert all_guards == ["TG1", "TG2", "TG3", "TG4"], f"Guardias: {all_guards}"

    for r in res.rutas:
        assert r.paradas[0].node_id == "deposito"
        assert r.paradas[-1].node_id == "deposito"

    comparacion = (
        f"  (vs NN: {res_nn_dist:.1f} km)" if res_nn_dist else ""
    )
    print(
        f"OK clarke_wright.py: {len(res.rutas)} ruta(s), "
        f"{res.distancia_total_sistema:.1f} km total{comparacion}"
    )
    for i, r in enumerate(res.rutas, 1):
        print(f"  Ruta {i}: {r.guardias} -> {r.distancia_total_km:.1f} km")
