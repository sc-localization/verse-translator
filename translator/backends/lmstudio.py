from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from translator.backends.base import ContextTooLongError, TranslatorBackend

logger = logging.getLogger(__name__)

_USER_INSTRUCTION = (
    "Translate the following JSON array of strings.\n"
    "Return ONLY a valid JSON array of the same length, no explanations.\n"
    "Keep variables (~func(), @tag, %ls, \\n, {0}, <tags>) unchanged.\n\n"
)

_LOAD_POLL_INTERVAL = 2.0  # seconds between status checks
_LOAD_TIMEOUT = 120  # seconds before giving up on model load

# Reserve half the context for output; input takes the other half
_DEFAULT_CONTEXT_LENGTH = 8192
_DEFAULT_MAX_OUTPUT_TOKENS = _DEFAULT_CONTEXT_LENGTH // 2


class LMStudioBackend(TranslatorBackend):
    """
    LM Studio local server — native /api/v1/chat endpoint.
    Automatically loads the model via LM Studio API if not already loaded.
    Default port: 1234.
    """

    def __init__(
        self,
        model: str = "local-model",
        host: str = "localhost",
        port: int = 1234,
        context_length: int = _DEFAULT_CONTEXT_LENGTH,
        max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        self.model = model
        self._base_url = f"http://{host}:{port}"
        self._context_length = context_length
        self._max_output_tokens = max_output_tokens

    @property
    def name(self) -> str:
        return f"lmstudio/{self.model}"

    def ensure_model_loaded(self) -> None:
        """Check if model is loaded; load it if not. Blocks until ready."""
        loaded, ctx = self._model_status()
        if loaded:
            logger.debug("Model %s already loaded", self.model)
            self._apply_context_length(ctx)
            return

        print(f"  Model {self.model!r} not loaded — requesting LM Studio to load it...")
        self._request_load()

        ctx = None
        elapsed = 0.0
        while elapsed < _LOAD_TIMEOUT:
            loaded, ctx = self._model_status()
            if loaded:
                break
            time.sleep(_LOAD_POLL_INTERVAL)
            elapsed += _LOAD_POLL_INTERVAL
        else:
            raise RuntimeError(
                f"Timed out waiting for model {self.model!r} to load in LM Studio "
                f"({_LOAD_TIMEOUT}s). Check the model name or download it manually."
            )

        self._apply_context_length(ctx)
        print(f"  Model {self.model!r} loaded.\n")

    def _apply_context_length(self, ctx: int | None) -> None:
        if ctx and ctx != self._context_length:
            self._context_length = ctx
            self._max_output_tokens = ctx // 2
            logger.debug("Context length set to %d tokens", ctx)

    def _model_status(self) -> tuple[bool, int | None]:
        """Return (is_loaded, context_length_or_None)."""
        try:
            req = urllib.request.Request(f"{self._base_url}/api/v1/models")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            for m in data.get("models", []):
                if m.get("key") == self.model:
                    instances = m.get("loaded_instances", [])
                    if instances:
                        ctx = instances[0].get("config", {}).get("context_length")
                        return True, ctx
                    return False, None
            return False, None
        except Exception:
            return False, None

    def _request_load(self) -> None:
        body = json.dumps({"model": self.model}).encode()
        req = urllib.request.Request(
            f"{self._base_url}/api/v1/models/load",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            body_text = e.read().decode(errors="replace")
            raise RuntimeError(f"LM Studio failed to load model: {body_text}") from e

    def translate_batch(self, values: list[str], system_prompt: str) -> list[str]:
        user_content = _USER_INSTRUCTION + json.dumps(values, ensure_ascii=False)
        body = json.dumps(
            {
                "model": self.model,
                "system_prompt": system_prompt,
                "input": user_content,
                "temperature": 0.3,
                "context_length": self._context_length,
                "max_output_tokens": self._max_output_tokens,
                "store": False,
            }
        ).encode()

        req = urllib.request.Request(
            f"{self._base_url}/api/v1/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode(errors="replace")
            if e.code == 400 and "context" in body_text.lower():
                raise ContextTooLongError(body_text) from e
            raise RuntimeError(f"LM Studio {e.code}: {body_text}") from e

        messages = [
            item for item in data.get("output", []) if item.get("type") == "message"
        ]
        if not messages:
            raise ValueError(f"No message in LM Studio response: {data}")

        output: str = messages[-1]["content"]

        return _parse_json_response(output, expected_len=len(values))


def _parse_json_response(output: str, expected_len: int) -> list[str]:
    start = output.find("[")
    end = output.rfind("]")

    if start == -1:
        raise ValueError(f"No JSON array found in response:\n{output[:500]}")

    if end == -1 or end < start:
        # Output was truncated — model hit max_output_tokens
        raise ContextTooLongError("Response truncated: no closing ']' found")

    try:
        parsed, _ = json.JSONDecoder().raw_decode(output, start)
    except json.JSONDecodeError as exc:
        # Splitting the batch often resolves model confusion that causes bad JSON
        raise ContextTooLongError(f"JSON decoding failed: {exc}") from exc

    if len(parsed) != expected_len:
        raise ValueError(f"Expected {expected_len} translations, got {len(parsed)}")

    return parsed
