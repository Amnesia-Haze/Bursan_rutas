"""core/scheduler.py — Cronograma diario de rutas de buses para guardias Bursan."""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import date, timedelta

try:
    from core.instance import BursanInstance
    from core.assignment import AssignmentResult, resolver_asignacion
    from heuristics import RoutingResult
    from core.routing import resolver_rutas
except ModuleNotFoundError:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from core.instance import BursanInstance
    from core.assignment import AssignmentResult, resolver_asignacion
    from heuristics import RoutingResult
    from core.routing import resolver_rutas


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DailySchedule:
    """Cronograma de un turno para un dia especifico."""

    fecha: str                        # "2026-06-10"
    turno: str                        # "dia" | "noche"
    asignacion: AssignmentResult
    rutas: RoutingResult
    guardias_disponibles: list[str]   # IDs de guardias activos ese dia
    guardias_reserva: list[str]       # IDs disponibles no asignados (emergencia)
    alertas: list[str]                # mensajes de alerta operacional


@dataclass
class WeeklySchedule:
    """Cronograma semanal agregado."""

    semana: str                       # "2026-W24"
    dias: list[DailySchedule]
    resumen_km: float
    resumen_costo_clp: float
    resumen_buses: int


# ---------------------------------------------------------------------------
# Funcion principal
# ---------------------------------------------------------------------------

def generar_calendario(
    inst: BursanInstance,
    fecha_inicio: str,
    n_dias: int = 7,
    modo_asignacion: str = "suma_total",
    metodo_ruteo: str = "nearest_neighbor",
) -> WeeklySchedule:
    """
    Genera el cronograma semanal de rutas de buses.

    Por cada dia del rango [fecha_inicio, fecha_inicio + n_dias):
      - Resuelve la asignacion optima guardia-empresa con ILP.
      - Separa por turno (dia / noche) y construye rutas de bus para cada uno.
      - Identifica guardias de reserva y genera alertas operacionales.

    En la version base todos los guardias activos estan disponibles cada dia.
    La funcion esta disenada para soportar disponibilidad variable por dia
    simplemente filtrando ``inst.guardias`` antes de llamar a ``resolver_asignacion``.

    Args:
        inst:              Instancia de Bursan.
        fecha_inicio:      Fecha de inicio en formato "YYYY-MM-DD".
        n_dias:            Numero de dias a programar (por defecto 7).
        modo_asignacion:   Modo del ILP: "suma_total" | "minimax" | "multiobjetivo".
        metodo_ruteo:      Heuristico: "nearest_neighbor" | "clarke_wright".

    Returns:
        WeeklySchedule con todos los DailySchedules y metricas agregadas.
    """
    start = date.fromisoformat(fecha_inicio)
    iso_cal = start.isocalendar()
    semana = f"{iso_cal[0]}-W{iso_cal[1]:02d}"

    activos_ids = [g.id for g in inst.guardias_activos()]
    dias: list[DailySchedule] = []

    for offset in range(n_dias):
        dia = start + timedelta(days=offset)
        fecha_str = dia.isoformat()

        # Version base: todos los guardias activos disponibles cada dia
        disponibles_hoy = list(activos_ids)

        full_asign = resolver_asignacion(inst, modo=modo_asignacion)

        if full_asign.status != "Optimal":
            for turno_str in ("dia", "noche"):
                dias.append(DailySchedule(
                    fecha=fecha_str,
                    turno=turno_str,
                    asignacion=full_asign,
                    rutas=_empty_routing(metodo_ruteo),
                    guardias_disponibles=disponibles_hoy,
                    guardias_reserva=disponibles_hoy,
                    alertas=["INFACTIBLE: no hay solucion para este dia"],
                ))
            continue

        for turno_str, turno_code in (("dia", "D"), ("noche", "N")):
            asign_t = _filter_asignacion(full_asign, turno_code)
            rutas_t = resolver_rutas(inst, asign_t, metodo=metodo_ruteo)
            asignados = {a["guardia_id"] for a in asign_t.asignaciones}
            reserva = [g for g in disponibles_hoy if g not in asignados]
            alertas = _build_alertas(
                turno_str, fecha_str, rutas_t, reserva, inst.max_distancia_ruta
            )
            dias.append(DailySchedule(
                fecha=fecha_str,
                turno=turno_str,
                asignacion=asign_t,
                rutas=rutas_t,
                guardias_disponibles=disponibles_hoy,
                guardias_reserva=reserva,
                alertas=alertas,
            ))

    resumen_km = round(sum(d.rutas.distancia_total_sistema for d in dias), 2)
    resumen_costo_clp = round(sum(d.rutas.costo_total_clp for d in dias), 2)
    resumen_buses = sum(d.rutas.n_buses_necesarios for d in dias)

    return WeeklySchedule(
        semana=semana,
        dias=dias,
        resumen_km=resumen_km,
        resumen_costo_clp=resumen_costo_clp,
        resumen_buses=resumen_buses,
    )


