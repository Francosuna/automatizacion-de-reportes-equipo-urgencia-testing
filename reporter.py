"""
Salus QA — Generador de Informe Final de Pruebas v2
Replica el formato del equipo: metadata, resultados por plan,
sección de incidentes desde la UH, seguimiento de ciclo anterior.
"""

import os, sys, json, base64, urllib.request, urllib.error
from datetime import datetime
from collections import defaultdict

# ─────────────────────────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────
ORGANIZATION = "osde-devops"
PROJECT      = "Desarrollo_Salus"
PAT          = os.environ.get("AZURE_DEVOPS_PAT", "7uqXY8uknpTAXQ8rGkG1IsEJ4j59jIqCN3W64ru5FT9dvx6PGb5yJQQJ99CCACAAAAAs8K2RAAASAZDO1IEm")

# IDs de los Test Plans a incluir (None = todos los activos)
TEST_PLAN_IDS = [90545]
# ─────────────────────────────────────────────────────────────

BASE_URL = f"https://dev.azure.com/{ORGANIZATION}/{PROJECT}/_apis"
HEADERS  = {
    "Content-Type": "application/json",
    "Authorization": "Basic " + base64.b64encode(f":{PAT}".encode()).decode()
}

SEVERITY_ORDER  = ["crítico", "critical", "1 - critical",
                   "alto",    "high",     "2 - high",
                   "mediano", "medium",   "3 - medium",
                   "bajo",    "low",      "4 - low"]

SEVERITY_LABELS = {
    "crítico": "Crítico", "critical": "Crítico", "1 - critical": "Crítico",
    "alto":    "Alto",    "high":     "Alto",    "2 - high":     "Alto",
    "mediano": "Mediano", "medium":   "Mediano", "3 - medium":   "Mediano",
    "bajo":    "Bajo",    "low":      "Bajo",    "4 - low":      "Bajo",
}

SEVERITY_STYLE = {
    "Crítico": {"bg": "#FCEBEB", "color": "#791F1F"},
    "Alto":    {"bg": "#FAEEDA", "color": "#633806"},
    "Mediano": {"bg": "#E6F1FB", "color": "#185FA5"},
    "Bajo":    {"bg": "#EAF3DE", "color": "#3B6D11"},
}

STATUS_COLORS = {
    "passed":     "#639922", "failed": "#E24B4A",
    "blocked":    "#BA7517", "notrun": "#D3D1C7",
    "active":     "#378ADD", "inprogress": "#378ADD",
}

# ─── HTTP helper ──────────────────────────────────────────────
def _get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  [HTTP {e.code}] {url}")
        return {}
    except Exception as e:
        print(f"  [ERROR] {e}")
        return {}

def _post(url, body):
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  [POST ERROR] {e}")
        return {}

# ─── Azure DevOps fetchers ────────────────────────────────────
def get_test_plans():
    d = _get(f"{BASE_URL}/testplan/plans?api-version=7.0")
    return d.get("value", [])

def get_test_suites(plan_id):
    d = _get(f"{BASE_URL}/testplan/Plans/{plan_id}/suites?api-version=7.0")
    return d.get("value", [])

def get_test_points(plan_id, suite_id):
    d = _get(f"{BASE_URL}/testplan/Plans/{plan_id}/Suites/{suite_id}/TestPoint?api-version=7.0")
    return d.get("value", [])

def get_work_item(wi_id):
    return _get(f"{BASE_URL}/wit/workitems/{wi_id}?$expand=relations&api-version=7.0")

def get_work_item_children(wi_id):
    """Devuelve los work items hijos (bugs) de una User Story."""
    wi = get_work_item(wi_id)
    if not wi:
        return []
    relations = wi.get("relations", [])
    child_ids = [
        r["url"].split("/")[-1]
        for r in relations
        if r.get("rel") == "System.LinkTypes.Hierarchy-Forward"
    ]
    if not child_ids:
        return []
    ids_str = ",".join(child_ids)
    d = _get(f"{BASE_URL}/wit/workitems?ids={ids_str}&$expand=fields&api-version=7.0")
    return d.get("value", [])

