"""core/routing.py — Orquestador CVRP: convierte asignaciones en rutas de bus optimizadas."""
from __future__ import annotations

import time
import warnings

try:
    from core.instance import BursanInstance, Guard
    from core.assignment import AssignmentResult
    from heuristics import RoutingResult, Stop, construir_matriz_distancias
    from heuristics.nearest_neighbor import nearest_neighbor_routing
    from heuristics.clarke_wright import clarke_wright_routing
    from heuristics.two_opt import improve_route_2opt
except ModuleNotFoundError:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from core.instance import BursanInstance, Guard
    from core.assignment import AssignmentResult
    from heuristics import RoutingResult, Stop, construir_matriz_distancias
    from heuristics.nearest_neighbor import nearest_neighbor_routing
    from heuristics.clarke_wright import clarke_wright_routing
    from heuristics.two_opt import improve_route_2opt


_METODOS_VALIDOS = frozenset({"nearest_neighbor", "clarke_wright"})

# Aproximaciones para la Region del Biobio — usar solo si geopy falla
COORDS_FALLBACK: dict[str, tuple[float, float]] = {
    # Guardias — domicilios aproximados por comuna
    "G1":  (-36.601, -72.959),  # Talcahuano
    "G2":  (-37.027, -73.134),  # Coronel
    "G3":  (-36.827, -73.066),  # Collao, Concepcion
    "G4":  (-36.924, -72.992),  # Chiguayante
    "G5":  (-36.924, -72.992),  # Chiguayante
    "G6":  (-36.820, -73.044),  # Concepcion centro
    "G7":  (-37.027, -73.134),  # Coronel
    "G8":  (-37.027, -73.134),  # Coronel
    "G9":  (-36.820, -73.044),  # Concepcion
    "G10": (-36.790, -73.105),  # Hualpen
    "G11": (-37.050, -72.930),  # Hualqui
    "G12": (-36.924, -72.992),  # Chiguayante
    "G13": (-36.924, -72.992),  # Chiguayante
    "G14": (-36.790, -73.105),  # Hualpen
    # Deposito base de Bursan
    "deposito": (-36.820, -73.044),  # Concepcion
    # Empresas clientes — coordenadas derivadas de direcciones fisicas reales
    "Noramco":   (-37.052, -73.138),  # Calle E Lote 18-A, Parque Industrial Escuadron, Coronel
    "ITI Chile": (-37.041, -73.145),  # Av. Golfo de Arauco 1006, Parque Industrial Coronel
    "Oleoducto": (-36.793, -73.118),  # Camino a Lenga 3381, Hualpen, Talcahuano
    "Indama":    (-36.922, -72.990),  # Av. Manuel Rodriguez 2881, Chiguayante
}


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------

def resolver_rutas(
    inst: BursanInstance,
    asignacion: AssignmentResult,
    metodo: str = "nearest_neighbor",
    mejorar_2opt: bool = True,
    seed: int = 42,
) -> RoutingResult:
    """
    Orquesta la construccion de rutas de bus a partir de una asignacion guardia-empresa.

    Flujo:
    1. Extrae la lista de asignaciones desde asignacion.asignaciones.
    2. Resuelve coordenadas para todos los nodos (inst > geocodificacion > fallback).
    3. Llama al metodo seleccionado (nearest_neighbor o clarke_wright).
    4. Si mejorar_2opt=True, aplica mejora 2-opt a cada ruta resultante.
    5. Retorna RoutingResult con metricas consolidadas.

    Args:
        inst:         Instancia de Bursan.
        asignacion:   Resultado del ILP con la lista de asignaciones.
        metodo:       "nearest_neighbor" | "clarke_wright".
        mejorar_2opt: Si True, aplica 2-opt a todas las rutas al finalizar.
        seed:         Semilla para reproducibilidad.

    Returns:
        RoutingResult valido (puede tener rutas vacias si la asignacion es infeasible).

    Raises:
        ValueError: si metodo no es uno de los valores validos.
    """
    if metodo not in _METODOS_VALIDOS:
        raise ValueError(
            f"metodo debe ser uno de {sorted(_METODOS_VALIDOS)}, recibido '{metodo}'."
        )

    if not asignacion.asignaciones:
        return _empty_result(metodo)

    # Resolver coordenadas para guardias sin lat/lon en la instancia
    coords = _build_coords(inst, asignacion.asignaciones)

    # Llamar al heuristico seleccionado
    if metodo == "clarke_wright":
        result = clarke_wright_routing(inst, asignacion.asignaciones, coords=coords, seed=seed)
    else:
        result = nearest_neighbor_routing(inst, asignacion.asignaciones, coords=coords, seed=seed)

    # Aplicar 2-opt si se solicita
    if mejorar_2opt and result.rutas:
        result = _apply_2opt(result, inst)

    return result


