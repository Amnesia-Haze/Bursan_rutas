# Bursan Rutas

Sistema de optimización de rutas de buses de acercamiento para guardias de seguridad de Bursan en la Región del Biobío, Chile. La aplicación permite modelar, resolver y visualizar asignaciones óptimas de guardias a empresas clientes, minimizando distancias recorridas y respetando restricciones operacionales como turnos, supervisores requeridos y estado de contratos.

El proyecto combina modelos de programación lineal entera (PuLP / OR-Tools) con una interfaz web interactiva (Streamlit) que permite al operador cargar datos, ajustar parámetros, ejecutar el optimizador y explorar los resultados en mapas y tablas. Las coordenadas geográficas se obtienen automáticamente mediante geocodificación (geopy / Nominatim) a partir de las direcciones registradas en los CSV.

## Instalación

```bash
pip install -r requirements.txt
```

## Ejecución

```bash
streamlit run app/app.py
```

## Estructura de carpetas

| Carpeta / Archivo | Descripción |
|---|---|
| `data/` | Datos de entrada: guardias, empresas y matriz de distancias en CSV |
| `core/` | Lógica del modelo de optimización (variables, restricciones, función objetivo) |
| `heuristics/` | Algoritmos heurísticos alternativos (greedy, savings, etc.) |
| `app/` | Aplicación Streamlit principal (`app.py`) |
| `app/pages/` | Páginas multipage de Streamlit |
| `app/components/` | Componentes reutilizables de la UI (mapas, tablas, formularios) |
| `tests/` | Suite de pruebas con pytest |
| `requirements.txt` | Dependencias del proyecto |
