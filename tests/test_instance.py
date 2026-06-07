"""tests/test_instance.py — Carga de datos y métodos de BursanInstance."""
from __future__ import annotations

from copy import deepcopy

import pytest


class TestCargaInstancia:
    def test_carga_14_guardias(self, inst_base):
        assert len(inst_base.guardias) == 14

    def test_supervisores(self, inst_base):
        sups = {g.id for g in inst_base.guardias if g.supervisor}
        assert sups == {"G1", "G6"}

    def test_distancia_conocida(self, inst_base):
        assert inst_base.distancia("G1", "Oleoducto") == pytest.approx(13.0)

    def test_costo_clp(self, inst_base):
        d = inst_base.distancia("G1", "Oleoducto")   # 13.0 km
        costo = inst_base.costo_clp(d)
        # 13.0 / 7.0 * 1560 = 2897.14...
        assert costo == pytest.approx(13.0 / 7.0 * 1560.0, rel=0.001)

    def test_guardias_activos(self, inst_base):
        assert len(inst_base.guardias_activos()) == 14

    def test_guardia_inactivo_excluido(self, inst_base):
        inst = deepcopy(inst_base)
        g3 = next(g for g in inst.guardias if g.id == "G3")
        g3.estado = "inactivo"
        activos = inst.guardias_activos()
        assert len(activos) == 13
        assert "G3" not in {g.id for g in activos}

    def test_empresas_tienen_direccion(self, inst_base):
        for e in inst_base.empresas:
            assert e.direccion and len(e.direccion.strip()) > 0

    def test_direcciones_empresas_correctas(self, inst_base):
        nombres = {e.nombre for e in inst_base.empresas}
        assert nombres == {"Noramco", "ITI Chile", "Oleoducto", "Indama"}