# ---------------------------------------------------------------------------
# Funciones de exportacion
# ---------------------------------------------------------------------------

def exportar_calendario_csv(schedule: WeeklySchedule, path: str) -> None:
    """
    Exporta el calendario a CSV.

    Columnas: fecha, turno, guardia_id, empresa, ruta_id, distancia_km, costo_clp.
    """
    fieldnames = ["fecha", "turno", "guardia_id", "empresa", "ruta_id", "distancia_km", "costo_clp"]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for ds in schedule.dias:
            guardia_ruta = _guardia_ruta_map(ds.rutas)
            for a in ds.asignacion.asignaciones:
                gid = a["guardia_id"]
                writer.writerow({
                    "fecha": ds.fecha,
                    "turno": ds.turno,
                    "guardia_id": gid,
                    "empresa": a["empresa"],
                    "ruta_id": guardia_ruta.get(gid, 0),
                    "distancia_km": a["distancia_km"],
                    "costo_clp": a["costo_clp"],
                })


def exportar_calendario_html(schedule: WeeklySchedule, path: str) -> None:
    """Genera reporte HTML autocontenido del calendario semanal."""
    lines: list[str] = []
    lines += _html_header(schedule.semana)

    # Resumen global
    fechas_unicas = sorted({d.fecha for d in schedule.dias})
    n_dias = len(fechas_unicas)
    lines.append('<section class="resumen">')
    lines.append(f"<h2>Resumen de la semana</h2>")
    lines.append('<table class="stats">')
    lines.append(f"<tr><th>Dias programados</th><td>{n_dias}</td></tr>")
    lines.append(f"<tr><th>Km totales</th><td>{schedule.resumen_km:,.1f} km</td></tr>")
    lines.append(f"<tr><th>Costo total combustible</th><td>${schedule.resumen_costo_clp:,.0f} CLP</td></tr>")
    lines.append(f"<tr><th>Buses-turno totales</th><td>{schedule.resumen_buses}</td></tr>")
    lines.append("</table>")
    lines.append("</section>")

    # Secciones por dia
    for fecha in fechas_unicas:
        lines.append(f'<section class="dia">')
        lines.append(f"<h2>{fecha}</h2>")

        for turno_str in ("dia", "noche"):
            ds = next((d for d in schedule.dias if d.fecha == fecha and d.turno == turno_str), None)
            if ds is None:
                continue

            turno_label = "Turno DIA" if turno_str == "dia" else "Turno NOCHE"
            lines.append(f'<div class="turno turno-{turno_str}">')
            lines.append(f'<h3>{turno_label}</h3>')

            if ds.alertas:
                for alerta in ds.alertas:
                    lines.append(f'<p class="alerta">{_esc(alerta)}</p>')

            if not ds.asignacion.asignaciones:
                lines.append('<p class="sin-asign">Sin asignaciones para este turno.</p>')
            else:
                guardia_ruta = _guardia_ruta_map(ds.rutas)
                lines.append('<table>')
                lines.append("<thead><tr>")
                for col in ("Guardia", "Empresa", "Ruta", "Km asign.", "Costo CLP asign."):
                    lines.append(f"<th>{col}</th>")
                lines.append("</tr></thead><tbody>")
                for a in sorted(ds.asignacion.asignaciones, key=lambda x: x["guardia_id"]):
                    gid = a["guardia_id"]
                    lines.append(
                        f"<tr><td>{_esc(gid)}</td>"
                        f"<td>{_esc(a['empresa'])}</td>"
                        f"<td>{guardia_ruta.get(gid, '-')}</td>"
                        f"<td>{a['distancia_km']:.1f}</td>"
                        f"<td>${a['costo_clp']:,.0f}</td></tr>"
                    )
                lines.append("</tbody></table>")
                lines.append(
                    f"<p class='summary'>"
                    f"<b>{ds.rutas.n_buses_necesarios} bus(es)</b> &mdash; "
                    f"{ds.rutas.distancia_total_sistema:.1f} km ruta &mdash; "
                    f"${ds.rutas.costo_total_clp:,.0f} CLP</p>"
                )

            if ds.guardias_reserva:
                reserva_str = ", ".join(ds.guardias_reserva)
                lines.append(f'<p class="reserva">Reserva ({len(ds.guardias_reserva)}): {_esc(reserva_str)}</p>')

            lines.append("</div>")  # turno

        lines.append("</section>")  # dia

    lines.append("</body></html>")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _filter_asignacion(full: AssignmentResult, turno_code: str) -> AssignmentResult:
    """Extrae del resultado ILP solo las asignaciones del turno indicado (D o N)."""
    filtered = [a for a in full.asignaciones if a["turno"] == turno_code]
    if not filtered:
        return AssignmentResult(
            status="Optimal",
            z_total=0.0, z_max=0.0, z_min=0.0, z_range=0.0,
            asignaciones=[],
            runtime_seg=full.runtime_seg,
            modo=full.modo, alpha=full.alpha, beta=full.beta,
        )
    dists = [a["distancia_km"] for a in filtered]
    return AssignmentResult(
        status="Optimal",
        z_total=round(sum(dists), 2),
        z_max=max(dists),
        z_min=min(dists),
        z_range=round(max(dists) - min(dists), 2),
        asignaciones=filtered,
        runtime_seg=full.runtime_seg,
        modo=full.modo, alpha=full.alpha, beta=full.beta,
    )


