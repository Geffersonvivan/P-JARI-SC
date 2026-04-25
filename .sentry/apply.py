#!/usr/bin/env python3
"""
Aplica as configurações do sentry.yml via API do Sentry.

Uso:
    export SENTRY_AUTH_TOKEN=<seu_token>   # Settings > Auth Tokens > Create New
    export SENTRY_ORG=<seu_org_slug>       # ex: "p-jari" ou "geffersonvivan"
    python .sentry/apply.py
"""

import os
import sys
import json
import urllib.request
import urllib.error
import yaml   # pip install pyyaml

TOKEN = os.environ.get("SENTRY_AUTH_TOKEN")
ORG   = os.environ.get("SENTRY_ORG")

if not TOKEN or not ORG:
    print("❌  Defina SENTRY_AUTH_TOKEN e SENTRY_ORG antes de rodar.")
    sys.exit(1)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "sentry.yml")
with open(CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)

PROJECT = cfg["project"]
BASE    = "https://sentry.io/api/0"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type":  "application/json",
}


def _request(method, url, data=None):
    body = json.dumps(data).encode() if data else None
    req  = urllib.request.Request(url, data=body, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  ⚠️  HTTP {e.code}: {e.read().decode()}")
        return None


# ── 1. Busca regras existentes ────────────────────────────────────────────────
print(f"\n📡  Buscando regras existentes em {ORG}/{PROJECT}...")
existing = _request("GET", f"{BASE}/projects/{ORG}/{PROJECT}/rules/") or []
existing_names = {r["name"]: r["id"] for r in existing}
print(f"   {len(existing_names)} regras encontradas: {list(existing_names.keys())}")

# ── 2. Cria / atualiza regras do sentry.yml ───────────────────────────────────
for rule in cfg.get("alert_rules", []):
    payload = {
        "name":          rule["name"],
        "environment":   rule.get("environment", "production"),
        "conditions":    rule["conditions"],
        "filters":       rule.get("filters", []),
        "actions":       rule["actions"],
        "actionMatch":   rule.get("action_match", "all"),
        "filterMatch":   rule.get("filter_match", "all"),
        "frequency":     rule.get("frequency", 30),
    }
    name = rule["name"]
    if name in existing_names:
        rid = existing_names[name]
        print(f"\n🔄  Atualizando '{name}' (id={rid})...")
        result = _request("PUT", f"{BASE}/projects/{ORG}/{PROJECT}/rules/{rid}/", payload)
    else:
        print(f"\n✅  Criando '{name}'...")
        result = _request("POST", f"{BASE}/projects/{ORG}/{PROJECT}/rules/", payload)

    if result:
        print(f"   → OK (id={result.get('id')})")

print("\n🎉  Concluído. Verifique em: https://sentry.io/organizations/{ORG}/alerts/rules/\n")
