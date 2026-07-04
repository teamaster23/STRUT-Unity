from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener


DEFAULT_LOCAL_OLLAMA_MODEL = "qwen3.5:latest"


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    api_key: str
    timeout_seconds: int = 600

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls.from_values()

    @classmethod
    def from_values(
        cls,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> "LLMConfig":
        base_url = base_url or os.getenv("STRUT_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
        model = model or os.getenv("STRUT_LLM_MODEL")
        if not model:
            if _is_local_url(base_url):
                model = _default_local_ollama_model(base_url)
            else:
                raise ValueError("STRUT_LLM_MODEL is required for non-local LLM endpoints.")
        api_key = api_key if api_key is not None else os.getenv("STRUT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        timeout = int(os.getenv("STRUT_LLM_TIMEOUT", "600"))
        return cls(base_url=base_url.rstrip("/"), model=model, api_key=api_key, timeout_seconds=timeout)


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.from_env()

    def chat_completion(self, messages: list[dict], temperature: float = 0.2) -> str:
        url = f"{self.config.base_url}/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        opener = build_opener(ProxyHandler({})) if _is_local_url(self.config.base_url) else build_opener()
        request = Request(url, data=body, headers=headers, method="POST")
        with opener.open(request, timeout=self.config.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


def _is_local_url(url: str) -> bool:
    host = urlparse(url).hostname
    return host in {"localhost", "127.0.0.1", "::1"}


def _default_local_ollama_model(base_url: str) -> str:
    try:
        result = subprocess.run(
            ["ollama", "list"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return DEFAULT_LOCAL_OLLAMA_MODEL

    installed_models = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            installed_models.append(parts[0])
    for model in installed_models:
        normalized = model.lower()
        if "qwen3.5" in normalized:
            return model
    return DEFAULT_LOCAL_OLLAMA_MODEL


def write_llm_trace(build_dir: str | Path, function_name: str, prompt: list[dict], response: str) -> dict:
    build = Path(build_dir)
    prompt_path = build / f"{function_name}_llm_prompt.json"
    response_path = build / f"{function_name}_llm_response.txt"
    prompt_path.write_text(json.dumps(_trace_prompt(prompt), indent=2), encoding="utf-8")
    response_path.write_text(response, encoding="utf-8")
    return {"llm_prompt": str(prompt_path), "llm_response": str(response_path)}


def _trace_prompt(prompt: list[dict]) -> list[dict]:
    return [_trace_message(message) for message in prompt]


def _trace_message(message: dict) -> dict:
    traced = dict(message)
    content = traced.get("content")
    if isinstance(content, str):
        traced["content"] = _readable_content(content)
    return traced


def _readable_content(content: str) -> dict:
    return {
        "raw": content,
        "lines": content.splitlines(),
        "sections": _content_sections(content),
    }


def _content_sections(content: str) -> list[dict]:
    markers = {
        "Function Context Database:": "function_context_database",
        "Function Source Code:": "function_source_code",
        "Structured Seed Cases:": "structured_seed_cases",
        "Current structured test suite:": "current_structured_test_suite",
    }

    sections: list[dict] = []
    current_title = "instructions"
    current_lines: list[str] = []

    for line in content.splitlines():
        if line in markers:
            _append_section(sections, current_title, current_lines)
            current_title = markers[line]
            current_lines = []
            continue
        current_lines.append(line)

    _append_section(sections, current_title, current_lines)
    return sections


def _append_section(sections: list[dict], title: str, lines: list[str]) -> None:
    if title == "instructions" and not any(line.strip() for line in lines):
        return

    section = {"title": title}
    if title == "function_source_code":
        language, code_lines = _strip_fenced_code(lines)
        if language:
            section["language"] = language
        section["code"] = "\n".join(code_lines)
    else:
        text = "\n".join(lines).strip()
        parsed = _try_parse_json(text)
        if parsed is None:
            section["lines"] = lines
        else:
            section["json"] = parsed
    sections.append(section)


def _strip_fenced_code(lines: list[str]) -> tuple[str | None, list[str]]:
    stripped = list(lines)
    while stripped and not stripped[0].strip():
        stripped.pop(0)
    while stripped and not stripped[-1].strip():
        stripped.pop()

    if len(stripped) >= 2 and stripped[0].startswith("```") and stripped[-1] == "```":
        language = stripped[0][3:].strip() or None
        return language, stripped[1:-1]
    return None, stripped


def _try_parse_json(text: str):
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
