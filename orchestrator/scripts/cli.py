#!/usr/bin/env python3
"""CLI para gerenciar issues e acionar o orquestrador via terminal / Claude Code."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from github_client import list_issues, create_issue, close_issue


def cmd_list(args):
    issues = list_issues(state=args.state, labels=args.labels)
    if not issues:
        print("Nenhuma issue encontrada.")
        return
    for i in issues:
        labels_str = f" [{', '.join(i.labels)}]" if i.labels else ""
        print(f"#{i.number}{labels_str} {i.title}")
        print(f"  {i.url}")
        if args.verbose and i.body:
            print(f"  {i.body[:200]}")
        print()


def cmd_nova(args):
    title = " ".join(args.titulo)
    labels = [l.strip() for l in args.labels.split(",")] if args.labels else []
    issue = create_issue(title, args.body or "", labels)
    print(f"✓ Issue criada: #{issue.number} {issue.title}")
    print(f"  {issue.url}")


def cmd_fechar(args):
    close_issue(args.numero, comment=args.comentario)
    print(f"✓ Issue #{args.numero} fechada.")


def cmd_briefing(_args):
    from briefing import main
    main()


def cmd_monitor(_args):
    from monitor import main
    main()


def main():
    parser = argparse.ArgumentParser(
        prog="orquestrador",
        description="Agente Orquestrador — gerenciador de pendências pessoais",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="comando")

    p_list = sub.add_parser("listar", help="Listar issues")
    p_list.add_argument("--state", default="open", choices=["open", "closed", "all"])
    p_list.add_argument("--labels", help="Filtrar por labels (vírgula)")
    p_list.add_argument("-v", "--verbose", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_nova = sub.add_parser("nova", help="Criar issue")
    p_nova.add_argument("titulo", nargs="+", help="Título da issue")
    p_nova.add_argument("--body", "-b", help="Descrição")
    p_nova.add_argument("--labels", "-l", help="Labels (vírgula), ex: nordika,urgente")
    p_nova.set_defaults(func=cmd_nova)

    p_fechar = sub.add_parser("fechar", help="Fechar issue")
    p_fechar.add_argument("numero", type=int)
    p_fechar.add_argument("--comentario", "-c", help="Comentário ao fechar")
    p_fechar.set_defaults(func=cmd_fechar)

    p_brief = sub.add_parser("briefing", help="Enviar briefing agora")
    p_brief.set_defaults(func=cmd_briefing)

    p_mon = sub.add_parser("monitor", help="Executar monitoramento agora")
    p_mon.set_defaults(func=cmd_monitor)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    main()
