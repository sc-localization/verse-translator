from __future__ import annotations

from translator.backends.cli_base import CLIBackend


class GeminiCLIBackend(CLIBackend):
    """
    Google Gemini via agy CLI — `agy -p "..."`.
    Install: https://antigravity.google/docs/cli-using
    Auth: Google account.
    """

    def __init__(self, model: str = "gemini-2.5-flash") -> None:
        self.model = model

    @property
    def name(self) -> str:
        return f"agy/{self.model}"

    def build_command(self, prompt: str) -> list[str]:
        return ["agy", "--model", self.model, "-p", prompt]
