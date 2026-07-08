"""Minimal async client for the local Ollama HTTP API."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

DEFAULT_BASE_URL = "http://localhost:11434"

# Local models can take a while to load on the first call, so the read timeout
# is long; the connect timeout stays short so a missing daemon fails fast.
_TIMEOUT = httpx.Timeout(connect=3.0, read=180.0, write=30.0, pool=180.0)


class OllamaError(RuntimeError):
    """Ollama is unreachable or returned an error response."""


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size_bytes: int
    family: str
    parameter_size: str


class OllamaClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")

    async def list_models(self) -> list[ModelInfo]:
        data = await self._request("GET", "/api/tags")
        models = [
            ModelInfo(
                name=entry.get("name", "<unknown>"),
                size_bytes=int(entry.get("size", 0)),
                family=(entry.get("details") or {}).get("family") or "",
                parameter_size=(entry.get("details") or {}).get("parameter_size") or "",
            )
            for entry in data.get("models", [])
        ]
        return sorted(models, key=lambda m: m.name)

    async def generate(self, model: str, prompt: str, system: str | None = None) -> str:
        payload: dict[str, object] = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        data = await self._request("POST", "/api/generate", payload)
        return str(data.get("response", ""))

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.request(method, f"{self._base_url}{path}", json=json)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text.strip()
            raise OllamaError(
                f"Ollama returned HTTP {exc.response.status_code} for {path}"
                + (f": {body}" if body else ".")
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Could not reach Ollama at {self._base_url}. Is the daemon running? "
                "Start it with 'ollama serve' (or set LLM_REDTEAM_OLLAMA_URL)."
            ) from exc
