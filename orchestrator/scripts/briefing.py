import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import anthropic
from github_client import list_issues, Issue
from telegram_client import send_message


SYSTEM_PROMPT = """Você é o assistente pessoal do Marciano Tonatto, profissional de BIM e coordenador de projetos.
Gere briefings matinais concisos em português brasileiro com base nas issues abertas do GitHub.

Regras:
- Seja direto, sem introduções longas
- Agrupe por contexto usando labels: BIM/Curso, Nordika, Consultorias, Pessoal, Viagens
- Destaque issues com label "urgente" ou "prazo"
- Sugira 2-3 prioridades do dia
- Use emojis com moderação para facilitar leitura no Telegram
- Máximo 800 caracteres no total"""


def _format_issues(issues: list) -> str:
    if not issues:
        return "Nenhuma issue aberta."
    lines = []
    for i in issues:
        labels_str = f"[{', '.join(i.labels)}] " if i.labels else ""
        lines.append(f"#{i.number} {labels_str}{i.title}")
        if i.body:
            lines.append(f"  {i.body[:150]}")
    return "\n".join(lines)


def generate_briefing(issues: list) -> str:
    client = anthropic.Anthropic()
    today = date.today().strftime("%A, %d/%m/%Y")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Data: {today}\n\nIssues abertas:\n{_format_issues(issues)}\n\nGere o briefing matinal.",
            }
        ],
    )
    return response.content[0].text


def main():
    issues = list_issues(state="open")
    briefing = generate_briefing(issues)
    send_message(f"☀️ *Briefing Matinal*\n\n{briefing}")
    print(f"Briefing enviado. Issues abertas: {len(issues)}")


if __name__ == "__main__":
    main()
