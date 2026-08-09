import os
import json
import httpx

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

SYSTEM_PROMPT = """You are an SRE diagnosing a service failure from raw logs.
Given a log excerpt, respond ONLY with JSON (no markdown fences, no preamble):
{
  "root_cause": "<one or two sentences>",
  "confidence": "<low|medium|high>",
  "proposed_fix": "<a short unified diff or plain-English patch description>"
}
"""


async def diagnose(log_excerpt: str, context: str = "") -> dict:
    if not GEMINI_API_KEY:
        return {
            "root_cause": "GEMINI_API_KEY not set — skipping live diagnosis.",
            "confidence": "low",
            "proposed_fix": "",
        }

    user_content = f"Context: {context}\n\nLog excerpt:\n{log_excerpt[-6000:]}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GEMINI_URL,
            params={"key": GEMINI_API_KEY},
            headers={"content-type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": user_content}]}],
                "generationConfig": {"maxOutputTokens": 500, "temperature": 0.2},
            },
        )
        resp.raise_for_status()
        data = resp.json()

    text = ""
    try:
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError):
        text = ""

    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"root_cause": text[:500] or "Diagnosis response was empty or unparseable.", "confidence": "low", "proposed_fix": ""}