# ---------------------------------------------------------------------------
# Funcion auxiliar publica
# ---------------------------------------------------------------------------

def geocodificar_guardias(guardias: list[Guard]) -> dict[str, tuple[float, float]]:
    """
    Obtiene coordenadas lat/lon para guardias que no las tienen via Nominatim (geopy).

    Respeta el rate-limit de Nominatim con sleep(1) entre consultas y hasta 3 reintentos
    por guardia en caso de timeout o error de servicio.

    Args:
        guardias: Lista de guardias a geocodificar (solo los que tienen lat/lon = None).

    Returns:
        Dict {guardia_id: (lat, lon)} con los guardias geocodificados exitosamente.
    """
    import time as _time

    result: dict[str, tuple[float, float]] = {}

    try:
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    except ImportError:
        warnings.warn(
            "geopy no esta instalado. Instalar con: pip install geopy. "
            "Usando coordenadas de fallback."
        )
        return result

    geocoder = Nominatim(user_agent="bursan_rutas_v1", timeout=10)

    for g in guardias:
        query = f"{g.direccion}, Region del Biobio, Chile"
        for attempt in range(3):
            try:
                location = geocoder.geocode(query)
                if location:
                    result[g.id] = (location.latitude, location.longitude)
                else:
                    warnings.warn(
                        f"Nominatim no encontro coordenadas para guardia {g.id}: {query}"
                    )
                _time.sleep(1.0)
                break
            except GeocoderTimedOut:
                if attempt < 2:
                    _time.sleep(2.0 * (attempt + 1))
                else:
                    warnings.warn(
                        f"Timeout geocodificando guardia {g.id} tras 3 intentos."
                    )
            except GeocoderServiceError as exc:
                warnings.warn(f"Error de servicio geocodificando guardia {g.id}: {exc}")
                break

    return result


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _build_coords(
    inst: BursanInstance,
    assignments: list[dict],
) -> dict[str, tuple[float, float]]:
    """
    Construye el dict de coords-override para nodos sin coordenadas en la instancia.

    Prioridad: coordenadas en inst > geocodificacion Nominatim > COORDS_FALLBACK.
    Solo agrega entradas al dict cuando el nodo carece de lat/lon en inst.
    """
    guard_map = {g.id: g for g in inst.guardias}
    empresa_map = {e.nombre: e for e in inst.empresas}

    # Guardias que necesitan geocodificacion
    needs_geocode: list[Guard] = []
    for a in assignments:
        gid = a["guardia_id"]
        g = guard_map.get(gid)
        if g and (g.lat is None or g.lon is None) and g not in needs_geocode:
            needs_geocode.append(g)

    geocoded: dict[str, tuple[float, float]] = {}
    if needs_geocode:
        geocoded = geocodificar_guardias(needs_geocode)

    coords: dict[str, tuple[float, float]] = {}

    # Guardias
    for a in assignments:
        gid = a["guardia_id"]
        g = guard_map.get(gid)
        if g and g.lat is not None and g.lon is not None:
            continue  # La instancia ya tiene las coordenadas
        if gid in geocoded:
            coords[gid] = geocoded[gid]
        elif gid in COORDS_FALLBACK:
            coords[gid] = COORDS_FALLBACK[gid]
            warnings.warn(f"Usando coordenadas de fallback para guardia {gid}.")
        else:
            warnings.warn(
                f"Sin coordenadas para guardia {gid}. "
                "Sera excluido del ruteo si no hay override."
            )

    # Empresas sin coordenadas en inst
    seen_empresas: set[str] = set()
    for a in assignments:
        ename = a["empresa"]
        if ename in seen_empresas:
            continue
        seen_empresas.add(ename)
        e = empresa_map.get(ename)
        if e and e.lat is not None and e.lon is not None:
            continue
        if ename in COORDS_FALLBACK:
            coords[ename] = COORDS_FALLBACK[ename]
            warnings.warn(f"Usando coordenadas de fallback para empresa {ename}.")
        else:
            warnings.warn(
                f"Sin coordenadas para empresa {ename}. "
                "Sera excluida del ruteo si no hay override."
            )

    return coords


