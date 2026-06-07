"""app/pages/3_Optimizar.py — Pagina principal de optimizacion de rutas Bursan."""
from __future__ import annotations

import io
import json
import zipfile
from copy import deepcopy

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))   # bursan_rutas/
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.instance import BursanInstance
from core.assignment import resolver_asignacion, AssignmentResult
from core.routing import resolver_rutas, COORDS_FALLBACK
from heuristics import RoutingResult

try:
    import folium
    from folium.plugins import PolyLineTextPath
    from streamlit_folium import st_folium
    _HAS_FOLIUM = True
except ImportError:
    _HAS_FOLIUM = False


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

PRIMARY = "#1a3a5c"
ACCENT  = "#f0622a"

_ROUTE_COLORS = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12",
    "#9b59b6", "#1abc9c", "#e67e22", "#34495e",
]

_FASE1_REF = {
    "z_total_km": 151.1,
    "nota": "Referencia del informe Bursan Fase 1 — ILP con distancias geocodificadas reales.",
}

_MODO_LABELS: dict[str, str] = {
    "suma_total":    "Minimizar distancia total",
    "minimax":       "Minimizar distancia maxima (equidad)",
    "multiobjetivo": "Multiobjetivo (a*suma + b*max)",
}
_MODO_INV: dict[str, str] = {v: k for k, v in _MODO_LABELS.items()}


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        [data-testid="stSidebar"] {{background-color: #f7f9fc;}}
        .metric-card {{
            background: #fff;
            border: 1px solid #e1e8f0;
            border-left: 4px solid {PRIMARY};
            border-radius: 6px;
            padding: 12px 14px;
            text-align: center;
        }}
        .metric-card .val {{font-size: 1.45rem; font-weight: 700; color: {PRIMARY};}}
        .metric-card .lbl {{font-size: 0.76rem; color: #6b7c93; margin-top: 3px;}}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def _init_state() -> None:
    for k, v in {
        "opt_result":     None,
        "opt_params_key": None,
        "sens_results":   None,
        "sens_param":     None,
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ---------------------------------------------------------------------------
# Helpers nucleares
# ---------------------------------------------------------------------------

def _params_key(params: dict) -> str:
    return json.dumps(
        {k: (v if v is not None else "null") for k, v in sorted(params.items())},
        sort_keys=True,
    )


def _run_optimization(
    inst: BursanInstance, params: dict
) -> tuple[BursanInstance, AssignmentResult, RoutingResult | None]:
    inst_opt = deepcopy(inst)
    inst_opt.capacidad_bus        = params["capacidad_bus"]
    inst_opt.max_distancia_ruta   = params["r_ruta"]
    inst_opt.max_distancia_vecino = params["r_vecino"]
    inst_opt.rendimiento_kmL      = params["rendimiento"]
    inst_opt.precio_combustible_clp = params["precio_comb"]

    asignacion = resolver_asignacion(
        inst_opt,
        modo          = params["modo"],
        alpha         = params["alpha"],
        beta          = params["beta"],
        d_max         = params["d_max"],
        delta_equidad = params.get("delta_equidad"),
        tiempo_limite = params.get("tiempo_limite", 60),
    )

    if asignacion.status != "Optimal":
        return inst_opt, asignacion, None

    routing = resolver_rutas(
        inst_opt,
        asignacion,
        metodo       = params["metodo"],
        mejorar_2opt = params["mejorar_2opt"],
    )
    return inst_opt, asignacion, routing


# ---------------------------------------------------------------------------
# Constructores de DataFrames
# ---------------------------------------------------------------------------

def _asign_df(asignacion: AssignmentResult, inst: BursanInstance) -> pd.DataFrame:
    guard_map = {g.id: g.nombre for g in inst.guardias}
    rows = [
        {
            "ID":          a["guardia_id"],
            "Nombre":      guard_map.get(a["guardia_id"], ""),
            "Empresa":     a["empresa"],
            "Turno":       "Dia" if a["turno"] == "D" else "Noche",
            "Dist. (km)":  round(a["distancia_km"], 1),
            "Costo (CLP)": f"${int(a['costo_clp']):,}",
        }
        for a in asignacion.asignaciones
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Empresa", "Turno", "Dist. (km)"])
    return df


def _rutas_df(routing: RoutingResult) -> pd.DataFrame:
    rows = []
    for i, r in enumerate(routing.rutas, 1):
        cos = sorted({s.node_id for s in r.paradas if s.node_type == "empresa"})
        rows.append({
            "Bus":        f"Bus {i}",
            "Guardias":   ", ".join(r.guardias),
            "Empresas":   ", ".join(cos),
            "N° paradas": len(r.guardias),
            "Km total":   round(r.distancia_total_km, 1),
            "Costo (CLP)": f"${int(r.costo_clp):,}",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Graficos
# ---------------------------------------------------------------------------

def _bar_asignacion(asignacion: AssignmentResult) -> go.Figure:
    df = pd.DataFrame([
        {
            "Guardia":    a["guardia_id"],
            "Empresa":    a["empresa"],
            "Turno":      "Dia" if a["turno"] == "D" else "Noche",
            "Dist. (km)": round(a["distancia_km"], 1),
        }
        for a in asignacion.asignaciones
    ]).sort_values("Dist. (km)")

    avg = df["Dist. (km)"].mean()
    fig = px.bar(
        df,
        x="Dist. (km)", y="Guardia",
        orientation="h",
        color="Empresa",
        hover_data=["Turno"],
        title="Distancia asignada por guardia",
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.add_vline(
        x=avg, line_dash="dash", line_color=ACCENT,
        annotation_text=f"Prom: {avg:.1f} km",
        annotation_position="top right",
    )
    fig.update_layout(
        height=420, margin=dict(l=10, r=10, t=40, b=10),
        legend_title_text="Empresa", xaxis_title="Distancia (km)", yaxis_title=None,
    )
    return fig


def _gantt_rutas(routing: RoutingResult) -> go.Figure:
    fig = go.Figure()
    for i, r in enumerate(routing.rutas):
        color = _ROUTE_COLORS[i % len(_ROUTE_COLORS)]
        cos = sorted({s.node_id for s in r.paradas if s.node_type == "empresa"})
        label = f"Bus {i + 1}"
        fig.add_trace(go.Bar(
            y=[label],
            x=[r.distancia_total_km],
            orientation="h",
            marker_color=color,
            name=label,
            text=f"{', '.join(r.guardias)}  →  {', '.join(cos)}",
            textposition="inside" if r.distancia_total_km > 8 else "outside",
            hovertemplate=(
                f"<b>{label}</b><br>"
                f"Guardias: {', '.join(r.guardias)}<br>"
                f"Empresas: {', '.join(cos)}<br>"
                f"Km: {r.distancia_total_km:.1f}<extra></extra>"
            ),
        ))
    fig.update_layout(
        title="Rutas de bus — km totales",
        xaxis_title="Distancia (km)",
        yaxis_title=None,
        height=max(200, len(routing.rutas) * 60 + 80),
        showlegend=False,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


def _sensitivity_chart(results: list[dict], param_label: str) -> go.Figure:
    df = pd.DataFrame(results)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["valor"], y=df["z_total"],
        mode="lines+markers", name="Z* total (km)",
        line=dict(color=PRIMARY, width=2), marker=dict(size=7),
        hovertemplate="Param: %{x}<br>Z* total: %{y:.1f} km<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["valor"], y=df["z_max"],
        mode="lines+markers", name="Z* max (km)",
        line=dict(color=ACCENT, width=2, dash="dot"), marker=dict(size=7),
        hovertemplate="Param: %{x}<br>Z* max: %{y:.1f} km<extra></extra>",
    ))
    fig.update_layout(
        title=f"Sensibilidad — {param_label}",
        xaxis_title=param_label, yaxis_title="Distancia (km)",
        height=380,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


# ---------------------------------------------------------------------------
# Mapa Folium
# ---------------------------------------------------------------------------

def _build_map(
    inst: BursanInstance,
    asignacion: AssignmentResult,
    routing: RoutingResult | None,
) -> "folium.Map":
    import folium as _folium
    from folium.plugins import PolyLineTextPath as _PLTP

    def _coords(node_id: str, entity=None) -> tuple[float, float] | tuple[None, None]:
        if entity is not None:
            lat = getattr(entity, "lat", None)
            lon = getattr(entity, "lon", None)
            if lat is not None and lon is not None:
                return lat, lon
        return COORDS_FALLBACK.get(node_id, (None, None))

    m = _folium.Map(location=[-36.90, -73.06], zoom_start=10, tiles="CartoDB positron")

    # Deposito
    dep = _coords("deposito")
    if dep[0] is not None:
        _folium.Marker(
            location=list(dep),
            icon=_folium.Icon(color="red", icon="home", prefix="fa"),
            popup=_folium.Popup("<b>Deposito Bursan</b>", max_width=200),
            tooltip="Deposito Bursan",
        ).add_to(m)

    # Empresas
    for e in inst.empresas:
        if not e.is_activa():
            continue
        lat, lon = _coords(e.nombre, e)
        if lat is None:
            continue
        popup_html = (
            f"<b>{e.nombre}</b><br><small>{e.direccion}</small><br><br>"
            f"Turno Dia: <b>{e.turno_dia}</b> | Turno Noche: <b>{e.turno_noche}</b>"
        )
        _folium.Marker(
            location=[lat, lon],
            icon=_folium.Icon(color="orange", icon="building", prefix="fa"),
            popup=_folium.Popup(popup_html, max_width=290),
            tooltip=e.nombre,
        ).add_to(m)

    # Guardias
    guard_map = {g.id: g for g in inst.guardias}
    assigned = {a["guardia_id"] for a in asignacion.asignaciones}
    for gid, g in guard_map.items():
        lat, lon = _coords(gid, g)
        if lat is None:
            continue
        color = PRIMARY if gid in assigned else "#aab0bb"
        a_info = next((a for a in asignacion.asignaciones if a["guardia_id"] == gid), None)
        popup_html = f"<b>{gid}</b><br>{g.nombre}<br><small>{g.direccion}</small>"
        if a_info:
            turno_s = "Dia" if a_info["turno"] == "D" else "Noche"
            popup_html += (
                f"<br><b>{a_info['empresa']}</b> ({turno_s})"
                f" — {a_info['distancia_km']:.1f} km"
            )
        _folium.CircleMarker(
            location=[lat, lon],
            radius=7, color=color,
            fill=True, fill_color=color, fill_opacity=0.75,
            popup=_folium.Popup(popup_html, max_width=250),
            tooltip=f"{gid}: {g.nombre}",
        ).add_to(m)

    # Rutas
    if routing:
        for i, ruta in enumerate(routing.rutas):
            color = _ROUTE_COLORS[i % len(_ROUTE_COLORS)]
            coords = [
                [s.lat, s.lon]
                for s in ruta.paradas
                if s.lat is not None and s.lon is not None
            ]
            if len(coords) < 2:
                continue
            cos = sorted({s.node_id for s in ruta.paradas if s.node_type == "empresa"})
            line = _folium.PolyLine(
                coords, color=color, weight=4, opacity=0.85,
                tooltip=f"Bus {i+1}: {', '.join(ruta.guardias)} → {', '.join(cos)}",
            )
            line.add_to(m)
            try:
                _PLTP(
                    line, "    ►    ", repeat=True, offset=25,
                    attributes={"font-size": "14", "fill": color},
                ).add_to(m)
            except Exception:
                pass

    return m


# ---------------------------------------------------------------------------
# Exportacion
# ---------------------------------------------------------------------------

def _generar_html(
    inst: BursanInstance,
    asignacion: AssignmentResult,
    routing: RoutingResult | None,
    params: dict,
) -> str:
    modo_label = _MODO_LABELS.get(asignacion.modo, asignacion.modo)
    rows_a = "".join(
        f"<tr><td>{a['guardia_id']}</td><td>{a['empresa']}</td>"
        f"<td>{'Dia' if a['turno'] == 'D' else 'Noche'}</td>"
        f"<td>{a['distancia_km']:.1f}</td>"
        f"<td>${int(a['costo_clp']):,}</td></tr>"
        for a in asignacion.asignaciones
    )
    rows_r = ""
    if routing:
        for i, r in enumerate(routing.rutas, 1):
            cos = sorted({s.node_id for s in r.paradas if s.node_type == "empresa"})
            rows_r += (
                f"<tr><td>Bus {i}</td><td>{', '.join(r.guardias)}</td>"
                f"<td>{', '.join(cos)}</td>"
                f"<td>{r.distancia_total_km:.1f}</td>"
                f"<td>${int(r.costo_clp):,}</td></tr>"
            )

    costo_total = int(routing.costo_total_clp) if routing else 0
    n_buses     = routing.n_buses_necesarios   if routing else 0

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Reporte Bursan Rutas</title>
<style>
  body{{font-family:Arial,sans-serif;max-width:960px;margin:40px auto;color:#1a1a1a}}
  h1{{color:#1a3a5c}} h2{{color:#1a3a5c;font-size:1.05rem;margin-top:24px}}
  table{{border-collapse:collapse;width:100%;margin-top:8px}}
  th{{background:#1a3a5c;color:#fff;padding:8px 12px;text-align:left}}
  td{{padding:7px 12px;border-bottom:1px solid #e1e8f0}}
  tr:nth-child(even){{background:#f7f9fc}}
  .metrics{{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px}}
  .card{{border:1px solid #e1e8f0;border-left:4px solid #1a3a5c;
         border-radius:6px;padding:12px 20px;min-width:130px;text-align:center}}
  .card .v{{font-size:1.4rem;font-weight:700;color:#1a3a5c}}
  .card .l{{font-size:0.74rem;color:#6b7c93;margin-top:4px}}
</style>
</head>
<body>
<h1>Reporte de Optimizacion Bursan Rutas</h1>
<p><b>Funcion objetivo:</b> {modo_label}</p>
<p><b>Estado ILP:</b> {asignacion.status} &nbsp;|&nbsp;
   <b>Tiempo calculo:</b> {asignacion.runtime_seg:.1f} s</p>
<div class="metrics">
  <div class="card"><div class="v">{asignacion.z_total:.1f} km</div><div class="l">Z* total</div></div>
  <div class="card"><div class="v">{asignacion.z_max:.1f} km</div><div class="l">Dist. maxima</div></div>
  <div class="card"><div class="v">{asignacion.z_range:.1f} km</div><div class="l">Rango equidad</div></div>
  <div class="card"><div class="v">{n_buses}</div><div class="l">Buses necesarios</div></div>
  <div class="card"><div class="v">${costo_total:,}</div><div class="l">Costo total CLP</div></div>
</div>
<h2>Asignaciones</h2>
<table>
<thead><tr><th>Guardia</th><th>Empresa</th><th>Turno</th>
           <th>Dist. (km)</th><th>Costo (CLP)</th></tr></thead>
<tbody>{rows_a}</tbody>
</table>
<h2>Rutas de bus</h2>
<table>
<thead><tr><th>Bus</th><th>Guardias</th><th>Empresas</th>
           <th>Km total</th><th>Costo (CLP)</th></tr></thead>
<tbody>{rows_r if rows_r else '<tr><td colspan="5">Sin datos de ruteo</td></tr>'}</tbody>
</table>
</body>
</html>"""


def _export_zip(
    inst: BursanInstance,
    asignacion: AssignmentResult,
    routing: RoutingResult | None,
    params: dict,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("asignacion.csv", _asign_df(asignacion, inst).to_csv(index=False))
        if routing:
            zf.writestr("rutas.csv", _rutas_df(routing).to_csv(index=False))
        zf.writestr("reporte.html", _generar_html(inst, asignacion, routing, params))
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Renderizadores de pestanas
# ---------------------------------------------------------------------------

def _render_asignacion(
    inst: BursanInstance,
    asignacion: AssignmentResult,
    routing: RoutingResult | None,
) -> None:
    if asignacion.status != "Optimal":
        st.error(
            f"El modelo ILP no encontro solucion factible (status: **{asignacion.status}**). "
            "Prueba aumentar D_max o desactivar la restriccion de equidad."
        )
        return

    n_activos  = len(inst.guardias_activos())
    n_asignados = len(asignacion.asignaciones)
    n_reserva   = n_activos - n_asignados
    n_buses     = routing.n_buses_necesarios   if routing else 0
    costo_total = int(routing.costo_total_clp) if routing else 0

    cols = st.columns(5)
    for col, val, lbl in [
        (cols[0], f"{asignacion.z_total:.1f} km",   "Z* total"),
        (cols[1], f"{asignacion.z_max:.1f} km",     "Dist. maxima"),
        (cols[2], f"{asignacion.z_range:.1f} km",   "Rango equidad"),
        (cols[3], str(n_buses),                      "Buses necesarios"),
        (cols[4], f"${costo_total:,}",               "Costo total CLP"),
    ]:
        col.markdown(
            f'<div class="metric-card"><div class="val">{val}</div>'
            f'<div class="lbl">{lbl}</div></div>',
            unsafe_allow_html=True,
        )

    if n_reserva > 0:
        st.caption(f"Guardias en reserva: {n_reserva} de {n_activos} activos.")

    st.markdown("")
    st.dataframe(_asign_df(asignacion, inst), use_container_width=True, hide_index=True)
    st.plotly_chart(_bar_asignacion(asignacion), use_container_width=True)

    with st.expander("Comparar con Fase 1 (referencia)"):
        c1, c2 = st.columns(2)
        c1.metric("Fase 1 — Z* total", f"{_FASE1_REF['z_total_km']:.1f} km")
        c2.metric(
            "Nuestro modelo — Z* total",
            f"{asignacion.z_total:.1f} km",
            delta=f"{asignacion.z_total - _FASE1_REF['z_total_km']:.1f} km",
            delta_color="inverse",
        )
        st.caption(_FASE1_REF["nota"])


def _render_rutas(routing: RoutingResult | None) -> None:
    if routing is None:
        st.info("Sin resultado de ruteo. Verifica que la asignacion sea factible.")
        return

    st.dataframe(_rutas_df(routing), use_container_width=True, hide_index=True)
    st.plotly_chart(_gantt_rutas(routing), use_container_width=True)

    st.markdown("---")
    st.markdown("**Secuencia de paradas por bus**")
    for i, ruta in enumerate(routing.rutas):
        color = _ROUTE_COLORS[i % len(_ROUTE_COLORS)]
        cos = sorted({s.node_id for s in ruta.paradas if s.node_type == "empresa"})
        with st.expander(
            f"Bus {i+1} — {ruta.distancia_total_km:.1f} km | "
            f"{len(ruta.guardias)} guardias | {', '.join(cos)}"
        ):
            st.markdown(" ➜ ".join(p.node_id for p in ruta.paradas))
            df_stops = pd.DataFrame([
                {
                    "Parada": p.node_id,
                    "Tipo":   p.node_type.capitalize(),
                    "Lat":    round(p.lat, 4) if p.lat is not None else "-",
                    "Lon":    round(p.lon, 4) if p.lon is not None else "-",
                }
                for p in ruta.paradas
            ])
            st.dataframe(df_stops, use_container_width=True, hide_index=True)


def _render_mapa(
    inst: BursanInstance,
    asignacion: AssignmentResult,
    routing: RoutingResult | None,
) -> None:
    if not _HAS_FOLIUM:
        st.warning(
            "Folium no esta instalado. Ejecuta: `pip install folium streamlit-folium`"
        )
        return

    m = _build_map(inst, asignacion, routing)
    st_folium(m, width="100%", height=520, returned_objects=[])

    lc = st.columns(4)
    lc[0].markdown("🔴 Deposito")
    lc[1].markdown("🟠 Empresa")
    lc[2].markdown("🔵 Guardia asignado")
    lc[3].markdown("⚪ No asignado")

    if routing and routing.rutas:
        partes = " ".join(
            f'<span style="color:{_ROUTE_COLORS[i % len(_ROUTE_COLORS)]};'
            f'font-weight:600">■ Bus {i+1}</span>'
            for i in range(len(routing.rutas))
        )
        st.markdown(f"Rutas: {partes}", unsafe_allow_html=True)


def _render_sensibilidad(inst: BursanInstance, base_params: dict) -> None:
    st.markdown("Analiza como cambia Z* al variar un parametro clave del modelo.")

    param_options: dict[str, tuple] = {
        "D_max guardia (km)":      ("d_max",        20, 65, 5),
        "Capacidad bus (guardias)": ("capacidad_bus", 5, 20, 1),
        "R_RUTA (km)":             ("r_ruta",        30, 80, 5),
    }
    if base_params.get("modo") == "multiobjetivo":
        param_options["Alpha (peso suma)"] = ("alpha", 0.0, 1.0, 0.05)

    param_label = st.selectbox("Parametro a variar", list(param_options.keys()), key="sens_sel")
    param_key, p_min, p_max, p_step = param_options[param_label]
    is_float = isinstance(p_min, float)

    if is_float:
        rango = st.slider(
            "Rango", min_value=p_min, max_value=p_max,
            value=(0.1, 0.9), step=p_step, key="sens_range_f",
        )
        n_steps = st.select_slider("Pasos", [5, 10, 15, 20], value=10, key="sens_steps")
        step_size = (rango[1] - rango[0]) / max(n_steps - 1, 1)
        values = [round(rango[0] + step_size * i, 2) for i in range(n_steps)]
    else:
        rango = st.slider(
            "Rango", min_value=p_min, max_value=p_max,
            value=(p_min, p_max), step=p_step, key="sens_range_i",
        )
        step_opt = [p_step, p_step * 2, p_step * 3]
        paso = st.select_slider("Paso", step_opt, value=p_step * 2, key="sens_step")
        values = list(range(rango[0], rango[1] + 1, paso))

    st.caption(f"Se ejecutaran {len(values)} optimizaciones ILP.")

    if st.button("▶ Ejecutar analisis de sensibilidad", key="btn_sens"):
        st.session_state.sens_results = None
        bar = st.progress(0)
        txt = st.empty()
        results: list[dict] = []
        for idx, val in enumerate(values):
            txt.text(f"Calculando {param_label} = {val} ...")
            p = dict(base_params)
            p[param_key] = val
            if param_key == "alpha" and p.get("modo") == "multiobjetivo":
                p["beta"] = round(1.0 - float(val), 2)
            try:
                inst_tmp = deepcopy(inst)
                inst_tmp.capacidad_bus        = p["capacidad_bus"]
                inst_tmp.max_distancia_ruta   = p["r_ruta"]
                inst_tmp.max_distancia_vecino = p["r_vecino"]
                a = resolver_asignacion(
                    inst_tmp,
                    modo          = p["modo"],
                    alpha         = p["alpha"],
                    beta          = p["beta"],
                    d_max         = p["d_max"],
                    delta_equidad = p.get("delta_equidad"),
                    tiempo_limite = 20,
                )
                results.append({
                    "valor":   val,
                    "z_total": round(a.z_total, 2),
                    "z_max":   round(a.z_max, 2),
                    "status":  a.status,
                })
            except Exception as exc:
                results.append({"valor": val, "z_total": None, "z_max": None, "status": str(exc)})
            bar.progress((idx + 1) / len(values))
        txt.empty()
        bar.empty()
        st.session_state.sens_results = results
        st.session_state.sens_param   = param_label

    if (
        st.session_state.sens_results is not None
        and st.session_state.sens_param == param_label
    ):
        valid = [r for r in st.session_state.sens_results if r.get("z_total") is not None]
        if valid:
            st.plotly_chart(_sensitivity_chart(valid, param_label), use_container_width=True)
        df_s = pd.DataFrame(st.session_state.sens_results)
        st.dataframe(df_s, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def _render_sidebar() -> tuple[dict, bool]:
    params: dict = {}
    do_opt = False

    with st.sidebar:
        st.markdown(f'<h3 style="color:{PRIMARY}">⚙️ Parametros</h3>', unsafe_allow_html=True)

        with st.expander("📊 Asignacion ILP", expanded=True):
            modo_label = st.radio(
                "Funcion objetivo",
                list(_MODO_LABELS.values()),
                key="p_modo",
                index=0,
            )
            params["modo"] = _MODO_INV[modo_label]

            if params["modo"] == "multiobjetivo":
                params["alpha"] = st.slider(
                    "a (peso suma total)", 0.0, 1.0, 0.5, 0.05, key="p_alpha"
                )
                params["beta"] = round(1.0 - params["alpha"], 2)
                st.caption(f"b (peso max) = {params['beta']:.2f}  [a + b = 1.00]")
            elif params["modo"] == "suma_total":
                params["alpha"], params["beta"] = 1.0, 0.0
            else:
                params["alpha"], params["beta"] = 0.0, 1.0

            params["d_max"] = st.slider("D_max por guardia (km)", 25, 70, 40, 5, key="p_dmax")

            usar_eq = st.checkbox("Restriccion de equidad D_max", key="p_eq")
            params["delta_equidad"] = None
            if usar_eq:
                params["delta_equidad"] = st.slider(
                    "D_max equidad (km)", 0, 40, 20, 2, key="p_delta"
                )

        with st.expander("🚌 Ruteo CVRP", expanded=True):
            params["metodo"] = st.selectbox(
                "Metodo heuristico",
                options=["nearest_neighbor", "clarke_wright"],
                format_func=lambda x: "Nearest Neighbor" if x == "nearest_neighbor" else "Clarke-Wright",
                key="p_metodo",
            )
            params["capacidad_bus"] = st.slider(
                "Capacidad bus (guardias)", 5, 20, 15, 1, key="p_cap"
            )
            params["r_ruta"]   = st.slider("R_RUTA (km)",   30, 80, 50, 5, key="p_rruta")
            params["r_vecino"] = st.slider("R_VECINO (km)", 10, 35, 25, 5, key="p_rvec")
            params["mejorar_2opt"] = st.checkbox("Mejorar con 2-opt", value=True, key="p_2opt")

        with st.expander("💰 Costos operacionales", expanded=False):
            params["rendimiento"] = st.number_input(
                "Rendimiento (km/L)", 3.0, 15.0, 7.0, 0.5, key="p_rend"
            )
            params["precio_comb"] = st.number_input(
                "Precio combustible (CLP/L)", 500, 3000, 1560, 10, key="p_prec"
            )

        st.markdown("---")
        do_opt = st.button(
            "🚀 OPTIMIZAR",
            type="primary",
            use_container_width=True,
            key="btn_opt",
        )

    return params, do_opt


# ---------------------------------------------------------------------------
# Layout principal
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Optimizar — Bursan Rutas",
    page_icon="🚀",
    layout="wide",
)
_inject_css()
_init_state()

if "inst" not in st.session_state or st.session_state.inst is None:
    st.warning("Instancia no cargada. Ve a la pagina de inicio (Home) para cargarla.")
    st.stop()

inst: BursanInstance = st.session_state.inst

params, do_optimize = _render_sidebar()

st.markdown(
    f'<h2 style="color:{PRIMARY};margin-bottom:0">🚀 Optimizacion de Rutas</h2>',
    unsafe_allow_html=True,
)
st.caption(
    f"Instancia: {len(inst.guardias_activos())} guardias activos | "
    f"{sum(e.demanda_total() for e in inst.empresas if e.is_activa())} puestos demandados"
)

if do_optimize:
    pkey = _params_key(params)
    if st.session_state.opt_params_key != pkey:
        with st.spinner("Resolviendo ILP + CVRP..."):
            inst_opt, asignacion, routing = _run_optimization(inst, params)
        st.session_state.opt_result     = {"asignacion": asignacion, "routing": routing, "inst_opt": inst_opt}
        st.session_state.opt_params_key = pkey
        st.session_state.sens_results   = None
    else:
        st.info("Resultado en cache — los parametros no cambiaron desde la ultima ejecucion.")

result = st.session_state.opt_result

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Asignacion",
    "🚌 Rutas de Bus",
    "🗺️ Mapa de Rutas",
    "📈 Sensibilidad",
])

_PLACEHOLDER = "Haz click en **🚀 OPTIMIZAR** para generar resultados."

with tab1:
    if result:
        _render_asignacion(result["inst_opt"], result["asignacion"], result["routing"])
        st.markdown("---")
        st.download_button(
            "📦 Exportar resultados (ZIP — asignacion.csv + rutas.csv + reporte.html)",
            data=_export_zip(result["inst_opt"], result["asignacion"], result["routing"], params),
            file_name="resultados_bursan.zip",
            mime="application/zip",
        )
    else:
        st.info(_PLACEHOLDER)

with tab2:
    if result:
        _render_rutas(result["routing"])
    else:
        st.info(_PLACEHOLDER)

with tab3:
    if result:
        _render_mapa(result["inst_opt"], result["asignacion"], result["routing"])
    else:
        st.info(_PLACEHOLDER)

with tab4:
    _render_sensibilidad(inst, params)
