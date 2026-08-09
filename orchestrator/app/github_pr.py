import os
import httpx

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_API = "https://api.github.com"

async def open_fix_pr(repo: str, branch: str, base: str, title: str, body: str) -> str | None:
    if not GITHUB_TOKEN:
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GITHUB_API}/repos/{repo}/pulls",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            json={"title": title, "head": branch, "base": base, "body": body},
        )
        resp.raise_for_status()
        return resp.json()["html_url"]