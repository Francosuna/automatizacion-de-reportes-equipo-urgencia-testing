"""
Salus QA Reporter — Web App (Flask) v3
Cada suite del Test Plan se muestra como sección independiente,
replicando el formato real del equipo.
"""

import os, json, base64, urllib.request, urllib.error
from datetime import datetime
from collections import defaultdict
from flask import Flask, render_template, request, Response, jsonify

app = Flask(__name__)

ORGANIZATION = os.environ.get("AZURE_ORG",     "osde-devops")
PROJECT      = os.environ.get("AZURE_PROJECT", "Desarrollo_Salus")
PAT          = os.environ.get("AZURE_DEVOPS_PAT", "")
BASE_URL     = f"https://dev.azure.com/{ORGANIZATION}/{PROJECT}/_apis"

def _headers():
    token = base64.b64encode(f":{PAT}".encode()).decode()
    return {"Content-Type": "application/json", "Authorization": f"Basic {token}"}

def _get(url):
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": e.code}
    except Exception as e:
        return {"_error": str(e)}

# ── Azure DevOps ───────────────────────────────────────────────
def get_test_plan(plan_id):
    return _get(f"{BASE_URL}/testplan/plans/{plan_id}?api-version=7.0")

def get_test_suites(plan_id):
    d = _get(f"{BASE_URL}/testplan/Plans/{plan_id}/suites?api-version=7.0")
    return d.get("value", [])

def get_test_points(plan_id, suite_id):
    d = _get(f"{BASE_URL}/testplan/Plans/{plan_id}/Suites/{suite_id}/TestPoint?api-version=7.0")
    return d.get("value", [])

def get_work_item(wi_id):
    return _get(f"{BASE_URL}/wit/workitems/{wi_id}?$expand=relations&api-version=7.0")

def get_work_item_children(wi_id):
    wi = get_work_item(wi_id)
    if not wi or "_error" in wi:
        return []
    child_ids = [
        r["url"].split("/")[-1]
        for r in wi.get("relations", [])
        if r.get("rel") == "System.LinkTypes.Hierarchy-Forward"
    ]
    if not child_ids:
        return []
    ids_str = ",".join(child_ids)
    d = _get(f"{BASE_URL}/wit/workitems?ids={ids_str}&$expand=fields&api-version=7.0")
    return d.get("value", [])

# ── Helpers ────────────────────────────────────────────────────
SEVERITY_LABELS = {
    "crítico":"Crítico","critical":"Crítico","1 - critical":"Crítico",
    "alto":"Alto","high":"Alto","2 - high":"Alto",
    "mediano":"Mediano","medium":"Mediano","3 - medium":"Mediano",
    "bajo":"Bajo","low":"Bajo","4 - low":"Bajo",
}
SEVERITY_STYLE = {
    "Crítico":{"bg":"#FCEBEB","color":"#791F1F"},
    "Alto":   {"bg":"#FAEEDA","color":"#633806"},
    "Mediano":{"bg":"#E6F1FB","color":"#185FA5"},
    "Bajo":   {"bg":"#EAF3DE","color":"#3B6D11"},
}
STATUS_COLORS = {
    "passed":"#639922","failed":"#E24B4A",
    "blocked":"#BA7517","notrun":"#D3D1C7","active":"#378ADD",
}

def _norm_sev(raw):
    if not raw: return "Bajo"
    return SEVERITY_LABELS.get(str(raw).lower().strip(), str(raw).title())

def _norm_status(raw):
    return (raw or "notrun").lower().replace(" ","")

def _sev_order(sev):
    return {"Crítico":0,"Alto":1,"Mediano":2,"Bajo":3}.get(sev, 4)

def pct(n, total):
    return round(n/total*100, 1) if total else 0.0

def _pill(label, count, style):
    if not count: return ""
    return (f'<span style="font-size:11px;font-weight:500;padding:2px 8px;border-radius:20px;'
            f'{style}white-space:nowrap;">{label} <b>{count}</b></span> ')

def _sev_pill(sev, count=None):
    st = SEVERITY_STYLE.get(sev, {"bg":"#F1EFE8","color":"#5F5E5A"})
    txt = f"{sev}{f' <b>{count}</b>' if count else ''}"
    return (f'<span style="font-size:11px;font-weight:500;padding:2px 8px;border-radius:20px;'
            f'background:{st["bg"]};color:{st["color"]};white-space:nowrap;">{txt}</span> ')

