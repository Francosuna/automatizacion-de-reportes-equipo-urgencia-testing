# CLAUDE.md — Salus QA Reporter

## Descripción general

Generador de informes finales de pruebas para el equipo de QA de SALUS (OSDE). La aplicación es un servidor Flask que:

1. Presenta un formulario web al QA Engineer para ingresar metadatos del ciclo de pruebas e IDs de Azure DevOps.
2. Consume la API de Azure DevOps para obtener resultados de Test Plans y bugs asociados a Work Items (UHs).
3. Genera un HTML autocontenido con el informe final, listo para exportar a PDF desde el navegador.

Deployado en **Railway** (`railway.app`). No tiene base de datos — es completamente stateless.

---

## Arquitectura y archivos clave

```
app.py            ← Aplicación principal (Flask). Todo el backend vive aquí.
reporter.py       ← Script CLI legacy. Útil como referencia pero no está en producción.
templates/
  index.html      ← Formulario web (frontend). Dark-themed, sin frameworks JS.
requirements.txt  ← flask==3.0.3, gunicorn==22.0.0, python-dotenv==1.0.1
Procfile          ← Comando de inicio para Railway: gunicorn app:app --bind 0.0.0.0:$PORT
```

### Archivos que NO son parte del proyecto
- `templates/RobloxStudioInstaller.exe` — binario accidental, ignorar.
- `check_ids.py`, `temp_fetch.py` — utilidades de debug, no son parte del flujo productivo.

---

## Variables de entorno

| Variable | Requerida | Default | Descripción |
|---|---|---|---|
| `AZURE_DEVOPS_PAT` | **Sí** (producción) | `""` | Personal Access Token de Azure DevOps |
| `AZURE_ORG` | No | `osde-devops` | Nombre de la organización en Azure DevOps |
| `AZURE_PROJECT` | No | `Desarrollo_Salus` | Nombre del proyecto en Azure DevOps |
| `PORT` | No (Railway lo inyecta) | `5000` | Puerto en el que escucha Gunicorn |

Para desarrollo local, crear un archivo `.env` en la raíz (ya está en `.gitignore`):
```
AZURE_DEVOPS_PAT=tu_pat_aqui
```

---

## Cómo correr el proyecto localmente

```bash
# 1. Crear y activar entorno virtual
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Crear .env con el PAT (ver sección Variables de entorno)

# 4. Levantar el servidor
python app.py
# → http://localhost:5000

# Sin PAT (modo demo)
# Navegar a http://localhost:5000/demo  ← funciona sin credenciales
```

---

## Rutas Flask

| Ruta | Método | Descripción |
|---|---|---|
| `/` | GET | Sirve el formulario (`templates/index.html`) |
| `/api/plan-name?id=<id>` | GET | Valida un Test Plan ID y retorna su nombre |
| `/api/workitem-name?id=<id>` | GET | Valida un Work Item ID, retorna título y tipo |
| `/generate` | POST | Genera el informe y lo descarga como archivo `.html` |
| `/demo` | GET | Informe de ejemplo con datos mock (sin Azure PAT) |

---

## Flujo principal: de la UI a la generación del informe

```
1. Usuario carga / → formulario index.html
   - Ingresa metadatos: producto, versión, ciclo, fechas, responsables
   - Ingresa IDs de Azure DevOps:
       · plan_ids[]        → uno o más Test Plan IDs
       · uh_id             → UH del ciclo actual (para incidentes 4.1)
       · prev_uh_id        → UH del ciclo anterior (para secciones 4.2 / 4.3)
       · alcance_uh_id     → UH de alcance (para sección 1 / Especificaciones)
   - Botones "Verificar" llaman a /api/plan-name y /api/workitem-name (AJAX)

2. Usuario envía el formulario → POST /generate

3. Flask llama a generate_report_html(request.form)
   a. Por cada plan_id → build_plan_data(plan_id)
      - get_test_plan() → nombre del plan
      - get_test_suites() → lista de suites
      - get_test_points() por suite → conteos por estado (passed/failed/blocked/notrun)
   b. build_incident_data(uh_id) → bugs del ciclo actual
      - _collect_bugs_from_feature(): recorre Feature→UserStory→Bugs
      - Agrupa por severidad y módulo
   c. build_incident_data(prev_uh_id) → incidentes del ciclo anterior
   d. build_alcance_data(alcance_uh_id) → bugs y tasks del alcance
   e. Arma el HTML inline con helpers:
      - _suite_card()       → tarjeta por suite (sección 3)
      - _incidents_block()  → sección de incidentes con donut charts (sección 4.x)
      - _alcance_block()    → tablas colapsables de alcance (sección 1)
      - _severity_ref()     → tabla de referencia de severidad (sección 6)

4. Retorna Response(html, mimetype="text/html") con header Content-Disposition
   → el navegador descarga informe_<producto>_<version>_ciclo<n>_<fecha>.html

5. El usuario abre el HTML descargado en el navegador y usa el botón
   "Exportar PDF" (window.print()) para generar el PDF final.
```