# ─── Normalize severity ───────────────────────────────────────
def _norm_sev(raw):
    if not raw:
        return "Bajo"
    k = str(raw).lower().strip()
    return SEVERITY_LABELS.get(k, raw.title())

def _norm_status(raw):
    return (raw or "notrun").lower().replace(" ", "")

def _sev_sort_key(sev):
    label = sev.lower()
    for i, s in enumerate(SEVERITY_ORDER):
        if label in s or s in label:
            return i
    return 99

# ─── Build report data ────────────────────────────────────────
def build_test_plan_data(test_plan_ids=None):
    all_plans = get_test_plans()
    if test_plan_ids:
        all_plans = [p for p in all_plans if p["id"] in test_plan_ids]
    elif TEST_PLAN_IDS:
        all_plans = [p for p in all_plans if p["id"] in TEST_PLAN_IDS]

    report = []
    for plan in all_plans:
        pid, pname = plan["id"], plan["name"]
        print(f"\n  Plan: {pname} (id={pid})")
        suites_data = []
        for suite in get_test_suites(pid):
            if suite.get("suiteType") == "root":
                continue
            sid, sname = suite["id"], suite["name"]
            points = get_test_points(pid, sid)
            counts = defaultdict(int)
            for pt in points:
                counts[_norm_status(pt.get("results", {}).get("outcome", "notRun"))] += 1
            total = len(points)
            suites_data.append({"id": sid, "name": sname, "total": total, "counts": dict(counts)})

        plan_counts = defaultdict(int)
        plan_total  = sum(s["total"] for s in suites_data)
        for s in suites_data:
            for k, v in s["counts"].items():
                plan_counts[k] += v

        # Resultado narrativo del plan
        fail  = plan_counts.get("failed", 0)
        block = plan_counts.get("blocked", 0)
        if fail == 0 and block == 0:
            result_label = "Exitoso"
            result_style = "background:#EAF3DE;color:#3B6D11;"
        elif fail > 0 or block > 0:
            result_label = "Fallido con incidentes"
            result_style = "background:#FCEBEB;color:#791F1F;"
        else:
            result_label = "En progreso"
            result_style = "background:#E6F1FB;color:#185FA5;"

        report.append({
            "id": pid, "name": pname,
            "total": plan_total, "counts": dict(plan_counts),
            "suites": suites_data,
            "result_label": result_label, "result_style": result_style
        })
    return report

def build_incident_data(uh_id):
    """Trae bugs hijos de la UH y los agrupa por severidad y módulo."""
    print(f"\n  Leyendo UH id={uh_id}...")
    uh = get_work_item(uh_id)
    uh_title = uh.get("fields", {}).get("System.Title", f"UH #{uh_id}") if uh else f"UH #{uh_id}"

    children = get_work_item_children(uh_id)
    bugs = [c for c in children if c.get("fields", {}).get("System.WorkItemType", "") == "Bug"]
    print(f"  Bugs encontrados: {len(bugs)}")

    incidents = []
    for bug in bugs:
        f    = bug.get("fields", {})
        sev  = _norm_sev(f.get("Microsoft.VSTS.Common.Severity") or f.get("Microsoft.VSTS.Common.Priority"))
        title = f.get("System.Title", "Sin título")
        state = f.get("System.State", "")
        area  = f.get("System.AreaPath", "").split("\\")[-1]
        # Intentar deducir módulo del título si no hay área
        module = area if area and area != PROJECT else title.split("-")[0].strip()
        incidents.append({
            "id":     bug["id"],
            "title":  title,
            "state":  state,
            "sev":    sev,
            "module": module,
        })

    # Agrupar por severidad
    by_sev = defaultdict(list)
    for inc in incidents:
        by_sev[inc["sev"]].append(inc)

    # Agrupar por módulo con conteo por severidad
    by_module = defaultdict(lambda: defaultdict(int))
    for inc in incidents:
        by_module[inc["module"]][inc["sev"]] += 1

    return {
        "uh_title":  uh_title,
        "uh_id":     uh_id,
        "total":     len(incidents),
        "incidents": incidents,
        "by_sev":    dict(by_sev),
        "by_module": {m: dict(v) for m, v in by_module.items()},
    }

