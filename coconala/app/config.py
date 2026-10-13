"""設定ファイル（config.yaml）と .env の読み込み。"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg["_root"] = str(path.resolve().parent)
    return cfg


def resolve(cfg: dict, rel: str) -> Path:
    """config.yaml のある場所からの相対パスを、絶対パスにする。"""
    p = Path(rel)
    return p if p.is_absolute() else Path(cfg["_root"]) / p


def load_dotenv(path: Path | None = None) -> None:
    """.env の KEY=VALUE を環境変数に入れる（すでにある値は上書きしない）。"""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
