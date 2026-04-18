import os
import requests
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional


GITHUB_API = "https://api.github.com"


@dataclass
class Issue:
    number: int
    title: str
    body: str
    labels: list
    state: str
    url: str
    created_at: str
    updated_at: str


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo() -> str:
    return os.environ.get("GITHUB_ISSUES_REPO", "marcianotonattors/agente-orquestrador")


def _to_issue(raw: dict) -> Issue:
    return Issue(
        number=raw["number"],
        title=raw["title"],
        body=raw.get("body") or "",
        labels=[lbl["name"] for lbl in raw["labels"]],
        state=raw["state"],
        url=raw["html_url"],
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
    )


def list_issues(state: str = "open", labels: Optional[str] = None) -> list:
    params = {"state": state, "per_page": 100}
    if labels:
        params["labels"] = labels

    resp = requests.get(
        f"{GITHUB_API}/repos/{_repo()}/issues",
        headers=_headers(),
        params=params,
    )
    resp.raise_for_status()
    return [_to_issue(i) for i in resp.json() if "pull_request" not in i]


def create_issue(title: str, body: str = "", labels: list = None) -> Issue:
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels

    resp = requests.post(
        f"{GITHUB_API}/repos/{_repo()}/issues",
        headers=_headers(),
        json=payload,
    )
    resp.raise_for_status()
    return _to_issue(resp.json())


def close_issue(number: int, comment: str = None) -> None:
    if comment:
        requests.post(
            f"{GITHUB_API}/repos/{_repo()}/issues/{number}/comments",
            headers=_headers(),
            json={"body": comment},
        ).raise_for_status()

    requests.patch(
        f"{GITHUB_API}/repos/{_repo()}/issues/{number}",
        headers=_headers(),
        json={"state": "closed"},
    ).raise_for_status()


def get_failed_workflows(repo: str = None) -> list:
    target = repo or _repo()
    resp = requests.get(
        f"{GITHUB_API}/repos/{target}/actions/runs",
        headers=_headers(),
        params={"status": "failure", "per_page": 10},
    )
    resp.raise_for_status()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = []
    for run in resp.json().get("workflow_runs", []):
        run_time = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        if run_time > cutoff:
            recent.append({
                "name": run["name"],
                "url": run["html_url"],
                "created_at": run["created_at"],
            })
    return recent
