import os, json, base64, urllib.request, urllib.error

ORGANIZATION = 'osde-devops'
PROJECT = 'Desarrollo_Salus'
PAT = os.environ.get('AZURE_DEVOPS_PAT', '')
BASE_URL = f'https://dev.azure.com/{ORGANIZATION}/{PROJECT}/_apis'

def _headers():
    token = base64.b64encode(f':{PAT}'.encode()).decode()
    return {'Content-Type': 'application/json', 'Authorization': f'Basic {token}'}

def _get(url):
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            if not raw: return {}
            return json.loads(raw)
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return {}

ids = '92472,92731,92563,90262'
wi_url = f'{BASE_URL}/wit/workitems?ids={ids}&$expand=relations&api-version=7.0'
res = _get(wi_url)

if "value" in res:
    for item in res["value"]:
        f = item.get("fields", {})
        print(f"ID: {item['id']}, Type: {f.get('System.WorkItemType')}, Title: {f.get('System.Title')}")
        relations = item.get("relations", [])
        children = [r for r in relations if r.get("rel") == "System.LinkTypes.Hierarchy-Forward"]
        print(f"  Children count: {len(children)}")
else:
    print("Could not fetch work items. Response empty or error.")
