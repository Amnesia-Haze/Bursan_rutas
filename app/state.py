"""app/state.py — Gestión centralizada de la instancia en session_state."""
import sys
import os
from datetime import datetime
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from core.instance import load_instance, BursanInstance


@st.cache_data
def _cargar_instancia_cached(data_dir: str = "data") -> BursanInstance:
    """Carga la instancia desde CSV. Cacheada por Streamlit para evitar
    lecturas repetidas de disco en cada rerun, PERO debe invalidarse
    explícitamente con recargar_instancia() tras cualquier cambio."""
    return load_instance(data_dir)


def get_instance(data_dir: str = "data") -> BursanInstance:
    """
    Retorna la instancia actual. Si no existe en session_state
    (por ejemplo, navegación directa a una subpágina), la carga.
    """
    if "inst" not in st.session_state:
        st.session_state.inst = _cargar_instancia_cached(data_dir)
        st.session_state["instance_loaded_at"] = datetime.now().strftime("%H:%M:%S")
    return st.session_state.inst


def recargar_instancia(data_dir: str = "data") -> BursanInstance:
    """
    Limpia el caché de Streamlit, vuelve a leer los CSV desde disco,
    y actualiza session_state. Llamar SIEMPRE después de:
    - agregar/desactivar un guardia
    - modificar demanda de una empresa
    - agregar/desactivar una empresa
    """
    _cargar_instancia_cached.clear()
    inst = _cargar_instancia_cached(data_dir)
    st.session_state.inst = inst
    st.session_state["instance_loaded_at"] = datetime.now().strftime("%H:%M:%S")

    # Invalidar resultado de optimización anterior: ya no corresponde
    # a los datos actuales
    for key in ("last_result", "last_asignacion", "last_rutas"):
        if key in st.session_state:
            del st.session_state[key]

    return inst


if __name__ == "__main__":
    print("✓ app/state.py creado correctamente")