def _bar(counts, total):
    if not total:
        return '<div style="height:7px;background:#E8E7E1;border-radius:4px;"></div>'
    order = ["passed","failed","blocked","active","inprogress","notrun"]
    segs  = "".join(
        f'<div style="width:{pct(counts.get(s,0),total)}%;background:{STATUS_COLORS.get(s,"#ccc")};'
        f'height:100%;border-radius:2px;" title="{s}: {counts.get(s,0)}"></div>'
        for s in order if counts.get(s,0)
    )
    return f'<div style="display:flex;gap:2px;height:7px;border-radius:4px;overflow:hidden;">{segs}</div>'

# ── Data builders ──────────────────────────────────────────────
def build_plan_data(plan_id):
    plan_info = get_test_plan(plan_id)
    if "_error" in plan_info:
        return None, f"Error {plan_info['_error']} al acceder al plan {plan_id}"

    plan_name   = plan_info.get("name", f"Plan {plan_id}")
    suites_data = []

    for suite in get_test_suites(plan_id):
        if suite.get("suiteType") == "root":
            continue
        sid, sname = suite["id"], suite["name"]
        points = get_test_points(plan_id, sid)
        counts = defaultdict(int)
        for pt in points:
            counts[_norm_status(pt.get("results",{}).get("outcome","notRun"))] += 1
        total = len(points)

        # Saltear suites contenedoras que no tienen casos directos
        if total == 0:
            continue

        fail  = counts.get("failed",0)
        block = counts.get("blocked",0)
        passed = counts.get("passed",0)

        if fail == 0 and block == 0:
            result_label = "Exitoso"
            result_style = "background:#EAF3DE;color:#3B6D11;"
        else:
            result_label = "Fallido con incidentes"
            result_style = "background:#FCEBEB;color:#791F1F;"

        suites_data.append({
            "id": sid, "name": sname, "total": total,
            "counts": dict(counts),
            "result_label": result_label, "result_style": result_style,
        })

    plan_counts = defaultdict(int)
    plan_total  = sum(s["total"] for s in suites_data)
    for s in suites_data:
        for k, v in s["counts"].items():
            plan_counts[k] += v

    fail  = plan_counts.get("failed",0)
    block = plan_counts.get("blocked",0)
    result_label = "Exitoso" if fail == 0 and block == 0 else "Fallido con incidentes"
    result_style = "background:#EAF3DE;color:#3B6D11;" if fail == 0 and block == 0 else "background:#FCEBEB;color:#791F1F;"

    return {
        "id": plan_id, "name": plan_name,
        "total": plan_total, "counts": dict(plan_counts),
        "suites": suites_data,
        "result_label": result_label, "result_style": result_style,
    }, None

def _collect_bugs_from_feature(feature_id):
    """
    Estructura: Feature → User Stories → Bugs
    Recorre las User Stories hijas de la Feature y trae sus bugs,
    usando el nombre de la User Story como módulo.
    """
    result = []  # lista de (bug_workitem, module_name)

    us_children = get_work_item_children(feature_id)
    for us in us_children:
        wi_type = us.get("fields",{}).get("System.WorkItemType","")
        us_title = us.get("fields",{}).get("System.Title","Sin módulo")

        if wi_type == "Bug":
            # Bug directo bajo la Feature
            result.append((us, us_title))
        elif wi_type in ("User Story","Feature","Task","Epic"):
            # Bajar a buscar bugs dentro de la User Story
            bug_children = get_work_item_children(us["id"])
            for child in bug_children:
                if child.get("fields",{}).get("System.WorkItemType","") == "Bug":
                    # Módulo = nombre de la User Story madre, limpiando prefijo "MVP-X. CTX. "
                    raw_name = us_title
                    # Quitar prefijos tipo "MVP-2. CT2. " para quedarse con la funcionalidad
                    parts = raw_name.split(". ")
                    module = ". ".join(parts[2:]) if len(parts) > 2 else raw_name
                    result.append((child, module))

    return result

