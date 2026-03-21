import os
from flask import Flask, render_template, request, jsonify, send_file, make_response
from reporter import (
    get_test_plans,
    build_test_plan_data,
    build_incident_data,
    generate_html,
    pct
)
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, template_folder='.')

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/api/plan-name')
def api_plan_name():
    plan_id = request.args.get('id')
    if not plan_id:
        return jsonify({"error": "Missing ID"}), 400
    
    try:
        plans = get_test_plans()
        plan = next((p for p in plans if str(p['id']) == plan_id), None)
        if plan:
            return jsonify({"name": plan['name']})
        return jsonify({"error": "Plan not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/generate', methods=['POST'])
def generate():
    try:
        # Extract form data
        producto = request.form.get('producto', 'SALUS WEB')
        version = request.form.get('version', '')
        ciclo = request.form.get('ciclo', '')
        agrupador = request.form.get('agrupador', 'SALUS')
        resultado = request.form.get('resultado', '')
        
        fecha_inicio_plan = request.form.get('fecha_inicio_plan', '')
        fecha_fin_plan = request.form.get('fecha_fin_plan', '')
        fecha_inicio_real = request.form.get('fecha_inicio_real', '')
        fecha_fin_real = request.form.get('fecha_fin_real', '')
        
        responsables = request.form.getlist('responsables')
        plan_id = request.form.get('plan_id')
        uh_id = request.form.get('uh_id')
        prev_uh_id = request.form.get('prev_uh_id')
        
        alcance = ["Smoke Test", "Paquete de incidencias", "Regresión"] # Default or could be from form
        
        # 1. Fetch Plan Data
        plan_ids = [int(plan_id)] if plan_id and plan_id.isdigit() else []
        plan_data = build_test_plan_data(test_plan_ids=plan_ids)
        
        # 2. Build detalle_pruebas
        detalle_pruebas = []
        for p in plan_data:
            t = p["total"]
            c = p["counts"]
            exitosos = c.get("passed", 0)
            incidencias = c.get("failed", 0) + c.get("blocked", 0)
            if exitosos == t and t > 0:
                res = f"Exitoso ({exitosos} de {t})"
            else:
                res = f"Fallido — Exitosos: {exitosos} ({pct(exitosos,t)}%) / Con incidencia: {incidencias} ({pct(incidencias,t)}%)"
            detalle_pruebas.append({
                "producto": producto,
                "titulo": p["name"],
                "tipo": "Funcional",
                "resultado": res
            })
            
        # 3. Fetch Incident Data
        inc_data = build_incident_data(int(uh_id)) if uh_id and uh_id.isdigit() else {"total": 0}
        prev_uh_data = build_incident_data(int(prev_uh_id)) if prev_uh_id and prev_uh_id.isdigit() else None
        
        # 4. Generate HTML
        meta = {
            "producto": producto, "version": version, "ciclo": ciclo,
            "agrupador": agrupador, "resultado": resultado,
            "fecha_inicio_plan": fecha_inicio_plan, "fecha_fin_plan": fecha_fin_plan,
            "fecha_inicio_real": fecha_inicio_real, "fecha_fin_real": fecha_fin_real,
            "alcance": alcance, "responsables": responsables,
            "detalle_pruebas": detalle_pruebas,
        }
        
        html_report = generate_html(meta, plan_data, inc_data, prev_uh_data)
        
        # Create response as downloadable file
        ver_slug = version.replace(".", "_").replace(" ", "") if version else "vX"
        ts = datetime.now().strftime("%Y-%m-%d")
        filename = f"informe_salus_{ver_slug}_ciclo{ciclo.replace('°','').replace(' ','')}_{ts}.html"
        
        response = make_response(html_report)
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        response.headers["Content-Type"] = "text/html"
        return response

    except Exception as e:
        return f"Error generando el informe: {str(e)}", 500

if __name__ == '__main__':
    # Try to use AZURE_DEVOPS_PAT from env
    if not os.environ.get("AZURE_DEVOPS_PAT"):
        print("WARNING: AZURE_DEVOPS_PAT not set in environment or .env file.")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
