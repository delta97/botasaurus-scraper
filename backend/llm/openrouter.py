"""Minimal OpenRouter chat-completions client (OpenAI-compatible schema)
with tool calling, usage capture, and basic retries."""
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from .. import config


class LLMError(Exception):
    pass


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: Optional[dict] = None


class OpenRouterClient:
    def __init__(self, api_key, model, base_url=None, timeout=120.0):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or config.OPENROUTER_BASE_URL).rstrip("/")
        self.timeout = timeout

    def chat(self, messages, tools=None, tool_choice=None, temperature=0.0, model=None) -> LLMResponse:
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # Optional OpenRouter attribution headers
            "HTTP-Referer": "https://github.com/delta97/botasaurus-scraper",
            "X-Title": "Botasaurus Automation Studio",
        }

        last_error = None
        for attempt in range(3):
            try:
                resp = httpx.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                if resp.status_code in (429, 500, 502, 503):
                    last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    time.sleep(2 * (attempt + 1))
                    continue
                if resp.status_code != 200:
                    raise LLMError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:500]}")
                return self._parse(resp.json())
            except httpx.HTTPError as exc:
                last_error = str(exc)
                time.sleep(2 * (attempt + 1))
        raise LLMError(f"OpenRouter request failed after retries: {last_error}")

    @staticmethod
    def _parse(data: dict) -> LLMResponse:
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected OpenRouter response shape: {json.dumps(data)[:500]}") from exc

        tool_calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                raise LLMError(f"Model returned invalid tool arguments: {fn.get('arguments')[:300]}")
            tool_calls.append(ToolCall(name=fn.get("name", ""), arguments=args))

        usage = data.get("usage") or {}
        return LLMResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )


def fetch_models(query=None, timeout=30.0):
    """Public endpoint — no API key required."""
    resp = httpx.get(f"{config.OPENROUTER_BASE_URL}/models", timeout=timeout)
    resp.raise_for_status()
    models = []
    for item in resp.json().get("data", []):
        models.append({
            "id": item.get("id"),
            "name": item.get("name"),
            "context_length": item.get("context_length"),
            "pricing": item.get("pricing"),
        })
    if query:
        q = query.lower()
        models = [m for m in models if q in (m["id"] or "").lower() or q in (m["name"] or "").lower()]
    return models
