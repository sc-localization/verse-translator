from __future__ import annotations

import json
import logging
import subprocess
from abc import abstractmethod

from translator.backends.base import TranslatorBackend

logger = logging.getLogger(__name__)

_USER_INSTRUCTION = (
    "Translate the following JSON array of strings.\n"
    "Return ONLY a valid JSON array of the same length, no explanations.\n"
    "Keep variables (~func(), @tag, %ls, \\n, {0}, <tags>) unchanged.\n\n"
)


class CLIBackend(TranslatorBackend):
    """
    Base for backends that work by spawning a subprocess CLI tool.
    Subclasses only need to implement build_command().
    """

    @abstractmethod
    def build_command(self, prompt: str) -> list[str]:
        """Return the argv list to run, with the full prompt embedded."""
        ...

    def translate_batch(self, values: list[str], system_prompt: str) -> list[str]:
        prompt = (
            system_prompt
            + "\n\n"
            + _USER_INSTRUCTION
            + json.dumps(values, ensure_ascii=False)
        )
        logger.debug("--- PROMPT ---\n%s\n--- END PROMPT ---", prompt)

        cmd = self.build_command(prompt)
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.debug("--- RESPONSE ---\n%s\n--- END RESPONSE ---", result.stdout)

        return _parse_json_response(result.stdout, expected_len=len(values))


def _parse_json_response(output: str, expected_len: int) -> list[str]:
    start = output.find("[")
    end = output.rfind("]")

    if start == -1 or end == -1:
        raise ValueError(f"No JSON array found in response:\n{output[:500]}")

    parsed: list[str] = json.loads(output[start : end + 1])

    if len(parsed) != expected_len:
        raise ValueError(f"Expected {expected_len} translations, got {len(parsed)}")

    return parsed
