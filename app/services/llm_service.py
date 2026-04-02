import httpx
import json
import re
from app.config import settings

OLLAMA_GENERATE_URL = f"{settings.OLLAMA_URL}/api/generate"


async def ollama_generate(prompt: str, model: str = "llama3.2", timeout: int = 60) -> str:
    """Call Ollama and return the generated text."""
    payload = {"model": model, "prompt": prompt, "stream": False,
               "format": "json", "options": {"temperature": 0.7, "num_predict": 3000}}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(OLLAMA_GENERATE_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")


def extract_json(raw: str) -> dict | list:
    """Try to extract JSON from LLM raw output."""
    raw = raw.strip()
    # LLM may wrap output in markdown fences
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    if match:
        raw = match.group(1)
    return json.loads(raw)