---

## Jerarquía de Work Items en Azure DevOps

El código asume esta estructura específica en Azure DevOps:

```
UH (User History / Feature de agrupación)
└── Feature
    └── User Story
        └── Bug
```

La función `_collect_bugs_from_feature()` recorre esta jerarquía usando el link type `System.LinkTypes.Hierarchy-Forward`. El nombre del módulo se deduce del título de la User Story, limpiando prefijos tipo `"MVP-2. CT2. "`.

---

## Secciones del informe generado

| Sección | Contenido |
|---|---|
| Header | Producto, versión, ciclo, resultado general, botón PDF |
| Índice | Links de navegación (solo en pantalla, oculto al imprimir) |
| 1 · Especificaciones | Alcance textual + tabla de bugs/tasks de `alcance_uh_id` |
| 2 · Detalle de pruebas | Tabla resumen por suite y plan |
| 3 · Resultados | Tarjetas métricas globales + una `_suite_card` por suite |
| 4.1 · Incidentes del ciclo | Bugs de `uh_id` — donut charts + tabla detalle |
| 4.2 · Bugs corregidos | Bugs cerrados del ciclo anterior (`prev_uh_id`) |
| 4.2.1 · No solucionados | Bugs abiertos del alcance actual |
| 4.3 · Pendientes | Bugs abiertos del ciclo anterior |
| 5 · Riesgos | Texto libre de riesgos y observaciones |
| 6 · Referencia severidad | Tabla estática de referencia |

---

## Convenciones y detalles importantes

### Normalización de severidad
`_norm_sev()` mapea variantes en inglés/español/numérico al label canónico:
- `"1 - critical"`, `"crítico"`, `"critical"` → `"Crítico"`
- `"2 - high"`, `"alto"`, `"high"` → `"Alto"`
- `"3 - medium"`, `"mediano"`, `"medium"` → `"Mediano"`
- `"4 - low"`, `"bajo"`, `"low"` → `"Bajo"`

### HTML generado es autocontenido
- Todos los estilos son inline (no hay CSS externo).
- Chart.js se carga desde CDN (`cdnjs.cloudflare.com`) dentro de cada bloque de incidentes.
- Los informes no requieren servidor para visualizarse.

### Paleta de colores (constantes en app.py)
```python
PRIMARY_COLOR   = "#061E29"  # Navy
SECONDARY_COLOR = "#1D546D"  # Steel Blue
ACCENT_COLOR    = "#5F9598"  # Sage Blue
BG_COLOR        = "#F3F4F4"  # Light Gray
```

### Sin suites vacías
`build_plan_data()` omite suites donde `total == 0` (suites contenedoras sin casos directos).

### Resultado de suite con umbrales
En la tabla de "Detalle de pruebas" (sección 2), el resultado usa umbrales porcentuales:
- `0%` incidencias → "Exitoso"
- `≤10%` → "Exitoso con incidentes menores"
- `≤30%` → "Con incidencias moderadas"
- `>30%` → "Con incidencias críticas"

### `reporter.py` vs `app.py`
`reporter.py` es el script CLI original. Tiene diferencias menores (módulo deducido por `AreaPath` en lugar de título de US, no hay recorrido recursivo Feature→US→Bug). **No modificar ni usar en producción** — existe como referencia histórica.

### Timeout de API
Todas las llamadas a Azure DevOps tienen `timeout=20` segundos. No hay retry ni caché — cada generación de informe hace todas las llamadas en fresco.

---

## Deploy en Railway

- El deploy se dispara automáticamente con cada push a `main`.
- El comando de inicio está en `Procfile`: `gunicorn app:app --bind 0.0.0.0:$PORT`
- Las variables de entorno (`AZURE_DEVOPS_PAT`, etc.) se configuran en el dashboard de Railway.
- No hay workers, colas ni tareas en background — es un servidor web puro.
