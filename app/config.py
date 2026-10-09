from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./certificate_generator.db")
    artifact_dir: Path = Path(os.getenv("ARTIFACT_DIR", "./artifacts"))
    worker_poll_seconds: float = float(os.getenv("WORKER_POLL_SECONDS", "0.2"))

    @property
    def database_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Only sqlite database URLs are supported by this implementation")
        return Path(self.database_url.removeprefix(prefix))
