"""tests/test_assignment.py — Modelo de asignación ILP (PuLP/CBC)."""
from __future__ import annotations

from copy import deepcopy

import pytest

from core.assignment import resolver_asignacion


class TestAsignacion:
    def test_resultado_conocido(self, asignacion_base):
        # Distancias hardcodeadas en _DISTANCIAS_KM dan z_total=168 km.
        # (El informe Fase 1 reporta 151.1 km con coordenadas geocodificadas reales.)
        assert asignacion_base.z_total == pytest.approx(168.0, abs=1.0)

    def test_status_optimal(self, asignacion_base):
        assert asignacion_base.status == "Optimal"

    def test_r3_supervisor_oleoducto(self, inst_base, asignacion_base):
        """R3: al menos un supervisor debe quedar asignado a Oleoducto."""
        oleoducto = [a for a in asignacion_base.asignaciones
                     if a["empresa"] == "Oleoducto"]
        guard_ids = {a["guardia_id"] for a in oleoducto}
        supervisors = {g.id for g in inst_base.guardias if g.supervisor}
        assert len(guard_ids & supervisors) >= 1

    def test_minimax_reduce_max(self, asignacion_base, asignacion_minimax):
        """Minimax debe reducir la distancia máxima respecto a suma_total."""
        assert asignacion_minimax.z_max < asignacion_base.z_max

    def test_infactible_sin_guardias(self, inst_base):
        inst = deepcopy(inst_base)
        for g in inst.guardias:
            g.estado = "inactivo"
        result = resolver_asignacion(inst)
        # Sin guardias activos el solver detecta la infactibilidad sin construir el ILP.
        assert result.status != "Optimal"

    def test_multiobjetivo_alpha1_igual_suma(self, inst_base, asignacion_base):
        """Con alpha=1, beta=0 el multiobjetivo es equivalente a suma_total."""
        result_multi = resolver_asignacion(
            inst_base, modo="multiobjetivo", alpha=1.0, beta=0.0
        )
        assert result_multi.z_total == pytest.approx(asignacion_base.z_total, rel=0.01)

    def test_todos_asignados(self, inst_base, asignacion_base):
        n_activos = len(inst_base.guardias_activos())
        assert len(asignacion_base.asignaciones) == n_activos