def _apply_2opt(result: RoutingResult, inst: BursanInstance) -> RoutingResult:
    """Aplica mejora 2-opt a todas las rutas de un RoutingResult."""
    # Recopilar todos los stops unicos de todas las rutas para la matriz de distancias
    all_stops: dict[str, Stop] = {}
    for r in result.rutas:
        for s in r.paradas:
            all_stops[s.node_id] = s

    dist_matrix = construir_matriz_distancias(list(all_stops.values()))

    improved = [
        improve_route_2opt(
            r,
            dist_matrix,
            R_RUTA=inst.max_distancia_ruta,
            R_VECINO=inst.max_distancia_vecino,
        )
        for r in result.rutas
    ]

    dist_total = round(sum(r.distancia_total_km for r in improved), 2)
    costo_total = round(sum(r.costo_clp for r in improved), 2)

    return RoutingResult(
        rutas=improved,
        distancia_total_sistema=dist_total,
        costo_total_clp=costo_total,
        n_buses_necesarios=len(improved),
        guardias_exclusivos=result.guardias_exclusivos,
        metodo=result.metodo,
    )


def _empty_result(metodo: str) -> RoutingResult:
    return RoutingResult(
        rutas=[],
        distancia_total_sistema=0.0,
        costo_total_clp=0.0,
        n_buses_necesarios=0,
        guardias_exclusivos=[],
        metodo=metodo,
    )


