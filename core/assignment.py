"""core/assignment.py — Resolución del problema de asignación guardias-empresas con PuLP."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    from core.instance import BursanInstance
except ModuleNotFoundError:
    import sys as _sys
    import os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from core.instance import BursanInstance

import pulp


# ---------------------------------------------------------------------------
# Dataclass de salida
# ---------------------------------------------------------------------------

@dataclass
class AssignmentResult:
    """Resultado de una resolución del modelo de asignación."""

    status: str          # "Optimal" | "Infeasible" | "Error"
    z_total: float       # suma de distancias asignadas (km)
    z_max: float         # distancia máxima asignada (km)
    z_min: float         # distancia mínima asignada (km)
    z_range: float       # z_max - z_min  (indicador de equidad)
    asignaciones: list[dict]  # [{guardia_id, empresa, turno, distancia_km, costo_clp}]
    runtime_seg: float
    modo: str            # "suma_total" | "minimax" | "multiobjetivo"
    alpha: float
    beta: float
    guardias_reserva: list[str] = field(default_factory=list)  # activos no asignados


# ---------------------------------------------------------------------------
# Constantes internas
# ---------------------------------------------------------------------------

_TURNOS = ("D", "N")
_MODOS_VALIDOS = frozenset({"suma_total", "minimax", "multiobjetivo"})


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def resolver_asignacion(
    inst: BursanInstance,
    modo: str = "suma_total",
    alpha: float = 1.0,
    beta: float = 0.0,
    d_max: float = 40.0,
    delta_equidad: Optional[float] = None,
    tiempo_limite: int = 60,
    _ignorar_supervisor: bool = False,
) -> AssignmentResult:
    """
    Resuelve el problema de asignación de guardias a empresas mediante ILP (PuLP/CBC).

    Modos de función objetivo:
    - "suma_total":    Min Σ d_ge * x_get
    - "minimax":       Min M  s.t. M >= d_ge * x_get  para todo (g,e,t)
    - "multiobjetivo": Min alpha*(Σ d_ge * x_get) + beta*M

    Restricciones:
    - R1: cada guardia activo asignado a lo sumo 1 (empresa, turno) — puede quedar en reserva
    - R2: cada puesto (empresa, turno) cubierto exactamente con n_ET guardias
    - R3: al menos 1 supervisor asignado a Oleoducto turno día
    - R4: distancia <= d_max por guardia (implementado via prefilter de variables)
    - R6 (opcional): z_max - z_min <= delta_equidad

    Args:
        inst:                Instancia completa de Bursan.
        modo:                Función objetivo.
        alpha:               Peso de suma total en modo multiobjetivo.
        beta:                Peso de distancia máxima en modo multiobjetivo.
        d_max:               Distancia máxima por guardia (km). Por defecto 40.0.
        delta_equidad:       Rango máximo z_max - z_min. None = sin restricción.
        tiempo_limite:       Tiempo límite CBC en segundos.
        _ignorar_supervisor: Uso interno del diagnóstico. Si True, omite R3.

    Returns:
        AssignmentResult con status, métricas de distancia, asignaciones y reserva.

    Raises:
        ValueError: si modo no es uno de los valores válidos.
    """
    if modo not in _MODOS_VALIDOS:
        raise ValueError(
            f"modo debe ser uno de {sorted(_MODOS_VALIDOS)}, recibido '{modo}'."
        )

    t0 = time.perf_counter()
    guardias = inst.guardias_activos()
    empresas = [e for e in inst.empresas if e.is_activa()]

    if not guardias or not empresas:
        return _resultado_vacio("Error", modo, alpha, beta, time.perf_counter() - t0)

    # Pre-calcular demanda por (empresa, turno)
    demand: dict[tuple[str, str], int] = {}
    for e in empresas:
        demand[(e.nombre, "D")] = e.turno_dia
        demand[(e.nombre, "N")] = e.turno_noche

    # -----------------------------------------------------------------------
    # Variables de decisión
    # x[(g_id, e_nombre, t)] = 1 si guardia g va a empresa e en turno t
    # Solo se crean para combinaciones con demand > 0 y d_ge <= d_max (R4 implícito)
    # -----------------------------------------------------------------------
    x: dict[tuple[str, str, str], pulp.LpVariable] = {}
    d_lkp: dict[tuple[str, str, str], float] = {}

    for g in guardias:
        for e in empresas:
            d_ge = inst.distancias.get(g.id, {}).get(e.nombre, float("inf"))
            for t in _TURNOS:
                if demand[(e.nombre, t)] > 0 and d_ge <= d_max:
                    key = (g.id, e.nombre, t)
                    safe = f"{g.id}_{e.id}_{t}"
                    x[key] = pulp.LpVariable(f"x_{safe}", cat="Binary")
                    d_lkp[key] = d_ge

    # Detección temprana de infactibilidad en R2:
    # cada puesto demandado debe tener al menos n_et candidatos disponibles.
    # (Ya NO se exige que cada guardia tenga un puesto: con R1 <= 1 puede ir a reserva.)
    for e in empresas:
        for t in _TURNOS:
            n_et = demand[(e.nombre, t)]
            if n_et == 0:
                continue
            available = sum(1 for k in x if k[1] == e.nombre and k[2] == t)
            if available < n_et:
                return _resultado_vacio(
                    "Infeasible", modo, alpha, beta, time.perf_counter() - t0
                )

    # -----------------------------------------------------------------------
    # Construir modelo ILP
    # -----------------------------------------------------------------------
    prob = pulp.LpProblem("Bursan_Asignacion", pulp.LpMinimize)

    suma_expr = pulp.lpSum(d_lkp[k] * x[k] for k in x)

    # Variables auxiliares para minimax / equidad
    need_M_max = modo in ("minimax", "multiobjetivo") or delta_equidad is not None
    M_max = pulp.LpVariable("M_max", lowBound=0) if need_M_max else None

    big_M = max(d_lkp.values()) if d_lkp else 0.0
    M_min = (
        pulp.LpVariable("M_min", lowBound=0, upBound=big_M)
        if delta_equidad is not None
        else None
    )

    # Función objetivo
    if modo == "suma_total":
        prob += suma_expr, "objetivo"
    elif modo == "minimax":
        prob += M_max, "objetivo"
    else:
        prob += alpha * suma_expr + beta * M_max, "objetivo"

    # R1: cada guardia activo asignado A LO SUMO a 1 puesto.
    # Los guardias activos no asignados quedan disponibles como RESERVA.
    # Esto permite que n_activos > demanda_total sea factible.
    for g in guardias:
        prob += (
            pulp.lpSum(x[k] for k in x if k[0] == g.id) <= 1,
            f"R1_{g.id}",
        )

    # R2: cada puesto cubierto exactamente con n_ET guardias
    for e in empresas:
        for t in _TURNOS:
            n_et = demand[(e.nombre, t)]
            if n_et == 0:
                continue
            prob += (
                pulp.lpSum(x[k] for k in x if k[1] == e.nombre and k[2] == t) == n_et,
                f"R2_{e.id}_{t}",
            )

    # R3: al menos 1 supervisor en Oleoducto turno día
    if not _ignorar_supervisor:
        oleo = next(
            (e for e in empresas if e.nombre == "Oleoducto" and e.requiere_supervisor),
            None,
        )
        if oleo:
            sup_ids = {g.id for g in guardias if g.supervisor}
            sup_vars = [
                x[k] for k in x
                if k[1] == "Oleoducto" and k[2] == "D" and k[0] in sup_ids
            ]
            if sup_vars:
                prob += pulp.lpSum(sup_vars) >= 1, "R3_supervisor_oleoducto"

    # Restricciones de M_max para minimax, multiobjetivo y/o R6
    if M_max is not None:
        for k, x_var in x.items():
            prob += M_max >= d_lkp[k] * x_var, f"Mmax_{k[0]}_{k[1]}_{k[2]}"

    # R6: equidad — rango de distancias asignadas
    if M_min is not None and delta_equidad is not None:
        for k, x_var in x.items():
            # M_min <= d_ge  cuando x=1  (big-M linearization)
            prob += (
                M_min <= d_lkp[k] + big_M * (1 - x_var),
                f"Mmin_{k[0]}_{k[1]}_{k[2]}",
            )
        prob += M_max - M_min <= delta_equidad, "R6_equidad"  # type: ignore[operator]

    # -----------------------------------------------------------------------
    # Resolver con CBC
    # -----------------------------------------------------------------------
    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=tiempo_limite)
    prob.solve(solver)
    runtime = time.perf_counter() - t0

    if prob.status != 1:  # 1 = Optimal
        raw = pulp.LpStatus.get(prob.status, "Unknown")
        return AssignmentResult(
            status="Infeasible" if prob.status == -1 else raw,
            z_total=0.0, z_max=0.0, z_min=0.0, z_range=0.0,
            asignaciones=[], runtime_seg=round(runtime, 3),
            modo=modo, alpha=alpha, beta=beta, guardias_reserva=[],
        )

    # -----------------------------------------------------------------------
    # Extraer solución
    # -----------------------------------------------------------------------
    asignaciones: list[dict] = []
    dists: list[float] = []

    for k, x_var in x.items():
        val = pulp.value(x_var)
        if val is not None and val > 0.5:
            g_id, e_nombre, t = k
            d_km = d_lkp[k]
            asignaciones.append(
                {
                    "guardia_id": g_id,
                    "empresa": e_nombre,
                    "turno": t,
                    "distancia_km": d_km,
                    "costo_clp": inst.costo_clp(d_km),
                }
            )
            dists.append(d_km)

    # Guardias activos que NO fueron asignados → reserva
    ids_asignados = {a["guardia_id"] for a in asignaciones}
    guardias_reserva = [g.id for g in guardias if g.id not in ids_asignados]

    z_total = round(sum(a["distancia_km"] for a in asignaciones), 2)
    z_max = max(dists) if dists else 0.0
    z_min = min(dists) if dists else 0.0

    return AssignmentResult(
        status="Optimal",
        z_total=z_total,
        z_max=z_max,
        z_min=z_min,
        z_range=round(z_max - z_min, 2),
        asignaciones=sorted(asignaciones, key=lambda a: a["guardia_id"]),
        runtime_seg=round(runtime, 3),
        modo=modo,
        alpha=alpha,
        beta=beta,
        guardias_reserva=sorted(guardias_reserva),
    )


# ---------------------------------------------------------------------------
# Helper privado
# ---------------------------------------------------------------------------

def _resultado_vacio(
    status: str, modo: str, alpha: float, beta: float, runtime: float
) -> AssignmentResult:
    """AssignmentResult sin solución (error o infactibilidad temprana)."""
    return AssignmentResult(
        status=status, z_total=0.0, z_max=0.0, z_min=0.0, z_range=0.0,
        asignaciones=[], runtime_seg=round(runtime, 3),
        modo=modo, alpha=alpha, beta=beta, guardias_reserva=[],
    )


# ---------------------------------------------------------------------------
# Diagnóstico de infactibilidad
# ---------------------------------------------------------------------------

def diagnosticar_infactibilidad(
    inst: BursanInstance,
    modo: str,
    alpha: float,
    beta: float,
    d_max: float,
    delta_equidad: float | None,
    tiempo_limite: int = 30,
) -> list[str]:
    """
    Cuando resolver_asignacion() retorna Infeasible, identifica causas
    probables re-resolviendo con relajaciones incrementales.
    Retorna lista de mensajes ordenados de más a menos probable,
    cada uno con una acción concreta sugerida.
    """
    causas: list[str] = []

    guardias = inst.guardias_activos()
    empresas = [e for e in inst.empresas if e.is_activa()]
    n_activos = len(guardias)
    demanda_total = sum(e.demanda_total() for e in empresas)

    # 1) Suficiencia bruta de guardias — causa raíz más común
    if n_activos < demanda_total:
        faltan = demanda_total - n_activos
        causas.append(
            f"🔴 **Guardias insuficientes**: hay {n_activos} activos pero se "
            f"requieren {demanda_total} puestos. Activa al menos {faltan} "
            f"guardia(s) más, o reduce la demanda en Empresas."
        )
        return causas  # causa raíz clara — no seguir diagnosticando

    # 2) Cobertura de puestos: algún puesto sin suficientes candidatos por D_max
    for e in empresas:
        for t, n_et in (("D", e.turno_dia), ("N", e.turno_noche)):
            if n_et == 0:
                continue
            candidatos = sum(
                1 for g in guardias
                if inst.distancias.get(g.id, {}).get(e.nombre, float("inf")) <= d_max
            )
            if candidatos < n_et:
                causas.append(
                    f"🟠 **{e.nombre} turno {t} no tiene candidatos suficientes** "
                    f"dentro de D_max={d_max:.0f} km: requiere {n_et}, hay {candidatos} "
                    f"guardias a ≤ {d_max:.0f} km. Aumenta D_max o agrega guardias "
                    f"cercanos a {e.nombre}."
                )

    # 3) Supervisor disponible para empresas que lo requieren.
    # Se usa el d_max REAL (no 9999) para aislar solo el efecto de R3.
    # Si con el mismo d_max pero sin R3 el problema es factible, entonces R3 es la causa.
    supervisores = [g for g in guardias if g.supervisor]
    r_sin_r3 = resolver_asignacion(
        inst, modo=modo, alpha=alpha, beta=beta, d_max=d_max,
        delta_equidad=None, tiempo_limite=tiempo_limite, _ignorar_supervisor=True,
    )
    if r_sin_r3.status == "Optimal":
        # El modelo es factible SIN R3 → la restricción de supervisor es la culpable
        empresas_suv = [e.nombre for e in empresas if e.requiere_supervisor]
        sup_ids = [g.id for g in supervisores]
        causas.append(
            f"🔴 **Restricción de supervisor (R3) infactible**. "
            f"Empresas que requieren supervisor: {empresas_suv}. "
            f"Supervisores activos: {sup_ids or 'NINGUNO'}. "
            f"Reactiva un supervisor (G1 o G6) o marca a otro guardia como supervisor."
        )

    # 4) Relajar restricción de equidad
    if delta_equidad is not None:
        r = resolver_asignacion(inst, modo=modo, alpha=alpha, beta=beta,
                                d_max=d_max, delta_equidad=None,
                                tiempo_limite=tiempo_limite)
        if r.status == "Optimal":
            causas.append(
                f"🟠 **Δ_max = {delta_equidad:.0f} km es demasiado estricto**. "
                f"Sin esa restricción, el rango real mínimo alcanzable es "
                f"≈ {r.z_range:.1f} km. Aumenta Δ_max a al menos "
                f"{math.ceil(r.z_range)} km, o desactiva la equidad."
            )

    # 5) Relajar D_max
    r2 = resolver_asignacion(inst, modo=modo, alpha=alpha, beta=beta,
                             d_max=9999, delta_equidad=delta_equidad,
                             tiempo_limite=tiempo_limite)
    if r2.status == "Optimal":
        causas.append(
            f"🟠 **D_max = {d_max:.0f} km es demasiado restrictivo**. "
            f"Con la asignación óptima se requiere al menos "
            f"{math.ceil(r2.z_max)} km para algún guardia. "
            f"Aumenta D_max a {math.ceil(r2.z_max)} km o más."
        )

    if not causas:
        causas.append(
            "🔴 **Restricciones incompatibles entre sí**. Prueba relajar "
            "Δ_max y D_max simultáneamente, o revisa que todos los "
            "guardias/empresas nuevos tengan distancias registradas."
        )

    return causas


# ---------------------------------------------------------------------------
# Línea base de comparación
# ---------------------------------------------------------------------------

def calcular_linea_base(inst: BursanInstance) -> AssignmentResult:
    """
    Recalcula la asignación 'línea base': suma total, sin restricciones
    de equidad ni D_max adicional (D_max=9999), usando la matriz de
    distancias ACTUAL de la instancia.

    Sirve como referencia de comparación para cualquier modo que el
    usuario haya seleccionado, calculada con los MISMOS datos que el
    modelo está usando en este momento.
    """
    return resolver_asignacion(
        inst, modo="suma_total", alpha=1.0, beta=0.0,
        d_max=9999, delta_equidad=None, tiempo_limite=30,
    )


# ---------------------------------------------------------------------------
# Prueba mínima
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import sys
    from copy import deepcopy

    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from core.instance import load_instance  # type: ignore[import]

    inst = load_instance()

    # --- Caso balanceado (demanda original = 14 puestos): 0 en reserva ---
    res = resolver_asignacion(inst, modo="suma_total")
    assert res.status == "Optimal", f"Status inesperado: {res.status}"
    demanda_base = sum(e.demanda_total() for e in inst.empresas if e.is_activa())
    assert len(res.asignaciones) == demanda_base, (
        f"Esperadas {demanda_base} asignaciones, got {len(res.asignaciones)}"
    )
    n_activos = len(inst.guardias_activos())
    assert len(res.guardias_reserva) == n_activos - demanda_base
    print(f"suma_total: Z* = {res.z_total:.1f} km  "
          f"[rango {res.z_min:.1f}..{res.z_max:.1f}]  "
          f"{len(res.asignaciones)} asignados, {len(res.guardias_reserva)} reserva  "
          f"t={res.runtime_seg:.2f}s")

    # --- Caso de la captura: 14 activos, demanda menor → guardias en reserva ---
    inst_red = deepcopy(inst)
    demandas_test = {
        "Noramco":   (1, 1),
        "ITI Chile": (2, 1),
        "Oleoducto": (3, 0),
        "Indama":    (1, 0),
    }  # suma = 9
    for e in inst_red.empresas:
        if e.nombre in demandas_test:
            e.turno_dia, e.turno_noche = demandas_test[e.nombre]
    demanda_red = sum(e.demanda_total() for e in inst_red.empresas if e.is_activa())
    assert demanda_red == 9, f"Demanda de prueba debería ser 9, es {demanda_red}"

    res_red = resolver_asignacion(inst_red, modo="suma_total")
    assert res_red.status == "Optimal", (
        f"INFEASIBLE con demanda=9 y 14 activos: {res_red.status}"
    )
    assert len(res_red.asignaciones) == 9
    assert len(res_red.guardias_reserva) == 5
    print(f"demanda=9:  {len(res_red.asignaciones)} asignados, "
          f"{len(res_red.guardias_reserva)} en reserva "
          f"({', '.join(res_red.guardias_reserva)})  Z*={res_red.z_total:.1f} km")

    # --- Modo minimax ---
    res_mm = resolver_asignacion(inst, modo="minimax")
    assert res_mm.status == "Optimal"
    print(f"minimax:    M* = {res_mm.z_max:.1f} km  Z_total = {res_mm.z_total:.1f} km")

    # --- Modo multiobjetivo ---
    res_mo = resolver_asignacion(inst, modo="multiobjetivo", alpha=0.5, beta=0.5)
    assert res_mo.status == "Optimal"
    print(f"multiobj:   Z* = {res_mo.z_total:.1f} km  M = {res_mo.z_max:.1f} km")

    # --- Con restriccion de equidad ---
    res_eq = resolver_asignacion(inst, modo="suma_total", delta_equidad=30.0)
    assert res_eq.status in ("Optimal", "Infeasible")
    if res_eq.status == "Optimal":
        assert res_eq.z_range <= 30.0 + 1e-4
        print(f"equidad30:  Z* = {res_eq.z_total:.1f} km  rango = {res_eq.z_range:.1f} km")

    # --- Diagnóstico D_max muy bajo ---
    r_inf = resolver_asignacion(inst, modo="suma_total", d_max=2.0, delta_equidad=None)
    assert r_inf.status == "Infeasible", f"Esperado Infeasible, got {r_inf.status}"
    causas = diagnosticar_infactibilidad(inst, "suma_total", 1.0, 0.0, 2.0, None)
    assert len(causas) > 0
    print("Diagnostico D_max bajo: OK")

    print("OK assignment.py: todas las aserciones pasaron")
    