#!/usr/bin/env python3
"""Registra ou remove o webhook do bot Telegram.

Uso:
  python setup_webhook.py registrar <url>
  python setup_webhook.py remover
  python setup_webhook.py status
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests


def _token():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("Erro: TELEGRAM_BOT_TOKEN não definido.")
    return token


def registrar(url: str):
    resp = requests.post(
        f"https://api.telegram.org/bot{_token()}/setWebhook",
        json={"url": url, "allowed_updates": ["message"]},
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("ok"):
        print(f"✓ Webhook registrado: {url}")
    else:
        sys.exit(f"Erro: {result.get('description')}")


def remover():
    resp = requests.post(
        f"https://api.telegram.org/bot{_token()}/deleteWebhook"
    )
    resp.raise_for_status()
    print("✓ Webhook removido.")


def status():
    resp = requests.get(
        f"https://api.telegram.org/bot{_token()}/getWebhookInfo"
    )
    resp.raise_for_status()
    info = resp.json().get("result", {})
    url = info.get("url") or "(nenhum)"
    pending = info.get("pending_update_count", 0)
    last_err = info.get("last_error_message", "")
    print(f"URL: {url}")
    print(f"Pendentes: {pending}")
    if last_err:
        print(f"Último erro: {last_err}")


if __name__ == "__main__":
    cmds = {"registrar": registrar, "remover": remover, "status": status}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "registrar":
        if len(sys.argv) < 3:
            sys.exit("Uso: python setup_webhook.py registrar <url>")
        registrar(sys.argv[2])
    else:
        cmds[cmd]()
