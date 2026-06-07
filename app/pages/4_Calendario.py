"""app/pages/4_Calendario.py — Cronograma semanal de rutas y disponibilidad de guardias."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))   # bursan_rutas/
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.instance import BursanInstance
from core.scheduler import (
    DailySchedule,
    WeeklySchedule,
    exportar_calendario_csv,
    exportar_calendario_html,
    generar_calendario,
)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

PRIMARY = "#1a3a5c"
ACCENT  = "#f0622a"

_DIA_ES = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]

_EMPRESA_COLORES: dict[str, dict[str, str]] = {
    "Noramco":   {"bg": "#fff3cd", "border": "#e6b800", "text": "#6b5a00"},
    "ITI Chile": {"bg": "#cce5ff", "border": "#3498db", "text": "#004085"},
    "Oleoducto": {"bg": "#d4edda", "border": "#27ae60", "text": "#155724"},
    "Indama":    {"bg": "#e2d9f3", "border": "#9b59b6", "text": "#4a235a"},
}
_EMPRESA_PLOTLY: dict[str, str] = {
    "Noramco":   "#e6b800",
    "ITI Chile": "#3498db",
    "Oleoducto": "#27ae60",
    "Indama":    "#9b59b6",
}
_EMPRESA_ABREV: dict[str, str] = {
    "Noramco": "Noramco", "ITI Chile": "ITI", "Oleoducto": "Oleo.", "Indama": "Indama",
}

_CAL_STATE = "cal_result"
_CAL_KEY   = "cal_params_key"

_MODOS = {
    "suma_total":    "Minimizar distancia total",
    "minimax":       "Minimizar distancia maxima",
    "multiobjetivo": "Multiobjetivo",
}
_METODOS = {"nearest_neighbor": "Nearest Neighbor", "clarke_wright": "Clarke-Wright"}


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .kpi-card {{
            background:#fff; border:1px solid #e1e8f0;
            border-left:4px solid {PRIMARY}; border-radius:6px;
            padding:12px 14px; text-align:center;
        }}
        .kpi-card .val {{font-size:1.4rem; font-weight:700; color:{PRIMARY};}}
        .kpi-card .lbl {{font-size:0.76rem; color:#6b7c93; margin-top:3px;}}
        .alert-warn  {{background:#fffbeb; border:1px solid #f59e0b; border-left:4px solid #f59e0b;
                       border-radius:4px; padding:6px 12px; margin:4px 0; font-size:0.88rem; color:#78350f;}}
        .alert-crit  {{background:#fff5f5; border:1px solid #f87171; border-left:4px solid #dc2626;
                       border-radius:4px; padding:6px 12px; margin:4px 0; font-size:0.88rem; color:#7f1d1d;}}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def _init_state() -> None:
    for k, v in {_CAL_STATE: None, _CAL_KEY: None}.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _params_key(fecha: str, n_dias: int, modo: str, metodo: str) -> str:
    return json.dumps({"f": fecha, "n": n_dias, "m": modo, "r": metodo}, sort_keys=True)


def _find_daily(schedule: WeeklySchedule, fecha: str, turno: str) -> DailySchedule | None:
    return next(
        (d for d in schedule.dias if d.fecha == fecha and d.turno == turno),
        None,
    )


def _is_infactible(ds: DailySchedule | None) -> bool:
    if ds is None:
        return False
    return any("INFACTIBLE" in a for a in ds.alertas)


def _fecha_label(f: str) -> str:
    d = date.fromisoformat(f)
    return f"{_DIA_ES[d.weekday()]} {d.strftime('%d/%m')}"


def _alerta_severidad(texto: str) -> str:
    if "INFACTIBLE" in texto:
        return "critico"
    if "RUTA_LARGA" in texto or "GUARDIA_AISLADO" in texto:
        return "advertencia"
    if "RESERVA_BAJA" in texto:
        return "advertencia"
    return "advertencia"


def _all_alertas(schedule: WeeklySchedule) -> list[dict]:
    result = []
    for ds in schedule.dias:
        for a in ds.alertas:
            result.append({
                "fecha":    ds.fecha,
                "turno":    ds.turno,
                "texto":    a,
                "sev":      _alerta_severidad(a),
            })
    return result


def _export_csv_bytes(schedule: WeeklySchedule) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        path = f.name
    try:
        exportar_calendario_csv(schedule, path)
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _export_html_bytes(schedule: WeeklySchedule) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        path = f.name
    try:
        exportar_calendario_html(schedule, path)
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Tabla pivotada (Vista Semanal)
# ---------------------------------------------------------------------------

def _build_pivot_html(inst: BursanInstance, schedule: WeeklySchedule) -> str:
    all_gids  = [g.id for g in inst.guardias]
    guard_map = {g.id: g for g in inst.guardias}
    fechas    = sorted({ds.fecha for ds in schedule.dias})

    # Lookup: asignaciones y reservas
    asign_lk: dict[tuple, dict] = {}
    reserva_lk: set[tuple]      = set()
    infactible_f: set[str]      = set()

    for ds in schedule.dias:
        for a in ds.asignacion.asignaciones:
            asign_lk[(ds.fecha, a["guardia_id"], ds.turno)] = a
        for gid in ds.guardias_reserva:
            reserva_lk.add((ds.fecha, gid, ds.turno))
        if _is_infactible(ds):
            infactible_f.add(ds.fecha)

    # ---- Cabecera ----
    th_sticky = (
        f"background:{PRIMARY};color:#fff;padding:8px 10px;white-space:nowrap;"
        "position:sticky;top:0;z-index:2"
    )
    th_guard = (
        f"{th_sticky};left:0;z-index:3;min-width:120px;border-right:2px solid #2c5282"
    )
    header_cells = [f'<th style="{th_guard}">Guardia</th>']
    for f in fechas:
        bg = "#9b1c1c" if f in infactible_f else PRIMARY
        header_cells.append(
            f'<th style="{th_sticky};background:{bg};min-width:90px;text-align:center">'
            f'{_fecha_label(f)}'
            f'{"<br><small>INFACT.</small>" if f in infactible_f else ""}'
            f"</th>"
        )

    # ---- Filas ----
    tbody_rows: list[str] = []
    for gid in all_gids:
        guard = guard_map.get(gid)
        active = guard is not None and guard.is_disponible()

        gname = guard.nombre if guard else gid
        td_guard = (
            f'<td style="background:#f7f9fc;font-weight:600;padding:6px 8px;white-space:nowrap;'
            f'position:sticky;left:0;z-index:1;border-right:2px solid #dde5f0;font-size:0.85rem">'
            f'{gid}<br><small style="font-weight:normal;color:#6b7c93">{gname}</small></td>'
        )
        row_cells = [td_guard]

        for f in fechas:
            a_dia   = asign_lk.get((f, gid, "dia"))
            a_noche = asign_lk.get((f, gid, "noche"))
            r_dia   = (f, gid, "dia")   in reserva_lk
            r_noche = (f, gid, "noche") in reserva_lk

            if not active:
                estado = guard.estado if guard else "inactivo"
                cell = (
                    '<td title="Guardia no disponible" '
                    'style="background:#fde8e8;color:#9b1c1c;text-align:center;'
                    'padding:5px 6px;font-size:0.78rem">'
                    f'{estado}</td>'
                )
            elif a_dia or a_noche:
                parts: list[str] = []
                tooltips: list[str] = []
                # Dia assignment
                if a_dia:
                    ec = _EMPRESA_COLORES.get(a_dia["empresa"], {"bg": "#eee", "border": "#aaa", "text": "#333"})
                    badge = f'<span style="background:{ec["border"]};color:#fff;border-radius:3px;padding:1px 3px;font-size:0.68rem">D</span>'
                    parts.append(
                        f'<span style="font-weight:600;color:{ec["text"]}">'
                        f'{_EMPRESA_ABREV.get(a_dia["empresa"], a_dia["empresa"][:6])}</span> {badge}'
                    )
                    tooltips.append(f'Dia: {a_dia["empresa"]} | {a_dia["distancia_km"]:.1f} km')
                # Noche assignment
                if a_noche:
                    ec2 = _EMPRESA_COLORES.get(a_noche["empresa"], {"bg": "#eee", "border": "#aaa", "text": "#333"})
                    badge2 = f'<span style="background:{ec2["border"]};color:#fff;border-radius:3px;padding:1px 3px;font-size:0.68rem">N</span>'
                    parts.append(
                        f'<span style="color:{ec2["text"]}">'
                        f'{_EMPRESA_ABREV.get(a_noche["empresa"], a_noche["empresa"][:6])}</span> {badge2}'
                    )
                    tooltips.append(f'Noche: {a_noche["empresa"]} | {a_noche["distancia_km"]:.1f} km')

                # Dominant company for cell background
                dom = a_dia or a_noche
                ec_dom = _EMPRESA_COLORES.get(dom["empresa"], {"bg": "#f9f9f9", "border": "#ccc", "text": "#333"})
                title_attr = " / ".join(tooltips)
                cell = (
                    f'<td title="{title_attr}" '
                    f'style="background:{ec_dom["bg"]};border-left:3px solid {ec_dom["border"]};'
                    f'text-align:center;padding:5px 6px;font-size:0.82rem">'
                    + "<br>".join(parts)
                    + "</td>"
                )
            elif r_dia or r_noche:
                turnos_r = []
                if r_dia:   turnos_r.append("D")
                if r_noche: turnos_r.append("N")
                cell = (
                    f'<td title="Reserva ({"/".join(turnos_r)}) — disponible para emergencia" '
                    'style="background:#f0f0f0;color:#888;text-align:center;'
                    'padding:5px 6px;font-size:0.78rem;font-style:italic">RESERVA</td>'
                )
            else:
                cell = '<td style="text-align:center;color:#ccc;padding:5px 6px">—</td>'

            row_cells.append(cell)

        tbody_rows.append(f'<tr>{"".join(row_cells)}</tr>')

    table = (
        '<div style="overflow:auto;max-height:480px;border:1px solid #dde5f0;border-radius:6px">'
        '<table style="border-collapse:collapse;font-size:0.88rem;width:100%">'
        f'<thead><tr>{"".join(header_cells)}</tr></thead>'
        f'<tbody>{"".join(tbody_rows)}</tbody>'
        '</table></div>'
    )
    return table


# ---------------------------------------------------------------------------
# Timeline de rutas por día
# ---------------------------------------------------------------------------

def _build_timeline_fig(
    ds_dia:   DailySchedule | None,
    ds_noche: DailySchedule | None,
    fecha_str: str,
) -> go.Figure:
    SPEED = 40.0  # km/h — velocidad promedio estimada

    fig = go.Figure()

    for turno_label, ds, start_h in [("Dia", ds_dia, 6.0), ("Noche", ds_noche, 18.0)]:
        if ds is None or not ds.rutas.rutas:
            continue
        for i, ruta in enumerate(ds.rutas.rutas):
            duration_h = ruta.distancia_total_km / SPEED
            cos = sorted({s.node_id for s in ruta.paradas if s.node_type == "empresa"})
            empresa = cos[0] if cos else "Desconocida"
            col = _EMPRESA_PLOTLY.get(empresa, "#95a5a6")
            label = f"{turno_label} Bus {i + 1}"

            fig.add_trace(go.Bar(
                x=[duration_h],
                y=[label],
                orientation="h",
                base=[start_h],
                marker_color=col,
                marker_line_color=col,
                marker_line_width=1.5,
                marker_opacity=0.85,
                name=empresa,
                customdata=[[", ".join(ruta.guardias), ruta.distancia_total_km, empresa]],
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Guardias: %{customdata[0]}<br>"
                    "Empresa: %{customdata[2]}<br>"
                    "Km totales: %{customdata[1]:.1f} km<br>"
                    "Salida: %{base:.0f}:00 h  |  Duracion: %{x:.1f} h"
                    "<extra></extra>"
                ),
                showlegend=False,
            ))

    n_bars = (len(ds_dia.rutas.rutas) if ds_dia else 0) + (len(ds_noche.rutas.rutas) if ds_noche else 0)
    fig.update_xaxes(
        title="Hora del dia",
        range=[4.5, 23.5],
        tickmode="array",
        tickvals=list(range(5, 24)),
        ticktext=[f"{h:02d}:00" for h in range(5, 24)],
        gridcolor="#e1e8f0",
    )
    fig.update_yaxes(title=None, autorange="reversed")
    fig.update_layout(
        title=f"Timeline de rutas — {_fecha_label(fecha_str)}",
        barmode="overlay",
        height=max(180, n_bars * 55 + 100),
        plot_bgcolor="#fafbfc",
        margin=dict(l=10, r=10, t=45, b=50),
    )
    return fig


# ---------------------------------------------------------------------------
# DataFrames para métricas
# ---------------------------------------------------------------------------

def _summary_df(schedule: WeeklySchedule) -> pd.DataFrame:
    fechas = sorted({ds.fecha for ds in schedule.dias})
    rows = []
    for f in fechas:
        ds_d = _find_daily(schedule, f, "dia")
        ds_n = _find_daily(schedule, f, "noche")
        buses   = (ds_d.rutas.n_buses_necesarios if ds_d else 0) + (ds_n.rutas.n_buses_necesarios if ds_n else 0)
        km      = (ds_d.rutas.distancia_total_sistema if ds_d else 0) + (ds_n.rutas.distancia_total_sistema if ds_n else 0)
        costo   = (ds_d.rutas.costo_total_clp if ds_d else 0) + (ds_n.rutas.costo_total_clp if ds_n else 0)
        reserva = len(ds_d.guardias_reserva if ds_d else []) + len(ds_n.guardias_reserva if ds_n else [])
        alertas = len(ds_d.alertas if ds_d else []) + len(ds_n.alertas if ds_n else [])
        rows.append({
            "Fecha":           f,
            "Dia semana":      _fecha_label(f),
            "N° buses":        buses,
            "Km totales":      round(km, 1),
            "Costo CLP":       f"${int(costo):,}",
            "Plazas reserva":  reserva,
            "N° alertas":      alertas,
        })
    return pd.DataFrame(rows)


def _km_empresa_df(schedule: WeeklySchedule) -> pd.DataFrame:
    rows = []
    for ds in schedule.dias:
        for a in ds.asignacion.asignaciones:
            rows.append({
                "Fecha":   ds.fecha,
                "Turno":   "Dia" if ds.turno == "dia" else "Noche",
                "Empresa": a["empresa"],
                "Km":      a["distancia_km"],
            })
    if not rows:
        return pd.DataFrame(columns=["Fecha", "Empresa", "Km"])
    df = pd.DataFrame(rows)
    return df.groupby(["Fecha", "Empresa"], as_index=False)["Km"].sum()


# ---------------------------------------------------------------------------
# Renderizadores de secciones
# ---------------------------------------------------------------------------

def _render_vista_semanal(inst: BursanInstance, schedule: WeeklySchedule) -> None:
    st.markdown("**Tabla de asignaciones — todos los guardias × todos los días**")
    legend_cols = st.columns(len(_EMPRESA_COLORES) + 2)
    for i, (emp, col_info) in enumerate(_EMPRESA_COLORES.items()):
        legend_cols[i].markdown(
            f'<span style="background:{col_info["bg"]};border-left:3px solid {col_info["border"]};'
            f'padding:2px 8px;border-radius:3px;font-size:0.8rem;color:{col_info["text"]}">'
            f'{emp}</span>',
            unsafe_allow_html=True,
        )
    legend_cols[-2].markdown(
        '<span style="background:#f0f0f0;padding:2px 8px;border-radius:3px;'
        'font-size:0.8rem;color:#888;font-style:italic">RESERVA</span>',
        unsafe_allow_html=True,
    )
    legend_cols[-1].markdown(
        '<span style="background:#fde8e8;padding:2px 8px;border-radius:3px;'
        'font-size:0.8rem;color:#9b1c1c">Inactivo</span>',
        unsafe_allow_html=True,
    )
    st.markdown("")
    st.markdown(_build_pivot_html(inst, schedule), unsafe_allow_html=True)


def _render_vista_por_dia(inst: BursanInstance, schedule: WeeklySchedule) -> None:
    fechas = sorted({ds.fecha for ds in schedule.dias})
    fecha_labels = {f: _fecha_label(f) for f in fechas}
    sel_fecha = st.selectbox(
        "Seleccionar dia",
        options=fechas,
        format_func=lambda f: fecha_labels[f],
        key="cal_sel_fecha",
    )

    ds_dia   = _find_daily(schedule, sel_fecha, "dia")
    ds_noche = _find_daily(schedule, sel_fecha, "noche")

    if _is_infactible(ds_dia) or _is_infactible(ds_noche):
        st.error("Dia INFACTIBLE: no se encontro solucion optima para este dia.")

    # Timeline chart
    st.plotly_chart(
        _build_timeline_fig(ds_dia, ds_noche, sel_fecha),
        use_container_width=True,
    )

    # Reserve panel
    col_res, col_detail = st.columns([1, 2])
    with col_res:
        st.markdown("**Guardias de reserva**")
        guard_map = {g.id: g for g in inst.guardias}
        res_dia   = ds_dia.guardias_reserva if ds_dia else []
        res_noche = ds_noche.guardias_reserva if ds_noche else []
        reservas_combined = sorted(set(res_dia) | set(res_noche))
        if reservas_combined:
            for gid in reservas_combined:
                turnos = []
                if gid in res_dia:   turnos.append("D")
                if gid in res_noche: turnos.append("N")
                g = guard_map.get(gid)
                nombre = g.nombre if g else gid
                st.markdown(
                    f'<div style="background:#f0f4ff;border-left:3px solid #3498db;'
                    f'padding:5px 10px;margin:3px 0;border-radius:0 4px 4px 0;font-size:0.88rem">'
                    f'<b>{gid}</b> — {nombre}<br>'
                    f'<small style="color:#3498db">Disponible para emergencia '
                    f'({", ".join(turnos)})</small></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("Sin guardias de reserva este dia.")

    with col_detail:
        st.markdown("**Detalle de asignaciones**")
        for turno_label, ds in [("Turno Dia", ds_dia), ("Turno Noche", ds_noche)]:
            if ds is None or not ds.asignacion.asignaciones:
                continue
            with st.expander(f"{turno_label} — {len(ds.asignacion.asignaciones)} guardias"):
                rows = [
                    {
                        "Guardia":    a["guardia_id"],
                        "Empresa":    a["empresa"],
                        "Km asign.":  round(a["distancia_km"], 1),
                        "Costo (CLP)": f"${int(a['costo_clp']):,}",
                    }
                    for a in sorted(ds.asignacion.asignaciones, key=lambda x: x["guardia_id"])
                ]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_alertas(schedule: WeeklySchedule) -> None:
    alertas = _all_alertas(schedule)
    if not alertas:
        st.success("Sin alertas operacionales para esta semana.")
        return

    n_crit = sum(1 for a in alertas if a["sev"] == "critico")
    n_warn = sum(1 for a in alertas if a["sev"] == "advertencia")

    col_f1, col_f2, col_f3 = st.columns([1, 1, 2])
    mostrar_warn = col_f1.checkbox(f"⚠️ Advertencia ({n_warn})", value=True, key="fil_warn")
    mostrar_crit = col_f2.checkbox(f"🔴 Critico ({n_crit})", value=True, key="fil_crit")
    sel_fecha_al = col_f3.selectbox(
        "Filtrar por fecha",
        options=["Todos"] + sorted({a["fecha"] for a in alertas}),
        key="fil_fecha_al",
    )

    filtradas = [
        a for a in alertas
        if (
            (mostrar_warn and a["sev"] == "advertencia")
            or (mostrar_crit and a["sev"] == "critico")
        )
        and (sel_fecha_al == "Todos" or a["fecha"] == sel_fecha_al)
    ]

    if not filtradas:
        st.info("Sin alertas para los filtros seleccionados.")
        return

    for a in filtradas:
        turno_s = "Dia" if a["turno"] == "dia" else "Noche"
        fecha_s = _fecha_label(a["fecha"])
        css_cls = "alert-crit" if a["sev"] == "critico" else "alert-warn"
        icono   = "🔴" if a["sev"] == "critico" else "⚠️"
        st.markdown(
            f'<div class="{css_cls}">'
            f'{icono} <b>{fecha_s} / {turno_s}:</b> {a["texto"]}'
            f'</div>',
            unsafe_allow_html=True,
        )


def _render_metricas(schedule: WeeklySchedule) -> None:
    df_sum  = _summary_df(schedule)
    df_kemp = _km_empresa_df(schedule)

    # KPI cards
    fechas_unicas = sorted({ds.fecha for ds in schedule.dias})
    km_sem   = schedule.resumen_km
    costo_sem = int(schedule.resumen_costo_clp)
    buses_dia = round(schedule.resumen_buses / max(len(fechas_unicas) * 2, 1), 1)
    dias_alertas = len({
        ds.fecha for ds in schedule.dias if ds.alertas
    })

    kc = st.columns(4)
    for col, val, lbl in [
        (kc[0], f"{km_sem:.1f} km",     "Km totales semana"),
        (kc[1], f"${costo_sem:,}",      "Costo CLP semana"),
        (kc[2], str(buses_dia),          "Buses promedio / turno"),
        (kc[3], str(dias_alertas),       "Dias con alertas"),
    ]:
        col.markdown(
            f'<div class="kpi-card"><div class="val">{val}</div>'
            f'<div class="lbl">{lbl}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    # Summary table
    st.markdown("**Resumen por dia**")
    st.dataframe(df_sum, use_container_width=True, hide_index=True)

    # Stacked bar by empresa
    if not df_kemp.empty:
        st.markdown("**Km de asignacion por empresa y dia**")
        fig = px.bar(
            df_kemp,
            x="Fecha",
            y="Km",
            color="Empresa",
            barmode="stack",
            color_discrete_map=_EMPRESA_PLOTLY,
            title="Distribucion de km de asignacion por empresa",
            labels={"Km": "Km asignados", "Fecha": "Fecha"},
        )
        fig.update_xaxes(
            tickvals=sorted(df_kemp["Fecha"].unique()),
            ticktext=[_fecha_label(f) for f in sorted(df_kemp["Fecha"].unique())],
        )
        fig.update_layout(
            height=360,
            legend_title_text="Empresa",
            margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Layout principal
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Calendario — Bursan Rutas",
    page_icon="📅",
    layout="wide",
)
_inject_css()
_init_state()

if "inst" not in st.session_state or st.session_state.inst is None:
    st.warning("Instancia no cargada. Ve a la pagina de inicio para cargarla.")
    st.stop()

inst: BursanInstance = st.session_state.inst

st.markdown(
    f'<h2 style="color:{PRIMARY};margin-bottom:4px">📅 Calendario Semanal de Rutas</h2>',
    unsafe_allow_html=True,
)
st.caption(
    f"Semana Bursan — {len(inst.guardias_activos())} guardias activos | "
    f"{sum(e.demanda_total() for e in inst.empresas if e.is_activa())} puestos demandados"
)

# ── Sección 1: Selector de semana ──────────────────────────────────────────

st.markdown(f'<h4 style="color:{PRIMARY}">1 — Configuracion del calendario</h4>', unsafe_allow_html=True)
with st.container():
    c1, c2, c3, c4, c5 = st.columns([2, 1, 2, 2, 1])
    fecha_pick = c1.date_input(
        "Inicio de semana",
        value=date.today(),
        key="cal_fecha",
    )
    n_dias = c2.slider("Dias", 1, 14, 7, 1, key="cal_ndias")
    modo = c3.selectbox(
        "Modo asignacion ILP",
        options=list(_MODOS.keys()),
        format_func=lambda k: _MODOS[k],
        key="cal_modo",
    )
    metodo = c4.selectbox(
        "Metodo de ruteo",
        options=list(_METODOS.keys()),
        format_func=lambda k: _METODOS[k],
        key="cal_metodo",
    )
    do_generate = c5.button(
        "📅 Generar",
        type="primary",
        use_container_width=True,
        key="btn_gen_cal",
    )

fecha_str = fecha_pick.isoformat()

if do_generate:
    pkey = _params_key(fecha_str, n_dias, modo, metodo)
    if st.session_state[_CAL_KEY] != pkey:
        with st.spinner(
            f"Generando calendario {n_dias} dia(s) desde {fecha_str} "
            f"— resolviendo {n_dias} ILP(s)..."
        ):
            schedule = generar_calendario(inst, fecha_str, n_dias, modo, metodo)
        st.session_state[_CAL_STATE] = schedule
        st.session_state[_CAL_KEY]   = pkey
    else:
        st.info("Calendario en cache — mismos parametros que la ultima generacion.")

schedule: WeeklySchedule | None = st.session_state[_CAL_STATE]

if schedule is None:
    st.info("Configura los parametros y haz click en **📅 Generar** para ver el calendario.")
    st.stop()

# ── Sección 2: Cronograma ──────────────────────────────────────────────────

st.markdown("---")
st.markdown(
    f'<h4 style="color:{PRIMARY}">2 — Cronograma {schedule.semana}</h4>',
    unsafe_allow_html=True,
)

tab_sem, tab_dia = st.tabs(["📊 Vista Semanal", "🕐 Vista por Dia"])

with tab_sem:
    _render_vista_semanal(inst, schedule)

with tab_dia:
    _render_vista_por_dia(inst, schedule)

# ── Sección 3: Alertas ─────────────────────────────────────────────────────

st.markdown("---")
all_al = _all_alertas(schedule)
st.markdown(
    f'<h4 style="color:{PRIMARY}">3 — Alertas operacionales ({len(all_al)} total)</h4>',
    unsafe_allow_html=True,
)
_render_alertas(schedule)

# ── Sección 4: Métricas ────────────────────────────────────────────────────

st.markdown("---")
st.markdown(f'<h4 style="color:{PRIMARY}">4 — Metricas de la semana</h4>', unsafe_allow_html=True)
_render_metricas(schedule)

# ── Exportar ───────────────────────────────────────────────────────────────

st.markdown("---")
ec1, ec2 = st.columns(2)
with ec1:
    st.download_button(
        "📋 Descargar CSV",
        data=_export_csv_bytes(schedule),
        file_name=f"calendario_bursan_{schedule.semana}.csv",
        mime="text/csv",
        use_container_width=True,
    )
with ec2:
    st.download_button(
        "📄 Descargar HTML",
        data=_export_html_bytes(schedule),
        file_name=f"calendario_bursan_{schedule.semana}.html",
        mime="text/html",
        use_container_width=True,
    )