def _build_alertas(
    turno_str: str,
    fecha_str: str,
    rutas: RoutingResult,
    reserva: list[str],
    r_ruta: float,
) -> list[str]:
    alertas: list[str] = []

    if len(reserva) < 2:
        alertas.append(
            f"RESERVA_BAJA: Solo {len(reserva)} guardia(s) de reserva "
            f"(turno {turno_str}, {fecha_str})."
        )

    for i, ruta in enumerate(rutas.rutas, 1):
        if ruta.distancia_total_km > r_ruta:
            alertas.append(
                f"RUTA_LARGA: Ruta {i} supera {r_ruta:.0f} km "
                f"({ruta.distancia_total_km:.1f} km, turno {turno_str}, {fecha_str})."
            )

    for gid in rutas.guardias_exclusivos:
        alertas.append(
            f"GUARDIA_AISLADO: Guardia {gid} requiere ruta exclusiva "
            f"(turno {turno_str}, {fecha_str})."
        )

    return alertas


def _guardia_ruta_map(rutas: RoutingResult) -> dict[str, int]:
    """Devuelve {guardia_id: numero_de_ruta (1-based)} para todos los guardias rutados."""
    mapping: dict[str, int] = {}
    for i, ruta in enumerate(rutas.rutas, 1):
        for gid in ruta.guardias:
            mapping[gid] = i
    return mapping