def build_incident_data(uh_id):
    if not uh_id:
        return {"total":0,"uh_title":"","incidents":[],"by_sev":{},"by_module":{}}
    uh = get_work_item(uh_id)
    if "_error" in uh:
        return {"total":0,"uh_title":f"Error UH {uh_id}","incidents":[],"by_sev":{},"by_module":{}}

    uh_title = uh.get("fields",{}).get("System.Title", f"UH #{uh_id}")

    # Feature → User Stories → Bugs, módulo = nombre de la User Story
    bug_pairs = _collect_bugs_from_feature(uh_id)

    incidents = []
    for bug, module in bug_pairs:
        f     = bug.get("fields",{})
        sev   = _norm_sev(f.get("Microsoft.VSTS.Common.Severity") or f.get("Microsoft.VSTS.Common.Priority"))
        title = f.get("System.Title","Sin título")
        state = f.get("System.State","")
        incidents.append({"id":bug["id"],"title":title,"state":state,"sev":sev,"module":module})

    by_sev    = defaultdict(list)
    by_module = defaultdict(lambda: defaultdict(int))
    for inc in incidents:
        by_sev[inc["sev"]].append(inc)
        by_module[inc["module"]][inc["sev"]] += 1

    return {
        "uh_id": uh_id, "uh_title": uh_title, "total": len(incidents),
        "incidents": sorted(incidents, key=lambda x: _sev_order(x["sev"])),
        "by_sev": dict(by_sev),
        "by_module": {m:dict(v) for m,v in by_module.items()},
    }

# ── HTML blocks ────────────────────────────────────────────────
def _suite_card(suite, prod):
    """Cada suite se muestra como una tarjeta independiente al estilo del reporte del equipo."""
    t = suite["total"]
    c = suite["counts"]
    passed  = c.get("passed",0)
    failed  = c.get("failed",0)
    blocked = c.get("blocked",0)
    notrun  = t - passed - failed - blocked

    ep = pct(passed, t)
    ip = pct(failed+blocked, t)

    # Detectar "No Aplica" (casos que quedaron sin ejecutar intencionalmente)
    noapl_note = ""
    if notrun > 0 and failed == 0 and blocked == 0:
        noapl_note = f'<span style="font-size:12px;color:#888;margin-left:8px;">Casos No Aplica: {notrun} ({pct(notrun,t)}%)</span>'

    return f"""
    <section style="margin-bottom:20px;background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;">
      <div style="padding:13px 20px;display:flex;align-items:center;justify-content:space-between;
                  border-bottom:1px solid #EDECEA;background:#FAFAF8;flex-wrap:wrap;gap:8px;">
        <div>
          <div style="font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.06em;">{prod}</div>
          <div style="font-size:15px;font-weight:600;color:#1a1a18;margin-top:2px;">{suite['name']}</div>
        </div>
        <span style="font-size:11px;font-weight:500;padding:2px 10px;border-radius:20px;{suite['result_style']}">{suite['result_label']}</span>
      </div>
      <div style="padding:14px 20px;">
        <div style="font-size:13px;color:#3d3d3a;margin-bottom:10px;">
          <b>Total, Casos de Prueba: {t}</b>
        </div>
        <div style="font-size:13px;color:#3d3d3a;margin-bottom:4px;">
          Casos exitosos: <b>{passed} ({ep}%)</b>
        </div>
        <div style="font-size:13px;color:#3d3d3a;margin-bottom:10px;">
          Casos con incidencia: <b>{failed+blocked} ({ip}%)</b>{noapl_note}
        </div>
        {_bar(c, t)}
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">
          {_pill("Passed",  passed,  "background:#EAF3DE;color:#3B6D11;")}
          {_pill("Failed",  failed,  "background:#FCEBEB;color:#791F1F;")}
          {_pill("Blocked", blocked, "background:#FAEEDA;color:#633806;")}
          {_pill("Not Run", notrun,  "background:#F1EFE8;color:#5F5E5A;") if notrun else ""}
        </div>
      </div>
    </section>"""

