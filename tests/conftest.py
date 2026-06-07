"""tests/conftest.py — Fixtures compartidas para la suite de pruebas Bursan Rutas."""
from __future__ import annotations

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Path setup: permite importar módulos de bursan_rutas/ sin instalar el paquete
# ---------------------------------------------------------------------------
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)   # bursan_rutas/
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.assignment import resolver_asignacion
from core.instance import BursanInstance, Company, Guard, load_instance
from core.routing import resolver_rutas


# ---------------------------------------------------------------------------
# Instancias
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def inst_base() -> BursanInstance:
    """Instancia completa con los 14 guardias y 4 empresas base de Bursan."""
    return load_instance()


@pytest.fixture
def inst_pequena() -> BursanInstance:
    """
    Instancia reducida (4 guardias, 2 empresas) con coordenadas explícitas
    próximas al depósito. Diseñada para que las rutas se mantengan dentro de
    R_RUTA=50 km y el ILP se resuelva en menos de un segundo.
    """
    guardias = [
        Guard("G1", "Guardia 1", "Punta Coralillo 647, Talcahuano",
              supervisor=True,  estado="activo", lat=-36.820, lon=-73.044),
        Guard("G2", "Guardia 2", "Coronel Centro",
              supervisor=False, estado="activo", lat=-36.825, lon=-73.048),
        Guard("G3", "Guardia 3", "Collao, Concepción",
              supervisor=False, estado="activo", lat=-36.818, lon=-73.040),
        Guard("G4", "Guardia 4", "Chiguayante",
              supervisor=False, estado="activo", lat=-36.823, lon=-73.049),
    ]
    empresas = [
        Company(
            id="E1", nombre="Oleoducto",
            direccion="Camino a Lenga 3381, Hualpén",
            turno_dia=2, turno_noche=0,
            requiere_supervisor=True, estado_contrato="activo",
            lat=-36.822, lon=-73.050,
        ),
        Company(
            id="E2", nombre="Noramco",
            direccion="Parque Industrial Escuadrón, Coronel",
            turno_dia=1, turno_noche=1,
            requiere_supervisor=False, estado_contrato="activo",
            lat=-36.817, lon=-73.042,
        ),
    ]
    distancias = {
        "G1": {"Oleoducto": 10.0, "Noramco": 22.0},
        "G2": {"Oleoducto": 28.0, "Noramco":  8.0},
        "G3": {"Oleoducto": 12.0, "Noramco": 18.0},
        "G4": {"Oleoducto": 24.0, "Noramco": 10.0},
    }
    return BursanInstance(
        guardias=guardias,
        empresas=empresas,
        distancias=distancias,
        capacidad_bus=4,
        max_distancia_ruta=50.0,
        max_distancia_vecino=25.0,
    )


# ---------------------------------------------------------------------------
# Resultados de optimización con alcance de sesión (evita resolver ILP repetidamente)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def asignacion_base(inst_base):
    """Resultado ILP suma_total sobre inst_base (calculado una vez por sesión)."""
    return resolver_asignacion(inst_base, modo="suma_total")


@pytest.fixture(scope="session")
def asignacion_minimax(inst_base):
    """Resultado ILP minimax sobre inst_base (calculado una vez por sesión)."""
    return resolver_asignacion(inst_base, modo="minimax")


@pytest.fixture(scope="session")
def routing_base(inst_base, asignacion_base):
    """Rutas NN sobre inst_base + asignacion_base (calculado una vez por sesión)."""
    return resolver_rutas(inst_base, asignacion_base, metodo="nearest_neighbor")
