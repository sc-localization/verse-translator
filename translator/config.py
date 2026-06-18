from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    # Input / output
    input_path: Path = Path("global.ini")
    output_dir: Path = Path("output/translations")
    version: str = "LIVE"

    # Language
    source_lang: str = "English"
    target_lang: str = "Russian"
    target_lang_code: str = "ru"

    # Batching
    batch_size: int = 50

    # Resilience
    max_retries: int = 3
    retry_delay_seconds: float = 2.0

    @property
    def output_path(self) -> Path:
        return self.output_dir / self.version / self.target_lang_code / "global.ini"
