from __future__ import annotations

import json
import urllib.request

from translator.backends.base import TranslatorBackend

_USER_INSTRUCTION = (
    "Translate the following JSON array of strings.\n"
    "Return ONLY a valid JSON array of the same length, no explanations.\n"
    "Keep variables (~func(), @tag, %ls, \\n, {0}, <tags>) unchanged.\n\n"
)


class LMStudioBackend(TranslatorBackend):
    """
    LM Studio local server — OpenAI-compatible HTTP API on localhost.
    Start server in LM Studio UI, then run this backend.
    Completely free, runs locally.
    Default port: 1234.
    """

    def __init__(
        self, model: str = "local-model", host: str = "localhost", port: int = 1234
    ) -> None:
        self.model = model
        self._url = f"http://{host}:{port}/v1/chat/completions"

    @property
    def name(self) -> str:
        return f"lmstudio/{self.model}"

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
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

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
