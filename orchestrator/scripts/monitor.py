import os
import sys
import json
import hashlib
import requests
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from github_client import list_issues, get_failed_workflows
from telegram_client import send_message


VERCEL_URL = os.environ.get("VERCEL_URL", "")
PLAYBOOK_REPO = os.environ.get("PLAYBOOK_REPO", "marcianotonattors/agente-playbook")
STATE_FILE = "/tmp/orchestrator_monitor_state.json"


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def _fp(data) -> str:
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()


def check_vercel() -> tuple:
    if not VERCEL_URL:
        return True, ""
    try:
        resp = requests.get(VERCEL_URL, timeout=10)
        if resp.status_code >= 500:
            return False, f"HTTP {resp.status_code}"
        return True, ""
    except requests.exceptions.Timeout:
        return False, "timeout após 10s"
    except requests.exceptions.ConnectionError as e:
        return False, f"conexão recusada"


def check_actions() -> tuple:
    try:
        failures = get_failed_workflows(repo=PLAYBOOK_REPO)
        return len(failures) == 0, failures
    except Exception as e:
        return False, [{"name": f"Erro ao consultar Actions: {e}", "url": "", "created_at": ""}]


def check_urgent() -> list:
    try:
        return list_issues(state="open", labels="urgente")
    except Exception:
        return []


def main():
    state = _load_state()
    alerts = []
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    vercel_ok, vercel_err = check_vercel()
    if not vercel_ok:
        fp = _fp(vercel_err)
        if state.get("vercel_fp") != fp:
            alerts.append(f"🔴 *agente-playbook fora do ar*\n{vercel_err}\n{VERCEL_URL}")
            state["vercel_fp"] = fp
    else:
        state.pop("vercel_fp", None)

    actions_ok, failures = check_actions()
    if not actions_ok:
        fp = _fp([f["name"] for f in failures])
        if state.get("actions_fp") != fp:
            lines = "\n".join(f"• [{f['name']}]({f['url']})" for f in failures[:5])
            alerts.append(f"⚠️ *GitHub Actions com falha*\n{lines}")
            state["actions_fp"] = fp
    else:
        state.pop("actions_fp", None)

    urgent = check_urgent()
    if urgent:
        fp = _fp([f"#{i.number}" for i in urgent])
        if state.get("urgent_fp") != fp:
            lines = "\n".join(f"• #{i.number} {i.title}" for i in urgent[:5])
            alerts.append(f"🚨 *Issues urgentes ({len(urgent)})*\n{lines}")
            state["urgent_fp"] = fp
    else:
        state.pop("urgent_fp", None)

    if alerts:
        msg = f"🤖 *Monitor — {now}*\n\n" + "\n\n".join(alerts)
        send_message(msg)
        print(f"Alertas enviados: {len(alerts)}")
    else:
        print(f"[{now}] Tudo OK.")

    _save_state(state)


if __name__ == "__main__":
    main()
