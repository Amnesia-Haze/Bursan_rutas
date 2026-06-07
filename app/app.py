"""app/app.py — Punto de entrada principal de Bursan Rutas."""
from __future__ import annotations

import os
import sys
from datetime import date

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_HERE     = os.path.dirname(os.path.abspath(__file__))   # bursan_rutas/app/
_ROOT     = os.path.dirname(_HERE)                         # bursan_rutas/
_DATA_DIR = os.path.join(_ROOT, "data")

if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.instance import BursanInstance, load_instance


# ---------------------------------------------------------------------------
# Page config  (debe ser la primera llamada Streamlit)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Bursan Rutas — Optimización Operacional",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# CSS global
# ---------------------------------------------------------------------------

def _inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Inter:wght@400;500;600&display=swap');

        html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
        .stApp { background-color: #f4f7fa; }

        h1, h2, h3 {
            font-family: 'Barlow Condensed', 'Inter', sans-serif !important;
            letter-spacing: 0.3px;
        }

        /* Sidebar oscuro en la home page */
        [data-testid="stSidebar"] {
            background-color: #1a3a5c !important;
        }
        [data-testid="stSidebarNav"] a {
            color: #c8daea !important;
            font-size: 0.93rem;
        }
        [data-testid="stSidebarNav"] a:hover,
        [data-testid="stSidebarNav"] a[aria-selected="true"] {
            color: #f0622a !important;
            background-color: rgba(240,98,42,0.12) !important;
        }
        [data-testid="stSidebarContent"] hr { border-color: #2c5282; }

        /* Botones primarios en naranja */
        .stButton > button[kind="primary"] {
            background-color: #f0622a !important;
            border-color: #f0622a !important;
            color: #fff !important;
            font-weight: 600;
        }
        .stButton > button[kind="primary"]:hover {
            background-color: #d4531f !important;
            border-color: #d4531f !important;
        }

        /* Cards de acceso rápido */
        .quick-card {
            background: #ffffff;
            border-radius: 10px;
            padding: 28px 18px 16px;
            box-shadow: 0 2px 12px rgba(26,58,92,0.10);
            border-top: 4px solid #f0622a;
            text-align: center;
            min-height: 155px;
            margin-bottom: 10px;
            transition: box-shadow 0.2s ease;
        }
        .quick-card:hover { box-shadow: 0 4px 20px rgba(26,58,92,0.18); }
        .quick-card .ci  { font-size: 2.2rem; margin-bottom: 10px; line-height: 1; }
        .quick-card .ct  {
            font-family: 'Barlow Condensed', sans-serif;
            font-size: 1.1rem; font-weight: 700; color: #1a3a5c; margin-bottom: 6px;
        }
        .quick-card .cd  { font-size: 0.8rem; color: #6b7c93; line-height: 1.5; }

        /* KPI inline chips */
        .kpi-chip {
            display: inline-block;
            border-radius: 20px;
            padding: 4px 16px;
            font-size: 0.85rem;
            font-weight: 600;
            margin: 0 4px;
        }

        /* Badge de estado */
        .status-ok    { background:#dcfce7; color:#166534; }
        .status-alert { background:#fee2e2; color:#991b1b; }

        /* Separador decorativo */
        .section-divider {
            border: none;
            border-top: 2px solid #e2eaf3;
            margin: 28px 0 20px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


_inject_css()


# ---------------------------------------------------------------------------
# Carga de instancia (una vez por sesión)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _cargar_instancia(data_dir: str) -> BursanInstance:
    return load_instance(data_dir)


if "inst" not in st.session_state:
    with st.spinner("🔄 Cargando datos de Bursan..."):
        st.session_state["inst"] = _cargar_instancia(_DATA_DIR)

inst: BursanInstance = st.session_state["inst"]


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown(
        """
        <div style="text-align:center;padding:20px 0 12px">
            <div style="font-size:2.8rem;line-height:1">🚌</div>
            <div style="font-family:'Barlow Condensed',sans-serif;font-size:1.5rem;
                        font-weight:700;color:#ffffff;letter-spacing:1.5px;margin-top:6px">
                BURSAN RUTAS
            </div>
            <div style="font-size:0.7rem;color:#7fa8c9;margin-top:3px;letter-spacing:0.5px">
                OPTIMIZACIÓN OPERACIONAL
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<hr style="border-color:#2c5282;margin:4px 0 12px">', unsafe_allow_html=True)

    # Resumen rápido del sistema
    n_activos  = len(inst.guardias_activos())
    demanda    = sum(e.demanda_total() for e in inst.empresas if e.is_activa())
    status_ok  = n_activos >= demanda
    badge_bg   = "#166534" if status_ok else "#991b1b"
    badge_bg2  = "#dcfce7" if status_ok else "#fee2e2"
    badge_text = "OK" if status_ok else "ALERTA"

    st.markdown(
        f"""
        <div style="padding:0 6px 8px">
            <div style="color:#7fa8c9;font-size:0.7rem;text-transform:uppercase;
                        letter-spacing:0.8px;margin-bottom:10px">Estado del sistema</div>
            <div style="display:flex;justify-content:space-between;
                        align-items:center;margin-bottom:7px">
                <span style="color:#c8daea;font-size:0.88rem">Guardias activos</span>
                <span style="color:#2eb8b0;font-weight:700;font-size:1.05rem">{n_activos}</span>
            </div>
            <div style="display:flex;justify-content:space-between;
                        align-items:center;margin-bottom:14px">
                <span style="color:#c8daea;font-size:0.88rem">Demanda total</span>
                <span style="color:#f0622a;font-weight:700;font-size:1.05rem">{demanda}</span>
            </div>
            <div style="background:{badge_bg2};color:{badge_bg};border-radius:20px;
                        padding:5px 0;text-align:center;font-size:0.85rem;font-weight:700;
                        letter-spacing:0.5px">
                {"✅" if status_ok else "⚠️"} {badge_text}
                {"— cobertura OK" if status_ok else "— guardias insuficientes"}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<hr style="border-color:#2c5282;margin:12px 0 8px">', unsafe_allow_html=True)

    st.markdown(
        """
        <div style="color:#7fa8c9;font-size:0.7rem;text-transform:uppercase;
                    letter-spacing:0.8px;padding:0 6px 6px">Módulos</div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<hr style="border-color:#2c5282;margin:8px 0 0">', unsafe_allow_html=True)

    # Versión / build info
    st.markdown(
        f"""
        <div style="color:#4a7099;font-size:0.68rem;text-align:center;
                    padding:12px 0 4px">
            Bursan Rutas v1.0 &nbsp;|&nbsp; {date.today().strftime("%d/%m/%Y")}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Página principal — Dashboard de bienvenida
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div style="margin-bottom:6px">
        <span style="font-family:'Barlow Condensed',sans-serif;font-size:2.4rem;
                     font-weight:700;color:#1a3a5c;line-height:1">
            Sistema de Optimización de Rutas
        </span>
        <span style="font-family:'Barlow Condensed',sans-serif;font-size:2.4rem;
                     font-weight:600;color:#f0622a"> — Bursan Empresas</span>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption(
    f"Región del Biobío · {n_activos} guardias activos · "
    f"{len([e for e in inst.empresas if e.is_activa()])} empresas cliente · "
    f"Semana {date.today().isocalendar()[0]}-W{date.today().isocalendar()[1]:02d}"
)

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

# ── Tarjetas de acceso rápido ──────────────────────────────────────────────

st.markdown(
    '<h3 style="color:#1a3a5c;margin-bottom:16px">Acceso rápido</h3>',
    unsafe_allow_html=True,
)

_CARDS = [
    ("👮", "Gestión de Guardias",   "Disponibilidad, estados y domicilios de los 14 guardias Bursan.", "pages/1_Oferta.py"),
    ("🏭", "Empresas Clientes",     "Turnos, demanda y contratos de Noramco, ITI Chile, Oleoducto e Indama.", "pages/2_Demanda.py"),
    ("🚀", "Optimizar Rutas",       "Modelo ILP + CVRP: asignación óptima y rutas de bus por turno.", "pages/3_Optimizar.py"),
    ("📅", "Calendario Semanal",    "Cronograma de guardias, alertas operacionales y exportación.", "pages/4_Calendario.py"),
]

card_cols = st.columns(4)
for col, (icon, titulo, desc, page_path) in zip(card_cols, _CARDS):
    with col:
        st.markdown(
            f'<div class="quick-card">'
            f'<div class="ci">{icon}</div>'
            f'<div class="ct">{titulo}</div>'
            f'<div class="cd">{desc}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if st.button("Abrir →", key=f"btn_{page_path}", use_container_width=True, type="primary"):
            try:
                st.switch_page(page_path)
            except AttributeError:
                st.info(f"Navega a **{titulo}** usando el menú lateral izquierdo.")

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

# ── Estado actual del sistema ──────────────────────────────────────────────

st.markdown(
    '<h3 style="color:#1a3a5c;margin-bottom:16px">Estado actual del sistema</h3>',
    unsafe_allow_html=True,
)

col_guard, col_emp = st.columns(2)

with col_guard:
    st.markdown("**Dotación de guardias**")

    _ESTADO_LABELS = {
        "activo":            "🟢 Activo",
        "licencia":          "🟡 Licencia",
        "fuera_de_servicio": "🔴 Fuera de servicio",
        "vacaciones":        "🔵 Vacaciones",
        "inactivo":          "⚫ Inactivo",
    }
    conteo: dict[str, int] = {}
    for g in inst.guardias:
        conteo[g.estado] = conteo.get(g.estado, 0) + 1

    df_estados = pd.DataFrame([
        {"Estado": _ESTADO_LABELS.get(k, k), "N° guardias": v}
        for k, v in sorted(conteo.items())
    ])
    total_row = pd.DataFrame([{"Estado": "**TOTAL**", "N° guardias": sum(conteo.values())}])
    st.dataframe(
        pd.concat([df_estados, total_row], ignore_index=True),
        use_container_width=True,
        hide_index=True,
    )

    n_sup = sum(1 for g in inst.guardias if g.supervisor and g.is_disponible())
    st.caption(f"Supervisores activos: {n_sup} | Guardias con coord. geocodificadas: "
               f"{sum(1 for g in inst.guardias if g.lat is not None)}")

with col_emp:
    st.markdown("**Demanda por empresa cliente**")

    df_emp = pd.DataFrame([
        {
            "Empresa":       e.nombre,
            "Turno Día":     e.turno_dia,
            "Turno Noche":   e.turno_noche,
            "Demanda Total": e.demanda_total(),
            "Requiere Sup.": "✓" if e.requiere_supervisor else "—",
            "Contrato":      "🟢 Activo" if e.is_activa() else "🔴 Inactivo",
        }
        for e in inst.empresas
    ])
    total_emp = pd.DataFrame([{
        "Empresa": "**TOTAL**",
        "Turno Día":     sum(e.turno_dia for e in inst.empresas if e.is_activa()),
        "Turno Noche":   sum(e.turno_noche for e in inst.empresas if e.is_activa()),
        "Demanda Total": demanda,
        "Requiere Sup.": "",
        "Contrato":      "",
    }])
    st.dataframe(
        pd.concat([df_emp, total_emp], ignore_index=True),
        use_container_width=True,
        hide_index=True,
    )

    cobertura_pct = round(n_activos / max(demanda, 1) * 100, 1)
    color_cob = "green" if cobertura_pct >= 100 else "red"
    st.markdown(
        f'Cobertura: <span style="color:{color_cob};font-weight:700">'
        f'{cobertura_pct}%</span> ({n_activos}/{demanda} guardias)',
        unsafe_allow_html=True,
    )

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

# ── Acción rápida: optimización del día ───────────────────────────────────

col_action, col_info = st.columns([1, 2])

with col_action:
    st.markdown(
        f'<h4 style="color:#1a3a5c;margin-bottom:8px">Optimización del día de hoy</h4>',
        unsafe_allow_html=True,
    )
    st.caption(f"Fecha: {date.today().strftime('%A %d de %B de %Y')}")
    if st.button(
        "🚀 Ejecutar optimización del día de hoy",
        type="primary",
        use_container_width=True,
        key="btn_opt_hoy",
    ):
        try:
            st.switch_page("pages/3_Optimizar.py")
        except AttributeError:
            st.info("Navega a **Optimizar Rutas** usando el menú lateral izquierdo.")

with col_info:
    if not status_ok:
        st.warning(
            f"**Atención:** hay {demanda - n_activos} puesto(s) de trabajo sin guardia disponible. "
            "Ve a **Gestión de Guardias** para revisar la disponibilidad."
        )
    else:
        errores = inst.validar()
        if errores:
            st.warning(
                f"La instancia tiene {len(errores)} advertencia(s). "
                "Revisa la configuración antes de optimizar.\n\n"
                + "\n".join(f"• {e}" for e in errores[:3])
                + ("\n• ..." if len(errores) > 3 else "")
            )
        else:
            st.success(
                f"Instancia válida. {n_activos} guardias cubre {demanda} puestos "
                f"en {len([e for e in inst.empresas if e.is_activa()])} empresas. "
                "Listo para optimizar."
            )
