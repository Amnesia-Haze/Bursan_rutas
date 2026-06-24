import sys
sys.path.insert(0, ".")
from copy import deepcopy
from core.instance import load_instance
from core.assignment import resolver_asignacion
from core.routing import resolver_rutas

inst = deepcopy(load_instance())
for e in inst.empresas:
    if e.nombre == "Noramco":
        e.turno_dia, e.turno_noche = 1, 1   # =2
    elif e.nombre == "ITI Chile":
        e.turno_dia, e.turno_noche = 2, 1   # =3
    elif e.nombre == "Oleoducto":
        e.turno_dia, e.turno_noche = 2, 0   # =2
    elif e.nombre == "Indama":
        e.turno_dia, e.turno_noche = 1, 1   # =2

demanda = sum(e.demanda_total() for e in inst.empresas if e.is_activa())
activos  = len(inst.guardias_activos())
print(f"Guardias activos   : {activos}")
print(f"Demanda configurada: {demanda}")
print()

asig = resolver_asignacion(inst, modo="suma_total", d_max=40, delta_equidad=None)

print("=== RESULTADO ASIGNACION (demanda=9) ===")
print(f"Status   : {asig.status}")
print(f"Z* total : {asig.z_total:.2f} km")
print(f"Asignados: {len(asig.asignaciones)}")
print(f"Reserva  : {asig.guardias_reserva}")
print()
print("Asignaciones:")
for a in asig.asignaciones:
    g_id  = a["guardia_id"]
    enom  = a["empresa"]
    turno = a["turno"]
    dist  = a["distancia_km"]
    costo = int(a["costo_clp"])
    g_obj = next((x for x in inst.guardias if x.id == g_id), None)
    gnom  = g_obj.nombre[:22] if g_obj else "?"
    print(f"  {g_id:<4s} {gnom:<22s} -> {enom:<12s} [{turno}] {dist:5.1f} km  ${costo:,}")

costo_total = sum(a["costo_clp"] for a in asig.asignaciones)
print()
print(f"Costo total traslados: ${costo_total:,.0f} CLP")

print()
print("=== RUTAS (nearest_neighbor) ===")
rutas = resolver_rutas(inst, asig, metodo="nearest_neighbor")
print(f"Metodo distancia     : {rutas.metodo_distancia}")
print(f"Dist total sistema   : {rutas.distancia_total_sistema:.2f} km")
print(f"Costo total          : ${rutas.costo_total_clp:,.0f} CLP")
print(f"Num vehiculos        : {len(rutas.rutas)}")
print(f"Buses necesarios     : {rutas.n_buses_necesarios}")
for i, r in enumerate(rutas.rutas, 1):
    nodos = " -> ".join(s.node_id for s in r.paradas)
    excl  = " [exclusiva]" if r.es_exclusiva else ""
    print(f"  Ruta {i}: {nodos}  ({r.distancia_total_km:.1f} km){excl}")
