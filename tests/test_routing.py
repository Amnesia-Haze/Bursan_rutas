"""tests/test_routing.py — Heurísticas de ruteo CVRP."""
from __future__ import annotations

import pytest

from core.assignment import resolver_asignacion
from core.routing import resolver_rutas


class TestRuteo:
    def test_rutas_no_exceden_ruta_max(self, inst_base, routing_base):
        """Rutas combinadas (no exclusivas) deben respetar R_RUTA."""
        non_exclusivas = [r for r in routing_base.rutas if not r.es_exclusiva]
        assert len(non_exclusivas) > 0, "Debe existir al menos una ruta no exclusiva"
        for ruta in non_exclusivas:
            assert ruta.distancia_total_km <= inst_base.max_distancia_ruta + 0.1

    def test_capacidad_respetada(self, inst_base, routing_base):
        for ruta in routing_base.rutas:
            assert len(ruta.guardias) <= inst_base.capacidad_bus

    def test_guardia_en_una_sola_ruta(self, routing_base):
        all_guards = [g for r in routing_base.rutas for g in r.guardias]
        assert len(all_guards) == len(set(all_guards))

    def test_ruta_exclusiva_generada(self, inst_base, asignacion_base):
        """Con coordenadas de fallback y R_VECINO=25 km, deben generarse rutas exclusivas."""
        routing = resolver_rutas(
            inst_base, asignacion_base,
            metodo="nearest_neighbor", mejorar_2opt=False,
        )
        assert len(routing.guardias_exclusivos) > 0

    def test_clarke_wright_vs_nn(self, inst_pequena):
        """Ambos métodos deben cubrir exactamente los guardias asignados."""
        result = resolver_asignacion(inst_pequena, modo="suma_total")
        routing_nn = resolver_rutas(inst_pequena, result, metodo="nearest_neighbor")
        routing_cw = resolver_rutas(inst_pequena, result, metodo="clarke_wright")
        for routing in (routing_nn, routing_cw):
            assert routing.n_buses_necesarios >= 1
            guards_in_routes = [g for r in routing.rutas for g in r.guardias]
            assert len(guards_in_routes) == len(result.asignaciones)
