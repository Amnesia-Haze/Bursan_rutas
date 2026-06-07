"""core/validator.py — Validación de instancia y entidades para Bursan Rutas."""
from __future__ import annotations

# Permite ejecutar el módulo directamente con `python core/validator.py`
# desde el directorio bursan_rutas/ sin manipular PYTHONPATH externamente.
try:
    from core.instance import BursanInstance
except ModuleNotFoundError:
    import sys as _sys
    import os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from core.instance import BursanInstance


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_VALID_ESTADOS_GUARDIA = frozenset(
    {"activo", "licencia", "fuera_de_servicio", "vacaciones", "inactivo"}
)
_VALID_ESTADOS_CONTRATO = frozenset({"activo", "inactivo"})
_REQUIRED_GUARD_FIELDS = frozenset({"id", "nombre", "direccion", "estado"})
_REQUIRED_COMPANY_FIELDS = frozenset({"nombre", "direccion", "turno_dia", "turno_noche"})
_GEOCODER_TIMEOUT = 5  # segundos


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def validate_instance(inst: BursanInstance) -> list[str]:
    """
    Valida la instancia completa contra las reglas de negocio de Bursan.

    Comprueba (en orden): supervisores disponibles, suficiencia de guardias,
    completitud y positividad de la matriz de distancias, demandas no negativas
    y parámetros de ruta.

    Returns:
        Lista de mensajes de error. Lista vacía significa instancia válida.
    """
    errores: list[str] = []

    activos = inst.guardias_activos()
    supervisores = [g for g in activos if g.supervisor]
    empresas_activas = [e for e in inst.empresas if e.is_activa()]

    # V1 — Supervisores mínimos en el pool de guardias activos
    if not supervisores:
        errores.append(
            "No hay ningún supervisor activo. Oleoducto requiere al menos uno."
        )

    # V2 — Cobertura específica para Oleoducto
    oleoducto = next((e for e in empresas_activas if e.nombre == "Oleoducto"), None)
    if oleoducto and oleoducto.requiere_supervisor and not supervisores:
        errores.append(
            "Oleoducto requiere supervisor certificado pero no hay supervisores disponibles."
        )

    # V3 — Suficiencia de guardias activos frente a demanda total
    n_activos = len(activos)
    demanda_total = sum(e.demanda_total() for e in empresas_activas)
    if n_activos < demanda_total:
        errores.append(
            f"Guardias activos insuficientes: {n_activos} disponibles, "
            f"{demanda_total} requeridos."
        )

    # V4 y V5 — Completitud y positividad de la matriz de distancias
    for g in activos:
        row = inst.distancias.get(g.id, {})
        for e in empresas_activas:
            valor = row.get(e.nombre)
            if valor is None:
                # V4: entrada ausente
                errores.append(f"Falta distancia de {g.id} a {e.nombre}.")
            elif valor <= 0:
                # V5: entrada inválida
                errores.append(
                    f"Distancia invalida: {g.id} -> {e.nombre} = {valor} km."
                )

    # V6 — Demandas no negativas
    for e in empresas_activas:
        if e.turno_dia < 0 or e.turno_noche < 0:
            errores.append(f"Demanda negativa en {e.nombre}.")

    # V7 — Parámetros de ruta coherentes
    if (
        inst.max_distancia_ruta <= 0
        or inst.max_distancia_vecino <= 0
        or inst.capacidad_bus < 1
    ):
        errores.append("Parametros de ruta invalidos (max_distancia_ruta, max_distancia_vecino o capacidad_bus).")

    return errores


# ---------------------------------------------------------------------------
# Validación de nuevas entidades
# ---------------------------------------------------------------------------

def validate_new_guard(inst: BursanInstance, guard_data: dict) -> list[str]:
    """
    Valida los datos de un nuevo guardia antes de incorporarlo a la instancia.

    Verifica: campos obligatorios presentes, id único entre los guardias
    existentes, estado en el conjunto de valores permitidos, y que las
    distancias a cada empresa activa (si se proveen en guard_data['distancias'])
    sean positivas y estén completas.

    Args:
        inst: Instancia actual de Bursan.
        guard_data: Diccionario con los campos del nuevo guardia. Campos
            obligatorios: id, nombre, direccion, estado. Clave opcional:
            distancias (dict[str, float] nombre_empresa → km).

    Returns:
        Lista de mensajes de error. Lista vacía significa datos válidos.
    """
    errores: list[str] = []

    # Campos obligatorios
    faltantes = sorted(_REQUIRED_GUARD_FIELDS - guard_data.keys())
    if faltantes:
        errores.append(f"Campos obligatorios faltantes: {faltantes}.")
        return errores  # Sin campos base no se puede continuar

    gid = str(guard_data["id"])

    # ID único
    if gid in {g.id for g in inst.guardias}:
        errores.append(f"Ya existe un guardia con id '{gid}'.")

    # Estado válido
    estado = str(guard_data["estado"])
    if estado not in _VALID_ESTADOS_GUARDIA:
        errores.append(
            f"Estado '{estado}' no permitido. "
            f"Valores válidos: {sorted(_VALID_ESTADOS_GUARDIA)}."
        )

    # Distancias a todas las empresas activas
    distancias: dict = guard_data.get("distancias", {})
    for e in inst.empresas:
        if not e.is_activa():
            continue
        valor = distancias.get(e.nombre)
        if valor is None:
            errores.append(f"Falta distancia de '{gid}' a {e.nombre}.")
        else:
            try:
                d = float(valor)
            except (TypeError, ValueError):
                errores.append(
                    f"Distancia de '{gid}' a {e.nombre} no es numérica: '{valor}'."
                )
                continue
            if d <= 0:
                errores.append(
                    f"Distancia inválida de '{gid}' a {e.nombre}: {d} km."
                )

    return errores


