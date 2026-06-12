"""Verifica conectividad con OpenRouteService y que las distancias sean realistas."""
import os
import sys

import truststore          # usa el almacén de certificados de Windows
truststore.inject_into_ssl()

from dotenv import load_dotenv
import openrouteservice

load_dotenv()

api_key = os.getenv("ORS_API_KEY")
if not api_key or api_key == "tu_api_key_aqui":
    sys.exit("ERROR: ORS_API_KEY no configurada en .env — pega tu clave primero.")

client = openrouteservice.Client(key=api_key)

# Depósito (Concepción) → Noramco (Coronel) — orden ORS: (lon, lat)
coords = [(-73.044, -36.820), (-73.138, -37.052)]

matrix = client.distance_matrix(
    locations=coords,
    profile="driving-car",
    metrics=["distance", "duration"],
    units="km",
)

km  = matrix["distances"][0][1]
min_ = matrix["durations"][0][1] / 60

print(f"ORS: Deposito->Noramco = {km:.1f} km ({min_:.0f} min)")

assert 35 <= km <= 50, (
    f"Distancia fuera de rango esperado 35-50 km: {km:.1f} km\n"
    "Verifica las coordenadas o la clave de API."
)
print("Criterio OK: distancia por carretera dentro de rango 35-50 km")
