"""ViralCut - turn long videos into viral short clips, posts and hashtags."""

import os
from pathlib import Path

__version__ = "1.0.0"


def _load_settings_file() -> None:
    """Read KEY=VALUE lines from viralcut/settings.env (e.g. ANTHROPIC_API_KEY) into the environment."""
    path = Path(__file__).parent / "settings.env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


_load_settings_file()
