"""Vercel Python serverless function — webhook do bot Telegram pessoal."""

from http.server import BaseHTTPRequestHandler
import json
import os
import requests


# ── GitHub helpers ────────────────────────────────────────────────────────────

def _gh_headers():
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo():
    return os.environ.get("GITHUB_ISSUES_REPO", "marcianotonattors/agente-orquestrador")


def gh_list_issues(labels=None):
    params = {"state": "open", "per_page": 50}
    if labels:
        params["labels"] = labels
    resp = requests.get(
        f"https://api.github.com/repos/{_repo()}/issues",
        headers=_gh_headers(),
        params=params,
    )
    resp.raise_for_status()
    return [i for i in resp.json() if "pull_request" not in i]


def gh_create_issue(title, body="", labels=None):
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    resp = requests.post(
        f"https://api.github.com/repos/{_repo()}/issues",
        headers=_gh_headers(),
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()


def gh_close_issue(number):
    requests.patch(
        f"https://api.github.com/repos/{_repo()}/issues/{number}",
        headers=_gh_headers(),
        json={"state": "closed"},
    ).raise_for_status()


# ── Telegram helpers ──────────────────────────────────────────────────────────

def tg_send(chat_id, text):
    requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        },
    )


# ── Command handlers ──────────────────────────────────────────────────────────

HELP = """\
*Comandos disponíveis:*
/nova <título> — Cria issue
/nova <título> | <descrição> — Com descrição
/nova <título> | <desc> | <label1,label2> — Com labels
/fechar <número> — Fecha issue
/listar — Issues abertas
/urgente — Issues urgentes
/ajuda — Este menu"""


def handle(text: str, chat_id: int) -> str:
    text = text.strip()

    if text.startswith("/nova"):
        parts = [p.strip() for p in text[5:].strip().split("|")]
        title = parts[0] if parts else ""
        if not title:
            return "Use: /nova Título da tarefa"
        body = parts[1] if len(parts) > 1 else ""
        labels = [l.strip() for l in parts[2].split(",")] if len(parts) > 2 else []
        issue = gh_create_issue(title, body, labels or None)
        return f"✅ Issue criada: [#{issue['number']} {issue['title']}]({issue['html_url']})"

    if text.startswith("/fechar"):
        num_str = text[7:].strip()
        try:
            gh_close_issue(int(num_str))
            return f"✅ Issue #{num_str} fechada."
        except (ValueError, TypeError):
            return "Use: /fechar <número>"

    if text == "/listar":
        issues = gh_list_issues()
        if not issues:
            return "Nenhuma issue aberta. 🎉"
        lines = [f"• #{i['number']} {i['title']}" for i in issues[:20]]
        return "*Issues abertas:*\n" + "\n".join(lines)

    if text == "/urgente":
        issues = gh_list_issues(labels="urgente")
        if not issues:
            return "Nenhuma issue urgente. ✅"
        lines = [f"• #{i['number']} {i['title']}" for i in issues]
        return "*Urgentes:*\n" + "\n".join(lines)

    if text in ("/ajuda", "/start", "/help"):
        return HELP

    return "Comando não reconhecido. Use /ajuda."


# ── Vercel handler ────────────────────────────────────────────────────────────

ALLOWED_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        message = body.get("message") or body.get("edited_message")
        if message:
            chat_id = message.get("chat", {}).get("id", 0)
            text = message.get("text", "")
            if chat_id == ALLOWED_CHAT_ID and text.startswith("/"):
                try:
                    reply = handle(text, chat_id)
                except Exception as e:
                    reply = f"❌ Erro: {e}"
                tg_send(chat_id, reply)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *args):
        pass
