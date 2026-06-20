from __future__ import annotations

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
