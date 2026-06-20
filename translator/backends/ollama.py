from __future__ import annotations

import json
import subprocess

from translator.backends.cli_base import CLIBackend


class OllamaBackend(CLIBackend):
    """
    Local models via Ollama — `ollama run <model> "..."`.
    Install: https://ollama.com  — completely free, runs locally.
    Good models for translation: qwen2.5:14b, mistral, gemma3
    """

    def __init__(self, model: str = "qwen2.5:14b") -> None:
        self.model = model

    @property
    def name(self) -> str:
        return f"ollama/{self.model}"

    def build_command(self, prompt: str) -> list[str]:
        return ["ollama", "run", self.model, prompt]

    def context_length(self) -> int | None:
        try:
            result = subprocess.run(
                ["ollama", "show", self.model, "--json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            data = json.loads(result.stdout)

            for key in ("context_length", "num_ctx"):
                val = data.get("model_info", {}).get(
                    "llama.context_length"
                ) or data.get(key)
                if val:
                    return int(val)

            for k, v in data.get("model_info", {}).items():
                if "context" in k:
                    return int(v)
        except Exception:
            pass

        return None