def _incidents_block(inc_data, section_num="4.1", title="Incidentes detectados durante las pruebas del ciclo", bug_label="Detalle de bugs"):
    if not inc_data or inc_data["total"] == 0:
        return f"""<section style="margin-bottom:20px;background:#fff;border-radius:12px;
                   border:1px solid #EDECEA;padding:16px 20px;">
                   <p style="color:#888;font-size:13px;">No se encontraron incidentes.</p></section>"""

    total  = inc_data["total"]
    by_sev = inc_data["by_sev"]

    sev_pills = "".join(_sev_pill(s, len(by_sev.get(s,[]))) for s in ["Crítico","Alto","Mediano","Bajo"] if by_sev.get(s))
    sev_pcts  = "  ·  ".join(
        f'<b>{s}s: {round(len(by_sev.get(s,[]))/total*100)}%</b>'
        for s in ["Crítico","Alto","Mediano","Bajo"] if by_sev.get(s)
    )

    # Donut charts
    sev_colors = {"Crítico":"#E24B4A","Alto":"#BA7517","Mediano":"#378ADD","Bajo":"#639922"}
    chart_id   = f"c{abs(hash(section_num+str(total)))%99999}"
    sev_labels = [s for s in ["Crítico","Alto","Mediano","Bajo"] if by_sev.get(s)]
    sev_vals   = [len(by_sev[s]) for s in sev_labels]
    sev_cols   = [sev_colors[s] for s in sev_labels]
    mod_labels = list(inc_data["by_module"].keys())[:6]
    mod_vals   = [sum(inc_data["by_module"][m].values()) for m in mod_labels]
    mod_cols   = ["#7F77DD","#1D9E75","#D85A30","#378ADD","#BA7517","#E24B4A"]

    mod_rows = "".join(
        f'<tr style="border-top:1px solid #EDECEA;">'
        f'<td style="padding:8px 16px;font-size:13px;color:#3d3d3a;">{mod}</td>'
        f'<td style="padding:8px 8px;text-align:center;font-size:13px;color:#888;">{sum(sv.values())}</td>'
        f'<td style="padding:8px 14px;">{"".join(_sev_pill(s,sv.get(s,0)) for s in ["Crítico","Alto","Mediano","Bajo"] if sv.get(s,0))}</td>'
        f'</tr>'
        for mod, sv in sorted(inc_data["by_module"].items())
    )

    bug_rows = "".join(
        f'<tr style="border-top:1px solid #EDECEA;">'
        f'<td style="padding:8px 14px;font-size:12px;color:#888;">#{inc["id"]}</td>'
        f'<td style="padding:8px 14px;font-size:13px;color:#3d3d3a;">{inc["title"]}</td>'
        f'<td style="padding:8px 8px;text-align:center;">{_sev_pill(inc["sev"])}</td>'
        f'<td style="padding:8px 8px;text-align:center;">'
        f'<span style="font-size:11px;font-weight:500;padding:2px 8px;border-radius:20px;'
        f'{"background:#EAF3DE;color:#3B6D11;" if inc["state"].lower() in ("closed","resolved","done","cerrado","resuelto") else "background:#F1EFE8;color:#5F5E5A;"}">'
        f'{inc["state"]}</span></td>'
        f'</tr>'
        for inc in inc_data["incidents"]
    )

    return f"""
    <section style="margin-bottom:20px;background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;">
      <div style="padding:14px 20px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
        <div style="font-size:11px;font-weight:600;color:#2B35C1;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;">{section_num}</div>
        <div style="font-size:14px;font-weight:600;color:#1a1a18;margin-bottom:3px;">{title}</div>
        <div style="font-size:12px;color:#888;">{inc_data.get('uh_title','')} · {total} incidentes en total</div>
      </div>
      <div style="padding:10px 20px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:5px;">
          {sev_pills}
        </div>
        <div style="font-size:12px;color:#888;">Porcentaje por criticidad — {sev_pcts}</div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px 20px;border-bottom:1px solid #EDECEA;">
        <div style="text-align:center;">
          <div style="font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;">Porcentaje por criticidad</div>
          <canvas id="{chart_id}_s" width="180" height="180" style="max-width:160px;margin:0 auto;display:block;"></canvas>
        </div>
        <div style="text-align:center;">
          <div style="font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;">Porcentaje por módulo / funcionalidad</div>
          <canvas id="{chart_id}_m" width="180" height="180" style="max-width:160px;margin:0 auto;display:block;"></canvas>
        </div>
      </div>
      <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
      <script>
      (function(){{
        new Chart(document.getElementById('{chart_id}_s'),{{type:'doughnut',data:{{labels:{sev_labels},datasets:[{{data:{sev_vals},backgroundColor:{sev_cols},borderWidth:2,borderColor:'#fff'}}]}},options:{{plugins:{{legend:{{position:'bottom',labels:{{font:{{size:11}},padding:6}}}}}},cutout:'65%',animation:false}}}});
        new Chart(document.getElementById('{chart_id}_m'),{{type:'doughnut',data:{{labels:{mod_labels},datasets:[{{data:{mod_vals},backgroundColor:{mod_cols},borderWidth:2,borderColor:'#fff'}}]}},options:{{plugins:{{legend:{{position:'bottom',labels:{{font:{{size:11}},padding:6}}}}}},cutout:'65%',animation:false}}}});
      }})();
      </script>
      <div style="padding:12px 20px 4px;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.05em;">Porcentaje de incidencias detectadas por módulo / funcionalidad</div>
      <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
        <thead><tr style="background:#F5F4F0;">
          <th style="padding:7px 16px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Módulo</th>
          <th style="padding:7px 8px;text-align:center;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Total</th>
          <th style="padding:7px 14px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Desglose</th>
        </tr></thead>
        <tbody>{mod_rows}</tbody>
      </table>
      <div style="padding:12px 20px 4px;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.05em;">{bug_label}</div>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#F5F4F0;">
          <th style="padding:7px 14px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">#</th>
          <th style="padding:7px 14px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Título</th>
          <th style="padding:7px 8px;text-align:center;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Severidad</th>
          <th style="padding:7px 8px;text-align:center;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Estado</th>
        </tr></thead>
        <tbody>{bug_rows}</tbody>
      </table>
    </section>"""

