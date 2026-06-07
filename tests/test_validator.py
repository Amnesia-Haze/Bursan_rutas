"""tests/test_validator.py — Validación de instancia y entidades."""
from __future__ import annotations

from copy import deepcopy

import pytest

from core.validator import validate_instance, validate_new_company


class TestValidador:
    def test_instancia_base_valida(self, inst_base):
        assert validate_instance(inst_base) == []

    def test_sin_supervisor_error(self, inst_base):
        inst = deepcopy(inst_base)
        for g in inst.guardias:
            if g.supervisor:
                g.estado = "inactivo"
        errores = validate_instance(inst)
        assert any("supervisor" in e.lower() for e in errores)

    def test_demanda_negativa_error(self, inst_base):
        inst = deepcopy(inst_base)
        inst.empresas[0].turno_dia = -1
        errores = validate_instance(inst)
        assert any("negativa" in e.lower() for e in errores)

    def test_guardias_insuficientes(self, inst_base):
        inst = deepcopy(inst_base)
        # Desactivar 3 guardias no supervisores → 11 activos < 14 demanda
        no_sups = [g for g in inst.guardias if not g.supervisor]
        for g in no_sups[:3]:
            g.estado = "inactivo"
        errores = validate_instance(inst)
        assert any("insuficientes" in e.lower() for e in errores)

    def test_empresa_sin_direccion_error(self, inst_base):
        msgs = validate_new_company(inst_base, {
            "nombre": "EmpresaNueva",
            "direccion": "",
            "turno_dia": 1,
            "turno_noche": 0,
        })
        bloqueantes = [m for m in msgs if not m.startswith("ADVERTENCIA:")]
        assert len(bloqueantes) > 0

    def test_empresa_direccion_fuera_region(self, inst_base):
        """Si geopy no está instalado genera ADVERTENCIA (no bloqueante); si está instalado
        y geocodifica correctamente, no hay mensajes. En ningún caso hay error bloqueante."""
        msgs = validate_new_company(inst_base, {
            "nombre": "Empresa Foranea",
            "direccion": "Avenida Apoquindo 3000, Las Condes, Santiago",
            "turno_dia": 1,
            "turno_noche": 0,
        })
        bloqueantes = [m for m in msgs if not m.startswith("ADVERTENCIA:")]
        assert len(bloqueantes) == 0
