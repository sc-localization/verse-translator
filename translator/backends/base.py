from __future__ import annotations

from abc import ABC, abstractmethod


class ContextTooLongError(Exception):
    """Raised when a batch exceeds the model's context window."""


class TranslatorBackend(ABC):
    """Common interface for all translation backends."""

    @abstractmethod
    def translate_batch(self, values: list[str], system_prompt: str) -> list[str]:
        """
        Translate a list of EN strings.

        Args:
            values: source strings (extracted values, not key=value lines)
            system_prompt: instruction block built by the pipeline

        Returns:
            translated strings, same length and order as input
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str: ...
