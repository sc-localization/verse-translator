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


class LMStudioBackend(TranslatorBackend):
    """
    LM Studio local server — OpenAI-compatible HTTP API on localhost.
    Automatically loads the model via LM Studio API if not already loaded.
    Default port: 1234.
    """

    def __init__(
        self, model: str = "local-model", host: str = "localhost", port: int = 1234
    ) -> None:
        self.model = model
        self._base_url = f"http://{host}:{port}"
        self._url = f"{self._base_url}/v1/chat/completions"

    @property
    def name(self) -> str:
        return f"lmstudio/{self.model}"

    def ensure_model_loaded(self) -> None:
        """Check if model is loaded; load it if not. Blocks until ready."""
        if self._is_model_loaded():
            logger.debug("Model %s already loaded", self.model)
            return

        print(f"  Model {self.model!r} not loaded — requesting LM Studio to load it...")
        self._request_load()

        while not self._is_model_loaded():
            time.sleep(_LOAD_POLL_INTERVAL)

        print(f"  Model {self.model!r} loaded.\n")

    def _is_model_loaded(self) -> bool:
        try:
            req = urllib.request.Request(f"{self._base_url}/api/v1/models")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            loaded = [m.get("id", "") for m in data.get("data", [])]
            return any(self.model in m_id for m_id in loaded)
        except Exception:
            return False

    def _request_load(self) -> None:
        body = json.dumps({"identifier": self.model}).encode()
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
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.3,
            }
        ).encode()

        req = urllib.request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode(errors="replace")
            if e.code == 400 and "context" in body_text:
                raise ContextTooLongError(body_text) from e
            raise RuntimeError(f"LM Studio {e.code}: {body_text}") from e

        output: str = data["choices"][0]["message"]["content"]

        return _parse_json_response(output, expected_len=len(values))


def _parse_json_response(output: str, expected_len: int) -> list[str]:
    start = output.find("[")
    end = output.rfind("]")

    if start == -1 or end == -1:
        raise ValueError(f"No JSON array found in response:\n{output[:500]}")

    parsed: list[str] = json.loads(output[start : end + 1])

    if len(parsed) != expected_len:
        raise ValueError(f"Expected {expected_len} translations, got {len(parsed)}")

    return parsed
