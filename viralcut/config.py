"""Where ViralCut keeps its data and the user's settings (API key, Whisper model)."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent
EDITABLE = ("ANTHROPIC_API_KEY", "VIRALCUT_WHISPER_MODEL")


def data_dir() -> Path:
    return Path(os.environ.get("VIRALCUT_DATA") or Path.cwd() / "viralcut_data")


def settings_path() -> Path:
    return data_dir() / "settings.env"


def _read(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            values[key.strip()] = value
    return values


def load_settings() -> None:
    """Apply viralcut/settings.env and <data dir>/settings.env without overriding real env vars."""
    for path in (PACKAGE_DIR / "settings.env", settings_path()):
        for key, value in _read(path).items():
            os.environ.setdefault(key, value)


def save_settings(updates: dict[str, str]) -> None:
    """Persist settings chosen in the app and apply them to this process."""
    path = settings_path()
    values = _read(path)
    for key, value in updates.items():
        if key not in EDITABLE:
            continue
        value = value.strip()
        if value:
            values[key] = value
            os.environ[key] = value
        else:
            values.pop(key, None)
            os.environ.pop(key, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
