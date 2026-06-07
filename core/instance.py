"""core/instance.py — Modelo de datos para la instancia de optimización Bursan Rutas."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import pandas as pd


# ---------------------------------------------------------------------------
# Datos de línea base — usados cuando los CSV no están disponibles
# ---------------------------------------------------------------------------

_GUARDIAS_BASE: list[dict] = [
    {"id": "G1",  "nombre": "Guardia 1",  "direccion": "Punta Coralillo 647, Los Cerros, Talcahuano",          "supervisor": True,  "estado": "activo"},
    {"id": "G2",  "nombre": "Guardia 2",  "direccion": "Juan Ignacio Bolivar N554, Villa Louta, Coronel",       "supervisor": False, "estado": "activo"},
    {"id": "G3",  "nombre": "Guardia 3",  "direccion": "Corral 257, Collao, Concepción",                        "supervisor": False, "estado": "activo"},
    {"id": "G4",  "nombre": "Guardia 4",  "direccion": "Manquimavida N°580, Chiguayante",                       "supervisor": False, "estado": "activo"},
    {"id": "G5",  "nombre": "Guardia 5",  "direccion": "Arturo Prat 397, Chiguayante",                          "supervisor": False, "estado": "activo"},
    {"id": "G6",  "nombre": "Guardia 6",  "direccion": "Volcán San Pedro 2899, Jorge Alessandri, Concepción",   "supervisor": True,  "estado": "activo"},
    {"id": "G7",  "nombre": "Guardia 7",  "direccion": "Las Ilusiones 598, Coronel",                            "supervisor": False, "estado": "activo"},
    {"id": "G8",  "nombre": "Guardia 8",  "direccion": "Los Carrera 853, Coronel",                              "supervisor": False, "estado": "activo"},
    {"id": "G9",  "nombre": "Guardia 9",  "direccion": "René Schneider 105, Concepción",                        "supervisor": False, "estado": "activo"},
    {"id": "G10", "nombre": "Guardia 10", "direccion": "Grecia 1982, Hualpén",                                  "supervisor": False, "estado": "activo"},
    {"id": "G11", "nombre": "Guardia 11", "direccion": "Calle 4 Casa 320, Sector Campo Santo, Hualqui",         "supervisor": False, "estado": "activo"},
    {"id": "G12", "nombre": "Guardia 12", "direccion": "Porvenir N°379, Chiguayante",                           "supervisor": False, "estado": "activo"},
    {"id": "G13", "nombre": "Guardia 13", "direccion": "Libertad 245, Villa Aranjuez Pasaje 2, Chiguayante",    "supervisor": False, "estado": "activo"},
    {"id": "G14", "nombre": "Guardia 14", "direccion": "Assen N°4419, Hualpén",                                 "supervisor": False, "estado": "activo"},
]

_EMPRESAS_BASE: list[dict] = [
    {
        "id": "E1", "nombre": "Noramco",
        "direccion": "Calle E Lote 18-A, Parque Industrial Escuadrón, Coronel, Región del Biobío",
        "turno_dia": 1, "turno_noche": 1, "requiere_supervisor": False,
        "lat": -37.052, "lon": -73.138, "estado_contrato": "activo",
    },
    {
        "id": "E2", "nombre": "ITI Chile",
        "direccion": "Avenida Golfo de Arauco 1006, Parque Industrial Coronel, Coronel, Región del Biobío",
        "turno_dia": 2, "turno_noche": 2, "requiere_supervisor": False,
        "lat": -37.041, "lon": -73.145, "estado_contrato": "activo",
    },
    {
        "id": "E3", "nombre": "Oleoducto",
        "direccion": "Camino a Lenga 3381, Hualpén, Talcahuano, Bío Bío",
        "turno_dia": 4, "turno_noche": 0, "requiere_supervisor": True,
        "lat": -36.793, "lon": -73.118, "estado_contrato": "activo",
    },
    {
        "id": "E4", "nombre": "Indama",
        "direccion": "Av. Manuel Rodríguez 2881, Chiguayante, Bío Bío",
        "turno_dia": 2, "turno_noche": 2, "requiere_supervisor": False,
        "lat": -36.922, "lon": -72.990, "estado_contrato": "activo",
    },
]

# distancias[guardia_id][empresa_nombre] = km
_DISTANCIAS_KM: dict[str, dict[str, float]] = {
    "G1":  {"Noramco": 32.1, "ITI Chile": 32.8, "Oleoducto": 13.0, "Indama": 25.3},
    "G2":  {"Noramco":  5.2, "ITI Chile":  6.1, "Oleoducto": 36.5, "Indama": 31.8},
    "G3":  {"Noramco": 30.4, "ITI Chile": 31.0, "Oleoducto": 15.2, "Indama": 12.1},
    "G4":  {"Noramco": 32.0, "ITI Chile": 32.7, "Oleoducto": 18.5, "Indama":  5.1},
    "G5":  {"Noramco": 31.2, "ITI Chile": 31.9, "Oleoducto": 17.8, "Indama":  4.3},
    "G6":  {"Noramco": 28.6, "ITI Chile": 29.3, "Oleoducto": 14.1, "Indama": 10.2},
    "G7":  {"Noramco":  4.1, "ITI Chile":  4.8, "Oleoducto": 38.3, "Indama": 33.5},
    "G8":  {"Noramco":  3.4, "ITI Chile":  4.1, "Oleoducto": 37.6, "Indama": 32.9},
    "G9":  {"Noramco": 29.7, "ITI Chile": 30.4, "Oleoducto": 16.0, "Indama": 13.4},
    "G10": {"Noramco": 35.2, "ITI Chile": 35.9, "Oleoducto":  5.1, "Indama": 20.4},
    "G11": {"Noramco": 38.4, "ITI Chile": 38.9, "Oleoducto": 28.7, "Indama": 22.1},
    "G12": {"Noramco": 30.5, "ITI Chile": 31.2, "Oleoducto": 16.3, "Indama":  3.2},
    "G13": {"Noramco": 31.1, "ITI Chile": 31.8, "Oleoducto": 17.0, "Indama":  3.9},
    "G14": {"Noramco": 34.5, "ITI Chile": 35.2, "Oleoducto":  6.2, "Indama": 19.7},
}


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _to_float_or_none(val: object) -> float | None:
    try:
        if pd.isna(val):  # type: ignore[arg-type]
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _to_bool(val: object) -> bool:
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes", "si", "sí")


def _check_cols(df: pd.DataFrame, required: list[str], path: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: columnas faltantes {missing}")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Guard:
    """Guardia de seguridad de Bursan."""

    id: str
    nombre: str
    direccion: str
    supervisor: bool
    estado: Literal["activo", "licencia", "fuera_de_servicio", "vacaciones", "inactivo"]
    lat: float | None = None
    lon: float | None = None

    def is_disponible(self) -> bool:
        """Retorna True si el guardia está en estado activo."""
        return self.estado == "activo"


@dataclass
class Company:
    """Empresa cliente que recibe guardias de seguridad."""

    id: str
    nombre: str
    direccion: str
    turno_dia: int
    turno_noche: int
    requiere_supervisor: bool
    estado_contrato: Literal["activo", "inactivo"] = "activo"
    lat: float | None = None
    lon: float | None = None

    def demanda_total(self) -> int:
        """Retorna el total de guardias requeridos (turno día + turno noche)."""
        return self.turno_dia + self.turno_noche

    def is_activa(self) -> bool:
        """Retorna True si el contrato de la empresa está vigente."""
        return self.estado_contrato == "activo"


@dataclass
class BursanInstance:
    """Instancia completa del problema de ruteo Bursan."""

    guardias: list[Guard]
    empresas: list[Company]
    distancias: dict[str, dict[str, float]]
    deposito_lat: float = -36.820
    deposito_lon: float = -73.044
    capacidad_bus: int = 15
    max_distancia_ruta: float = 50.0     # R_RUTA: radio máximo de la ruta completa
    max_distancia_vecino: float = 25.0   # R_VECINO: radio para paradas intermedias
    rendimiento_kmL: float = 7.0
    precio_combustible_clp: float = 1560.0

    def guardias_activos(self) -> list[Guard]:
        """Retorna los guardias con estado activo."""
        return [g for g in self.guardias if g.is_disponible()]

    def distancia(self, guardia_id: str, empresa_nombre: str) -> float:
        """Distancia en km entre un guardia y una empresa, buscada por nombre de empresa."""
        return self.distancias[guardia_id][empresa_nombre]

    def costo_clp(self, km: float) -> float:
        """Costo en CLP para una distancia dada según rendimiento y precio de combustible."""
        return round(km / self.rendimiento_kmL * self.precio_combustible_clp, 2)

    def validar(self) -> list[str]:
        """
        Valida la integridad de la instancia.

        Retorna una lista de mensajes de error; lista vacía si todo está bien.
        Comprobaciones: IDs duplicados, capacidad de bus, supervisores disponibles
        y completitud de la matriz de distancias para guardias y empresas activos.
        """
        errores: list[str] = []

        gids = [g.id for g in self.guardias]
        if len(gids) != len(set(gids)):
            errores.append("Existen guardias con IDs duplicados.")

        eids = [e.id for e in self.empresas]
        if len(eids) != len(set(eids)):
            errores.append("Existen empresas con IDs duplicados.")

        if self.capacidad_bus < 1:
            errores.append(f"capacidad_bus debe ser >= 1 (actual: {self.capacidad_bus}).")

        activos = self.guardias_activos()
        supervisores = [g for g in activos if g.supervisor]
        empresas_activas = [e for e in self.empresas if e.is_activa()]

        if any(e.requiere_supervisor for e in empresas_activas) and not supervisores:
            errores.append(
                "Una o más empresas activas requieren supervisor pero no hay supervisores activos."
            )

        nombres_activos = {e.nombre for e in empresas_activas}
        for g in activos:
            if g.id not in self.distancias:
                errores.append(f"Guardia {g.id} no tiene distancias registradas.")
                continue
            for nombre in nombres_activos:
                if nombre not in self.distancias[g.id]:
                    errores.append(f"Falta distancia: {g.id} → {nombre}.")

        return errores


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_instance(data_dir: str = "data") -> BursanInstance:
    """
    Carga la instancia desde los CSV en data_dir.

    Si alguno de los tres CSV no existe, usa los datos de línea base hardcodeados.
    Lanza ValueError si los CSV existen pero les faltan columnas obligatorias.
    """
    g_path = os.path.join(data_dir, "guardias.csv")
    e_path = os.path.join(data_dir, "empresas.csv")
    d_path = os.path.join(data_dir, "distancias.csv")

    if not all(os.path.exists(p) for p in (g_path, e_path, d_path)):
        return _instance_from_baseline()
    return _instance_from_csv(g_path, e_path, d_path)


def save_guardias(instance: BursanInstance, path: str) -> None:
    """Persiste el estado actual de los guardias de la instancia en un CSV."""
    rows = [
        {
            "id": g.id,
            "nombre": g.nombre,
            "direccion": g.direccion,
            "supervisor": g.supervisor,
            "estado": g.estado,
            "lat": g.lat,
            "lon": g.lon,
        }
        for g in instance.guardias
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


# ---------------------------------------------------------------------------
# Constructores privados
# ---------------------------------------------------------------------------

def _instance_from_baseline() -> BursanInstance:
    guardias = [
        Guard(
            id=g["id"],
            nombre=g["nombre"],
            direccion=g["direccion"],
            supervisor=g["supervisor"],
            estado=g["estado"],
        )
        for g in _GUARDIAS_BASE
    ]
    empresas = [
        Company(
            id=e["id"],
            nombre=e["nombre"],
            direccion=e["direccion"],
            turno_dia=e["turno_dia"],
            turno_noche=e["turno_noche"],
            requiere_supervisor=e["requiere_supervisor"],
            estado_contrato=e["estado_contrato"],
            lat=e.get("lat"),
            lon=e.get("lon"),
        )
        for e in _EMPRESAS_BASE
    ]
    distancias = {gid: dict(v) for gid, v in _DISTANCIAS_KM.items()}
    return BursanInstance(guardias=guardias, empresas=empresas, distancias=distancias)


def _instance_from_csv(g_path: str, e_path: str, d_path: str) -> BursanInstance:
    # --- Guardias ---
    gdf = pd.read_csv(g_path)
    _check_cols(gdf, ["id", "nombre", "direccion", "supervisor", "estado"], g_path)
    has_g_coords = "lat" in gdf.columns and "lon" in gdf.columns
    guardias = [
        Guard(
            id=str(row["id"]),
            nombre=str(row["nombre"]),
            direccion=str(row["direccion"]),
            supervisor=_to_bool(row["supervisor"]),
            estado=str(row["estado"]),
            lat=_to_float_or_none(row["lat"]) if has_g_coords else None,
            lon=_to_float_or_none(row["lon"]) if has_g_coords else None,
        )
        for _, row in gdf.iterrows()
    ]

    # --- Empresas ---
    edf = pd.read_csv(e_path)
    _check_cols(
        edf,
        ["id", "nombre", "direccion", "turno_dia", "turno_noche", "requiere_supervisor"],
        e_path,
    )
    has_e_coords = "lat" in edf.columns and "lon" in edf.columns
    has_ec = "estado_contrato" in edf.columns
    empresas = [
        Company(
            id=str(row["id"]),
            nombre=str(row["nombre"]),
            direccion=str(row["direccion"]),
            turno_dia=int(row["turno_dia"]),
            turno_noche=int(row["turno_noche"]),
            requiere_supervisor=_to_bool(row["requiere_supervisor"]),
            estado_contrato=str(row["estado_contrato"]) if has_ec else "activo",
            lat=_to_float_or_none(row["lat"]) if has_e_coords else None,
            lon=_to_float_or_none(row["lon"]) if has_e_coords else None,
        )
        for _, row in edf.iterrows()
    ]

    # --- Distancias: empresa_id → empresa_nombre ---
    id_to_nombre = {e.id: e.nombre for e in empresas}
    ddf = pd.read_csv(d_path)
    _check_cols(ddf, ["guardia_id", "empresa_id", "distancia_km"], d_path)
    distancias: dict[str, dict[str, float]] = {}
    for _, row in ddf.iterrows():
        gid = str(row["guardia_id"])
        nombre = id_to_nombre.get(str(row["empresa_id"]), str(row["empresa_id"]))
        distancias.setdefault(gid, {})[nombre] = float(row["distancia_km"])

    return BursanInstance(guardias=guardias, empresas=empresas, distancias=distancias)


# ---------------------------------------------------------------------------
# Prueba mínima
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    inst = load_instance()
    assert len(inst.guardias_activos()) == 14
    assert inst.distancia("G1", "Oleoducto") == 13.0
    assert inst.costo_clp(13.0) == round(13 / 7 * 1560, 2)
    errores = inst.validar()
    assert errores == [], f"Errores de validación: {errores}"
    print("OK instance.py: todas las aserciones pasaron")