def _severity_ref():
    data = [
        ("Bajo",    "Mínimo. No afecta funcionalidad principal.", "Errores tipográficos, detalles visuales.", "Puede esperar."),
        ("Mediano", "Afecta funcionalidades secundarias.",        "Botón no funcional con alternativa.",      "Planificar para próximos sprints."),
        ("Alto",    "Afecta funcionalidades clave.",              "Fallos en formularios críticos.",          "Requiere atención en la próxima versión."),
        ("Crítico", "Bloquea el sistema o pérdida de datos.",     "Caída del sistema, fuga de datos.",        "Urgencia máxima. Hotfix inmediato."),
    ]
    rows = "".join(
        f'<tr style="border-top:1px solid #EDECEA;">'
        f'<td style="padding:8px 16px;">{_sev_pill(s)}</td>'
        f'<td style="padding:8px 14px;font-size:13px;color:#3d3d3a;">{imp}</td>'
        f'<td style="padding:8px 14px;font-size:13px;color:#888;">{ex}</td>'
        f'<td style="padding:8px 14px;font-size:13px;color:#3d3d3a;">{act}</td>'
        f'</tr>'
        for s,imp,ex,act in data
    )
    return f"""<section style="margin-bottom:20px;background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;">
      <div style="padding:13px 20px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
        <div style="font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.06em;">Referencia de severidad y prioridad de errores</div>
      </div>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#F5F4F0;">
          <th style="padding:7px 16px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Severidad</th>
          <th style="padding:7px 14px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Impacto</th>
          <th style="padding:7px 14px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Ejemplos</th>
          <th style="padding:7px 14px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Urgencia / Acción</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>"""

