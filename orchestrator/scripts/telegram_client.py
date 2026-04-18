import os
import requests


def _token() -> str:
    return os.environ["TELEGRAM_BOT_TOKEN"]


def _default_chat() -> str:
    return os.environ["TELEGRAM_CHAT_ID"]


def send_message(text: str, chat_id: str = None, parse_mode: str = "Markdown") -> dict:
    resp = requests.post(
        f"https://api.telegram.org/bot{_token()}/sendMessage",
        json={
            "chat_id": chat_id or _default_chat(),
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        },
    )
    resp.raise_for_status()
    return resp.json()


def get_updates(offset: int = None) -> list:
    params = {"timeout": 30}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(
        f"https://api.telegram.org/bot{_token()}/getUpdates",
        params=params,
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


def set_webhook(url: str) -> dict:
    resp = requests.post(
        f"https://api.telegram.org/bot{_token()}/setWebhook",
        json={"url": url},
    )
    resp.raise_for_status()
    return resp.json()
