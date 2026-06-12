"""app/pages/1_Oferta.py — Panel de oferta de guardias Bursan."""
from __future__ import annotations

import math
import os
import sys

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Path setup — permite importar desde bursan_rutas/
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))   # app/pages/
_ROOT = os.path.dirname(os.path.dirname(_HERE))       # bursan_rutas/
_DATA_DIR = os.path.join(_ROOT, "data")
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.instance import BursanInstance, Guard, save_guardias
from core.validator import validate_new_guard

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # app/
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
from state import get_instance, recargar_instancia

# ---------------------------------------------------------------------------
# Constantes de presentacion
# ---------------------------------------------------------------------------
_COLOR_PRIMARY = "#1a3a5c"
_COLOR_ACCENT  = "#f0622a"

_ESTADOS_LABEL: dict[str, str] = {
    "activo":            "🟢 Activo",
    "licencia":          "🟡 Licencia",
    "fuera_de_servicio": "🔴 Fuera de servicio",
    "vacaciones":        "🔵 Vacaciones",
    "inactivo":          "⚫ Inactivo",
}
_LABEL_TO_ESTADO = {v: k for k, v in _ESTADOS_LABEL.items()}
_ESTADOS_FORM   = ["activo", "licencia", "fuera_de_servicio", "vacaciones", "inactivo"]

# Coordenadas de empresas (fallback cuando inst no tiene lat/lon en CSV)
_COORDS_EMP: dict[str, tuple[float, float]] = {
    "Noramco":   (-37.052, -73.138),
    "ITI Chile": (-37.041, -73.145),
    "Oleoducto": (-36.793, -73.118),
    "Indama":    (-36.922, -72.990),
}

# ---------------------------------------------------------------------------
# Configuracion de pagina
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Oferta | Bursan Rutas",
    page_icon="👮",
    layout="wide",
)

