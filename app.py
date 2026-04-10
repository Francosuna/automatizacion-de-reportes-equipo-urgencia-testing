"""
Salus QA Reporter — Web App (Flask) v3
Cada suite del Test Plan se muestra como sección independiente,
replicando el formato real del equipo.
"""

import os, json, re, base64, urllib.request, urllib.error
import psycopg2, psycopg2.extras
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv
from flask import Flask, render_template, request, Response, jsonify, session, redirect, url_for, g
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

ORGANIZATION   = os.environ.get("AZURE_ORG",        "osde-devops")
PROJECT        = os.environ.get("AZURE_PROJECT",     "Desarrollo_Salus")
PAT            = os.environ.get("AZURE_DEVOPS_PAT",  "")
DATABASE_URL   = os.environ.get("DATABASE_URL",      "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD",    "admin123")

# ── SQLAlchemy — Informe model ──────────────────────────────────
_sa_url = DATABASE_URL.replace("postgres://", "postgresql://") if DATABASE_URL else "sqlite:///informes.db"
app.config["SQLALCHEMY_DATABASE_URI"] = _sa_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

class Informe(db.Model):
    __tablename__ = "informes"
    id               = db.Column(db.Integer, primary_key=True)
    equipo           = db.Column(db.String(100), nullable=False)
    producto         = db.Column(db.String(100), nullable=False)
    version          = db.Column(db.String(50))
    ciclo            = db.Column(db.String(50))
    fecha_generacion = db.Column(db.DateTime, default=datetime.utcnow)
    html             = db.Column(db.Text, nullable=False)

