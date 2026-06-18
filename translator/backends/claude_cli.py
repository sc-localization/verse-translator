from __future__ import annotations

from translator.backends.cli_base import CLIBackend


class ClaudeCLIBackend(CLIBackend):
    """claude --print "..." — free via Claude Pro subscription."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        self.model = model

    @property
    def name(self) -> str:
        return f"claude-cli/{self.model}"

    def build_command(self, prompt: str) -> list[str]:
        return ["claude", "--model", self.model, "--print", prompt]
