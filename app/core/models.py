from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class RunContext:
    run_id: str
    selected_date: datetime
    work_dir: Path
    dry_run: bool = False

    @property
    def date_ddmmyyyy(self) -> str:
        return self.selected_date.strftime("%d-%m-%Y")

    @property
    def date_slash(self) -> str:
        return self.selected_date.strftime("%d/%m/%Y")

    @property
    def date_short(self) -> str:
        return self.selected_date.strftime("%d-%m-%y")

    @property
    def message_date(self) -> str:
        return self.selected_date.strftime("%d/%m")