# ---------------------------------------------------------------------------
# CSS corporativo
# ---------------------------------------------------------------------------
st.markdown(f"""
<style>
    section.main > div {{ padding-top: 1rem; }}
    h1 {{ color: {_COLOR_PRIMARY} !important; font-size: 1.7rem !important; }}
    h2, h3 {{ color: {_COLOR_PRIMARY} !important; }}
    div[data-testid="stMetric"] {{
        background: white;
        border-radius: 8px;
        padding: 12px 16px;
        border-left: 4px solid {_COLOR_PRIMARY};
        box-shadow: 0 1px 3px rgba(0,0,0,.08);
    }}
    div[data-testid="stMetricLabel"] {{ font-size: .85rem; color: #555; }}
    .stDownloadButton button {{ background-color: {_COLOR_PRIMARY}; color: white; border: none; }}
    .stDownloadButton button:hover {{ background-color: #25527a; }}
    .stButton button[kind=primary] {{
        background-color: {_COLOR_ACCENT} !important;
        border-color: {_COLOR_ACCENT} !important;
    }}
    .info-box {{
        background: #eef3f9; border-left: 4px solid {_COLOR_PRIMARY};
        padding: 8px 14px; border-radius: 0 4px 4px 0;
        font-size: .88rem; margin-bottom: 6px;
    }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
def _init_ss() -> None:
    get_instance(_DATA_DIR)   # carga inst en session_state si no existe aún
    if "confirm_mass" not in st.session_state:
        st.session_state.confirm_mass = False
    if "ng_calc_dists" not in st.session_state:
        st.session_state.ng_calc_dists = {}


# ---------------------------------------------------------------------------
# Funciones auxiliares — geometria y geocodificacion
# ---------------------------------------------------------------------------
def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2.0 * R * math.asin(math.sqrt(min(a, 1.0))), 2)


def _geocodificar(address: str) -> tuple[float, float] | None:
    try:
        from geopy.geocoders import Nominatim
        geo = Nominatim(user_agent="bursan_rutas_oferta", timeout=10)
        loc = geo.geocode(f"{address}, Region del Biobio, Chile")
        if loc:
            return loc.latitude, loc.longitude
        return None
    except Exception:
        return None


def _calc_dists_from_address(
    address: str, inst: BursanInstance
) -> dict[str, float] | None:
    coords = _geocodificar(address)
    if coords is None:
        return None
    result: dict[str, float] = {}
    for e in inst.empresas:
        if not e.is_activa():
            continue
        if e.lat is not None and e.lon is not None:
            elat, elon = e.lat, e.lon
        elif e.nombre in _COORDS_EMP:
            elat, elon = _COORDS_EMP[e.nombre]
        else:
            continue
        result[e.nombre] = _haversine(coords[0], coords[1], elat, elon)
    return result


# ---------------------------------------------------------------------------
# Funciones auxiliares — persistencia
# ---------------------------------------------------------------------------
def _save_inst(inst: BursanInstance) -> None:
    """Guarda guardias.csv en el directorio de datos."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    save_guardias(inst, os.path.join(_DATA_DIR, "guardias.csv"))


def _append_distancias_csv(inst: BursanInstance, gid: str, dists: dict[str, float]) -> None:
    """Agrega filas al distancias.csv para el nuevo guardia."""
    d_path = os.path.join(_DATA_DIR, "distancias.csv")
    emp_id_map = {e.nombre: e.id for e in inst.empresas}
    new_rows = [
        {"guardia_id": gid, "empresa_id": emp_id_map.get(n, n), "distancia_km": v}
        for n, v in dists.items()
    ]
    if os.path.exists(d_path):
        df = pd.read_csv(d_path)
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    else:
        df = pd.DataFrame(new_rows)
    df.to_csv(d_path, index=False)


# ---------------------------------------------------------------------------
# Funciones auxiliares — dataframe
# ---------------------------------------------------------------------------
def _inst_to_df(inst: BursanInstance, estados_raw: list[str] | None = None) -> pd.DataFrame:
    rows = []
    for g in inst.guardias:
        if estados_raw and g.estado not in estados_raw:
            continue
        rows.append({
            "ID":        g.id,
            "Nombre":    g.nombre,
            "Dirección": g.direccion,
            "Grado":     "⭐ Supervisor" if g.supervisor else "Guardia",
            "Estado":    _ESTADOS_LABEL.get(g.estado, g.estado),
        })
    return pd.DataFrame(rows)


def _detect_estado_changes(
    original: pd.DataFrame, edited: pd.DataFrame
) -> dict[str, str]:
    """Devuelve {guardia_id: nuevo_estado_raw} para las filas donde cambió Estado."""
    changes: dict[str, str] = {}
    for i in range(len(original)):
        orig_label = original.iloc[i]["Estado"]
        edit_label = edited.iloc[i]["Estado"]
        if orig_label != edit_label:
            gid = original.iloc[i]["ID"]
            changes[gid] = _LABEL_TO_ESTADO.get(edit_label, edit_label)
    return changes


# ---------------------------------------------------------------------------
# Sección 0 — Métricas rápidas
# ---------------------------------------------------------------------------
def _render_metricas(inst: BursanInstance) -> None:
    total        = len(inst.guardias)
    activos      = len(inst.guardias_activos())
    supervisores = sum(1 for g in inst.guardias if g.supervisor and g.is_disponible())
    no_disp      = sum(
        1 for g in inst.guardias
        if g.estado in ("licencia", "fuera_de_servicio", "vacaciones")
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total guardias",    total)
    c2.metric("Activos hoy",        activos)
    c3.metric("Supervisores act.",  supervisores)
    c4.metric("No disponibles",     no_disp,
              delta=f"{no_disp} en licencia/fuera/vacaciones",
              delta_color="inverse")


# ---------------------------------------------------------------------------
# Sección 1 — Tabla de guardias
# ---------------------------------------------------------------------------
def _render_tabla(inst: BursanInstance) -> None:
    st.subheader("📋 Guardias registrados")

    ctrl_l, ctrl_r = st.columns([4, 2])
    with ctrl_l:
        todas_labels = list(_ESTADOS_LABEL.values())
        sel_labels = st.multiselect(
            "Filtrar por estado",
            options=todas_labels,
            default=todas_labels,
            key="filter_estados",
            label_visibility="collapsed",
        )
    with ctrl_r:
        df_export = _inst_to_df(inst)
        st.download_button(
            "📥 Exportar CSV",
            data=df_export.to_csv(index=False).encode("utf-8"),
            file_name="guardias_bursan.csv",
            mime="text/csv",
            use_container_width=True,
        )

    estados_raw = [_LABEL_TO_ESTADO[lbl] for lbl in sel_labels if lbl in _LABEL_TO_ESTADO]
    df = _inst_to_df(inst, estados_raw=estados_raw if sel_labels != todas_labels else None)

    if df.empty:
        st.info("No hay guardias con los estados seleccionados.")
        return

    edited = st.data_editor(
        df,
        column_config={
            "ID":        st.column_config.TextColumn("ID",        disabled=True, width="small"),
            "Nombre":    st.column_config.TextColumn("Nombre",    disabled=True, width="medium"),
            "Dirección": st.column_config.TextColumn("Dirección", disabled=True, width="large"),
            "Grado":     st.column_config.TextColumn("Grado",     disabled=True, width="small"),
            "Estado":    st.column_config.SelectboxColumn(
                "Estado",
                options=list(_ESTADOS_LABEL.values()),
                width="medium",
            ),
        },
        hide_index=True,
        use_container_width=True,
        key="guard_editor",
    )

    if st.button("💾 Guardar cambios de estado", type="primary", key="btn_save_table"):
        changes = _detect_estado_changes(df, edited)
        if not changes:
            st.info("Sin cambios pendientes.")
        else:
            for gid, nuevo in changes.items():
                g = next((g for g in inst.guardias if g.id == gid), None)
                if g:
                    g.estado = nuevo
            _save_inst(inst)
            recargar_instancia(_DATA_DIR)
            st.success("✓ Cambio guardado. La instancia se actualizó.")
            st.rerun()


# ---------------------------------------------------------------------------
# Sección 2 — Agregar nuevo guardia
# ---------------------------------------------------------------------------
def _render_agregar(inst: BursanInstance) -> None:
    st.markdown('<p class="info-box">Complete todos los campos. '
                'Las distancias pueden calcularse automáticamente si geopy está instalado.</p>',
                unsafe_allow_html=True)

    c_izq, c_der = st.columns(2)
    with c_izq:
        new_id     = st.text_input("ID único *",      key="ng_id",     placeholder="G15")
        new_nombre = st.text_input("Nombre completo *", key="ng_nombre", placeholder="Juan Pérez González")
        new_dir    = st.text_input(
            "Dirección *", key="ng_dir",
            placeholder="Arturo Prat 123, Coronel, Región del Biobío",
            help="Formato: Calle N°, Ciudad, Región del Biobío",
        )
    with c_der:
        new_grado  = st.selectbox("Grado",         ["Guardia", "Supervisor"], key="ng_grado")
        new_estado = st.selectbox("Estado inicial", _ESTADOS_FORM[:3],        key="ng_estado")

    # --- Distancias ---
    st.markdown("**📍 Distancias a empresas clientes (km)**")
    auto_calc = st.checkbox(
        "Calcular automáticamente desde la dirección (requiere geopy + conexión)",
        key="ng_auto",
    )
    if auto_calc:
        if st.button("🔄 Calcular distancias", key="ng_btn_calc"):
            addr = st.session_state.get("ng_dir", "").strip()
            if not addr:
                st.warning("Ingrese la dirección antes de calcular.")
            else:
                with st.spinner("Geocodificando..."):
                    dists = _calc_dists_from_address(addr, inst)
                if dists:
                    st.session_state.ng_calc_dists = dists
                    st.success(
                        f"Distancias calculadas (haversine desde coordenadas de '{addr[:45]}...')."
                        if len(addr) > 45 else
                        f"Distancias calculadas (haversine desde coordenadas de '{addr}')."
                    )
                else:
                    st.error("No se pudo geocodificar la dirección. Ingrese las distancias manualmente.")

    empresas_activas = [e for e in inst.empresas if e.is_activa()]
    calc = st.session_state.get("ng_calc_dists", {})

    dist_vals: dict[str, float] = {}
    cols_d = st.columns(2)
    for i, e in enumerate(empresas_activas):
        default_val = float(calc.get(e.nombre, 0.0))
        with cols_d[i % 2]:
            dist_vals[e.nombre] = st.number_input(
                f"{e.nombre} (km)",
                min_value=0.0,
                value=default_val,
                step=0.1,
                key=f"ng_dist_{e.nombre}",
                help=f"Dir: {e.direccion}",
            )

    st.markdown("")  # spacing
    if st.button("✅ Registrar guardia", type="primary", key="ng_btn_register"):
        guard_data = {
            "id":        (st.session_state.get("ng_id") or "").strip(),
            "nombre":    (st.session_state.get("ng_nombre") or "").strip(),
            "direccion": (st.session_state.get("ng_dir") or "").strip(),
            "supervisor": new_grado == "Supervisor",
            "estado":    new_estado,
            "distancias": dist_vals,
        }
        errors = validate_new_guard(inst, guard_data)
        # Separar advertencias de errores bloqueantes
        bloqueantes = [e for e in errors if not e.startswith("ADVERTENCIA")]
        advertencias = [e for e in errors if e.startswith("ADVERTENCIA")]

        for adv in advertencias:
            st.warning(adv)
        if bloqueantes:
            for err in bloqueantes:
                st.error(err)
        else:
            new_guard = Guard(
                id=guard_data["id"],
                nombre=guard_data["nombre"],
                direccion=guard_data["direccion"],
                supervisor=guard_data["supervisor"],
                estado=guard_data["estado"],
            )
            inst.guardias.append(new_guard)
            inst.distancias[guard_data["id"]] = dist_vals
            _save_inst(inst)
            _append_distancias_csv(inst, guard_data["id"], dist_vals)
            recargar_instancia(_DATA_DIR)

            # Limpiar campos del formulario
            for k in ["ng_id", "ng_nombre", "ng_dir"]:
                st.session_state.pop(k, None)
            for e in empresas_activas:
                st.session_state.pop(f"ng_dist_{e.nombre}", None)
            st.session_state.ng_calc_dists = {}

            st.success("✓ Cambio guardado. La instancia se actualizó.")
            st.rerun()


# ---------------------------------------------------------------------------
# Sección 3 — Cambio de estado masivo
# ---------------------------------------------------------------------------
def _render_masivo(inst: BursanInstance) -> None:
    opciones = [
        f"{g.id} — {g.nombre} ({_ESTADOS_LABEL.get(g.estado, g.estado)})"
        for g in inst.guardias
    ]
    gid_from_opcion = {
        f"{g.id} — {g.nombre} ({_ESTADOS_LABEL.get(g.estado, g.estado)})": g.id
        for g in inst.guardias
    }

    seleccion = st.multiselect(
        "Guardias a modificar",
        options=opciones,
        key="mass_sel",
        placeholder="Seleccione uno o más guardias...",
    )
    nuevo_estado_mass = st.selectbox(
        "Nuevo estado para todos los seleccionados",
        options=_ESTADOS_FORM,
        key="mass_estado",
        format_func=lambda e: _ESTADOS_LABEL.get(e, e),
    )

    if not seleccion:
        st.info("Seleccione al menos un guardia.")
        return

    c_prep, _ = st.columns([2, 5])
    with c_prep:
        if st.button("⚙️ Preparar actualización", key="mass_prep"):
            st.session_state.confirm_mass   = True
            st.session_state.pending_ids    = [gid_from_opcion[s] for s in seleccion]
            st.session_state.pending_estado = nuevo_estado_mass

    # --- Confirmación ---
    if st.session_state.confirm_mass:
        pids    = st.session_state.pending_ids
        pestado = st.session_state.pending_estado

        st.warning(
            f"**Confirmar:** cambiar {len(pids)} guardia(s) a "
            f"**{_ESTADOS_LABEL.get(pestado, pestado)}**\n\n"
            f"IDs afectados: {', '.join(pids)}"
        )
        col_ok, col_cancel, _ = st.columns([1, 1, 5])
        with col_ok:
            if st.button("✅ Confirmar", type="primary", key="mass_ok"):
                updated = 0
                for gid in pids:
                    g = next((g for g in inst.guardias if g.id == gid), None)
                    if g:
                        g.estado = pestado
                        updated += 1
                _save_inst(inst)
                recargar_instancia(_DATA_DIR)
                st.session_state.confirm_mass = False
                st.success("✓ Cambio guardado. La instancia se actualizó.")
                st.rerun()
        with col_cancel:
            if st.button("❌ Cancelar", key="mass_cancel"):
                st.session_state.confirm_mass = False
                st.rerun()


# ---------------------------------------------------------------------------
# Layout principal
# ---------------------------------------------------------------------------
_init_ss()
inst: BursanInstance = get_instance(_DATA_DIR)

st.title("👮 Gestión de Guardias — Oferta Operacional")
_render_metricas(inst)

st.divider()

_render_tabla(inst)

st.divider()

with st.expander("➕ Registrar nuevo guardia", expanded=False):
    _render_agregar(inst)

st.divider()

with st.expander("🔄 Cambio de estado masivo", expanded=False):
    _render_masivo(inst)
