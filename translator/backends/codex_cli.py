from __future__ import annotations

from translator.backends.cli_base import CLIBackend


class CodexCLIBackend(CLIBackend):
    """
    OpenAI Codex CLI — `codex -q "..."`.
    Install: npm install -g @openai/codex
    Authenticates via OpenAI account (OPENAI_API_KEY).
    """

    def __init__(self, model: str = "o4-mini") -> None:
        self.model = model

    @property
    def name(self) -> str:
        return f"codex-cli/{self.model}"

    def build_command(self, prompt: str) -> list[str]:
        return ["codex", "--model", self.model, "-q", prompt]