# ─── HTML helpers ────────────────────────────────────────────
def pct(n, total):
    return round(n / total * 100, 1) if total else 0.0

def _pill(label, count, style):
    if not count:
        return ""
    return (f'<span style="font-size:11px;font-weight:500;padding:2px 8px;border-radius:20px;'
            f'{style}white-space:nowrap;">{label} <b>{count}</b></span> ')

def _bar(counts, total):
    if not total:
        return '<div style="height:7px;background:#E8E7E1;border-radius:4px;"></div>'
    order  = ["passed","failed","blocked","active","inprogress","paused","notrun"]
    segs   = "".join(
        f'<div style="width:{pct(counts.get(s,0),total)}%;background:{STATUS_COLORS.get(s,"#ccc")};'
        f'height:100%;border-radius:2px;" title="{s}: {counts.get(s,0)}"></div>'
        for s in order if counts.get(s, 0)
    )
    return f'<div style="display:flex;gap:2px;height:7px;border-radius:4px;overflow:hidden;">{segs}</div>'

def _severity_pill(sev, count=None):
    st = SEVERITY_STYLE.get(sev, {"bg":"#F1EFE8","color":"#5F5E5A"})
    label = f"{sev}{f' <b>{count}</b>' if count else ''}"
    return (f'<span style="font-size:11px;font-weight:500;padding:2px 8px;border-radius:20px;'
            f'background:{st["bg"]};color:{st["color"]};white-space:nowrap;">{label}</span> ')

