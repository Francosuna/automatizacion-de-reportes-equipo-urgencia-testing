import sys
import os
from datetime import datetime

# Añadir el directorio actual al path para importar app
sys.path.append(os.getcwd())

from app import generate_report_html

# Mock data extracted from the user's file
alc_data = {
    "uh_id": 91960,
    "uh_title": "MVP-2. Ciclo de testing 2",
    "total": 1,
    "nuevas": [{"id": 91960, "title": "Listados generales. Filtrado de fechas. Búsqueda avanzada utilizando el criterio \"Algún valor\". Cambio de conector", "state": "Active"}],
    "bugs": [],
    "tasks": [],
    "incidents": [] # No hay incidentes de alcance listados en la tabla 1 del original
}

inc_data = {
    "total": 15,
    "incidents": [
        {"id": 77993, "title": "Formulario del caso - No se actualiza la información del socio al modificar Apellido y Nombre", "state": "Closed", "sev": "Crítico", "module": "Formulario del caso"},
        {"id": 77702, "title": "Listas - No se cargan datos después de aplicar filtro de fechas (botonera)", "state": "Closed", "sev": "Crítico", "module": "Listados generales"},
        {"id": 78115, "title": "Formulario del caso - Tratamiento en domicilio/Enfermería - Campos “Medicamento autorizado” y “Otro medicamento” deshabilitados", "state": "Closed", "sev": "Alto", "module": "Formulario del caso"},
        {"id": 78027, "title": "Formulario del caso - Error en árbol del caso y asignación de prestador al ejecutar script de automatización", "state": "Closed", "sev": "Alto", "module": "Formulario del caso"},
        {"id": 78052, "title": "Formulario del caso - Al rechazar un recurso, no se heredan los datos de Centro/Sede", "state": "Closed", "sev": "Alto", "module": "Formulario del caso"},
        {"id": 78116, "title": "Formulario del caso - Tratamiento en domicilio/Kinesiología- Campos “Medico prescriptor” y “Numero de sesiones” deshabilitados", "state": "Closed", "sev": "Alto", "module": "Formulario del caso"},
        {"id": 78005, "title": "Al crear un caso de un servicio cualquiera y asociarlo a un servicio de Seguimiento Operativo muestra otro servicio", "state": "Closed", "sev": "Alto", "module": "Formulario del caso"},
        {"id": 77961, "title": "Formulario del caso - Reclamos - Códigos de resolución incorrectos", "state": "Closed", "sev": "Alto", "module": "Formulario del caso"},
        {"id": 78385, "title": "Error inesperado al acceder a diferentes formularios", "state": "Closed", "sev": "Alto", "module": "Formulario del caso"},
        {"id": 78604, "title": "Formulario del caso - Interconsulta presencial y Virtual - Solicita completar el Centro para finalizar un recurso Anulado", "state": "Closed", "sev": "Mediano", "module": "Formulario del caso"},
        {"id": 77987, "title": "Formulario del caso - Reclamos - Formato de fecha incorrecto", "state": "Closed", "sev": "Mediano", "module": "Formulario del caso"},
        {"id": 78612, "title": "Formulario del caso - Solicita completar un \"Centro\" para finalizar un recurso de interconsulta virtual", "state": "Closed", "sev": "Mediano", "module": "Formulario del caso"},
        {"id": 78816, "title": "Integracion ysocial (generar contacto en SALUS) - Aviso cuando se crea un contacto", "state": "Informacion", "sev": "Bajo", "module": "Integraciones"},
        {"id": 77687, "title": "Login - Detalle", "state": "Closed", "sev": "Bajo", "module": "Lanzadera (página de inicio)"},
        {"id": 78617, "title": "Formulario de información Prestador - El campo Código, Denominación y Tipo permiten ingresar mayor cantidad de caracteres", "state": "Closed", "sev": "Bajo", "module": "Formulario de información del prestador"}
    ]
}

# Re-calculate aggregates for inc_data
from collections import defaultdict
by_sev = defaultdict(list)
by_mod = defaultdict(lambda: defaultdict(int))
for i in inc_data["incidents"]:
    by_sev[i["sev"]].append(i)
    by_mod[i["module"]][i["sev"]] += 1
inc_data["by_sev"] = dict(by_sev)
inc_data["by_module"] = {m: dict(v) for m, v in by_mod.items()}

# Mock prev_data (simplified top 5 for preview)
prev_data = {
    "total": 156,
    "incidents": [{"id": 0, "title": "Bugs corregidos ciclo anterior", "state": "Closed", "sev": "Mediano", "module": "Anterior"}]*156,
    "by_sev": {"Crítico": [1]*20, "Alto": [1]*31, "Mediano": [1]*83, "Bajo": [1]*22},
    "by_module": {
        "Formulario de contacto": {"Crítico": 8, "Alto": 12, "Mediano": 40, "Bajo": 9},
        "Formulario del caso": {"Crítico": 4, "Alto": 10, "Mediano": 29, "Bajo": 6},
    }
}

form = {
    "producto": "SALUS WEB",
    "version": "17.2.1",
    "ciclo": "2",
    "agrupador": "AGRUPADOR URGENCIAS - SALUS",
    "resultado": "Fallido con incidentes",
    "fecha_inicio_plan": "07/11/2025",
    "fecha_fin_plan": "26/11/2025",
    "fecha_inicio_real": "07/11/2025",
    "fecha_fin_real": "26/11/2025",
    "alcance": ["Smoke Test", "Paquete de incidencias", "Pruebas integrales"],
    "responsables": ["No especificado"],
    "riesgos": "N/A",
    "observaciones": "N/A",
    "plan_ids": ["123"]
}

demo_data = {
    "alcance": alc_data,
    "inc": inc_data,
    "prev": prev_data,
    "total_all": 205,
    "pass_all": 183,
    "fail_all": 13,
    "block_all": 0,
    "notrun_all": 9
}

html, err = generate_report_html(form, demo_data=demo_data)

if err:
    print(f"Error: {err}")
else:
    output_path = "f:/automatizacion de reportes equipo urgencia testing/templates/informe_salus_web_17_2_1_ciclo2_V2.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Reporte generado en: {output_path}")