# ── DB ─────────────────────────────────────────────────────────
def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def init_db():
    if not DATABASE_URL:
        return
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS teams (
                    id            SERIAL PRIMARY KEY,
                    name          TEXT NOT NULL UNIQUE,
                    slug          TEXT NOT NULL UNIQUE,
                    azure_org     TEXT NOT NULL DEFAULT 'osde-devops',
                    azure_project TEXT NOT NULL DEFAULT 'Desarrollo_Salus',
                    azure_pat     TEXT NOT NULL,
                    created_at    TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        conn.commit()

def _get_all_teams():
    if not DATABASE_URL:
        return []
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, slug, azure_org, azure_project FROM teams ORDER BY name")
            return cur.fetchall()

def _get_team_by_id(team_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM teams WHERE id = %s", (team_id,))
            return cur.fetchone()

def _create_team(name, slug, azure_org, azure_project, azure_pat):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO teams (name, slug, azure_org, azure_project, azure_pat) VALUES (%s,%s,%s,%s,%s)",
                (name, slug, azure_org, azure_project, azure_pat)
            )
        conn.commit()

def _update_team(team_id, name, slug, azure_org, azure_project, azure_pat):
    with get_db() as conn:
        with conn.cursor() as cur:
            if azure_pat:
                cur.execute(
                    "UPDATE teams SET name=%s, slug=%s, azure_org=%s, azure_project=%s, azure_pat=%s WHERE id=%s",
                    (name, slug, azure_org, azure_project, azure_pat, team_id)
                )
            else:
                cur.execute(
                    "UPDATE teams SET name=%s, slug=%s, azure_org=%s, azure_project=%s WHERE id=%s",
                    (name, slug, azure_org, azure_project, team_id)
                )
        conn.commit()

def _delete_team(team_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM teams WHERE id = %s", (team_id,))
        conn.commit()

# ── Admin auth ─────────────────────────────────────────────────
def _admin_authed():
    return session.get("admin_ok") is True

# ── Azure config via Flask g (fallback a env vars) ─────────────
def _headers():
    pat = getattr(g, "team_pat", PAT)
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {"Content-Type": "application/json", "Authorization": f"Basic {token}"}

def _base_url():
    org  = getattr(g, "team_org",  ORGANIZATION)
    proj = getattr(g, "team_project", PROJECT)
    return f"https://dev.azure.com/{org}/{proj}/_apis"

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
    return _get(f"{_base_url()}/testplan/plans/{plan_id}?api-version=7.0")

def get_test_suites(plan_id):
    d = _get(f"{_base_url()}/testplan/Plans/{plan_id}/suites?api-version=7.0")
    return d.get("value", [])

def get_test_points(plan_id, suite_id):
    d = _get(f"{_base_url()}/testplan/Plans/{plan_id}/Suites/{suite_id}/TestPoint?api-version=7.0")
    return d.get("value", [])

def get_work_item(wi_id):
    return _get(f"{_base_url()}/wit/workitems/{wi_id}?$expand=relations&api-version=7.0")

def get_work_items_batch(wi_ids):
    if not wi_ids:
        return []
    ids_str = ",".join(str(i) for i in wi_ids)
    d = _get(f"{_base_url()}/wit/workitems?ids={ids_str}&$expand=fields&api-version=7.0")
    return d.get("value", [])

def get_work_item_children(wi_id):
    wi = get_work_item(wi_id)
    if not wi or "_error" in wi:
        return []
    rel_types = ("System.LinkTypes.Hierarchy-Forward", "System.LinkTypes.Related")
    child_ids = []
    for r in wi.get("relations", []):
        if r.get("rel") in rel_types:
            parts = r["url"].split("/")
            if parts:
                child_ids.append(parts[-1])
    
    print(f"[LOG] UH {wi_id} links encontrados: {len(child_ids)} ({child_ids})")
    return get_work_items_batch(child_ids)

# ── Helpers ────────────────────────────────────────────────────
SEVERITY_LABELS = {
    "crítico":"Crítico","critical":"Crítico","1 - critical":"Crítico",
    "alto":"Alto","high":"Alto","2 - high":"Alto",
    "mediano":"Mediano","medium":"Mediano","3 - medium":"Mediano",
    "bajo":"Bajo","low":"Bajo","4 - low":"Bajo",
}
# ── Color Palette & Styles ──────────────────────────────────────
# Theme Colors
# Theme Colors
PRIMARY_COLOR   = "#061E29" # Navy
SECONDARY_COLOR = "#1D546D" # Steel Blue
ACCENT_COLOR    = "#5F9598" # Sage Blue
BG_COLOR        = "#F3F4F4" # Light Gray

SEVERITY_STYLE = {
    "Crítico":{"bg":"#FCEBEB","color":"#791F1F"}, # Red
    "Alto":   {"bg":"#FAEEDA","color":"#633806"}, # Orange
    "Mediano":{"bg":"#FFF9C4","color":"#6B5900"}, # Yellow
    "Bajo":   {"bg":"#EAF3DE","color":"#3B6D11"}, # Green
}
STATUS_COLORS = {
    "passed":"#5F9598",
    "failed":"#E24B4A",
    "blocked":"#BA7517",
    "notrun":"#d1d1d1",
    "active":"#1D546D",
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
    return (f'<span style="font-size:12px;font-weight:600;padding:2px 10px;border-radius:20px;'
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

        if fail == 0:
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
    result_label = "Exitoso" if fail == 0 else "Fallido con incidentes"
    result_style = "background:#EAF3DE;color:#3B6D11;" if fail == 0 else "background:#FCEBEB;color:#791F1F;"

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
            # Saltar contenedores de versión (ej: "Versión 16.10") — son sub-UHs, no módulos reales
            _VERSION_RE = re.compile(r'^[Vv]ersi[oó]n\s+\d+[\.\d]*$')
            if _VERSION_RE.match(us_title.strip()):
                continue
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

def build_alcance_data(uh_id):
    """Trae los hijos directos de la UH de alcance separados en Bugs y Tasks."""
    if not uh_id:
        return {"total":0,"uh_title":"","bugs":[],"tasks":[]}
    uh = get_work_item(uh_id)
    if "_error" in uh:
        return {"total":0,"uh_title":f"Error UH {uh_id}","bugs":[],"tasks":[]}

    uh_title  = uh.get("fields",{}).get("System.Title", f"UH #{uh_id}")
    children  = get_work_item_children(uh_id)

    bugs  = []
    tasks = []
    for child in children:
        f      = child.get("fields",{})
        wi_type= f.get("System.WorkItemType","")
        title  = f.get("System.Title","Sin título")
        state  = f.get("System.State","")
        wi_id  = child["id"]
        item   = {"id": wi_id, "title": title, "state": state}
        if wi_type == "Bug":
            bugs.append(item)
        elif wi_type in ("Task", "Requirement", "Issue"):
            tasks.append(item)
        # Ignorar UH/Feature en la lista de implementaciones/nuevas funcionalidades

    return {
        "uh_id":   uh_id,
        "uh_title": uh_title,
        "total":   len(bugs) + len(tasks),
        "bugs":    bugs,
        "tasks":   tasks,
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
    ip = pct(failed, t)  # solo failed cuenta como incidencia

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
        {'<div style="font-size:13px;color:#3d3d3a;margin-bottom:10px;">Casos con incidencia: <b>' + str(failed) + ' (' + str(ip) + '%)</b></div>' if failed > 0 else ''}
        {_bar(c, t)}
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">
          {_pill("Passed",   passed,  "background:#EAF3DE;color:#3B6D11;")}
          {_pill("Failed",   failed,  "background:#FCEBEB;color:#791F1F;") if failed else ""}
          {_pill("Blocked",  blocked, "background:#FAEEDA;color:#633806;") if blocked else ""}
          {_pill("Not Applicable", notrun, "background:#F1EFE8;color:#5F5E5A;") if notrun else ""}
        </div>
      </div>
    </section>"""

def _alcance_block(alcance_data):
    """Sección 1 — muestra todos los bugs y tasks del alcance abiertamente."""
    if not alcance_data or alcance_data["total"] == 0:
        return ""

    def state_pill(state):
        closed = state.lower() in ("closed","resolved","done","cerrado","resuelto")
        style  = f"background:#EAF3DE;color:#3B6D11;" if closed else "background:#E6EBEF;color:#1D546D;"
        return f'<span style="font-size:11px;font-weight:600;padding:2px 10px;border-radius:20px;{style}">{state}</span>'

    def build_rows(items):
        closed_states = {"closed","resolved","done","cerrado","resuelto"}
        sorted_items = sorted(items, key=lambda x: (1 if x["state"].lower() in closed_states else 0))
        return "".join(
            f'<tr style="border-top:1px solid #EDECEA;">'
            f'<td style="padding:10px 14px;font-size:12px;color:#888;">#{item["id"]}</td>'
            f'<td style="padding:10px 14px;font-size:13px;color:#3d3d3a;">{item["title"]}</td>'
            f'<td style="padding:10px 10px;text-align:center;">{state_pill(item["state"])}</td>'
            f'</tr>'
            for item in sorted_items
        )

    html = f"""
    <div style="margin-top:12px; border-top: 1px solid #EDECEA; padding-top: 12px;">
      <div style="font-size:11px; font-weight:600; color:{ACCENT_COLOR}; text-transform:uppercase; letter-spacing:.05em; margin-bottom:12px;">
        {alcance_data["uh_title"]} (Total: {alcance_data["total"]} ítems)
      </div>"""

    def _collapsible_table(title, count, items):
        if not items: return ""
        rows = build_rows(items)
        return f"""
        <details style="margin-bottom:10px; border:1px solid #EDECEA; border-radius:10px; background:#fff; overflow:hidden;" open>
          <summary style="padding:10px 14px; background:#FAFAF8; font-size:11px; font-weight:700; color:#3d3d3a; text-transform:uppercase; cursor:pointer; list-style:none; display:flex; justify-content:space-between; align-items:center;">
            <span>{title} ({count})</span>
            <span style="font-size:10px; color:#888;">[Click para contraer/expandir]</span>
          </summary>
          <div style="border-top:1px solid #EDECEA;">
            <table style="width:100%; border-collapse:collapse;">
              <thead>
                <tr style="background:#F5F4F0;">
                  <th style="padding:7px 14px; text-align:left; font-size:10px; color:#888;">#</th>
                  <th style="padding:7px 14px; text-align:left; font-size:10px; color:#888;">Título</th>
                  <th style="padding:7px 10px; text-align:center; font-size:10px; color:#888;">Estado</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
        </details>"""

    html += _collapsible_table("Implementaciones / Nuevas Funcionalidades", len(alcance_data["tasks"]), alcance_data["tasks"])
    html += _collapsible_table("Incidentes planificados", len(alcance_data["bugs"]), alcance_data["bugs"])

    html += "</div>"
    return html

def _incidents_block(inc_data, section_num="4.1", title="Incidentes detectados durante las pruebas del ciclo", bug_label="Detalle de bugs"):
    # Mostrar estructura completa incluso sin incidentes (similar a "No Aplica")
    if not inc_data or inc_data["total"] == 0:
        return f"""<section style="margin-bottom:20px;background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;">
      <div style="padding:16px 20px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <div style="font-size:11px;font-weight:700;color:{SECONDARY_COLOR};text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;">{section_num}</div>
            <div style="font-size:16px;font-weight:600;color:{PRIMARY_COLOR};margin-bottom:3px;">{title}</div>
          </div>
          <div style="text-align:right;background:{SECONDARY_COLOR};color:#fff;padding:8px 18px;border-radius:10px;">
            <div style="font-size:10px;text-transform:uppercase;font-weight:600;opacity:0.8;">Total Incidentes</div>
            <div style="font-size:24px;font-weight:700;">0</div>
          </div>
        </div>
      </div>
      <div style="padding:20px;text-align:center;color:#888;font-size:13px;background:#FAFAF8;">No se encontraron incidentes — N/A</div>
    </section>"""

    total  = inc_data["total"]
    by_sev = inc_data["by_sev"]

    sev_pills = "".join(_sev_pill(s, len(by_sev.get(s,[]))) for s in ["Crítico","Alto","Mediano","Bajo"] if by_sev.get(s))
    # Mostrar cantidad absoluta por criticidad (no %)
    sev_counts_line = "  ·  ".join(
        f'<b>{s}s: {len(by_sev.get(s,[]))}</b>'
        for s in ["Crítico","Alto","Mediano","Bajo"] if by_sev.get(s)
    )

    # Donut charts
    sev_colors = {"Crítico":"#E24B4A", "Alto":"#D88C3A", "Mediano":"#ECC21D", "Bajo":"#5F9598"}
    chart_id   = f"c{abs(hash(section_num+str(total)))%99999}"
    sev_labels = [s for s in ["Crítico","Alto","Mediano","Bajo"] if by_sev.get(s)]
    sev_vals   = [len(by_sev[s]) for s in sev_labels]
    sev_cols   = [sev_colors[s] for s in sev_labels]
    
    # Ordenamiento por cantidad de incidentes (de mayor a menor)
    sorted_modules = sorted(inc_data["by_module"].items(), key=lambda x: sum(x[1].values()), reverse=True)
    
    # Truncar nombres de módulos a máximo 30 caracteres para mejor visualización en gráficos
    mod_labels = [m[:30] + "..." if len(m) > 30 else m for m, _ in sorted_modules][:6]
    mod_vals   = [sum(v.values()) for _, v in sorted_modules][:6]
    mod_cols   = [SECONDARY_COLOR, ACCENT_COLOR, PRIMARY_COLOR, "#d1d1d1", "#8baeb0", "#487182"]

    mod_rows = "".join(
        f'<tr style="border-top:1px solid #EDECEA;">'
        f'<td style="padding:11px 16px;font-size:14px;color:#3d3d3a;">{mod}</td>'
        f'<td style="padding:11px 8px;text-align:center;font-size:14px;color:#3d3d3a;font-weight:600;">{sum(sv.values())}</td>'
        f'<td style="padding:11px 8px;text-align:center;font-size:14px;font-weight:600;color:{SECONDARY_COLOR};">{pct(sum(sv.values()), total)}%</td>'
        f'<td style="padding:11px 14px;">{"".join(_sev_pill(s,sv.get(s,0)) for s in ["Crítico","Alto","Mediano","Bajo"] if sv.get(s,0))}</td>'
        f'</tr>'
        for mod, sv in sorted_modules
    )

    bug_rows = ""
    sev_edge_colors = {"Crítico":"#E24B4A", "Alto":"#D88C3A", "Mediano":"#ECC21D", "Bajo":"#5F9598"}
    
    for idx, inc in enumerate(inc_data["incidents"]):
        edge_col = sev_edge_colors.get(inc["sev"], "#888")
        # Zebra: par #F9F8F6, impar #fff
        row_bg = "#F9F8F6" if idx % 2 == 1 else "#ffffff"
        
        bug_rows += (
            f'<tr style="border-top:1px solid #E4E2DF; background:{row_bg};">'
            f'<td style="padding:11px 14px; padding-left:12px; font-size:12px; color:#888; border-left:3px solid {edge_col};">'
            f'#{inc["id"]}</td>'
            f'<td style="padding:11px 14px; font-size:14px; color:#3d3d3a;">{inc["title"]}</td>'
            f'<td style="padding:11px 8px; text-align:center;">{_sev_pill(inc["sev"])}</td>'
            f'<td style="padding:11px 8px; text-align:center;">'
            f'<span style="font-size:12px; font-weight:600; padding:2px 10px; border-radius:20px;'
            f'{"background:#EAF3DE;color:#3B6D11;" if inc["state"].lower() in ("closed","resolved","done","cerrado","resuelto") else "background:#F1EFE8;color:#5F5E5A;"}">'
            f'{inc["state"]}</span></td>'
            f'</tr>'
        )

    return f"""
    <section id="incidentes_{section_num}" style="margin-bottom:24px;background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;">
      <div style="padding:16px 20px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <div style="font-size:11px;font-weight:700;color:{SECONDARY_COLOR};text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;">{section_num}</div>
            <div style="font-size:16px;font-weight:600;color:{PRIMARY_COLOR};margin-bottom:3px;">{title}</div>
            <div style="font-size:13px;color:#888;">{inc_data.get('uh_title','')}</div>
          </div>
          <div style="text-align:right;background:{SECONDARY_COLOR};color:#fff;padding:8px 18px;border-radius:10px;">
            <div style="font-size:10px;text-transform:uppercase;font-weight:600;opacity:0.8;">Total Incidentes</div>
            <div style="font-size:24px;font-weight:700;">{total}</div>
          </div>
        </div>
      </div>
      <div style="padding:10px 20px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:5px;">
          {sev_pills}
        </div>
        <div style="font-size:12px;color:#888;">Cantidad por criticidad — {sev_counts_line}</div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;padding:24px 20px;border-bottom:1px solid #EDECEA;">
        <div style="text-align:center;">
          <div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:16px;">Por criticidad</div>
          <canvas id="{chart_id}_s" width="320" height="320" style="max-width:320px;margin:0 auto;display:block;"></canvas>
        </div>
        <div style="text-align:center;">
          <div style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:16px;">Por módulo / funcionalidad</div>
          <canvas id="{chart_id}_m" width="320" height="320" style="max-width:320px;margin:0 auto;display:block;"></canvas>
        </div>
      </div>
      <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
      <script>
      (function(){{
        // Plugin para mostrar porcentajes dentro del donut
        var percentagePlugin = {{
          id: 'textCenter',
          afterDatasetsDraw: function(chart) {{
            var ctx = chart.ctx;
            var centerX = chart.chartArea.left + chart.chartArea.width / 2;
            var centerY = chart.chartArea.top + chart.chartArea.height / 2;
            var radius = Math.min(chart.chartArea.width, chart.chartArea.height) / 2;
            var innerRadius = radius * 0.6;
            
            var data = chart.data.datasets[0].data;
            var total = data.reduce(function(a, b) {{ return a + b; }}, 0);
            
            var angle = 0;
            for (var i = 0; i < data.length; i++) {{
              var value = data[i];
              var percentage = Math.round(value / total * 100);
              
              // Ángulo medio de la sección
              var sectionAngle = (value / total) * 2 * Math.PI;
              var midAngle = angle + sectionAngle / 2;
              
              // Posición del texto
              var x = centerX + Math.cos(midAngle - Math.PI / 2) * ((innerRadius + radius) / 2);
              var y = centerY + Math.sin(midAngle - Math.PI / 2) * ((innerRadius + radius) / 2);
              
              // Dibujar porcentaje
              ctx.save();
              ctx.font = 'bold 14px Arial';
              ctx.fillStyle = '#ffffff';
              ctx.textAlign = 'center';
              ctx.textBaseline = 'middle';
              ctx.shadowColor = 'rgba(0,0,0,0.5)';
              ctx.shadowBlur = 3;
              ctx.fillText(percentage + '%', x, y);
              ctx.restore();
              
              angle += sectionAngle;
            }}
          }}
        }};
        
        // Tooltip mejorado con cantidad + porcentaje
        var ttCb = {{
          label: function(ctx) {{
            var sum = ctx.chart.data.datasets[0].data.reduce(function(a,b){{return a+b}},0);
            var count = ctx.parsed;
            var p = Math.round(count / sum * 100);
            return ' ' + ctx.label + ': ' + count + ' incidentes (' + p + '%)';
          }}
        }};
        
        var ttOpts = {{
          enabled:true,
          backgroundColor:'rgba(30,30,30,.95)',
          titleFont:{{size:12,weight:'600'}},
          bodyFont:{{size:11}},
          padding:10,
          cornerRadius:8,
          callbacks:ttCb
        }};
        
        // Leyenda con etiquetas truncadas para módulos largos
        var legOpts = {{
          position:'bottom',
          labels:{{
            font:{{size:12,weight:'500'}},
            padding:14,
            usePointStyle:true,
            pointStyle:'rectRounded',
            boxWidth:14,
            boxHeight:10
          }}
        }};
        
        // Chart de severidad (criticidad)
        new Chart(document.getElementById('{chart_id}_s'),{{
          type:'doughnut',
          data:{{
            labels:{sev_labels},
            datasets:[{{
              data:{sev_vals},
              backgroundColor:{sev_cols},
              borderWidth:3,
              borderColor:'#fff',
              hoverBorderWidth:4,
              hoverOffset:8
            }}]
          }},
          options:{{
            responsive:true,
            maintainAspectRatio:true,
            plugins:{{
              tooltip:ttOpts,
              legend:legOpts,
              percentagePlugin: percentagePlugin
            }},
            cutout:'60%'
          }},
          plugins:[percentagePlugin]
        }});
        
        // Chart de módulos
        new Chart(document.getElementById('{chart_id}_m'),{{
          type:'doughnut',
          data:{{
            labels:{mod_labels},
            datasets:[{{
              data:{mod_vals},
              backgroundColor:{mod_cols},
              borderWidth:3,
              borderColor:'#fff',
              hoverBorderWidth:4,
              hoverOffset:8
            }}]
          }},
          options:{{
            responsive:true,
            maintainAspectRatio:true,
            plugins:{{
              tooltip:ttOpts,
              legend:legOpts,
              percentagePlugin: percentagePlugin
            }},
            cutout:'60%'
          }},
          plugins:[percentagePlugin]
        }});
      }})();
      </script>
      <div style="padding:12px 20px;display:flex;align-items:center;justify-content:space-between;cursor:pointer;
                  background:#FAFAF8;border-top:1px solid #EDECEA;border-bottom:1px solid #EDECEA;
                  transition:background .15s;"
           onmouseover="this.style.background='#F1F0EC'" onmouseout="this.style.background='#FAFAF8'"
           onclick="var tbl=this.closest('section').querySelector('.mod-table'); var arrow=this.querySelector('.mod-arrow'); if(tbl.style.display==='none'){{ tbl.style.display='table'; arrow.style.transform='rotate(90deg)'; }} else {{ tbl.style.display='none'; arrow.style.transform='rotate(0deg)'; }}">
        <span style="font-size:12px;font-weight:600;color:#5F5E5A;text-transform:uppercase;letter-spacing:.06em;">Desglose por módulo / funcionalidad ({len(inc_data['by_module'])} módulos)</span>
        <span class="mod-arrow" style="font-size:12px;color:#888;transition:transform .2s;display:inline-block;transform:rotate(90deg);">&#9654;</span>
      </div>
      <table class="mod-table" style="width:100%;border-collapse:collapse;margin-bottom:8px;display:table;">
        <thead><tr style="background:#F5F4F0;">
          <th style="padding:7px 16px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Módulo</th>
          <th style="padding:7px 8px;text-align:center;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Total</th>
          <th style="padding:7px 8px;text-align:center;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">% del total</th>
          <th style="padding:7px 14px;text-align:left;font-size:10px;font-weight:500;color:#888;text-transform:uppercase;">Desglose</th>
        </tr></thead>
        <tbody>{mod_rows}</tbody>
      </table>
      <div style="padding:12px 20px;display:flex;align-items:center;justify-content:space-between;cursor:pointer;
                  background:#FAFAF8;border-top:1px solid #EDECEA;border-bottom:1px solid #EDECEA;
                  margin-top:6px;transition:background .15s;"
           onmouseover="this.style.background='#F1F0EC'" onmouseout="this.style.background='#FAFAF8'"
           onclick="var tbl=this.closest('section').querySelector('.inc-table'); var arrow=this.querySelector('.toggle-arrow'); if(tbl.style.display==='none'){{ tbl.style.display='table'; arrow.style.transform='rotate(90deg)'; }} else {{ tbl.style.display='none'; arrow.style.transform='rotate(0deg)'; }}">
        <span style="font-size:12px;font-weight:600;color:#5F5E5A;text-transform:uppercase;letter-spacing:.06em;">{bug_label} ({len(inc_data['incidents'])})</span>
        <span class="toggle-arrow" style="font-size:12px;color:#888;transition:transform .2s;display:inline-block;transform:rotate(90deg);">&#9654;</span>
      </div>
      <table class="inc-table" style="width:100%;border-collapse:collapse;display:table;">
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
def generate_report_html(form, demo_data=None):
    """Orquestador principal que construye el HTML final."""
    version = form.get("version", "vX")
    print(f"\n>>> [LOG] Generando reporte para versión: {version}")
    now     = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    if demo_data:
        # MODO DEMO
        prod    = form.get("producto","SALUS WEB")
        version = form.get("version","v1.0")
        ciclo   = form.get("ciclo","1")
        agrup   = form.get("agrupador","DEMO")
        result  = form.get("resultado","Exitoso")
        fi_plan = form.get("fecha_inicio_plan","01/01/2026")
        ff_plan = form.get("fecha_fin_plan","15/01/2026")
        fi_real = form.get("fecha_inicio_real","01/01/2026")
        ff_real = form.get("fecha_fin_real","15/01/2026")
        alcance      = form.get("alcance", [])
        resps        = form.get("responsables", [])
        riesgos      = form.get("riesgos","")
        observaciones= form.get("observaciones","")
        
        alcance_data = demo_data["alcance"]
        inc_data     = demo_data["inc"]
        prev_data_42 = demo_data.get("prev_42")
        prev_data_43 = demo_data.get("prev_43")
        total_all    = demo_data["total_all"]
        pass_all     = demo_data["pass_all"]
        fail_all     = demo_data["fail_all"]
        block_all    = demo_data["block_all"]
        notrun_all   = demo_data["notrun_all"]
        plans_data   = demo_data.get("plans", [])
    else:
        # MODO REAL
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
        alcance_id   = int(form.get("alcance_uh_id", 0)) if form.get("alcance_uh_id","").strip().isdigit() else None
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
        prev_uh_id = int(form.get("prev_uh_id", 0)) if form.get("prev_uh_id","").strip().isdigit() else None

        alcance_data = build_alcance_data(alcance_id) if alcance_id else None
        inc_data     = build_incident_data(uh_id)
        # 4.2 / 4.2.1: bugs del alcance actual (alcance_id), separados por estado (closed vs no-closed)
        prev_data_42 = build_incident_data(alcance_id) if alcance_id else None
        # 4.3: pendiente de corrección solo a partir del ciclo anterior real
        prev_data_43 = build_incident_data(prev_uh_id) if prev_uh_id else None

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
            fail_cnt  = c_s.get("failed",0)
            pass_cnt  = c_s.get("passed",0)
            if pass_cnt + fail_cnt > 0:
                ip = pct(fail_cnt, pass_cnt + fail_cnt)
            else:
                ip = 0
            # Etiqueta descriptiva estandarizada
            if fail_cnt == 0:
                res_txt   = "Exitoso"
                res_style = "background:#EAF3DE;color:#3B6D11;"
            elif ip <= 10:
                res_txt   = "Exitoso con incidentes menores"
                res_style = "background:#FAEEDA;color:#633806;"
            elif ip <= 30:
                res_txt   = "Con incidencias moderadas"
                res_style = "background:#E6F1FB;color:#185FA5;"
            else:
                res_txt   = "Con incidencias críticas"
                res_style = "background:#FCEBEB;color:#791F1F;"
            res_pill = f'<span style="font-size:11px;font-weight:600;padding:2px 10px;border-radius:20px;white-space:nowrap;{res_style}">{res_txt}</span>'
            det_rows += (f'<tr style="border-top:1px solid #EDECEA;">'
                         f'<td style="padding:8px 20px;font-size:13px;color:#888;">{prod} / {pd["name"]}</td>'
                         f'<td style="padding:8px 14px;font-size:13px;color:#3d3d3a;">{s["name"]}</td>'
                         f'<td style="padding:8px 14px;font-size:13px;color:#888;">Funcional</td>'
                         f'<td style="padding:8px 14px;font-size:13px;color:#3d3d3a;">{res_pill}</td>'
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
        title=f"Incidentes detectados durante las pruebas del ciclo {ciclo} — Versión {version} de {prod}",
        bug_label="Detalle de bugs detectados"
    )

    # Sección 4.2 / 4.2.1 / 4.3 — Ciclo anterior + Incidentes de alcance no solucionados
    prev_sections = ""
    
    # 4.2 Paquete de incidentes corregidos (ciclo anterior)
    if prev_data_42 and prev_data_42.get("total",0) > 0:
        resueltos  = [i for i in prev_data_42["incidents"] if i["state"].lower() in ("closed","resolved","done","cerrado","resuelto")]
        prev_res = {
            "uh_title": alcance_data.get("uh_title") if alcance_data else prev_data_42.get("uh_title", ""),
            "incidents": [],
            "total": 0,
            "by_sev": {},
            "by_module": {}
        }
        if resueltos:
            prev_res = dict(prev_data_42)
            prev_res["uh_title"] = alcance_data.get("uh_title") if alcance_data else prev_data_42.get("uh_title", "")
            prev_res["incidents"] = resueltos
            prev_res["total"] = len(resueltos)
            by_sev_r = {}
            by_mod_r = {}
            for i in resueltos:
                s, m = i.get("sev","Bajo"), i.get("module","")
                if s not in by_sev_r: by_sev_r[s] = []
                by_sev_r[s].append(i)
                if m not in by_mod_r: by_mod_r[m] = {}
                if s not in by_mod_r[m]: by_mod_r[m][s] = 0
                by_mod_r[m][s] += 1
            prev_res["by_sev"] = by_sev_r
            prev_res["by_module"] = by_mod_r
            prev_res["total"] = len(resueltos)

        prev_title_42 = alcance_data.get('uh_title') if alcance_data and alcance_data.get('uh_title') else (prev_data_42.get('uh_title') if prev_data_42 else '')
        prev_sections += _incidents_block(
            prev_res,
            section_num="4.2",
            title=f"Paquete de incidentes corregidos ({prev_title_42})",
            bug_label="Detalle de bugs corregidos"
        )
    else:
        # No hay datos de ciclo anterior, mostrar bloque vacío (no aplica)
        prev_sections += _incidents_block(
            {"uh_title":"","incidents":[],"total":0,"by_sev":{},"by_module":{}},
            section_num="4.2",
            title="Paquete de incidentes corregidos (N/A)",
            bug_label="Detalle de bugs corregidos"
        )

    # 4.2.1 Ítems entregados pero no solucionados (del alcance actual, misma fuente que 4.2)
    if prev_data_42 and isinstance(prev_data_42.get("incidents"), list):
        unsolved_incidents = [i for i in prev_data_42["incidents"] if i.get("state","").lower() not in ("closed","resolved","done","cerrado","resuelto")]
        if unsolved_incidents:
            by_sev_u = {}
            by_mod_u = {}
            for i in unsolved_incidents:
                s, m = i["sev"], i["module"]
                if s not in by_sev_u: by_sev_u[s] = []
                by_sev_u[s].append(i)
                if m not in by_mod_u: by_mod_u[m] = {}
                if s not in by_mod_u[m]: by_mod_u[m][s] = 0
                by_mod_u[m][s] += 1

            unsolved_inc_data = {
                "total": len(unsolved_incidents),
                "uh_title": prev_data_42["uh_title"],
                "incidents": sorted(unsolved_incidents, key=lambda x: _sev_order(x.get("sev","Bajo"))),
                "by_sev": by_sev_u,
                "by_module": by_mod_u,
            }
            prev_sections += _incidents_block(
                unsolved_inc_data,
                section_num="4.2.1",
                title=f"Ítems entregados pero no solucionados del ciclo actual ({version})",
                bug_label="Detalle de bugs no solucionados"
            )

    # 4.3 Incidencias pendientes de corrección (ciclo anterior)
    pendientes = []
    prev_pend = {
        "uh_title": "",
        "incidents": [],
        "total": 0,
        "by_sev": {},
        "by_module": {}
    }

    if prev_data_43 and isinstance(prev_data_43.get("incidents"), list):
        inc_list = prev_data_43["incidents"]
        pendientes = [i for i in inc_list if i.get("state","").lower() not in ("closed","resolved","done","cerrado","resuelto")]
        prev_pend["uh_title"] = prev_data_43.get("uh_title", "")

    if pendientes:
        prev_pend["incidents"] = pendientes
        prev_pend["total"] = len(pendientes)

        by_sev_p = {}
        by_mod_p = {}
        for i in pendientes:
            s, m = i.get("sev", "Bajo"), i.get("module", "")
            if s not in by_sev_p: by_sev_p[s] = []
            by_sev_p[s].append(i)
            if m not in by_mod_p: by_mod_p[m] = {}
            if s not in by_mod_p[m]: by_mod_p[m][s] = 0
            by_mod_p[m][s] += 1

        prev_pend["by_sev"] = by_sev_p
        prev_pend["by_module"] = by_mod_p

    prev_sections += _incidents_block(
        prev_pend,
        section_num="4.3",
        title=f"Incidencias pendientes de corrección de la Versión anterior ({prev_pend.get('uh_title','')})",
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
    body{{font-family:'DM Sans',sans-serif;background:#F3F4F4;color:#061E29;padding:32px 24px;line-height:1.65;font-weight:500;}}
    h2{{font-size:13px;font-weight:700;color:#1D546D;text-transform:uppercase;letter-spacing:.08em;margin:16px 0 12px;display:flex;align-items:center;gap:8px;}}
    h2::before{{content:'';display:inline-block;width:3px;height:14px;background:{ACCENT_COLOR};border-radius:2px;}}
    h1, h2, h3, .subtitle{{ font-weight: 600 !important; }}
    
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ font-size: 12px; font-weight: 600 !important; color: #444 !important; text-transform: uppercase; padding: 11px 14px; text-align: left; background: #F5F4F0; }}
    td {{ font-size: 14px; font-weight: 500; padding: 11px 14px; color: #3d3d3a; }}
    
    .btn-export:hover {{ background: {SECONDARY_COLOR} !important; opacity: 0.9; transform: translateY(-1px); transition: all 0.2s; }}
    .nav-link {{ color: {SECONDARY_COLOR}; text-decoration: none; font-size: 12px; font-weight: 600; }}
    .nav-link:hover {{ text-decoration: underline; }}

    @media print{{
        body{{background:#fff;padding:0;}}
        .no-print{{display:none !important;}}
        table, td, th {{ font-size: 12pt !important; }}
        tr {{ page-break-inside: avoid !important; }}
    }}
  </style>
</head>
<body>
<div style="max-width:960px;margin:0 auto;">

  <!-- Header -->
  <div style="background:{PRIMARY_COLOR};border-radius:12px 12px 0 0;padding:28px 32px;color:{BG_COLOR};">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;">
      <div>
        <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.12em;margin-bottom:8px;opacity:0.8;">{agrup}</div>
        <h1 style="font-size:28px;font-weight:600;">Informe Final de Pruebas</h1>
        <div style="font-size:15px;margin-top:4px;opacity:0.9;">{prod} · Ciclo {ciclo} · {version}</div>
      </div>
      <div style="display:flex;gap:10px;align-items:center;">
        <span style="font-size:12px;font-weight:600;padding:6px 16px;border-radius:8px;
          background:{BG_COLOR};color:{PRIMARY_COLOR};border:1px solid rgba(255,255,255,0.2);">{result or "—"}</span>
        <button class="no-print btn-export" onclick="window.print()" style="padding:6px 16px;border-radius:8px;
          border:none;background:{ACCENT_COLOR};color:#fff;font-family:inherit;font-size:12px;font-weight:600;cursor:pointer;">Exportar PDF</button>
      </div>
    </div>
  </div>

  <!-- Indice de Navegacion -->
  <div class="no-print" style="background:#fff; border:1px solid #EDECEA; border-top:none; padding:12px 32px; display:flex; gap:20px; flex-wrap:wrap; border-bottom: 2px solid #F3F4F4;">
    <a href="#especificaciones" class="nav-link">Especificaciones</a>
    <a href="#detalle" class="nav-link">Detalle de pruebas</a>
    <a href="#resultados" class="nav-link">Resultados</a>
    <a href="#incidentes" class="nav-link">Incidentes</a>
    <a href="#riesgos" class="nav-link">Riesgos</a>
  </div>

  <div style="background:#fff;border-radius:0 0 12px 12px;border:1px solid #EDECEA;border-top:none;padding:24px 32px;margin-bottom:24px;">
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:24px;">
      <div>
        <div style="font-size:10px;color:#888;text-transform:uppercase;font-weight:600;letter-spacing:.05em;margin-bottom:6px;">Producto</div>
        <div style="font-size:14px;font-weight:600;color:{PRIMARY_COLOR};">{prod}</div>
        <div style="font-size:12px;color:#888;margin-top:2px;">Versión {version}</div>
      </div>
      <div>
        <div style="font-size:10px;color:#888;text-transform:uppercase;font-weight:600;letter-spacing:.05em;margin-bottom:6px;">Plan de ejecución</div>
        <div style="font-size:12px;color:#3d3d3a;">
          <span style="color:#888;">Planificado:</span> {fi_plan} → {ff_plan}<br>
          <span style="color:#888;">Real:</span> {fi_real} → {ff_real}
        </div>
      </div>
      <div>
        <div style="font-size:10px;color:#888;text-transform:uppercase;font-weight:600;letter-spacing:.05em;margin-bottom:6px;">Responsables de ejecución</div>
        <ul style="list-style:none;padding:0;">{resp_li}</ul>
      </div>
    </div>
  </div>

  <!-- 1. Especificaciones -->
  <div id="especificaciones" style="background:#fff;border-radius:12px;border:1px solid #EDECEA;padding:16px 20px;margin-bottom:24px;">
    <h2>1 · Especificaciones</h2>
    <div style="font-size:11px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Alcance {version}</div>
    <ul style="padding-left:18px;">{alc_li}</ul>
    {_alcance_block(alcance_data) if alcance_data else ""}
  </div>

  <!-- 2. Detalle de pruebas -->
  <div id="detalle" style="background:#fff;border-radius:12px;border:1px solid #EDECEA;overflow:hidden;margin-bottom:24px;">
    <div style="padding:13px 20px;border-bottom:1px solid #EDECEA;background:#FAFAF8;">
      <h2 style="margin:0;">2 · Detalle de pruebas</h2>
    </div>
    <table>
      <thead><tr>
        <th>Producto</th>
        <th>Título / Descripción</th>
        <th>Tipo de prueba</th>
        <th>Resultado</th>
      </tr></thead>
      <tbody>{det_rows}</tbody>
    </table>
  </div>

  <!-- 3. Resultados -->
  <div id="resultados" style="margin-bottom:12px;"><h2>3 · Resultados de las pruebas</h2></div>
  <div style="display:grid;grid-template-columns:1.5fr repeat(4, 1fr);gap:16px;margin-bottom:24px;">
    <div style="background:{PRIMARY_COLOR};border-radius:12px;padding:16px 20px;color:#fff;">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;opacity:0.8;">Total Casos</div>
      <div style="font-size:32px;font-weight:700;margin:6px 0 4px;">{total_all}</div>
      <div style="font-size:12px;opacity:0.8;">Casos totales ejecutados</div>
    </div>
    <div style="background:#EBF7F2;border-radius:12px;padding:16px 20px;border:1px solid #C2E7D9;">
      <div style="font-size:11px;font-weight:700;color:#2D6A4F;text-transform:uppercase;letter-spacing:.05em;">Passed</div>
      <div style="font-size:28px;font-weight:700;color:#1B4332;margin:4px 0 2px;">{pass_all}</div>
      <div style="font-size:11px;font-weight:600;color:#2D6A4F;">{pct(pass_all,total_all)}%</div>
    </div>
    <div style="background:#FDF2F2;border-radius:12px;padding:16px 20px;border:1px solid #F9D6D6;">
      <div style="font-size:11px;font-weight:700;color:#A32D2D;text-transform:uppercase;letter-spacing:.05em;">Failed</div>
      <div style="font-size:28px;font-weight:700;color:#501313;margin:4px 0 2px;">{fail_all}</div>
      <div style="font-size:11px;font-weight:600;color:#A32D2D;">{pct(fail_all,total_all)}%</div>
    </div>
    <div style="background:#FFF9F0;border-radius:12px;padding:16px 20px;border:1px solid #FFE8CC;">
      <div style="font-size:11px;font-weight:700;color:#854F0B;text-transform:uppercase;letter-spacing:.05em;">Blocked</div>
      <div style="font-size:28px;font-weight:700;color:#412402;margin:4px 0 2px;">{block_all}</div>
      <div style="font-size:11px;font-weight:600;color:#854F0B;">{pct(block_all,total_all)}%</div>
    </div>
    <div style="background:#F8F9F9;border-radius:12px;padding:16px 20px;border:1px solid #E5E7EB;">
      <div style="font-size:11px;font-weight:700;color:#4B5563;text-transform:uppercase;letter-spacing:.05em;">Not Run</div>
      <div style="font-size:28px;font-weight:700;color:#1F2937;margin:4px 0 2px;">{notrun_all}</div>
      <div style="font-size:11px;font-weight:600;color:#4B5563;">{pct(notrun_all,total_all)}%</div>
    </div>
  </div>
  {suite_cards}

  <!-- 4. Incidentes -->
  <div id="incidentes" style="background:#fff;border-radius:12px;border:1px solid #EDECEA;padding:14px 20px;margin-bottom:12px;">
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
def home():
    total = Informe.query.count()
    return render_template("home.html", total_informes=total)

@app.route("/generar")
def index():
    return render_template("index.html")

@app.route("/generar-demo")
def index_demo():
    """Versión demo del formulario: sin datos de equipo, pre-llenado con Franco Osuna."""
    return render_template("index.html", demo_mode=True, demo_responsable="Franco Osuna")

@app.route("/api/plan-name")
def plan_name():
    plan_id = request.args.get("id","")
    if not plan_id.isdigit():
        return jsonify({"error": "ID inválido"}), 400
    info = get_test_plan(int(plan_id))
    if "_error" in info:
        return jsonify({"error": f"No se encontró el plan {plan_id}"}), 404
    return jsonify({"name": info.get("name","")})

@app.route("/api/workitem-name")
def workitem_name():
    wi_id = request.args.get("id","")
    if not wi_id.isdigit():
        return jsonify({"error": "ID inválido"}), 400
    wi = get_work_item(int(wi_id))
    if "_error" in wi or not wi:
        return jsonify({"error": f"Work Item #{wi_id} no existe en Azure DevOps"}), 404
    
    wi_type = wi.get("fields", {}).get("System.WorkItemType", "Work Item")
    name = wi.get("fields", {}).get("System.Title", "")
    
    return jsonify({"name": name, "type": wi_type})

@app.route("/api/teams")
def api_teams():
    teams = _get_all_teams()
    return jsonify([{"id": t["id"], "name": t["name"]} for t in teams])

@app.route("/generate", methods=["POST"])
def generate():
    team_id = request.form.get("team_id", "").strip()
    if team_id.isdigit() and DATABASE_URL:
        team = _get_team_by_id(int(team_id))
        if team:
            g.team_pat     = team["azure_pat"]
            g.team_org     = team["azure_org"]
            g.team_project = team["azure_project"]
        else:
            return "Error: equipo no encontrado.", 400
    elif not PAT:
        return "Error: AZURE_DEVOPS_PAT no configurado y no se seleccionó equipo.", 500
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

@app.route("/analyzer")
def analyzer():
    return render_template("analyzer.html")

@app.route("/demo")
def demo_report():
    """Genera un reporte de ejemplo con datos realistas (sin Azure PAT)."""
    prod    = "Demo App"
    version = "v18.3.0"
    ciclo   = "N°3"
    agrup   = "AGRUPADOR FUNCIONAL"
    result  = "Fallido con incidentes críticos y altos"
    fi_plan = "24/03/2026"; ff_plan = "07/04/2026"
    fi_real = "24/03/2026"; ff_real = "09/04/2026"
    resps   = ["Franco Osuna"]
    alcance = ["Smoke Test", "Paquete de incidencias", "Pruebas integrales"]
    riesgos = "Inestabilidad en el ambiente de integración durante ventanas de deploy nocturno."
    observaciones = "Se requiere hotfix urgente en módulo de Formulario del Caso antes del próximo release."

    # ── Mock alcance_data (sección 1) ──────────────────────────
    alc_data = {
        "uh_id": 91200, "uh_title": "CT3. Alcance funcional v18.3.0",
        "total": 7,
        "bugs": [
            {"id": 91101, "title": "Adjuntos DICOM no se procesan al guardar el caso", "state": "Active"},
            {"id": 91102, "title": "Timeout en generación de reportes de consultas masivos", "state": "Active"},
            {"id": 91103, "title": "Doble carga al confirmar turno por doble click", "state": "Closed"},
        ],
        "tasks": [
            {"id": 91110, "title": "Refactor módulo de Autenticación SSO", "state": "Done"},
            {"id": 91111, "title": "Integración con API de Padrones SISA", "state": "In Progress"},
            {"id": 91112, "title": "Mejora de performance en grilla de Historial Clínico", "state": "Done"},
            {"id": 91113, "title": "Nuevo panel de Liquidaciones y Facturación", "state": "To Do"},
        ]
    }

    # ── Mock planes y suites (secciones 2 y 3) ─────────────────
    def _mk_suite(name, passed, failed, blocked=0, notrun=0):
        total = passed + failed + blocked + notrun
        fail_b = failed + blocked
        if fail_b == 0:
            rl, rs = "Exitoso", "background:#EAF3DE;color:#3B6D11;"
        elif fail_b / total <= 0.10:
            rl, rs = "Exitoso con incidentes menores", "background:#FAEEDA;color:#633806;"
        elif fail_b / total <= 0.30:
            rl, rs = "Con incidencias moderadas", "background:#E6F1FB;color:#185FA5;"
        else:
            rl, rs = "Con incidencias críticas", "background:#FCEBEB;color:#791F1F;"
        return {
            "name": name, "total": total,
            "counts": {"passed": passed, "failed": failed, "blocked": blocked},
            "result_label": rl, "result_style": rs
        }

    plans_mock = [
        {
            "id": 1001, "name": "TC3 — Demo App v18.3.0 · Smoke Test",
            "total": 74, "counts": {"passed": 72, "failed": 2, "blocked": 0},
            "result_label": "Exitoso con incidentes menores", "result_style": "background:#FAEEDA;color:#633806;",
            "suites": [
                _mk_suite("Smoke Test · Formulario del Caso",       25,  2),
                _mk_suite("Smoke Test · Gestión de Turnos",         32,  0),
                _mk_suite("Smoke Test · Autenticación y Accesos",   15,  0),
            ]
        },
        {
            "id": 1002, "name": "TC3 — Demo App v18.3.0 · Paquete de Incidencias",
            "total": 103, "counts": {"passed": 88, "failed": 11, "blocked": 1},
            "result_label": "Con incidencias críticas", "result_style": "background:#FCEBEB;color:#791F1F;",
            "suites": [
                _mk_suite("Formulario del Caso",            36, 5, blocked=1, notrun=2),
                _mk_suite("Gestión de Turnos",              22, 3),
                _mk_suite("Historial Clínico",              18, 2),
                _mk_suite("Integraciones",                  12, 1, notrun=1),
            ]
        },
        {
            "id": 1003, "name": "TC3 — Demo App v18.3.0 · Pruebas Integrales",
            "total": 41, "counts": {"passed": 37, "failed": 2, "blocked": 0},
            "result_label": "Exitoso con incidentes menores", "result_style": "background:#FAEEDA;color:#633806;",
            "suites": [
                _mk_suite("Flujo Alta de Afiliado",                 20, 0),
                _mk_suite("Flujo Autorización + Liquidación",       17, 2, notrun=2),
            ]
        },
    ]

    # ── Mock incidentes ciclo actual (sección 4.1) ──────────────
    mock_incidents = [
        {"id": 91301, "title": "Excepción no controlada al guardar caso con adjunto de tipo DICOM",
         "state": "Active", "sev": "Crítico", "module": "Formulario del Caso"},
        {"id": 91302, "title": "Error 500 al confirmar turno online desde la aplicación móvil",
         "state": "Active", "sev": "Crítico", "module": "Gestión de Turnos"},
        {"id": 91303, "title": "Filtro por fecha no respeta zona horaria en reporte de consultas",
         "state": "Active", "sev": "Alto",    "module": "Historial Clínico"},
        {"id": 91304, "title": "Validación de cobertura retorna vacío para afiliados con plan 210",
         "state": "Active", "sev": "Alto",    "module": "Integraciones"},
        {"id": 91305, "title": "Historial clínico no carga cuando el paciente supera los 500 registros",
         "state": "Active", "sev": "Alto",    "module": "Historial Clínico"},
        {"id": 91306, "title": "Botón 'Confirmar derivación' queda inactivo tras expiración de sesión",
         "state": "Active", "sev": "Alto",    "module": "Formulario del Caso"},
        {"id": 91307, "title": "Etiqueta 'Pendiente de autorización' persiste tras aprobación de solicitud",
         "state": "Active", "sev": "Mediano", "module": "Formulario del Caso"},
        {"id": 91308, "title": "PDF de resumen de turno no incluye médico de cabecera cuando el campo está vacío",
         "state": "Active", "sev": "Mediano", "module": "Gestión de Turnos"},
        {"id": 91309, "title": "Texto truncado en modal de confirmación de baja de afiliado",
         "state": "Active", "sev": "Bajo",    "module": "Liquidaciones"},
        {"id": 91310, "title": "Color de fondo incorrecto en fila seleccionada de grilla de liquidaciones",
         "state": "Active", "sev": "Bajo",    "module": "Liquidaciones"},
    ]
    by_sev_i = defaultdict(list)
    by_mod_i = defaultdict(lambda: defaultdict(int))
    for i in mock_incidents:
        by_sev_i[i["sev"]].append(i)
        by_mod_i[i["module"]][i["sev"]] += 1
    inc_data = {
        "uh_id": 91200, "uh_title": "CT3. Ciclo de testing 3",
        "total": len(mock_incidents),
        "incidents": mock_incidents,
        "by_sev": dict(by_sev_i),
        "by_module": {m: dict(v) for m, v in by_mod_i.items()}
    }

    # ── Mock prev_42 (bugs del alcance — mezcla closed/active → 4.2 y 4.2.1) ──
    mock_prev_42_incidents = [
        {"id": 90801, "title": "Doble carga de formulario al confirmar turno por doble click",
         "state": "Closed", "sev": "Alto",    "module": "Gestión de Turnos"},
        {"id": 90802, "title": "Campos del formulario no se limpian al cambiar de afiliado",
         "state": "Closed", "sev": "Mediano", "module": "Formulario del Caso"},
        {"id": 90803, "title": "Error de CORS intermitente al consultar endpoint de autorizaciones",
         "state": "Closed", "sev": "Alto",    "module": "Integraciones"},
        {"id": 90804, "title": "Timeout al generar reportes de consultas con más de 3 meses de rango",
         "state": "Active", "sev": "Alto",    "module": "Historial Clínico"},
        {"id": 90805, "title": "Paginación omite el último registro en listado de afiliados filtrado",
         "state": "Active", "sev": "Mediano", "module": "Autenticación y Accesos"},
    ]
    by_sev_42 = defaultdict(list)
    by_mod_42 = defaultdict(lambda: defaultdict(int))
    for i in mock_prev_42_incidents:
        by_sev_42[i["sev"]].append(i)
        by_mod_42[i["module"]][i["sev"]] += 1
    prev_42_data = {
        "uh_id": 90800, "uh_title": "CT2. Alcance funcional v18.2.0",
        "total": len(mock_prev_42_incidents),
        "incidents": mock_prev_42_incidents,
        "by_sev": dict(by_sev_42),
        "by_module": {m: dict(v) for m, v in by_mod_42.items()}
    }

    # ── Mock prev_43 (ciclo anterior — solo bugs pendientes importan para 4.3) ──
    mock_prev_43_incidents = [
        {"id": 89901, "title": "Fallo de sincronización con SISA durante actualizaciones de padrón nocturnas",
         "state": "Active", "sev": "Alto",    "module": "Integraciones"},
        {"id": 89902, "title": "Búsqueda de afiliado por DNI retorna resultados duplicados",
         "state": "Active", "sev": "Alto",    "module": "Autenticación y Accesos"},
        {"id": 89903, "title": "Spinner de carga no desaparece tras error de red en Gestión de Turnos",
         "state": "Active", "sev": "Mediano", "module": "Gestión de Turnos"},
    ]
    by_sev_43 = defaultdict(list)
    by_mod_43 = defaultdict(lambda: defaultdict(int))
    for i in mock_prev_43_incidents:
        by_sev_43[i["sev"]].append(i)
        by_mod_43[i["module"]][i["sev"]] += 1
    prev_43_data = {
        "uh_id": 89900, "uh_title": "CT2. Ciclo de testing 2",
        "total": len(mock_prev_43_incidents),
        "incidents": mock_prev_43_incidents,
        "by_sev": dict(by_sev_43),
        "by_module": {m: dict(v) for m, v in by_mod_43.items()}
    }

    # ── Totales globales ────────────────────────────────────────
    total_all = 218; pass_all = 197; fail_all = 15; block_all = 1; notrun_all = 5

    html, _ = generate_report_html({
        "producto": prod, "version": version, "ciclo": ciclo, "agrupador": agrup,
        "resultado": result,
        "fecha_inicio_plan": fi_plan, "fecha_fin_plan": ff_plan,
        "fecha_inicio_real": fi_real, "fecha_fin_real": ff_real,
        "responsables": resps, "alcance": alcance,
        "riesgos": riesgos, "observaciones": observaciones,
        "plan_ids": ["1001", "1002", "1003"]
    }, demo_data={
        "alcance":   alc_data,
        "inc":       inc_data,
        "prev_42":   prev_42_data,
        "prev_43":   prev_43_data,
        "plans":     plans_mock,
        "total_all": total_all, "pass_all": pass_all,
        "fail_all":  fail_all,  "block_all": block_all, "notrun_all": notrun_all,
    })

    return Response(html, mimetype="text/html")

# ── Admin routes ───────────────────────────────────────────────
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin_ok"] = True
            return redirect(url_for("admin"))
        error = "Contraseña incorrecta."
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin_ok", None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
def admin():
    if not _admin_authed():
        return redirect(url_for("admin_login"))
    teams = _get_all_teams()
    return render_template("admin.html", teams=teams)

@app.route("/admin/new", methods=["POST"])
def admin_new():
    if not _admin_authed():
        return redirect(url_for("admin_login"))
    name    = request.form.get("name", "").strip()
    slug    = request.form.get("slug", "").strip()
    org     = request.form.get("azure_org", ORGANIZATION).strip()
    project = request.form.get("azure_project", PROJECT).strip()
    pat     = request.form.get("azure_pat", "").strip()
    if not name or not slug or not pat:
        return redirect(url_for("admin"))
    _create_team(name, slug, org, project, pat)
    return redirect(url_for("admin"))

@app.route("/admin/edit/<int:team_id>", methods=["GET", "POST"])
def admin_edit(team_id):
    if not _admin_authed():
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        name    = request.form.get("name", "").strip()
        slug    = request.form.get("slug", "").strip()
        org     = request.form.get("azure_org", ORGANIZATION).strip()
        project = request.form.get("azure_project", PROJECT).strip()
        pat     = request.form.get("azure_pat", "").strip()
        _update_team(team_id, name, slug, org, project, pat)
        return redirect(url_for("admin"))
    team = _get_team_by_id(team_id)
    if not team:
        return redirect(url_for("admin"))
    return render_template("admin_edit.html", team=team)

@app.route("/admin/delete/<int:team_id>", methods=["POST"])
def admin_delete(team_id):
    if not _admin_authed():
        return redirect(url_for("admin_login"))
    _delete_team(team_id)
    return redirect(url_for("admin"))

# ── Historial routes ───────────────────────────────────────────
@app.route("/save", methods=["POST"])
def save_informe():
    equipo   = request.form.get("equipo", "").strip()
    producto = request.form.get("producto", "").strip()
    version  = request.form.get("version", "").strip()
    ciclo    = request.form.get("ciclo", "").strip()
    html     = request.form.get("html_content", "")
    if not equipo or not producto or not html:
        return jsonify({"error": "Faltan campos requeridos"}), 400
    informe = Informe(equipo=equipo, producto=producto,
                      version=version, ciclo=ciclo, html=html)
    db.session.add(informe)
    db.session.commit()
    return jsonify({"ok": True, "id": informe.id})

@app.route("/historial")
def historial():
    informes = Informe.query.order_by(Informe.fecha_generacion.desc()).all()
    grupos = {}
    for inf in informes:
        grupos.setdefault(inf.equipo, {}).setdefault(inf.producto, []).append(inf)
    return render_template("historial.html", grupos=grupos)

@app.route("/historial/<int:informe_id>/download")
def historial_download(informe_id):
    inf = db.get_or_404(Informe, informe_id)
    filename = f"informe_{inf.equipo}_{inf.producto}_{inf.version}_ciclo{inf.ciclo}.html"
    filename = filename.replace(" ", "_").lower()
    return Response(inf.html, mimetype="text/html",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})

@app.route("/historial/<int:informe_id>/preview")
def historial_preview(informe_id):
    inf = db.get_or_404(Informe, informe_id)
    return Response(inf.html, mimetype="text/html")

@app.route("/historial/<int:informe_id>/delete", methods=["POST"])
def historial_delete(informe_id):
    inf = db.get_or_404(Informe, informe_id)
    db.session.delete(inf)
    db.session.commit()
    return redirect(url_for("historial"))

# ── Startup ────────────────────────────────────────────────────
try:
    init_db()
except Exception as e:
    print(f"[WARN] init_db falló: {e}")
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"[WARN] db.create_all falló: {e}")

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))