def _empty_routing(metodo: str) -> RoutingResult:
    return RoutingResult(
        rutas=[],
        distancia_total_sistema=0.0,
        costo_total_clp=0.0,
        n_buses_necesarios=0,
        guardias_exclusivos=[],
        metodo=metodo,
    )


def _esc(text: str) -> str:
    """Escapa caracteres HTML basicos."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _html_header(semana: str) -> list[str]:
    css = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: Arial, sans-serif; font-size: 14px; color: #222; padding: 20px; }
h1 { font-size: 1.6em; color: #1a3a5c; border-bottom: 3px solid #1a3a5c;
     padding-bottom: 8px; margin-bottom: 16px; }
h2 { font-size: 1.2em; color: #1a3a5c; margin: 20px 0 8px; }
h3 { font-size: 1em; margin-bottom: 6px; }
section.resumen { background: #f0f4f8; border: 1px solid #ccd9e8;
                  padding: 12px 16px; display: inline-block;
                  border-radius: 4px; margin-bottom: 24px; }
table.stats th { text-align: left; padding: 3px 16px 3px 0; color: #444; }
table.stats td { padding: 3px 0; font-weight: bold; }
section.dia { border: 1px solid #dde5f0; border-radius: 4px;
              margin-bottom: 16px; overflow: hidden; }
section.dia > h2 { background: #1a3a5c; color: #fff;
                   padding: 8px 14px; margin: 0; }
.turno { padding: 10px 14px; border-bottom: 1px solid #eee; }
.turno-dia   { background: #fffdf0; border-left: 5px solid #e6b800; }
.turno-noche { background: #f0f4ff; border-left: 5px solid #1a73e8; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
thead th { background: #2c5282; color: #fff; padding: 6px 10px; text-align: left; }
tbody td { padding: 5px 10px; border-bottom: 1px solid #ddd; }
tbody tr:nth-child(even) { background: #f7f9fc; }
p.alerta { color: #9b1c1c; background: #fff5f5; border: 1px solid #fca5a5;
           padding: 4px 10px; border-radius: 3px; margin: 4px 0; font-size: 0.9em; }
p.summary { margin-top: 6px; color: #333; }
p.reserva { margin-top: 6px; color: #666; font-size: 0.88em; }
p.sin-asign { color: #888; font-style: italic; margin: 4px 0; }
"""
    return [
        "<!DOCTYPE html>",
        '<html lang="es">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>Calendario Bursan {_esc(semana)}</title>",
        f"<style>{css}</style>",
        "</head>",
        "<body>",
        f"<h1>Calendario Semanal Bursan &mdash; {_esc(semana)}</h1>",
    ]


