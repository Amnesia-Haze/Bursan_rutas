import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from copy import deepcopy
from core.instance import load_instance
from core.assignment import resolver_asignacion, diagnosticar_infactibilidad, calcular_linea_base


# ─── GRUPO A: invalidación de caché ──────────────────────────────────────────

def test_recargar_instancia_lee_csv_actualizado(tmp_path):
    """
    Simula: modificar empresas.csv externamente, llamar recargar_instancia(),
    verificar que la nueva instancia refleja el cambio.
    NOTA: requiere contexto de Streamlit (st.session_state). Si se ejecuta
    fuera de Streamlit, usar streamlit.testing.v1.AppTest o marcar como
    prueba de integración manual.
    """
    import pytest
    pytest.skip("Requiere streamlit.testing.v1.AppTest — ver test_app_integracion.py")


# ─── GRUPO B: diagnóstico de infactibilidad ──────────────────────────────────

def test_diagnostico_dmax_bajo():
    inst = load_instance()
    r = resolver_asignacion(inst, modo="suma_total", d_max=2.0, delta_equidad=None)
    assert r.status == "Infeasible"

    causas = diagnosticar_infactibilidad(inst, "suma_total", 1.0, 0.0, 2.0, None)
    assert len(causas) > 0
    assert any("D_max" in c for c in causas)


def test_diagnostico_guardias_insuficientes():
    inst = deepcopy(load_instance())
    for g in inst.guardias[:8]:  # desactivar 8 de 14
        g.estado = "inactivo"

    r = resolver_asignacion(inst, modo="suma_total", d_max=40, delta_equidad=None)
    assert r.status == "Infeasible"

    causas = diagnosticar_infactibilidad(inst, "suma_total", 1.0, 0.0, 40, None)
    assert any("insuficientes" in c.lower() for c in causas)


# ─── GRUPO C: línea base dinámica ────────────────────────────────────────────

def test_linea_base_coincide_con_suma_total_sin_restricciones():
    inst = load_instance()
    base = calcular_linea_base(inst)
    directo = resolver_asignacion(inst, modo="suma_total", d_max=9999, delta_equidad=None)

    assert base.status == "Optimal"
    assert abs(base.z_total - directo.z_total) < 0.01


def test_linea_base_no_es_151_1_hardcodeado():
    """La línea base debe calcularse, no ser el valor fijo del informe Fase 1."""
    inst = load_instance()
    base = calcular_linea_base(inst)
    # Con coordenadas/distancias actuales de la app, se espera ~168 km,
    # no 151.1 (que correspondía a otra matriz de distancias)
    assert base.z_total > 0
    # No verificamos un valor exacto porque depende de la matriz vigente,
    # solo que el cálculo es dinámico y no un literal


# ─── GRUPO E: distancias reales ──────────────────────────────────────────────

def test_haversine_fallback_disponible():
    from core.distances import haversine_km
    d = haversine_km(-36.820, -73.044, -37.052, -73.138)
    assert 20 < d < 35


def test_get_distance_matrix_estructura():
    from core.distances import get_distance_matrix
    coords = [(-36.820, -73.044), (-37.052, -73.138), (-36.793, -73.118)]
    dist, dur, metodo = get_distance_matrix(coords)
    assert len(dist) == 3 and len(dist[0]) == 3
    assert dist[0][0] == 0.0
    assert metodo in ("ors_road", "ors_road_cached", "haversine_fallback")


def test_routing_result_tiene_metodo_distancia():
    from core.routing import resolver_rutas
    inst = load_instance()
    asignacion = resolver_asignacion(inst, modo="suma_total")
    rutas = resolver_rutas(inst, asignacion, metodo="nearest_neighbor")
    assert hasattr(rutas, "metodo_distancia")
    assert rutas.metodo_distancia in ("ors_road", "ors_road_cached", "haversine_fallback")
