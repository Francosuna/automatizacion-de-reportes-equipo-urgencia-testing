import os, json, base64, urllib.request, urllib.error

ORGANIZATION = 'osde-devops'
PROJECT = 'Desarrollo_Salus'
PAT = 'f3m63vvev44pxtpndp3p7g5k533rpxp73r74d7u5u7u5u7u5u7u5' # Dummy or use OS env
PAT = os.environ.get('AZURE_DEVOPS_PAT', '')
BASE_URL = f'https://dev.azure.com/{ORGANIZATION}/{PROJECT}/_apis'

def _headers():
    token = base64.b64encode(f':{PAT}'.encode()).decode()
    return {'Content-Type': 'application/json', 'Authorization': f'Basic {token}'}

def _get(url):
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode()}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

ids = '92472,92731,92563,90262'
res = _get(f'{BASE_URL}/wit/workitems?ids={ids}&$expand=fields&api-version=7.0')
if res:
    print(json.dumps(res, indent=2))
else:
    print("No response or error.")
