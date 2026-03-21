# Salus QA Reporter — App Web

Formulario web que genera el Informe Final de Pruebas conectando con Azure DevOps.
Hosteado en Railway, accesible por URL para todo el equipo.

---

## Archivos del proyecto

```
salus_qa_web/
├── app.py              ← Backend Flask (toda la lógica)
├── templates/
│   └── index.html      ← Formulario web
├── requirements.txt    ← Flask + Gunicorn
├── Procfile            ← Instrucción de inicio para Railway
└── README.md
```

---

## Deploy paso a paso

### Paso 1 — Subir a GitHub

1. Crear un repositorio **privado** en github.com
2. Subir estos archivos:
```bash
git init
git add .
git commit -m "Salus QA Reporter"
git remote add origin https://github.com/tu-usuario/salus-qa-reporter.git
git push -u origin main
```

### Paso 2 — Crear cuenta en Railway

1. Ir a **railway.app**
2. Registrarse con la cuenta de GitHub (el mismo usuario que subió el repo)
3. Plan gratuito alcanza para el uso del equipo

### Paso 3 — Crear el proyecto en Railway

1. Dashboard → **New Project**
2. Elegir **Deploy from GitHub repo**
3. Seleccionar el repositorio `salus-qa-reporter`
4. Railway detecta el `Procfile` automáticamente y arranca el deploy

### Paso 4 — Configurar el PAT (variable de entorno)

1. En Railway → tu proyecto → pestaña **Variables**
2. Agregar estas variables:

| Variable | Valor |
|---|---|
| `AZURE_DEVOPS_PAT` | tu_pat_de_azure_devops |
| `AZURE_ORG` | osde-devops |
| `AZURE_PROJECT` | Desarrollo_Salus |

3. Railway reinicia la app automáticamente

### Paso 5 — Obtener la URL

1. Railway → tu proyecto → pestaña **Settings** → **Domains**
2. Generar dominio público → te da algo como `salus-qa-reporter.up.railway.app`
3. Compartir esa URL con el equipo

---

## Uso diario (para el equipo)

1. Entrar a la URL del equipo
2. Completar el formulario:
   - Producto, versión, ciclo, resultado
   - Fechas y responsables
   - ID del Test Plan (con botón "Verificar" para confirmar el nombre)
   - ID de la UH de incidentes del ciclo actual
   - ID de la UH del ciclo anterior (opcional)
3. Click en **Generar informe**
4. Se descarga el HTML → abrirlo en el browser → **Exportar PDF**

---

## Actualizar el código

Cualquier cambio que se pushee a `main` en GitHub se deploya automáticamente en Railway.

```bash
git add .
git commit -m "descripción del cambio"
git push
```

---

## Troubleshooting

| Problema | Solución |
|---|---|
| La app no arranca | Verificar que el `Procfile` esté en la raíz del repo |
| Error 500 al generar | Verificar que `AZURE_DEVOPS_PAT` esté configurado en Variables de Railway |
| "No se encontró el plan" | Verificar que el ID del plan sea correcto y el PAT tenga permiso de Test Management |
| Bugs no aparecen | Verificar que los bugs sean hijos directos de la UH (link Hierarchy-Forward en Azure DevOps) |