def validate_new_company(inst: BursanInstance, company_data: dict) -> list[str]:
    """
    Valida los datos de una nueva empresa antes de incorporarla a la instancia.

    Verifica: campos obligatorios presentes, nombre único, dirección no vacía,
    demandas no negativas y geocodificabilidad de la dirección (advertencia no
    bloqueante si Nominatim no resuelve la dirección o geopy no está disponible).

    Args:
        inst: Instancia actual de Bursan.
        company_data: Diccionario con los campos de la nueva empresa. Campos
            obligatorios: nombre, direccion, turno_dia, turno_noche.

    Returns:
        Lista de mensajes. Errores bloquean la operación; líneas que comienzan
        con 'ADVERTENCIA:' son informativas y no bloquean.
    """
    errores: list[str] = []

    # Campos obligatorios
    faltantes = sorted(_REQUIRED_COMPANY_FIELDS - company_data.keys())
    if faltantes:
        errores.append(f"Campos obligatorios faltantes: {faltantes}.")
        return errores

    nombre = str(company_data["nombre"]).strip()
    direccion = str(company_data.get("direccion", "")).strip()

    # Nombre único
    if nombre in {e.nombre for e in inst.empresas}:
        errores.append(f"Ya existe una empresa con nombre '{nombre}'.")

    # Dirección no vacía
    if not direccion:
        errores.append("La dirección de la empresa es obligatoria.")

    # Demandas no negativas
    for campo in ("turno_dia", "turno_noche"):
        val = company_data.get(campo, 0)
        try:
            if int(val) < 0:
                errores.append(f"Demanda negativa en '{nombre}' ({campo}: {val}).")
        except (TypeError, ValueError):
            errores.append(f"Valor inválido para {campo}: '{val}'.")

    # Geocodificación — advertencia no bloqueante
    if direccion:
        advertencia = _try_geocode(direccion)
        if advertencia:
            errores.append(advertencia)

    return errores


# ---------------------------------------------------------------------------
# Helper privado
# ---------------------------------------------------------------------------

def _try_geocode(address: str) -> str | None:
    """
    Intenta geocodificar una dirección con Nominatim.

    Returns:
        Cadena con prefijo 'ADVERTENCIA:' si falla, None si tiene éxito.
    """
    try:
        from geopy.geocoders import Nominatim  # importación diferida; no es stdlib
        geolocator = Nominatim(user_agent="bursan_rutas_validator")
        location = geolocator.geocode(address, timeout=_GEOCODER_TIMEOUT)
        if location is None:
            return (
                f"ADVERTENCIA: No se pudo geocodificar '{address}'. "
                "Verifica que la dirección sea correcta."
            )
        return None
    except ImportError:
        return (
            "ADVERTENCIA: geopy no está instalado; "
            "no se pudo verificar la dirección."
        )
    except Exception as exc:  # red / timeout / servicio caído
        return f"ADVERTENCIA: Error de geocodificación para '{address}': {exc}."


# ---------------------------------------------------------------------------
# Prueba mínima
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import sys

    # Asegurar que el directorio raíz del proyecto esté en sys.path
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from core.instance import load_instance  # type: ignore[import]

    inst = load_instance()

    # --- validate_instance ---
    errores = validate_instance(inst)
    assert errores == [], f"Se esperaba lista vacia, se obtuvo: {errores}"

    # --- validate_new_guard: campos faltantes ---
    e1 = validate_new_guard(inst, {"id": "G15", "nombre": "Guardia 15"})
    assert any("faltante" in m for m in e1), "Deberia detectar campos faltantes"

    # --- validate_new_guard: id duplicado ---
    distancias_ok = {
        e.nombre: 10.0 for e in inst.empresas if e.is_activa()
    }
    e2 = validate_new_guard(
        inst,
        {"id": "G1", "nombre": "X", "direccion": "X", "estado": "activo",
         "distancias": distancias_ok},
    )
    assert any("G1" in m for m in e2), "Deberia detectar id duplicado"

    # --- validate_new_company: nombre duplicado ---
    e3 = validate_new_company(
        inst,
        {"nombre": "Noramco", "direccion": "X", "turno_dia": 1, "turno_noche": 0},
    )
    assert any("Noramco" in m for m in e3), "Deberia detectar nombre duplicado"

    # --- validate_new_company: demanda negativa ---
    e4 = validate_new_company(
        inst,
        {"nombre": "NuevaEmp", "direccion": "Avda. Arturo Prat 1, Concepcion",
         "turno_dia": -1, "turno_noche": 0},
    )
    assert any("negativa" in m for m in e4), "Deberia detectar demanda negativa"

    print("OK validator.py: todas las aserciones pasaron")
