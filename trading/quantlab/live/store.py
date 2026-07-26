"""On-disk state for the long-running service.

Everything the service needs to survive a restart lives in one directory as
plain JSON and JSONL: the paper fills, the orders queued for the next bar, the
alert log, and a heartbeat. Plain text on purpose — a 24/7 process that you
cannot inspect with ``cat`` while it is running is a process you cannot trust.

Writes go through a temp file and ``os.replace`` so a crash mid-write cannot
leave a half-written state file behind.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class Store:
    """A directory of JSON/JSONL state files."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.root / name

    def write_json(self, name: str, payload: Any) -> None:
        """Atomically replace ``name`` with ``payload``."""
        target = self.path(name)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str))
        os.replace(tmp, target)

    def read_json(self, name: str, default: Any = None) -> Any:
        target = self.path(name)
        if not target.exists():
            return default
        return json.loads(target.read_text())

    def append_jsonl(self, name: str, rows: list[dict]) -> None:
        """Append rows to a JSONL log, flushing to disk before returning."""
        if not rows:
            return
        with self.path(name).open("a") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def read_jsonl(self, name: str) -> list[dict]:
        target = self.path(name)
        if not target.exists():
            return []
        return [json.loads(line) for line in target.read_text().splitlines() if line.strip()]