# ─── HTML sections ───────────────────────────────────────────
def _html_suite_rows(suites):
    if not suites:
        return '<tr><td colspan="5" style="padding:10px 16px;color:#888;font-size:13px;">Sin suites con datos</td></tr>'
    rows = ""
    for s in suites:
        t = s["total"]; c = s["counts"]
        pp = pct(c.get("passed",0), t)
        color = "#3B6D11" if pp >= 80 else "#791F1F" if pp < 50 else "#633806"
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
          <td style="padding:9px 8px;text-align:center;font-size:13px;font-weight:500;color:{color};">{pp}%</td>
        </tr>"""
    return rows

def _html_plan_block(plan):
    t = plan["total"]; c = plan["counts"]
    suite_rows = _html_suite_rows(plan["suites"])
    passed_pct = pct(c.get("passed",0), t)
    failed_pct = pct(c.get("failed",0), t)
    return f"""
    <section style="margin-bottom:24px;background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;">
      <div style="padding:14px 20px;display:flex;align-items:center;justify-content:space-between;
                  border-bottom:1px solid #EDECEA;background:#FAFAF8;flex-wrap:wrap;gap:8px;">
        <div>
          <div style="font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.06em;">Test plan</div>
          <div style="font-size:16px;font-weight:600;color:#1a1a18;margin-top:2px;">{plan['name']}</div>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          {_pill("Passed",  c.get("passed",0),  "background:#EAF3DE;color:#3B6D11;")}
          {_pill("Failed",  c.get("failed",0),  "background:#FCEBEB;color:#791F1F;")}
          {_pill("Blocked", c.get("blocked",0), "background:#FAEEDA;color:#633806;")}
          {_pill("Not Run", c.get("notrun",0),  "background:#F1EFE8;color:#5F5E5A;")}
          <span style="font-size:11px;color:#888;margin-left:4px;">{t} casos</span>
          <span style="font-size:11px;font-weight:500;padding:2px 9px;border-radius:20px;{plan['result_style']}">{plan['result_label']}</span>
        </div>
      </div>
      <div style="padding:10px 20px;background:#FAFAF8;border-bottom:1px solid #EDECEA;">
        {_bar(c, t)}
        <div style="display:flex;justify-content:space-between;font-size:11px;color:#888;margin-top:4px;">
          <span>Pass {passed_pct}%</span><span>Fail {failed_pct}%</span>
          <span>Total casos exitosos: <b>{c.get("passed",0)} ({passed_pct}%)</b></span>
          <span>Con incidencia: <b>{c.get("failed",0)+c.get("blocked",0)} ({round(failed_pct+pct(c.get("blocked",0),t),1)}%)</b></span>
        </div>
      </div>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#F5F4F0;">
          <th style="padding:8px 16px;text-align:left;font-size:11px;font-weight:500;color:#888;letter-spacing:.04em;text-transform:uppercase;">Suite</th>
          <th style="padding:8px 8px;text-align:center;font-size:11px;font-weight:500;color:#888;letter-spacing:.04em;text-transform:uppercase;">Total</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;letter-spacing:.04em;text-transform:uppercase;">Estado</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;letter-spacing:.04em;text-transform:uppercase;">Progreso</th>
          <th style="padding:8px 8px;text-align:center;font-size:11px;font-weight:500;color:#888;letter-spacing:.04em;text-transform:uppercase;">Pass %</th>
        </tr></thead>
        <tbody>{suite_rows}</tbody>
      </table>
    </section>"""

def _html_incidents_section(inc_data):
    if not inc_data or inc_data["total"] == 0:
        return '<section style="margin-bottom:24px;background:#fff;border-radius:12px;border:1px solid #EDECEA;padding:20px;"><p style="color:#888;font-size:13px;">No se encontraron incidentes en la UH.</p></section>'

    total = inc_data["total"]
    by_sev = inc_data["by_sev"]

    # Pills de resumen por severidad
    sev_summary = ""
    sev_pcts    = ""
    for label in ["Crítico","Alto","Mediano","Bajo"]:
        cnt = len(by_sev.get(label, []))
        if cnt:
            sev_summary += _severity_pill(label, cnt)
            sev_pcts    += f'<span style="font-size:12px;color:#888;">{label}: <b>{round(cnt/total*100)}%</b></span>  '

    # Tabla de incidentes por módulo
    module_rows = ""
    for mod, sev_counts in sorted(inc_data["by_module"].items()):
        mod_total = sum(sev_counts.values())
        pills = "".join(_severity_pill(s, sev_counts.get(s,0)) for s in ["Crítico","Alto","Mediano","Bajo"] if sev_counts.get(s,0))
        module_rows += f"""<tr style="border-top:1px solid #EDECEA;">
          <td style="padding:9px 16px;font-size:13px;color:#3d3d3a;">{mod}</td>
          <td style="padding:9px 8px;text-align:center;font-size:13px;color:#888;">{mod_total}</td>
          <td style="padding:9px 14px;">{pills}</td>
        </tr>"""

    # Lista de bugs individuales
    bug_rows = ""
    for inc in sorted(inc_data["incidents"], key=lambda x: _sev_sort_key(x["sev"])):
        st    = inc["state"]
        closed = st.lower() in ("closed","resolved","done","cerrado","resuelto")
        state_style = "background:#EAF3DE;color:#3B6D11;" if closed else "background:#F1EFE8;color:#5F5E5A;"
        bug_rows += f"""<tr style="border-top:1px solid #EDECEA;">
          <td style="padding:8px 16px;font-size:12px;color:#888;">#{inc['id']}</td>
          <td style="padding:8px 14px;font-size:13px;color:#3d3d3a;">{inc['title']}</td>
          <td style="padding:8px 8px;text-align:center;">{_severity_pill(inc['sev'])}</td>
          <td style="padding:8px 8px;text-align:center;">
            <span style="font-size:11px;font-weight:500;padding:2px 8px;border-radius:20px;{state_style}">{st}</span>
          </td>
        </tr>"""

    return f"""
    <section style="margin-bottom:24px;background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;">
      <div style="padding:14px 20px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
        <div style="font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.06em;">Incidentes detectados · {inc_data['uh_title']}</div>
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:6px;flex-wrap:wrap;gap:8px;">
          <div>{sev_summary}</div>
          <div style="font-size:11px;color:#888;">{total} incidentes en total</div>
        </div>
      </div>
      <div style="padding:10px 20px;background:#FAFAF8;border-bottom:1px solid #EDECEA;font-size:12px;color:#888;">
        Porcentaje por criticidad: {sev_pcts}
      </div>

      <div style="padding:14px 20px 4px;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.05em;">Por módulo / funcionalidad</div>
      <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
        <thead><tr style="background:#F5F4F0;">
          <th style="padding:8px 16px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Módulo</th>
          <th style="padding:8px 8px;text-align:center;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Total</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Desglose</th>
        </tr></thead>
        <tbody>{module_rows}</tbody>
      </table>

      <div style="padding:14px 20px 4px;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.05em;">Detalle de bugs</div>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#F5F4F0;">
          <th style="padding:8px 16px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">#</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Título</th>
          <th style="padding:8px 8px;text-align:center;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Severidad</th>
          <th style="padding:8px 8px;text-align:center;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Estado</th>
        </tr></thead>
        <tbody>{bug_rows}</tbody>
      </table>
    </section>"""

def _html_severity_ref():
    rows = ""
    data = [
        ("Bajo",    "Mínimo. No afecta funcionalidad principal.",
                    "Errores tipográficos, detalles visuales menores.",
                    "Puede esperar. Se corrige cuando haya disponibilidad."),
        ("Mediano", "Afecta funcionalidades secundarias. Puede haber workaround.",
                    "Botón no funcional con alternativa disponible.",
                    "Importante pero no urgente. Planificar para próximos sprints."),
        ("Alto",    "Afecta funcionalidades clave. Sin solución alternativa clara.",
                    "Fallos en formularios críticos, errores de cálculo.",
                    "Alta prioridad. Requiere atención en la próxima versión."),
        ("Crítico", "Bloquea el sistema, pérdida de datos o seguridad.",
                    "Caída del sistema, pérdida de info, errores de autenticación.",
                    "Urgencia máxima. Requiere hotfix inmediato."),
    ]
    for sev, impact, examples, action in data:
        st = SEVERITY_STYLE.get(sev, {"bg":"#F1EFE8","color":"#5F5E5A"})
        rows += f"""<tr style="border-top:1px solid #EDECEA;">
          <td style="padding:9px 16px;"><span style="font-size:12px;font-weight:500;padding:2px 8px;
            border-radius:20px;background:{st['bg']};color:{st['color']};">{sev}</span></td>
          <td style="padding:9px 14px;font-size:13px;color:#3d3d3a;">{impact}</td>
          <td style="padding:9px 14px;font-size:13px;color:#888;">{examples}</td>
          <td style="padding:9px 14px;font-size:13px;color:#3d3d3a;">{action}</td>
        </tr>"""
    return f"""
    <section style="margin-bottom:24px;background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;">
      <div style="padding:14px 20px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
        <div style="font-size:10px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.06em;">Referencia de severidad y prioridad</div>
      </div>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#F5F4F0;">
          <th style="padding:8px 16px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Severidad</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Impacto</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Ejemplos</th>
          <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Urgencia / Acción</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>"""

# ─── Full HTML ────────────────────────────────────────────────
def generate_html(meta, plan_data, inc_data, prev_uh_data):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # KPIs globales
    total_all = sum(p["total"] for p in plan_data)
    pass_all  = sum(p["counts"].get("passed",  0) for p in plan_data)
    fail_all  = sum(p["counts"].get("failed",  0) for p in plan_data)
    block_all = sum(p["counts"].get("blocked", 0) for p in plan_data)
    notrun_all= total_all - pass_all - fail_all - block_all

    result_color = "#791F1F" if meta["resultado"] and "fallido" in meta["resultado"].lower() else "#3B6D11"

    # Responsables
    resp_list = "".join(
        f'<li style="font-size:13px;color:#3d3d3a;padding:2px 0;">{r}</li>'
        for r in meta["responsables"]
    ) if meta["responsables"] else '<li style="font-size:13px;color:#888;">—</li>'

    # Plan blocks
    plan_blocks = "".join(_html_plan_block(p) for p in plan_data)

    # Incidents section
    inc_html = _html_incidents_section(inc_data)

    # Previous cycle section
    prev_html = ""
    if prev_uh_data and prev_uh_data["total"] > 0:
        prev_html = _html_incidents_section(prev_uh_data)
        prev_html = prev_html.replace(
            "Incidentes detectados",
            "Incidencias pendientes del ciclo anterior"
        )

    sev_ref = _html_severity_ref()

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Informe Final de Pruebas — {meta['producto']} {meta['version']}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:'DM Sans',sans-serif;background:#F5F4F0;color:#1a1a18;min-height:100vh;padding:32px 24px;}}
    h2{{font-size:14px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.07em;margin:0 0 14px;}}
    @media print{{body{{background:#fff;padding:0;}}.no-print{{display:none;}}}}
  </style>
</head>
<body>
<div style="max-width:960px;margin:0 auto;">

  <!-- Portada / header -->
  <div style="background:#fff;border-radius:12px;border:1px solid #EDECEA;padding:24px 28px;margin-bottom:20px;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;">
      <div>
        <div style="font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px;">
          {meta['agrupador']}
        </div>
        <h1 style="font-size:26px;font-weight:600;color:#1a1a18;line-height:1.2;">Informe Final de Pruebas</h1>
        <div style="font-size:15px;color:#888;margin-top:4px;">{meta['producto']} · Ciclo {meta['ciclo']} · {meta['version']}</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;">
        <span style="font-size:13px;font-weight:500;padding:5px 14px;border-radius:8px;
          background:{result_color}1A;color:{result_color};border:1px solid {result_color}33;">
          {meta['resultado'] or '—'}
        </span>
        <button class="no-print" onclick="window.print()"
          style="padding:5px 14px;border-radius:8px;border:1px solid #EDECEA;
                 background:#fff;font-family:inherit;font-size:13px;cursor:pointer;color:#3d3d3a;">
          Exportar PDF
        </button>
      </div>
    </div>

    <!-- Metadata grid -->
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:20px;padding-top:20px;border-top:1px solid #EDECEA;">
      <div>
        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Producto</div>
        <div style="font-size:13px;color:#1a1a18;font-weight:500;">{meta['producto']}</div>
        <div style="font-size:12px;color:#888;margin-top:2px;">Versión {meta['version']}</div>
      </div>
      <div>
        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Plan de ejecución</div>
        <div style="font-size:12px;color:#3d3d3a;">
          <span style="color:#888;">Planificado:</span> {meta['fecha_inicio_plan']} → {meta['fecha_fin_plan']}<br>
          <span style="color:#888;">Real:</span> {meta['fecha_inicio_real']} → {meta['fecha_fin_real']}
        </div>
      </div>
      <div>
        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Responsables</div>
        <ul style="list-style:none;padding:0;">{resp_list}</ul>
      </div>
    </div>
  </div>

  <!-- 1. Especificaciones / alcance -->
  <div style="background:#fff;border-radius:12px;border:1px solid #EDECEA;padding:20px 24px;margin-bottom:20px;">
    <h2>1 · Especificaciones</h2>
    <div style="font-size:12px;font-weight:500;color:#888;margin-bottom:6px;">Alcance</div>
    <ul style="padding-left:18px;">
      {"".join(f'<li style="font-size:13px;color:#3d3d3a;padding:2px 0;">{a}</li>' for a in meta['alcance'])}
    </ul>
  </div>

  <!-- 2. Detalle de pruebas -->
  <div style="background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;margin-bottom:20px;">
    <div style="padding:14px 24px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
      <h2 style="margin:0;">2 · Detalle de pruebas</h2>
    </div>
    <table style="width:100%;border-collapse:collapse;">
      <thead><tr style="background:#F5F4F0;">
        <th style="padding:8px 20px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Producto</th>
        <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Título / Descripción</th>
        <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Tipo de prueba</th>
        <th style="padding:8px 14px;text-align:left;font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.04em;">Resultado</th>
      </tr></thead>
      <tbody>
        {"".join(
            f'<tr style="border-top:1px solid #EDECEA;">'
            f'<td style="padding:9px 20px;font-size:13px;color:#888;">{r["producto"]}</td>'
            f'<td style="padding:9px 14px;font-size:13px;color:#3d3d3a;">{r["titulo"]}</td>'
            f'<td style="padding:9px 14px;font-size:13px;color:#888;">{r["tipo"]}</td>'
            f'<td style="padding:9px 14px;font-size:13px;color:#3d3d3a;">{r["resultado"]}</td>'
            f'</tr>'
            for r in meta["detalle_pruebas"]
        )}
      </tbody>
    </table>
  </div>

  <!-- 3. Resultados -->
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
  {plan_blocks}

  <!-- 4. Incidentes del ciclo -->
  <div style="margin-bottom:8px;"><h2>4 · Detalle de incidentes</h2></div>
  {inc_html}

  <!-- 4.x Incidencias ciclo anterior -->
  {"<div style='margin-bottom:8px;'><h2>4.1 · Incidencias pendientes del ciclo anterior</h2></div>" + prev_html if prev_html else ""}

  <!-- 5. Referencia de severidad -->
  <div style="margin-bottom:8px;"><h2>5 · Referencia de severidad y prioridad</h2></div>
  {sev_ref}

  <div style="text-align:center;padding:16px 0;font-size:12px;color:#aaa;">
    Salus QA Reporter · {now} · {ORGANIZATION} / {PROJECT}
  </div>
</div>
</body>
</html>"""

