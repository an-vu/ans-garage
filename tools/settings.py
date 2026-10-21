"""Machine-specific paths for the tools and tests.

Read from settings.json next to the repository folder (never committed), or from the file named by the
ANS_GARAGE_SETTINGS environment variable. Relative paths are resolved against the settings file's folder.
See settings.example.json in the repository root.
"""
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def settings_file():
    return Path(os.environ.get("ANS_GARAGE_SETTINGS") or REPO.parent / "settings.json")


def load():
    path = settings_file()
    if not path.is_file():
        raise FileNotFoundError("Settings not found: %s (copy settings.example.json there and fill it in)" % path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: str((path.parent / v).resolve()) if isinstance(v, str) and not k.startswith("_") else v
            for k, v in raw.items()}


def path(key):
    value = load().get(key)
    if not value:
        raise KeyError("Setting '%s' is missing from %s" % (key, settings_file()))
    return Path(value)