# ---------------------------------------------------------------------------
# Prueba minima
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os, sys
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from core.instance import Guard, Company, BursanInstance  # type: ignore[import]
    from core.assignment import AssignmentResult  # type: ignore[import]

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

    _asign = AssignmentResult(
        status="Optimal",
        z_total=42.0, z_max=16.0, z_min=5.5, z_range=10.5,
        asignaciones=[
            {"guardia_id": "TG1", "empresa": "CorpA", "turno": "D", "distancia_km": 16.0, "costo_clp": 0},
            {"guardia_id": "TG2", "empresa": "CorpA", "turno": "D", "distancia_km": 14.0, "costo_clp": 0},
            {"guardia_id": "TG3", "empresa": "CorpB", "turno": "D", "distancia_km": 5.5,  "costo_clp": 0},
            {"guardia_id": "TG4", "empresa": "CorpB", "turno": "D", "distancia_km": 6.3,  "costo_clp": 0},
        ],
        runtime_seg=0.1, modo="suma_total", alpha=1.0, beta=0.0,
    )

    # --- nearest_neighbor + 2-opt ---
    res_nn = resolver_rutas(_inst, _asign, metodo="nearest_neighbor", mejorar_2opt=True)
    assert len(res_nn.rutas) >= 1, "NN: debe haber al menos una ruta"
    assert res_nn.distancia_total_sistema > 0
    assert res_nn.n_buses_necesarios == len(res_nn.rutas)
    assert sorted(g for r in res_nn.rutas for g in r.guardias) == ["TG1", "TG2", "TG3", "TG4"]
    for r in res_nn.rutas:
        assert r.paradas[0].node_id == "deposito"
        assert r.paradas[-1].node_id == "deposito"
    print(
        f"NN+2opt : {len(res_nn.rutas)} ruta(s), "
        f"{res_nn.distancia_total_sistema:.1f} km, "
        f"${res_nn.costo_total_clp:,.0f} CLP"
    )

    # --- clarke_wright + 2-opt ---
    res_cw = resolver_rutas(_inst, _asign, metodo="clarke_wright", mejorar_2opt=True)
    assert len(res_cw.rutas) >= 1, "CW: debe haber al menos una ruta"
    assert res_cw.distancia_total_sistema > 0
    assert sorted(g for r in res_cw.rutas for g in r.guardias) == ["TG1", "TG2", "TG3", "TG4"]
    print(
        f"CW+2opt : {len(res_cw.rutas)} ruta(s), "
        f"{res_cw.distancia_total_sistema:.1f} km, "
        f"${res_cw.costo_total_clp:,.0f} CLP"
    )

    # --- Asignacion vacia → resultado vacio valido ---
    _empty = AssignmentResult(
        status="Infeasible", z_total=0, z_max=0, z_min=0, z_range=0,
        asignaciones=[], runtime_seg=0, modo="suma_total", alpha=1.0, beta=0.0,
    )
    res_empty = resolver_rutas(_inst, _empty)
    assert len(res_empty.rutas) == 0
    assert res_empty.distancia_total_sistema == 0.0

    # --- Guardias sin coordenadas → se usa COORDS_FALLBACK ---
    _g_nocords = [
        Guard("G1", "Guardia 1", "Punta Coralillo 647, Talcahuano", False, "activo"),
        Guard("G2", "Guardia 2", "Juan Ignacio Bolivar N554, Coronel", False, "activo"),
    ]
    _e_nocords = [
        Company("E1", "Noramco",   "Calle E Lote 18-A, Coronel",          1, 0, False, "activo"),
        Company("E2", "ITI Chile", "Av. Golfo de Arauco 1006, Coronel",   1, 0, False, "activo"),
    ]
    _d_nocords = {
        "G1": {"Noramco": 32.1, "ITI Chile": 32.8},
        "G2": {"Noramco": 5.2,  "ITI Chile": 6.1},
    }
    _inst_nc = BursanInstance(guardias=_g_nocords, empresas=_e_nocords, distancias=_d_nocords)
    _asign_nc = AssignmentResult(
        status="Optimal",
        z_total=37.3, z_max=32.1, z_min=5.2, z_range=26.9,
        asignaciones=[
            {"guardia_id": "G1", "empresa": "Noramco",   "turno": "D", "distancia_km": 32.1, "costo_clp": 0},
            {"guardia_id": "G2", "empresa": "ITI Chile", "turno": "D", "distancia_km": 6.1,  "costo_clp": 0},
        ],
        runtime_seg=0.1, modo="suma_total", alpha=1.0, beta=0.0,
    )
    import warnings as _w
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        res_fb = resolver_rutas(_inst_nc, _asign_nc, metodo="nearest_neighbor")
    fallback_warns = [str(w.message) for w in caught if "fallback" in str(w.message).lower()]
    assert len(fallback_warns) >= 2, f"Esperaba warnings de fallback, got: {fallback_warns}"
    assert len(res_fb.rutas) >= 1, "Debe rutear incluso sin coords en instancia"
    print(
        f"Fallback: {len(res_fb.rutas)} ruta(s), "
        f"{res_fb.distancia_total_sistema:.1f} km  "
        f"({len(fallback_warns)} warnings de fallback)"
    )

    print("OK routing.py: todas las aserciones pasaron")