# ─── Interactive prompt helpers ───────────────────────────────
def _ask(prompt, default=""):
    val = input(prompt).strip()
    return val if val else default

def _ask_list(prompt):
    print(prompt)
    items = []
    while True:
        val = input("  (enter vacío para terminar): ").strip()
        if not val:
            break
        items.append(val)
    return items

# ─── Main ─────────────────────────────────────────────────────
def main():
    if PAT in ("TU_PAT_AQUI", "") or not PAT:
        print("⚠  Configurá AZURE_DEVOPS_PAT antes de correr.")
        print("   set AZURE_DEVOPS_PAT=tu_token  && python reporter.py")
        sys.exit(1)

    print("=" * 55)
    print("  SALUS QA — Generador de Informe Final de Pruebas")
    print("=" * 55)

    # ── Metadata interactiva ──────────────────────────────────
    print("\n[ Metadata del ciclo ]")
    producto       = _ask("Producto (ej: SALUS WEB): ", "SALUS WEB")
    version        = _ask("Versión (ej: v17.2.1): ", "")
    ciclo          = _ask("N° de ciclo (ej: N°2): ", "")
    agrupador      = _ask("Agrupador (ej: AGRUPADOR URGENCIAS - SALUS): ", "SALUS")
    resultado      = _ask("Resultado del ciclo (ej: Fallido con incidentes críticos): ", "")
    fecha_ip       = _ask("Fecha inicio planificada (ej: 07/11/2025): ", "")
    fecha_fp       = _ask("Fecha fin planificada: ", "")
    fecha_ir       = _ask("Fecha inicio real: ", fecha_ip)
    fecha_fr       = _ask("Fecha fin real: ", fecha_fp)

    print("\nAlcance del ciclo (ingresá uno por línea):")
    alcance        = _ask_list("") or ["Smoke Test", "Paquete de incidencias", "Regresión"]

    print("\nResponsables (ingresá uno por línea):")
    responsables   = _ask_list("") or []

    # ── Detalle de pruebas ────────────────────────────────────
    print("\n[ Detalle de pruebas — se completa desde los Test Plans ]")
    print("  (los resultados se calculan automáticamente, pero podés agregar filas extra)")
    detalle_extra = []
    agregar = _ask("¿Querés agregar filas manuales de pruebas? (s/n): ", "n")
    if agregar.lower() == "s":
        while True:
            prod = _ask("  Producto: ", "")
            if not prod:
                break
            tit  = _ask("  Título: ", "")
            tipo = _ask("  Tipo de prueba: ", "Funcional")
            res  = _ask("  Resultado: ", "")
            detalle_extra.append({"producto": prod, "titulo": tit, "tipo": tipo, "resultado": res})

    # ── Test Plans ────────────────────────────────────────────
    print("\n[ Cargando Test Plans desde Azure DevOps... ]")
    plan_data = build_test_plan_data()

    # Armar filas de detalle de pruebas desde planes
    detalle_auto = []
    for p in plan_data:
        t = p["total"]; c = p["counts"]
        exitosos = c.get("passed", 0)
        incidencias = c.get("failed", 0) + c.get("blocked", 0)
        if exitosos == t:
            res = f"Exitoso ({exitosos} de {t})"
        else:
            res = f"Fallido — Exitosos: {exitosos} ({pct(exitosos,t)}%) / Con incidencia: {incidencias} ({pct(incidencias,t)}%)"
        detalle_auto.append({"producto": producto, "titulo": p["name"], "tipo": "Funcional", "resultado": res})

    detalle_pruebas = detalle_auto + detalle_extra

    # ── UH de incidentes ─────────────────────────────────────
    print("\n[ Incidentes del ciclo ]")
    uh_id_str = _ask("ID de la UH de incidentes del ciclo actual (enter para omitir): ", "")
    inc_data  = build_incident_data(int(uh_id_str)) if uh_id_str.isdigit() else {"total": 0}

    # ── UH ciclo anterior ─────────────────────────────────────
    prev_uh_str  = _ask("ID de la UH de incidentes del ciclo ANTERIOR (enter para omitir): ", "")
    prev_uh_data = build_incident_data(int(prev_uh_str)) if prev_uh_str.isdigit() else None

    # ── Generar HTML ──────────────────────────────────────────
    meta = {
        "producto": producto, "version": version, "ciclo": ciclo,
        "agrupador": agrupador, "resultado": resultado,
        "fecha_inicio_plan": fecha_ip, "fecha_fin_plan": fecha_fp,
        "fecha_inicio_real": fecha_ir, "fecha_fin_real": fecha_fr,
        "alcance": alcance, "responsables": responsables,
        "detalle_pruebas": detalle_pruebas,
    }

    html     = generate_html(meta, plan_data, inc_data, prev_uh_data)
    ts       = datetime.now().strftime("%Y-%m-%d")
    ver_slug = version.replace(".", "_").replace(" ", "") if version else "vX"
    filename = f"informe_salus_{ver_slug}_ciclo{ciclo.replace('°','').replace(' ','')}_{ts}.html"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅  Informe generado: {filename}")
    print("    Abrilo en el browser · usá el botón 'Exportar PDF' para distribuirlo.")

if __name__ == "__main__":
    main()