# ---------------------------------------------------------------------------
# Prueba minima
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os, sys, tempfile
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from core.instance import Guard, Company, BursanInstance  # type: ignore[import]

    _g = [
        Guard("TG1", "Test1", "Dir1", False, "activo", -36.820, -73.044),
        Guard("TG2", "Test2", "Dir2", False, "activo", -36.835, -73.060),
        Guard("TG3", "Test3", "Dir3", False, "activo", -36.850, -73.074),
        Guard("TG4", "Test4", "Dir4", False, "activo", -36.865, -73.088),
    ]
    _e = [
        Company("TE1", "CorpA", "DirA", 2, 0, False, "activo", -36.960, -73.090),
        Company("TE2", "CorpB", "DirB", 2, 0, False, "activo", -36.880, -73.020),
    ]
    _d = {
        "TG1": {"CorpA": 16.0, "CorpB": 7.0},
        "TG2": {"CorpA": 14.0, "CorpB": 6.0},
        "TG3": {"CorpA": 12.0, "CorpB": 5.5},
        "TG4": {"CorpA": 10.5, "CorpB": 6.3},
    }
    _inst = BursanInstance(guardias=_g, empresas=_e, distancias=_d)

    # Generar 2 dias (4 DailySchedules: 2 dias x 2 turnos)
    sched = generar_calendario(_inst, "2026-06-10", n_dias=2)

    assert sched.semana == "2026-W24", f"Semana esperada 2026-W24, got {sched.semana}"
    assert len(sched.dias) == 4, f"Esperados 4 DailySchedules (2 dias x 2 turnos), got {len(sched.dias)}"

    # Turnos dia deben tener asignaciones (turno_dia=2 para cada empresa)
    dias_dia = [d for d in sched.dias if d.turno == "dia"]
    assert all(len(d.asignacion.asignaciones) == 4 for d in dias_dia), (
        "Cada turno dia debe tener 4 asignaciones"
    )

    # Turnos noche deben estar vacios (turno_noche=0 para ambas empresas)
    dias_noche = [d for d in sched.dias if d.turno == "noche"]
    assert all(len(d.asignacion.asignaciones) == 0 for d in dias_noche), (
        "Turno noche debe estar vacio (turno_noche=0 en ambas empresas)"
    )

    # Reserva turno dia: 0 (todos asignados); no debe generar alerta RESERVA_BAJA
    # porque los 4 guardias estan todos en dia, reserva=0 < 2 → SI genera alerta
    for ds in dias_dia:
        assert any("RESERVA_BAJA" in a for a in ds.alertas), (
            f"Esperaba alerta RESERVA_BAJA para {ds.fecha} dia (reserva={ds.guardias_reserva})"
        )

    # Reserva turno noche: todos los guardias libres (4 >= 2) → NO alerta RESERVA_BAJA
    for ds in dias_noche:
        assert not any("RESERVA_BAJA" in a for a in ds.alertas), (
            f"No esperaba alerta RESERVA_BAJA para {ds.fecha} noche"
        )

    # Metricas globales coherentes
    assert sched.resumen_km > 0, "km totales debe ser positivo"
    assert sched.resumen_costo_clp > 0
    assert sched.resumen_buses == sum(d.rutas.n_buses_necesarios for d in sched.dias)

    print(
        f"Calendario generado: {sched.semana} — "
        f"{len(sched.dias)} turnos, "
        f"{sched.resumen_km:.1f} km totales, "
        f"${sched.resumen_costo_clp:,.0f} CLP, "
        f"{sched.resumen_buses} buses"
    )

    # --- Exportar CSV ---
    tmpdir = tempfile.mkdtemp()
    csv_path = os.path.join(tmpdir, "calendario.csv")
    exportar_calendario_csv(sched, csv_path)
    assert os.path.exists(csv_path) and os.path.getsize(csv_path) > 0

    with open(csv_path, encoding="utf-8") as f:
        lines = f.readlines()
    # 1 header + 4 asignaciones/dia × 2 dias = 9 filas (noche tiene 0 asignaciones)
    assert len(lines) == 9, f"CSV esperaba 9 lineas (1 header + 8 asign), got {len(lines)}"
    assert lines[0].startswith("fecha,turno,guardia_id"), f"Header CSV incorrecto: {lines[0]}"
    print(f"CSV exportado: {csv_path} ({len(lines)-1} filas de datos)")

    # --- Exportar HTML ---
    html_path = os.path.join(tmpdir, "calendario.html")
    exportar_calendario_html(sched, html_path)
    assert os.path.exists(html_path) and os.path.getsize(html_path) > 0

    with open(html_path, encoding="utf-8") as f:
        html_content = f.read()
    assert "2026-W24" in html_content, "HTML debe contener el identificador de semana"
    assert "<!DOCTYPE html>" in html_content
    assert "2026-06-10" in html_content
    print(f"HTML exportado: {html_path} ({len(html_content):,} chars)")

    print("OK scheduler.py: todas las aserciones pasaron")