# ── Report generator ───────────────────────────────────────────
def generate_report_html(form):
    now     = datetime.now().strftime("%d/%m/%Y %H:%M")
    prod    = form.get("producto","SALUS WEB")
    version = form.get("version","")
    ciclo   = form.get("ciclo","")
    agrup   = form.get("agrupador","SALUS")
    result  = form.get("resultado","")
    fi_plan = form.get("fecha_inicio_plan","")
    ff_plan = form.get("fecha_fin_plan","")
    fi_real = form.get("fecha_inicio_real","")
    ff_real = form.get("fecha_fin_real","")
    alcance      = [a.strip() for a in form.getlist("alcance") if a.strip()]
    resps        = [r.strip() for r in form.getlist("responsables") if r.strip()]
    riesgos      = form.get("riesgos","").strip() or "N/A"
    observaciones= form.get("observaciones","").strip() or "N/A"

    # Múltiples Test Plans
    plan_ids_raw = [p.strip() for p in form.getlist("plan_ids") if p.strip().isdigit()]
    if not plan_ids_raw:
        return None, "No se ingresaron IDs de Test Plans válidos."

    plans_data = []
    for pid_str in plan_ids_raw:
        pd, err = build_plan_data(int(pid_str))
        if err:
            return None, err
        plans_data.append(pd)

    uh_id   = int(form.get("uh_id", 0)) if form.get("uh_id","").strip().isdigit() else None
    prev_id = int(form.get("prev_uh_id", 0)) if form.get("prev_uh_id","").strip().isdigit() else None

    inc_data  = build_incident_data(uh_id)
    prev_data = build_incident_data(prev_id) if prev_id else None

    # Totales globales sumando todos los planes
    from collections import defaultdict as _dd
    global_counts = _dd(int)
    for pd in plans_data:
        for k, v in pd["counts"].items():
            global_counts[k] += v
    total_all  = sum(pd["total"] for pd in plans_data)
    pass_all   = global_counts.get("passed",0)
    fail_all   = global_counts.get("failed",0)
    block_all  = global_counts.get("blocked",0)
    notrun_all = total_all - pass_all - fail_all - block_all

    result_color = "#791F1F" if result and "fallido" in result.lower() else "#3B6D11"
    resp_li = "".join(f'<li style="font-size:13px;color:#3d3d3a;padding:2px 0;">{r}</li>' for r in resps) or '<li style="font-size:13px;color:#888;">—</li>'
    alc_li  = "".join(f'<li style="font-size:13px;color:#3d3d3a;padding:2px 0;">{a}</li>' for a in alcance) or '<li style="font-size:13px;color:#888;">—</li>'

    # Sección 2 — Detalle de pruebas (una fila por suite de cada plan)
    det_rows = ""
    for pd in plans_data:
        for s in pd["suites"]:
            t = s["total"]; c_s = s["counts"]
            ep = pct(c_s.get("passed",0), t)
            ip = pct(c_s.get("failed",0)+c_s.get("blocked",0), t)
            res_txt = f"Exitoso ({c_s.get('passed',0)} de {t})" if c_s.get("failed",0)+c_s.get("blocked",0) == 0 else f"Fallido — Exitosos: {c_s.get('passed',0)} ({ep}%) / Con incidencia: {c_s.get('failed',0)+c_s.get('blocked',0)} ({ip}%)"
            det_rows += (f'<tr style="border-top:1px solid #EDECEA;">'
                         f'<td style="padding:8px 20px;font-size:13px;color:#888;">{prod} / {pd["name"]}</td>'
                         f'<td style="padding:8px 14px;font-size:13px;color:#3d3d3a;">{s["name"]}</td>'
                         f'<td style="padding:8px 14px;font-size:13px;color:#888;">Funcional</td>'
                         f'<td style="padding:8px 14px;font-size:13px;color:#3d3d3a;">{res_txt}</td>'
                         f'</tr>')

    # Sección 3 — Suites agrupadas por plan
    suite_cards = ""
    for pd in plans_data:
        suite_cards += f'''<div style="margin-top:16px;margin-bottom:8px;">
          <div style="font-size:10px;font-weight:500;color:#888;text-transform:uppercase;
            letter-spacing:.07em;padding:8px 0 6px;border-bottom:1px solid #EDECEA;margin-bottom:10px;">
            Test plan · {pd["name"]}
          </div></div>'''
        suite_cards += "".join(_suite_card(s, prod) for s in pd["suites"])

    # Sección 4.1 — Incidentes del ciclo actual
    inc_section = _incidents_block(
        inc_data,
        section_num="4.1",
        title=f"Incidentes detectados durante las pruebas del ciclo {ciclo} — Versión {version} de SALUS Web",
        bug_label="Detalle de bugs detectados"
    )

    # Sección 4.2 / 4.3 — Ciclo anterior: corregidos y pendientes
    prev_sections = ""
    if prev_data and prev_data["total"] > 0:
        resueltos  = [i for i in prev_data["incidents"] if i["state"].lower() in ("closed","resolved","done","cerrado","resuelto")]
        pendientes = [i for i in prev_data["incidents"] if i["state"].lower() not in ("closed","resolved","done","cerrado","resuelto")]

        if resueltos:
            prev_res = dict(prev_data)
            prev_res["incidents"] = resueltos
            prev_res["total"] = len(resueltos)
            by_sev_r = defaultdict(list)
            by_mod_r = defaultdict(lambda: defaultdict(int))
            for i in resueltos:
                by_sev_r[i["sev"]].append(i)
                by_mod_r[i["module"]][i["sev"]] += 1
            prev_res["by_sev"] = dict(by_sev_r)
            prev_res["by_module"] = {m:dict(v) for m,v in by_mod_r.items()}
            prev_sections += _incidents_block(
                prev_res,
                section_num="4.2",
                title=f"Paquete de incidentes corregidas — Versión anterior (Ciclo {ciclo} MVP 2) de SALUS Web",
                bug_label="Detalle de bugs corregidos"
            )

        if pendientes:
            prev_pend = dict(prev_data)
            prev_pend["incidents"] = pendientes
            prev_pend["total"] = len(pendientes)
            by_sev_p = defaultdict(list)
            by_mod_p = defaultdict(lambda: defaultdict(int))
            for i in pendientes:
                by_sev_p[i["sev"]].append(i)
                by_mod_p[i["module"]][i["sev"]] += 1
            prev_pend["by_sev"] = dict(by_sev_p)
            prev_pend["by_module"] = {m:dict(v) for m,v in by_mod_p.items()}
            prev_sections += _incidents_block(
                prev_pend,
                section_num="4.3",
                title=f"Incidencias pendientes de corrección de la Versión anterior (Ciclo {ciclo} MVP 2) de SALUS Web",
                bug_label="Detalle de bugs pendientes"
            )

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Informe Final — {prod} {version}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:'DM Sans',sans-serif;background:#F5F4F0;color:#1a1a18;padding:32px 24px;}}
    h2{{font-size:13px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.07em;margin:0 0 12px;}}
    @media print{{body{{background:#fff;padding:0;}}.no-print{{display:none;}}}}
  </style>
</head>
<body>
<div style="max-width:960px;margin:0 auto;">

  <!-- Header -->
  <div style="background:#fff;border-radius:12px;border:1px solid #EDECEA;padding:22px 24px;margin-bottom:16px;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;">
      <div>
        <div style="font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.1em;margin-bottom:5px;">{agrup}</div>
        <h1 style="font-size:24px;font-weight:600;color:#1a1a18;">Informe Final de Pruebas</h1>
        <div style="font-size:14px;color:#888;margin-top:3px;">{prod} · Ciclo {ciclo} · {version}</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;">
        <span style="font-size:12px;font-weight:500;padding:5px 14px;border-radius:8px;
          background:{result_color}1A;color:{result_color};border:1px solid {result_color}33;">{result or "—"}</span>
        <button class="no-print" onclick="window.print()" style="padding:5px 14px;border-radius:8px;
          border:1px solid #EDECEA;background:#fff;font-family:inherit;font-size:12px;cursor:pointer;">Exportar PDF</button>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:18px;padding-top:18px;border-top:1px solid #EDECEA;">
      <div>
        <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Producto</div>
        <div style="font-size:13px;font-weight:500;">{prod}</div>
        <div style="font-size:12px;color:#888;margin-top:2px;">Versión {version}</div>
      </div>
      <div>
        <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Plan de ejecución</div>
        <div style="font-size:12px;color:#3d3d3a;">
          <span style="color:#888;">Planificado:</span> {fi_plan} → {ff_plan}<br>
          <span style="color:#888;">Real:</span> {fi_real} → {ff_real}
        </div>
      </div>
      <div>
        <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px;">Responsables de ejecución</div>
        <ul style="list-style:none;padding:0;">{resp_li}</ul>
      </div>
    </div>
  </div>

  <!-- 1. Especificaciones -->
  <div style="background:#fff;border-radius:12px;border:1px solid #EDECEA;padding:16px 20px;margin-bottom:16px;">
    <h2>1 · Especificaciones</h2>
    <div style="font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Alcance {version}</div>
    <ul style="padding-left:18px;">{alc_li}</ul>
  </div>

  <!-- 2. Detalle de pruebas -->
  <div style="background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;margin-bottom:16px;">
    <div style="padding:13px 20px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
      <h2 style="margin:0;">2 · Detalle de pruebas</h2>
    </div>
    <table style="width:100%;border-collapse:collapse;">
      <thead><tr style="background:#F5F4F0;">
        <th style="padding:7px 20px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Producto</th>
        <th style="padding:7px 14px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Título / Descripción</th>
        <th style="padding:7px 14px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Tipo de prueba</th>
        <th style="padding:7px 14px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Resultado</th>
      </tr></thead>
      <tbody>{det_rows}</tbody>
    </table>
  </div>

  <!-- 3. Resultados -->
  <div style="margin-bottom:12px;"><h2>3 · Resultados de las pruebas</h2></div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px;">
    <div style="background:#EAF3DE;border-radius:10px;padding:13px 16px;">
      <div style="font-size:10px;font-weight:500;color:#3B6D11;text-transform:uppercase;letter-spacing:.05em;">Passed</div>
      <div style="font-size:26px;font-weight:600;color:#27500A;margin:3px 0 2px;">{pass_all}</div>
      <div style="font-size:11px;color:#3B6D11;">{pct(pass_all,total_all)}% del total</div>
    </div>
    <div style="background:#FCEBEB;border-radius:10px;padding:13px 16px;">
      <div style="font-size:10px;font-weight:500;color:#A32D2D;text-transform:uppercase;letter-spacing:.05em;">Failed</div>
      <div style="font-size:26px;font-weight:600;color:#501313;margin:3px 0 2px;">{fail_all}</div>
      <div style="font-size:11px;color:#A32D2D;">{pct(fail_all,total_all)}% del total</div>
    </div>
    <div style="background:#FAEEDA;border-radius:10px;padding:13px 16px;">
      <div style="font-size:10px;font-weight:500;color:#854F0B;text-transform:uppercase;letter-spacing:.05em;">Blocked</div>
      <div style="font-size:26px;font-weight:600;color:#412402;margin:3px 0 2px;">{block_all}</div>
      <div style="font-size:11px;color:#854F0B;">{pct(block_all,total_all)}% del total</div>
    </div>
    <div style="background:#F1EFE8;border-radius:10px;padding:13px 16px;">
      <div style="font-size:10px;font-weight:500;color:#5F5E5A;text-transform:uppercase;letter-spacing:.05em;">Not Run</div>
      <div style="font-size:26px;font-weight:600;color:#2C2C2A;margin:3px 0 2px;">{notrun_all}</div>
      <div style="font-size:11px;color:#5F5E5A;">{pct(notrun_all,total_all)}% del total</div>
    </div>
  </div>
  {suite_cards}

  <!-- 4. Incidentes -->
  <div style="background:#fff;border-radius:12px;border:1px solid #EDECEA;padding:14px 20px;margin-bottom:12px;">
    <h2 style="margin:0;">4 · Detalle de incidentes</h2>
    <div style="font-size:13px;color:#888;margin-top:6px;">Durante las pruebas se detectaron los siguientes incidentes, agrupados según su nivel de criticidad.</div>
  </div>
  {inc_section}
  {prev_sections}

  <!-- 5. Riesgos -->
  <div style="background:#fff;border-radius:12px;border:1px solid #EDECEA;padding:16px 20px;margin-bottom:16px;">
    <h2>5 · Detalle de riesgos detectados</h2>
    <div style="font-size:13px;color:#3d3d3a;">{riesgos}</div>
    <div style="margin-top:12px;">
      <div style="font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Observaciones</div>
      <div style="font-size:13px;color:#3d3d3a;">{observaciones}</div>
    </div>
  </div>

  <!-- 6. Referencia de severidad -->
  <div style="margin-bottom:12px;"><h2>6 · Referencia de severidad y prioridad de errores</h2></div>
  {_severity_ref()}

  <div style="text-align:center;padding:16px 0;font-size:11px;color:#aaa;">
    Salus QA Reporter · {now} · {ORGANIZATION} / {PROJECT}
  </div>
</div>
</body></html>"""
    return html, None

# ── Routes ─────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/plan-name")
def plan_name():
    plan_id = request.args.get("id","")
    if not plan_id.isdigit():
        return jsonify({"error": "ID inválido"}), 400
    info = get_test_plan(int(plan_id))
    if "_error" in info:
        return jsonify({"error": f"No se encontró el plan {plan_id}"}), 404
    return jsonify({"name": info.get("name","")})

@app.route("/generate", methods=["POST"])
def generate():
    if not PAT:
        return "Error: AZURE_DEVOPS_PAT no configurado.", 500
    html, err = generate_report_html(request.form)
    if err:
        return f"Error al generar el informe: {err}", 500
    prod    = request.form.get("producto","salus").replace(" ","_").lower()
    version = request.form.get("version","vX").replace(".","_")
    ciclo   = request.form.get("ciclo","").replace("°","").replace(" ","")
    ts      = datetime.now().strftime("%Y-%m-%d")
    filename = f"informe_{prod}_{version}_ciclo{ciclo}_{ts}.html"
    return Response(html, mimetype="text/html",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
