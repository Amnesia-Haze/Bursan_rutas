"""core/assignment.py — Resolución del problema de asignación guardias-empresas con PuLP."""
from __future__ import annotations

import time
from dataclasses import dataclass
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
) -> AssignmentResult:
    """
    Resuelve el problema de asignación de guardias a empresas mediante ILP (PuLP/CBC).

    Modos de función objetivo:
    - "suma_total":    Min Σ d_ge * x_get
    - "minimax":       Min M  s.t. M >= d_ge * x_get  para todo (g,e,t)
    - "multiobjetivo": Min alpha*(Σ d_ge * x_get) + beta*M

    Restricciones:
    - R1: cada guardia activo asignado a exactamente 1 (empresa, turno)
    - R2: cada puesto (empresa, turno) cubierto exactamente con n_ET guardias
    - R3: al menos 1 supervisor asignado a Oleoducto turno día
    - R4: distancia <= d_max por guardia (implementado via prefilter de variables)
    - R6 (opcional): z_max - z_min <= delta_equidad

    Args:
        inst:           Instancia completa de Bursan.
        modo:           Función objetivo.
        alpha:          Peso de suma total en modo multiobjetivo.
        beta:           Peso de distancia máxima en modo multiobjetivo.
        d_max:          Distancia máxima por guardia (km). Por defecto 40.0.
        delta_equidad:  Rango máximo z_max - z_min. None = sin restricción.
        tiempo_limite:  Tiempo límite CBC en segundos.

    Returns:
        AssignmentResult con status, métricas de distancia y lista de asignaciones.

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

    # Detección temprana de infactibilidad en R1 y R2
    for g in guardias:
        if not any(k[0] == g.id for k in x):
            return _resultado_vacio(
                "Infeasible", modo, alpha, beta, time.perf_counter() - t0
            )

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

    # R1: cada guardia activo asignado a exactamente 1 puesto
    for g in guardias:
        prob += (
            pulp.lpSum(x[k] for k in x if k[0] == g.id) == 1,
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
    oleo = next((e for e in empresas if e.nombre == "Oleoducto" and e.requiere_supervisor), None)
    if oleo:
        sup_ids = {g.id for g in guardias if g.supervisor}
        sup_vars = [x[k] for k in x if k[1] == "Oleoducto" and k[2] == "D" and k[0] in sup_ids]
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
            modo=modo, alpha=alpha, beta=beta,
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
        modo=modo, alpha=alpha, beta=beta,
    )


# ---------------------------------------------------------------------------
# Prueba mínima
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import sys

    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from core.instance import load_instance  # type: ignore[import]

    inst = load_instance()

    # --- Modo suma_total ---
    res = resolver_asignacion(inst, modo="suma_total")
    assert res.status == "Optimal", f"Status inesperado: {res.status}"
    # Valor obtenido con distancias aproximadas (la referencia de Fase 1 es 151.1 km,
    # alcanzable una vez que se geocodifiquen las distancias reales).
    assert abs(res.z_total - 168.0) < 0.5, (
        f"Z* = {res.z_total:.2f} km (esperado 168.0 con distancias aproximadas)"
    )
    print(f"suma_total: Z* = {res.z_total:.1f} km  "
          f"[rango {res.z_min:.1f}..{res.z_max:.1f}]  "
          f"t={res.runtime_seg:.2f}s")

    # Verificar que las 14 asignaciones son exactamente 14 (una por guardia)
    assert len(res.asignaciones) == 14, f"Esperadas 14 asignaciones, got {len(res.asignaciones)}"

    # --- Modo minimax ---
    res_mm = resolver_asignacion(inst, modo="minimax")
    assert res_mm.status == "Optimal"
    # Minimax minimiza la peor distancia, no la suma; Z* distinto de suma_total
    print(f"minimax:    M* = {res_mm.z_max:.1f} km  Z_total = {res_mm.z_total:.1f} km")

    # --- Modo multiobjetivo alpha=0.5, beta=0.5 ---
    res_mo = resolver_asignacion(inst, modo="multiobjetivo", alpha=0.5, beta=0.5)
    assert res_mo.status == "Optimal"
    print(f"multiobj:   Z* = {res_mo.z_total:.1f} km  M = {res_mo.z_max:.1f} km")

    # --- Con restriccion de equidad ---
    res_eq = resolver_asignacion(inst, modo="suma_total", delta_equidad=30.0)
    assert res_eq.status in ("Optimal", "Infeasible"), f"Status inesperado: {res_eq.status}"
    if res_eq.status == "Optimal":
        assert res_eq.z_range <= 30.0 + 1e-4, f"Rango {res_eq.z_range} > delta_equidad 30.0"
        print(f"equidad30:  Z* = {res_eq.z_total:.1f} km  rango = {res_eq.z_range:.1f} km")

    print("OK assignment.py: todas las aserciones pasaron")
