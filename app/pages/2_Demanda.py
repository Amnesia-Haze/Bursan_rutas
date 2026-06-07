"""app/pages/2_Demanda.py — Panel de demanda de empresas clientes Bursan."""
from __future__ import annotations

import math
import os
import sys
import urllib.parse

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_DATA_DIR = os.path.join(_ROOT, "data")
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.instance import BursanInstance, Company, load_instance
from core.validator import validate_new_company

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
_COLOR_PRIMARY = "#1a3a5c"
_COLOR_ACCENT  = "#f0622a"

# ---------------------------------------------------------------------------
# Configuracion de pagina
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Demanda | Bursan Rutas",
    page_icon="🏭",
    layout="wide",
)

# ---------------------------------------------------------------------------
# CSS corporativo (consistente con 1_Oferta.py)
# ---------------------------------------------------------------------------
st.markdown(f"""
<style>
    section.main > div {{ padding-top: 1rem; }}
    h1 {{ color: {_COLOR_PRIMARY} !important; font-size: 1.7rem !important; }}
    h2, h3 {{ color: {_COLOR_PRIMARY} !important; }}
    div[data-testid="stMetric"] {{
        background: white; border-radius: 8px; padding: 12px 16px;
        border-left: 4px solid {_COLOR_PRIMARY};
        box-shadow: 0 1px 3px rgba(0,0,0,.08);
    }}
    .stDownloadButton button {{ background-color: {_COLOR_PRIMARY}; color: white; border: none; }}
    .stButton button[kind=primary] {{
        background-color: {_COLOR_ACCENT} !important;
        border-color: {_COLOR_ACCENT} !important;
    }}
    .balance-ok  {{ background:#d1fae5; border-left:4px solid #065f46;
                    color:#065f46; padding:8px 14px; border-radius:0 4px 4px 0;
                    font-weight:bold; font-size:.95rem; margin-bottom:8px; }}
    .balance-err {{ background:#fee2e2; border-left:4px solid #991b1b;
                    color:#991b1b; padding:8px 14px; border-radius:0 4px 4px 0;
                    font-weight:bold; font-size:.95rem; margin-bottom:8px; }}
    .info-box {{ background:#eef3f9; border-left:4px solid {_COLOR_PRIMARY};
                 padding:8px 14px; border-radius:0 4px 4px 0;
                 font-size:.88rem; margin-bottom:6px; }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
def _init_ss() -> None:
    if "inst" not in st.session_state:
        st.session_state.inst = load_instance(_DATA_DIR)
    if "demand_adj" not in st.session_state:
        st.session_state.demand_adj = {}       # {empresa_nombre: int} ajuste temporal
    if "confirm_inactivar" not in st.session_state:
        st.session_state.confirm_inactivar = False
    if "nueva_emp_result" not in st.session_state:
        st.session_state.nueva_emp_result = None


# ---------------------------------------------------------------------------
# Helpers — geometria y geocodificacion
# ---------------------------------------------------------------------------
def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2.0 * R * math.asin(math.sqrt(min(a, 1.0))), 2)


def _geocodificar(address: str) -> tuple[float, float] | None:
    try:
        from geopy.geocoders import Nominatim
        geo = Nominatim(user_agent="bursan_rutas_demanda", timeout=10)
        loc = geo.geocode(f"{address}, Region del Biobio, Chile")
        if loc:
            return loc.latitude, loc.longitude
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers — persistencia
# ---------------------------------------------------------------------------
def _save_empresas(inst: BursanInstance) -> None:
    rows = [{
        "id":                  e.id,
        "nombre":              e.nombre,
        "direccion":           e.direccion,
        "turno_dia":           e.turno_dia,
        "turno_noche":         e.turno_noche,
        "requiere_supervisor": e.requiere_supervisor,
        "estado_contrato":     e.estado_contrato,
        "lat":                 e.lat,
        "lon":                 e.lon,
    } for e in inst.empresas]
    os.makedirs(_DATA_DIR, exist_ok=True)
    pd.DataFrame(rows).to_csv(os.path.join(_DATA_DIR, "empresas.csv"), index=False)


def _next_empresa_id(inst: BursanInstance) -> str:
    nums = [int(e.id[1:]) for e in inst.empresas if e.id.startswith("E") and e.id[1:].isdigit()]
    return f"E{max(nums) + 1}" if nums else "E1"


# ---------------------------------------------------------------------------
# Helpers — tabla
# ---------------------------------------------------------------------------
def _gmaps_url(e: Company) -> str:
    if e.lat is not None and e.lon is not None:
        return f"https://maps.google.com/?q={e.lat},{e.lon}"
    q = urllib.parse.quote(e.direccion)
    return f"https://maps.google.com/?q={q}"


def _inst_to_df(inst: BursanInstance) -> pd.DataFrame:
    return pd.DataFrame([{
        "Empresa":    e.nombre,
        "Dirección":  e.direccion,
        "Turno Día":  e.turno_dia,
        "Turno Noche": e.turno_noche,
        "Total":      e.demanda_total(),
        "Supervisor": "✅ Sí" if e.requiere_supervisor else "No",
        "Contrato":   "🟢 Activo" if e.is_activa() else "⚫ Inactivo",
        "📍":          _gmaps_url(e),
    } for e in inst.empresas])


def _detect_changes(
    df_orig: pd.DataFrame, df_edit: pd.DataFrame, gestor: bool
) -> dict[str, dict]:
    cambios: dict[str, dict] = {}
    fields = ["Turno Día", "Turno Noche"]
    if gestor:
        fields.append("Dirección")
    for i in range(len(df_orig)):
        o, e = df_orig.iloc[i], df_edit.iloc[i]
        nombre = o["Empresa"]
        row_c: dict = {}
        for f in fields:
            if o[f] != e[f]:
                row_c[f] = e[f]
        if row_c:
            cambios[nombre] = row_c
    return cambios


def _apply_changes(inst: BursanInstance, cambios: dict[str, dict]) -> list[str]:
    """Aplica cambios de dotacion/direccion a la instancia. Retorna lista de errores."""
    errores: list[str] = []
    for nombre, row_c in cambios.items():
        emp = next((e for e in inst.empresas if e.nombre == nombre), None)
        if emp is None:
            continue
        for col, val in row_c.items():
            if col == "Turno Día":
                try:
                    v = int(val)
                    if v < 0:
                        errores.append(f"{nombre}: Turno Día no puede ser negativo ({v}).")
                    else:
                        emp.turno_dia = v
                except (ValueError, TypeError):
                    errores.append(f"{nombre}: Turno Día debe ser un entero.")
            elif col == "Turno Noche":
                try:
                    v = int(val)
                    if v < 0:
                        errores.append(f"{nombre}: Turno Noche no puede ser negativo ({v}).")
                    else:
                        emp.turno_noche = v
                except (ValueError, TypeError):
                    errores.append(f"{nombre}: Turno Noche debe ser un entero.")
            elif col == "Dirección":
                emp.direccion = str(val).strip()
    return errores


# ---------------------------------------------------------------------------
# Banner balance oferta/demanda
# ---------------------------------------------------------------------------
def _render_balance(inst: BursanInstance, adj: dict[str, int]) -> None:
    activos      = len(inst.guardias_activos())
    dem_dia      = sum(e.turno_dia   for e in inst.empresas if e.is_activa())
    dem_noche    = sum(e.turno_noche for e in inst.empresas if e.is_activa())
    dem_base     = dem_dia + dem_noche
    dem_ajustada = dem_base + sum(adj.values())
    balance      = activos - dem_ajustada
    adj_txt      = f" (+{sum(adj.values())} ajuste temp.)" if adj else ""

    css_class = "balance-ok" if balance >= 0 else "balance-err"
    icono     = "✅" if balance >= 0 else "⚠️"
    balance_s = f"+{balance} (OK)" if balance >= 0 else f"{balance} (DÉFICIT — faltan guardias)"

    st.markdown(
        f'<div class="{css_class}">'
        f"{icono} Guardias activos: <b>{activos}</b> &nbsp;|&nbsp; "
        f"Demanda total: <b>{dem_ajustada}</b>{adj_txt} "
        f"(Día: {dem_dia}, Noche: {dem_noche}) &nbsp;|&nbsp; Balance: {balance_s}"
        f"</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sección 0 — Métricas rápidas
# ---------------------------------------------------------------------------
def _render_metricas(inst: BursanInstance) -> None:
    n_activas    = sum(1 for e in inst.empresas if e.is_activa())
    total_dia    = sum(e.turno_dia   for e in inst.empresas if e.is_activa())
    total_noche  = sum(e.turno_noche for e in inst.empresas if e.is_activa())
    c1, c2, c3   = st.columns(3)
    c1.metric("Empresas activas",           n_activas)
    c2.metric("Guardias requeridos — Día",  total_dia)
    c3.metric("Guardias requeridos — Noche", total_noche)


# ---------------------------------------------------------------------------
# Sección 1 — Tabla editable de empresas
# ---------------------------------------------------------------------------
def _render_tabla(inst: BursanInstance) -> None:
    st.subheader("📋 Dotación por empresa")

    ctrl_l, ctrl_r = st.columns([5, 1])
    with ctrl_l:
        gestor = st.checkbox(
            "🔓 Modo gestor (habilita edición de direcciones)",
            key="gestor_mode",
        )
    with ctrl_r:
        df_dl = _inst_to_df(inst)
        st.download_button(
            "📥 Exportar CSV",
            data=df_dl.to_csv(index=False).encode("utf-8"),
            file_name="empresas_bursan.csv",
            mime="text/csv",
            use_container_width=True,
        )

    df = _inst_to_df(inst)
    edited = st.data_editor(
        df,
        column_config={
            "Empresa":     st.column_config.TextColumn("Empresa",     disabled=True, width="medium"),
            "Dirección":   st.column_config.TextColumn("Dirección",   disabled=not gestor, width="large"),
            "Turno Día":   st.column_config.NumberColumn("Turno Día",   min_value=0, step=1, width="small"),
            "Turno Noche": st.column_config.NumberColumn("Turno Noche", min_value=0, step=1, width="small"),
            "Total":       st.column_config.NumberColumn("Total",       disabled=True, width="small"),
            "Supervisor":  st.column_config.TextColumn("Supervisor",  disabled=True, width="small"),
            "Contrato":    st.column_config.TextColumn("Contrato",    disabled=True, width="small"),
            "📍":           st.column_config.LinkColumn(
                "Mapa",
                help="Abrir en Google Maps",
                display_text="📍 Ver",
                width="small",
            ),
        },
        hide_index=True,
        use_container_width=True,
        key="empresa_editor",
    )

    if st.button("💾 Guardar cambios de dotación", type="primary", key="btn_save_emp"):
        cambios = _detect_changes(df, edited, gestor)
        if not cambios:
            st.info("Sin cambios pendientes.")
        else:
            errores = _apply_changes(inst, cambios)
            if errores:
                for err in errores:
                    st.error(err)
            else:
                _save_empresas(inst)
                n_emps = len(cambios)
                st.success(f"✅ {n_emps} empresa(s) actualizada(s).")
                st.rerun()


# ---------------------------------------------------------------------------
# Sección 2 — Ajuste de demanda de emergencia
# ---------------------------------------------------------------------------
def _render_ajuste(inst: BursanInstance) -> None:
    st.markdown(
        '<p class="info-box">Los ajustes son temporales (solo esta sesión). '
        "No modifican el CSV permanente ni el modelo de optimización hasta que "
        "se ejecute manualmente.</p>",
        unsafe_allow_html=True,
    )

    adj = st.session_state.demand_adj
    empresas_activas = [e for e in inst.empresas if e.is_activa()]

    cols = st.columns(len(empresas_activas) if len(empresas_activas) <= 4 else 2)
    for i, e in enumerate(empresas_activas):
        with cols[i % len(cols)]:
            st.slider(
                f"{e.nombre}",
                min_value=0, max_value=5,
                value=adj.get(e.nombre, 0),
                key=f"adj_{e.nombre}",
                help=f"Guardias de emergencia adicionales para turno día en {e.nombre}",
            )

    col_ap, col_rst, _ = st.columns([1.5, 1.5, 5])
    with col_ap:
        if st.button("⚡ Aplicar ajuste temporal", type="primary", key="btn_adj_apply"):
            st.session_state.demand_adj = {
                e.nombre: int(st.session_state.get(f"adj_{e.nombre}", 0))
                for e in empresas_activas
                if int(st.session_state.get(f"adj_{e.nombre}", 0)) > 0
            }
            st.rerun()
    with col_rst:
        if st.button("🔄 Limpiar ajustes", key="btn_adj_clear"):
            st.session_state.demand_adj = {}
            for e in empresas_activas:
                st.session_state.pop(f"adj_{e.nombre}", None)
            st.rerun()

    if adj:
        # Balance con ajuste aplicado
        activos  = len(inst.guardias_activos())
        dem_base = sum(e.demanda_total() for e in empresas_activas)
        dem_adj  = dem_base + sum(adj.values())
        balance  = activos - dem_adj
        icon = "✅" if balance >= 0 else "⚠️"
        color = "#065f46" if balance >= 0 else "#991b1b"
        st.markdown(
            f'<p style="color:{color};font-weight:bold;margin-top:6px;">'
            f'{icon} Con ajuste activo: {activos} activos / {dem_adj} requeridos '
            f"— Balance: {balance:+d}</p>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("Sin ajustes temporales activos.")


# ---------------------------------------------------------------------------
# Sección 3 — Agregar empresa nueva
# ---------------------------------------------------------------------------
def _render_agregar(inst: BursanInstance) -> None:
    # Mostrar resultado de un registro previo
    res = st.session_state.nueva_emp_result
    if res:
        if res.get("success"):
            st.success(f"✅ Empresa **{res['nombre']}** registrada correctamente.")
            if res.get("lat") and res.get("lon"):
                st.caption(f"Coordenadas geocodificadas: ({res['lat']:.5f}, {res['lon']:.5f})")
                df_map = pd.DataFrame({"lat": [res["lat"]], "lon": [res["lon"]]})
                st.map(df_map, zoom=13)
            st.warning(
                "⚠️ **Matriz de distancias pendiente.** "
                "Esta empresa no tiene distancias registradas desde los domicilios de guardias. "
                "El modelo la excluirá hasta que se ingresen. "
                "Use la página de Optimización para calcularlas automáticamente "
                "o ingréselas en la sección de Oferta."
            )
        if st.button("➕ Registrar otra empresa", key="btn_nueva_otra"):
            st.session_state.nueva_emp_result = None
            st.rerun()
        return

    st.markdown(
        '<p class="info-box">La dirección física se geocodificará automáticamente '
        "para ubicar la empresa en el mapa de rutas.</p>",
        unsafe_allow_html=True,
    )

    c_izq, c_der = st.columns(2)
    with c_izq:
        ne_nombre = st.text_input(
            "Nombre de la empresa *",
            key="ne_nombre",
            placeholder="Ej: Petroquímica Sur S.A.",
        )
        ne_dir = st.text_input(
            "Dirección física completa *",
            key="ne_dir",
            placeholder="Calle Las Industrias 100, Parque Industrial, Coronel, Región del Biobío",
            help="Esta dirección se geocodificará para ubicar la empresa en el mapa.",
        )
    with c_der:
        ne_dia   = st.number_input("Turno Día requerido",   min_value=0, value=1, key="ne_dia")
        ne_noche = st.number_input("Turno Noche requerido", min_value=0, value=0, key="ne_noche")
        ne_sup   = st.checkbox("Requiere supervisor certificado", key="ne_sup")

    st.markdown("")
    if st.button("✅ Registrar empresa", type="primary", key="ne_btn_registrar"):
        company_data = {
            "nombre":    (st.session_state.get("ne_nombre") or "").strip(),
            "direccion": (st.session_state.get("ne_dir") or "").strip(),
            "turno_dia":   ne_dia,
            "turno_noche": ne_noche,
            "requiere_supervisor": ne_sup,
        }

        errores = validate_new_company(inst, company_data)
        bloqueantes = [e for e in errores if not e.startswith("ADVERTENCIA")]
        advertencias = [e for e in errores if e.startswith("ADVERTENCIA")]

        for adv in advertencias:
            st.warning(adv)
        if bloqueantes:
            for err in bloqueantes:
                st.error(err)
            st.stop()

        # Geocodificar
        lat, lon = None, None
        if company_data["direccion"]:
            with st.spinner("Geocodificando dirección..."):
                coords = _geocodificar(company_data["direccion"])
            if coords:
                lat, lon = coords
            else:
                st.warning(
                    "No se pudo geocodificar la dirección. "
                    "La empresa se guardará sin coordenadas."
                )

        new_id = _next_empresa_id(inst)
        new_emp = Company(
            id=new_id,
            nombre=company_data["nombre"],
            direccion=company_data["direccion"],
            turno_dia=company_data["turno_dia"],
            turno_noche=company_data["turno_noche"],
            requiere_supervisor=company_data["requiere_supervisor"],
            estado_contrato="activo",
            lat=lat,
            lon=lon,
        )
        inst.empresas.append(new_emp)
        _save_empresas(inst)

        # No agregar filas a distancias.csv — distancias faltantes se detectan en validación
        for k in ["ne_nombre", "ne_dir"]:
            st.session_state.pop(k, None)

        st.session_state.nueva_emp_result = {
            "success": True,
            "nombre": new_emp.nombre,
            "lat": lat,
            "lon": lon,
        }
        st.rerun()


# ---------------------------------------------------------------------------
# Sección 4 — Terminar contrato
# ---------------------------------------------------------------------------
def _render_inactivar(inst: BursanInstance) -> None:
    activas = [e for e in inst.empresas if e.is_activa()]
    if not activas:
        st.info("No hay empresas activas.")
        return

    opciones = {
        f"{e.nombre} ({e.turno_dia}D + {e.turno_noche}N)": e.nombre
        for e in activas
    }
    sel_label = st.selectbox(
        "Empresa a dar de baja",
        options=list(opciones.keys()),
        key="inactivar_sel",
    )

    if st.button("🚫 Marcar como inactiva", key="btn_inactivar_prep"):
        st.session_state.confirm_inactivar = True
        st.session_state.inactivar_nombre = opciones[sel_label]

    if st.session_state.confirm_inactivar:
        nombre_pendiente = st.session_state.inactivar_nombre
        emp_pendiente = next((e for e in inst.empresas if e.nombre == nombre_pendiente), None)
        if emp_pendiente:
            st.warning(
                f"**¿Confirmar baja de contrato?** \n\n"
                f"Empresa: **{nombre_pendiente}** — "
                f"{emp_pendiente.turno_dia}D + {emp_pendiente.turno_noche}N guardias\n\n"
                "La empresa permanecerá en el CSV pero no participará en el modelo "
                "de optimización mientras esté inactiva."
            )
            col_ok, col_cancel, _ = st.columns([1, 1, 5])
            with col_ok:
                if st.button("✅ Confirmar baja", type="primary", key="btn_inactivar_ok"):
                    emp_pendiente.estado_contrato = "inactivo"
                    _save_empresas(inst)
                    st.session_state.confirm_inactivar = False
                    st.success(f"Contrato de **{nombre_pendiente}** marcado como inactivo.")
                    st.rerun()
            with col_cancel:
                if st.button("❌ Cancelar", key="btn_inactivar_cancel"):
                    st.session_state.confirm_inactivar = False
                    st.rerun()

    # Empresas inactivas — opción de reactivar
    inactivas = [e for e in inst.empresas if not e.is_activa()]
    if inactivas:
        st.markdown("---")
        st.markdown("**Empresas con contrato inactivo:**")
        for e in inactivas:
            c_nom, c_btn = st.columns([4, 1])
            with c_nom:
                st.markdown(f"⚫ **{e.nombre}** — {e.direccion[:60]}...")
            with c_btn:
                if st.button("Reactivar", key=f"react_{e.nombre}"):
                    e.estado_contrato = "activo"
                    _save_empresas(inst)
                    st.success(f"Contrato de {e.nombre} reactivado.")
                    st.rerun()


# ---------------------------------------------------------------------------
# Layout principal
# ---------------------------------------------------------------------------
_init_ss()
inst: BursanInstance = st.session_state.inst
adj: dict[str, int]  = st.session_state.demand_adj

_render_balance(inst, adj)

st.title("🏭 Empresas Clientes — Demanda Operacional")
_render_metricas(inst)

st.divider()

_render_tabla(inst)

st.divider()

with st.expander("⚡ Ajuste de demanda de emergencia (temporal)", expanded=False):
    _render_ajuste(inst)

with st.expander("➕ Registrar nueva empresa cliente", expanded=False):
    _render_agregar(inst)

with st.expander("🚫 Terminar contrato de empresa", expanded=False):
    _render_inactivar(inst)
