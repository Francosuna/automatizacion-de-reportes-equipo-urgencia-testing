"""
Salus QA Reporter — Web App (Flask)
Deploy en Railway: conecta con Azure DevOps y genera el informe HTML.
"""

import os, json, base64, urllib.request, urllib.error
from datetime import datetime
from collections import defaultdict
from flask import Flask, render_template, request, Response, jsonify

app = Flask(__name__)

# ── Config (viene de variables de entorno en Railway) ──────────
ORGANIZATION = os.environ.get("AZURE_ORG",     "osde-devops")
PROJECT      = os.environ.get("AZURE_PROJECT", "Desarrollo_Salus")
PAT          = os.environ.get("AZURE_DEVOPS_PAT", "")

BASE_URL = f"https://dev.azure.com/{ORGANIZATION}/{PROJECT}/_apis"

def _headers():
    token = base64.b64encode(f":{PAT}".encode()).decode()
    return {"Content-Type": "application/json", "Authorization": f"Basic {token}"}

# ── HTTP helper ────────────────────────────────────────────────
def _get(url):
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": e.code}
    except Exception as e:
        return {"_error": str(e)}

# ── Azure DevOps helpers ───────────────────────────────────────
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

# ── Data builders ──────────────────────────────────────────────
SEVERITY_LABELS = {
    "crítico":"Crítico","critical":"Crítico","1 - critical":"Crítico",
    "alto":"Alto","high":"Alto","2 - high":"Alto",
    "mediano":"Mediano","medium":"Mediano","3 - medium":"Mediano",
    "bajo":"Bajo","low":"Bajo","4 - low":"Bajo",
}
SEVERITY_STYLE = {
    "Crítico": {"bg":"#FCEBEB","color":"#791F1F"},
    "Alto":    {"bg":"#FAEEDA","color":"#633806"},
    "Mediano": {"bg":"#E6F1FB","color":"#185FA5"},
    "Bajo":    {"bg":"#EAF3DE","color":"#3B6D11"},
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

def build_plan_data(plan_id):
    plan_info = get_test_plan(plan_id)
    if "_error" in plan_info:
        return None, f"Error {plan_info['_error']} al acceder al plan {plan_id}"

    plan_name = plan_info.get("name", f"Plan {plan_id}")
    suites_data = []
    for suite in get_test_suites(plan_id):
        if suite.get("suiteType") == "root":
            continue
        sid   = suite["id"]
        sname = suite["name"]
        points = get_test_points(plan_id, sid)
        counts = defaultdict(int)
        for pt in points:
            counts[_norm_status(pt.get("results",{}).get("outcome","notRun"))] += 1
        suites_data.append({"id":sid,"name":sname,"total":len(points),"counts":dict(counts)})

    plan_counts = defaultdict(int)
    plan_total  = sum(s["total"] for s in suites_data)
    for s in suites_data:
        for k,v in s["counts"].items():
            plan_counts[k] += v

    fail  = plan_counts.get("failed",0)
    block = plan_counts.get("blocked",0)
    if fail == 0 and block == 0:
        result_label = "Exitoso"
        result_style = "background:#EAF3DE;color:#3B6D11;"
    else:
        result_label = "Fallido con incidentes"
        result_style = "background:#FCEBEB;color:#791F1F;"

    return {
        "id":plan_id,"name":plan_name,"total":plan_total,
        "counts":dict(plan_counts),"suites":suites_data,
        "result_label":result_label,"result_style":result_style
    }, None

def build_incident_data(uh_id):
    if not uh_id:
        return {"total":0,"uh_title":"","incidents":[],"by_sev":{},"by_module":{}}
    uh = get_work_item(uh_id)
    if "_error" in uh:
        return {"total":0,"uh_title":f"Error al acceder UH {uh_id}","incidents":[],"by_sev":{},"by_module":{}}

    uh_title  = uh.get("fields",{}).get("System.Title", f"UH #{uh_id}")
    children  = get_work_item_children(uh_id)
    bugs      = [c for c in children if c.get("fields",{}).get("System.WorkItemType","") == "Bug"]
    incidents = []
    for bug in bugs:
        f      = bug.get("fields",{})
        sev    = _norm_sev(f.get("Microsoft.VSTS.Common.Severity") or f.get("Microsoft.VSTS.Common.Priority"))
        title  = f.get("System.Title","Sin título")
        state  = f.get("System.State","")
        area   = f.get("System.AreaPath","").split("\\")[-1]
        module = area if area and area != PROJECT else title.split("-")[0].strip()
        incidents.append({"id":bug["id"],"title":title,"state":state,"sev":sev,"module":module})

    by_sev    = defaultdict(list)
    by_module = defaultdict(lambda: defaultdict(int))
    for inc in incidents:
        by_sev[inc["sev"]].append(inc)
        by_module[inc["module"]][inc["sev"]] += 1

    return {
        "uh_id":uh_id,"uh_title":uh_title,"total":len(incidents),
        "incidents":sorted(incidents, key=lambda x: _sev_order(x["sev"])),
        "by_sev":dict(by_sev),
        "by_module":{m:dict(v) for m,v in by_module.items()},
    }

# ── HTML report generator (same as CLI version) ───────────────
def _pill(label, count, style):
    if not count: return ""
    return (f'<span style="font-size:11px;font-weight:500;padding:2px 8px;border-radius:20px;'
            f'{style}white-space:nowrap;">{label} <b>{count}</b></span> ')

def _bar(counts, total):
    if not total:
        return '<div style="height:7px;background:#E8E7E1;border-radius:4px;"></div>'
    order = ["passed","failed","blocked","active","inprogress","notrun"]
    segs  = "".join(
        f'<div style="width:{pct(counts.get(s,0),total)}%;background:{STATUS_COLORS.get(s,"#ccc")};height:100%;border-radius:2px;"></div>'
        for s in order if counts.get(s,0)
    )
    return f'<div style="display:flex;gap:2px;height:7px;border-radius:4px;overflow:hidden;">{segs}</div>'

def _sev_pill(sev, count=None):
    st = SEVERITY_STYLE.get(sev,{"bg":"#F1EFE8","color":"#5F5E5A"})
    txt = f"{sev}{f' <b>{count}</b>' if count else ''}"
    return f'<span style="font-size:11px;font-weight:500;padding:2px 8px;border-radius:20px;background:{st["bg"]};color:{st["color"]};white-space:nowrap;">{txt}</span> '

def _suite_rows(suites):
    if not suites:
        return '<tr><td colspan="5" style="padding:10px 16px;color:#888;font-size:13px;">Sin suites con datos</td></tr>'
    rows = ""
    for s in suites:
        t=s["total"]; c=s["counts"]
        pp = pct(c.get("passed",0), t)
        col = "#3B6D11" if pp>=80 else "#791F1F" if pp<50 else "#633806"
        pills = "".join([
            _pill("Passed",  c.get("passed",0),  "background:#EAF3DE;color:#3B6D11;"),
            _pill("Failed",  c.get("failed",0),  "background:#FCEBEB;color:#791F1F;"),
            _pill("Blocked", c.get("blocked",0), "background:#FAEEDA;color:#633806;"),
            _pill("Not Run", c.get("notrun",0),  "background:#F1EFE8;color:#5F5E5A;"),
        ])
        rows += f"""<tr style="border-top:1px solid #EDECEA;">
          <td style="padding:9px 16px;font-size:13px;color:#3d3d3a;">{s['name']}</td>
          <td style="padding:9px 8px;text-align:center;font-size:13px;color:#888;">{t}</td>
          <td style="padding:9px 14px;">{pills}</td>
          <td style="padding:9px 14px;min-width:110px;">{_bar(c,t)}</td>
          <td style="padding:9px 8px;text-align:center;font-size:13px;font-weight:500;color:{col};">{pp}%</td>
        </tr>"""
    return rows

def _plan_block(plan):
    t=plan["total"]; c=plan["counts"]
    return f"""
    <section style="margin-bottom:24px;background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;">
      <div style="padding:14px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #EDECEA;background:#FAFAF8;flex-wrap:wrap;gap:8px;">
        <div>
          <div style="font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.06em;">Test plan</div>
          <div style="font-size:16px;font-weight:600;color:#1a1a18;margin-top:2px;">{plan['name']}</div>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          {_pill("Passed",  c.get("passed",0),  "background:#EAF3DE;color:#3B6D11;")}
          {_pill("Failed",  c.get("failed",0),  "background:#FCEBEB;color:#791F1F;")}
          {_pill("Blocked", c.get("blocked",0), "background:#FAEEDA;color:#633806;")}
          {_pill("Not Run", c.get("notrun",0),  "background:#F1EFE8;color:#5F5E5A;")}
          <span style="font-size:11px;font-weight:500;padding:2px 9px;border-radius:20px;{plan['result_style']}">{plan['result_label']}</span>
        </div>
      </div>
      <div style="padding:10px 20px;background:#FAFAF8;border-bottom:1px solid #EDECEA;">
        {_bar(c,t)}
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#888;margin-top:4px;">
          <span>Exitosos: <b>{c.get("passed",0)} ({pct(c.get("passed",0),t)}%)</b></span>
          <span>Con incidencia: <b>{c.get("failed",0)+c.get("blocked",0)} ({round(pct(c.get("failed",0),t)+pct(c.get("blocked",0),t),1)}%)</b></span>
          <span>Total: <b>{t}</b></span>
        </div>
      </div>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#F5F4F0;">
          <th style="padding:8px 16px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Suite</th>
          <th style="padding:8px 8px;text-align:center;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Total</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Estado</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Progreso</th>
          <th style="padding:8px 8px;text-align:center;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Pass %</th>
        </tr></thead>
        <tbody>{_suite_rows(plan['suites'])}</tbody>
      </table>
    </section>"""

def _incidents_block(inc_data, title="Detalle de incidentes"):
    if not inc_data or inc_data["total"] == 0:
        return f"""<section style="margin-bottom:24px;background:#fff;border-radius:12px;border:1px solid #EDECEA;padding:20px;">
          <p style="color:#888;font-size:13px;">No se encontraron incidentes.</p></section>"""
    total  = inc_data["total"]
    by_sev = inc_data["by_sev"]
    sev_pills = "".join(_sev_pill(s, len(by_sev.get(s,[]))) for s in ["Crítico","Alto","Mediano","Bajo"] if by_sev.get(s))
    sev_pcts  = "  ".join(f'<span style="font-size:12px;color:#888;">{s}: <b>{round(len(by_sev.get(s,[]))/total*100)}%</b></span>'
                          for s in ["Crítico","Alto","Mediano","Bajo"] if by_sev.get(s))
    mod_rows = "".join(
        f'<tr style="border-top:1px solid #EDECEA;">'
        f'<td style="padding:9px 16px;font-size:13px;color:#3d3d3a;">{mod}</td>'
        f'<td style="padding:9px 8px;text-align:center;font-size:13px;color:#888;">{sum(sv.values())}</td>'
        f'<td style="padding:9px 14px;">{"".join(_sev_pill(s,sv.get(s,0)) for s in ["Crítico","Alto","Mediano","Bajo"] if sv.get(s,0))}</td>'
        f'</tr>'
        for mod, sv in sorted(inc_data["by_module"].items())
    )
    bug_rows = "".join(
        f'<tr style="border-top:1px solid #EDECEA;">'
        f'<td style="padding:8px 16px;font-size:12px;color:#888;">#{inc["id"]}</td>'
        f'<td style="padding:8px 14px;font-size:13px;color:#3d3d3a;">{inc["title"]}</td>'
        f'<td style="padding:8px 8px;text-align:center;">{_sev_pill(inc["sev"])}</td>'
        f'<td style="padding:8px 8px;text-align:center;"><span style="font-size:11px;font-weight:500;padding:2px 8px;border-radius:20px;'
        f'{"background:#EAF3DE;color:#3B6D11;" if inc["state"].lower() in ("closed","resolved","done","cerrado","resuelto") else "background:#F1EFE8;color:#5F5E5A;"}">'
        f'{inc["state"]}</span></td>'
        f'</tr>'
        for inc in inc_data["incidents"]
    )
    return f"""
    <section style="margin-bottom:24px;background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;">
      <div style="padding:14px 20px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
        <div style="font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.06em;">{title} · {inc_data.get('uh_title','')}</div>
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:6px;flex-wrap:wrap;gap:8px;">
          <div>{sev_pills}</div>
          <div style="font-size:11px;color:#888;">{total} incidentes · {sev_pcts}</div>
        </div>
      </div>
      <div style="padding:14px 20px 4px;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.05em;">Por módulo</div>
      <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
        <thead><tr style="background:#F5F4F0;">
          <th style="padding:8px 16px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Módulo</th>
          <th style="padding:8px 8px;text-align:center;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Total</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Desglose</th>
        </tr></thead>
        <tbody>{mod_rows}</tbody>
      </table>
      <div style="padding:14px 20px 4px;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.05em;">Detalle de bugs</div>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#F5F4F0;">
          <th style="padding:8px 16px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">#</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Título</th>
          <th style="padding:8px 8px;text-align:center;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Severidad</th>
          <th style="padding:8px 8px;text-align:center;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Estado</th>
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
        f'<td style="padding:9px 16px;">{_sev_pill(s)}</td>'
        f'<td style="padding:9px 14px;font-size:13px;color:#3d3d3a;">{imp}</td>'
        f'<td style="padding:9px 14px;font-size:13px;color:#888;">{ex}</td>'
        f'<td style="padding:9px 14px;font-size:13px;color:#3d3d3a;">{act}</td>'
        f'</tr>'
        for s,imp,ex,act in data
    )
    return f"""<section style="margin-bottom:24px;background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;">
      <div style="padding:14px 20px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
        <div style="font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.06em;">Referencia de severidad</div>
      </div>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#F5F4F0;">
          <th style="padding:8px 16px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Severidad</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Impacto</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Ejemplos</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Acción</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>"""

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
    alcance = [a.strip() for a in form.get("alcance","").split("\n") if a.strip()]
    resps   = [r.strip() for r in form.getlist("responsables") if r.strip()]

    plan_id = int(form.get("plan_id", 0))
    uh_id   = int(form.get("uh_id", 0)) if form.get("uh_id","").strip().isdigit() else None
    prev_id = int(form.get("prev_uh_id", 0)) if form.get("prev_uh_id","").strip().isdigit() else None

    plan_data, err = build_plan_data(plan_id)
    if err:
        return None, err

    inc_data  = build_incident_data(uh_id)
    prev_data = build_incident_data(prev_id) if prev_id else None

    total_all  = plan_data["total"]
    c          = plan_data["counts"]
    pass_all   = c.get("passed",0)
    fail_all   = c.get("failed",0)
    block_all  = c.get("blocked",0)
    notrun_all = total_all - pass_all - fail_all - block_all

    result_color = "#791F1F" if result and "fallido" in result.lower() else "#3B6D11"
    resp_li  = "".join(f'<li style="font-size:13px;color:#3d3d3a;padding:2px 0;">{r}</li>' for r in resps) or '<li style="font-size:13px;color:#888;">—</li>'
    alc_li   = "".join(f'<li style="font-size:13px;color:#3d3d3a;padding:2px 0;">{a}</li>' for a in alcance) or '<li style="font-size:13px;color:#888;">—</li>'

    # Detalle de pruebas automático
    ep = pct(pass_all, total_all)
    ip = pct(fail_all+block_all, total_all)
    det_result = f"Exitosos: {pass_all} ({ep}%) / Con incidencia: {fail_all+block_all} ({ip}%)"
    det_row = (f'<tr style="border-top:1px solid #EDECEA;">'
               f'<td style="padding:9px 20px;font-size:13px;color:#888;">{prod}</td>'
               f'<td style="padding:9px 14px;font-size:13px;color:#3d3d3a;">{plan_data["name"]}</td>'
               f'<td style="padding:9px 14px;font-size:13px;color:#888;">Funcional</td>'
               f'<td style="padding:9px 14px;font-size:13px;color:#3d3d3a;">{det_result}</td>'
               f'</tr>')

    prev_section = ""
    if prev_data and prev_data["total"] > 0:
        prev_section = f'<div style="margin-bottom:8px;"><h2>4.1 · Incidencias pendientes del ciclo anterior</h2></div>' + _incidents_block(prev_data, "Incidencias pendientes")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Informe Final — {prod} {version}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
  <style>*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
  body{{font-family:'DM Sans',sans-serif;background:#F5F4F0;color:#1a1a18;padding:32px 24px;}}
  h2{{font-size:14px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.07em;margin:0 0 14px;}}
  @media print{{body{{background:#fff;padding:0;}}.no-print{{display:none;}}}}</style>
</head>
<body>
<div style="max-width:960px;margin:0 auto;">
  <div style="background:#fff;border-radius:12px;border:1px solid #EDECEA;padding:24px 28px;margin-bottom:20px;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;">
      <div>
        <div style="font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px;">{agrup}</div>
        <h1 style="font-size:26px;font-weight:600;color:#1a1a18;">Informe Final de Pruebas</h1>
        <div style="font-size:15px;color:#888;margin-top:4px;">{prod} · Ciclo {ciclo} · {version}</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;">
        <span style="font-size:13px;font-weight:500;padding:5px 14px;border-radius:8px;background:{result_color}1A;color:{result_color};border:1px solid {result_color}33;">{result or "—"}</span>
        <button class="no-print" onclick="window.print()" style="padding:5px 14px;border-radius:8px;border:1px solid #EDECEA;background:#fff;font-family:inherit;font-size:13px;cursor:pointer;">Exportar PDF</button>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:20px;padding-top:20px;border-top:1px solid #EDECEA;">
      <div>
        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Producto</div>
        <div style="font-size:13px;font-weight:500;">{prod}</div>
        <div style="font-size:12px;color:#888;margin-top:2px;">Versión {version}</div>
      </div>
      <div>
        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Plan de ejecución</div>
        <div style="font-size:12px;color:#3d3d3a;">
          <span style="color:#888;">Planificado:</span> {fi_plan} → {ff_plan}<br>
          <span style="color:#888;">Real:</span> {fi_real} → {ff_real}
        </div>
      </div>
      <div>
        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Responsables</div>
        <ul style="list-style:none;padding:0;">{resp_li}</ul>
      </div>
    </div>
  </div>
  <div style="background:#fff;border-radius:12px;border:1px solid #EDECEA;padding:20px 24px;margin-bottom:20px;">
    <h2>1 · Especificaciones</h2>
    <div style="font-size:12px;font-weight:500;color:#888;margin-bottom:6px;">Alcance</div>
    <ul style="padding-left:18px;">{alc_li}</ul>
  </div>
  <div style="background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;margin-bottom:20px;">
    <div style="padding:14px 24px;border-bottom:1px solid #EDECEA;background:#FAFAF8;"><h2 style="margin:0;">2 · Detalle de pruebas</h2></div>
    <table style="width:100%;border-collapse:collapse;">
      <thead><tr style="background:#F5F4F0;">
        <th style="padding:8px 20px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Producto</th>
        <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Título</th>
        <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Tipo</th>
        <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;">Resultado</th>
      </tr></thead>
      <tbody>{det_row}</tbody>
    </table>
  </div>
  <div style="margin-bottom:8px;"><h2>3 · Resultados de las pruebas</h2></div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px;">
    <div style="background:#EAF3DE;border-radius:10px;padding:14px 18px;">
      <div style="font-size:10px;font-weight:500;color:#3B6D11;text-transform:uppercase;letter-spacing:.05em;">Passed</div>
      <div style="font-size:28px;font-weight:600;color:#27500A;margin:3px 0 2px;">{pass_all}</div>
      <div style="font-size:12px;color:#3B6D11;">{pct(pass_all,total_all)}% del total</div>
    </div>
    <div style="background:#FCEBEB;border-radius:10px;padding:14px 18px;">
      <div style="font-size:10px;font-weight:500;color:#A32D2D;text-transform:uppercase;letter-spacing:.05em;">Failed</div>
      <div style="font-size:28px;font-weight:600;color:#501313;margin:3px 0 2px;">{fail_all}</div>
      <div style="font-size:12px;color:#A32D2D;">{pct(fail_all,total_all)}% del total</div>
    </div>
    <div style="background:#FAEEDA;border-radius:10px;padding:14px 18px;">
      <div style="font-size:10px;font-weight:500;color:#854F0B;text-transform:uppercase;letter-spacing:.05em;">Blocked</div>
      <div style="font-size:28px;font-weight:600;color:#412402;margin:3px 0 2px;">{block_all}</div>
      <div style="font-size:12px;color:#854F0B;">{pct(block_all,total_all)}% del total</div>
    </div>
    <div style="background:#F1EFE8;border-radius:10px;padding:14px 18px;">
      <div style="font-size:10px;font-weight:500;color:#5F5E5A;text-transform:uppercase;letter-spacing:.05em;">Not Run</div>
      <div style="font-size:28px;font-weight:600;color:#2C2C2A;margin:3px 0 2px;">{notrun_all}</div>
      <div style="font-size:12px;color:#5F5E5A;">{pct(notrun_all,total_all)}% del total</div>
    </div>
  </div>
  {_plan_block(plan_data)}
  <div style="margin-bottom:8px;"><h2>4 · Detalle de incidentes</h2></div>
  {_incidents_block(inc_data)}
  {prev_section}
  <div style="margin-bottom:8px;"><h2>5 · Referencia de severidad</h2></div>
  {_severity_ref()}
  <div style="text-align:center;padding:16px 0;font-size:12px;color:#aaa;">Salus QA Reporter · {now} · {ORGANIZATION} / {PROJECT}</div>
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
        return "Error: AZURE_DEVOPS_PAT no configurado en el servidor.", 500
    html, err = generate_report_html(request.form)
    if err:
        return f"Error al generar el informe: {err}", 500
    prod    = request.form.get("producto","salus").replace(" ","_").lower()
    version = request.form.get("version","vX").replace(".","_")
    ciclo   = request.form.get("ciclo","").replace("°","").replace(" ","")
    ts      = datetime.now().strftime("%Y-%m-%d")
    filename = f"informe_{prod}_{version}_ciclo{ciclo}_{ts}.html"
    return Response(
        html,
        mimetype="text/html",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
