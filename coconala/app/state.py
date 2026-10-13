"""見た案件・応募した案件・案件データの保存。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.jobs_dir = self.dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json"
        data = {}
        if self.state_path.exists():
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.seen: dict[str, str] = data.get("seen", {})
        self.applied: dict[str, str] = data.get("applied", {})

    def save(self) -> None:
        self.state_path.write_text(
            json.dumps({"seen": self.seen, "applied": self.applied}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def mark_seen(self, req_id: str) -> None:
        self.seen.setdefault(req_id, datetime.now().isoformat(timespec="seconds"))

    def mark_applied(self, req_id: str) -> None:
        self.applied[req_id] = datetime.now().isoformat(timespec="seconds")
        self.save()

    def save_job(self, job: dict) -> None:
        path = self.jobs_dir / f"{job['id']}.json"
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_job(self, req_id: str) -> dict | None:
        path = self.jobs_dir / f"{req_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_last_run(self, ids: list[str]) -> None:
        (self.dir / "last_run.json").write_text(json.dumps(ids), encoding="utf-8")

    def load_last_run(self) -> list[str]:
        path = self.dir / "last_run.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
