"""Game names for Steam app ids.

Looked up in this order, and the first hit wins.
1. The app manifest of an installed game. Steam's install folder comes from
   the registry, and every Steam library listed in its libraryfolders.vdf is
   searched for steamapps/appmanifest_<id>.acf.
2. The Steam store API, for games that are no longer installed.
Found names are cached in the database by service/sessions.py.
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

STORE_URL = "https://store.steampowered.com/api/appdetails?appids={}&filters=basic"
STORE_TIMEOUT = 4  # seconds

_NAME_RE = re.compile(r'^\s*"name"\s*"(.*)"\s*$', re.MULTILINE)
_PATH_RE = re.compile(r'^\s*"path"\s*"(.*)"\s*$', re.MULTILINE)


def _steam_install() -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            return Path(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:
        return None


def _library_dirs(extra_roots: list[Path]) -> list[Path]:
    roots = [r for r in [_steam_install(), *extra_roots] if r is not None]
    dirs: list[Path] = []
    for root in roots:
        main = root / "steamapps"
        if main not in dirs:
            dirs.append(main)
        vdf = main / "libraryfolders.vdf"
        if vdf.exists():
            for raw in _PATH_RE.findall(vdf.read_text(encoding="utf-8", errors="replace")):
                library = Path(raw.replace("\\\\", "\\")) / "steamapps"
                if library not in dirs:
                    dirs.append(library)
    return dirs


def _from_manifest(app_id: str, extra_roots: list[Path]) -> str | None:
    for library in _library_dirs(extra_roots):
        manifest = library / f"appmanifest_{app_id}.acf"
        if manifest.exists():
            match = _NAME_RE.search(manifest.read_text(encoding="utf-8", errors="replace"))
            if match:
                return match.group(1)
    return None


def _from_store(app_id: str) -> str | None:
    with urllib.request.urlopen(STORE_URL.format(app_id), timeout=STORE_TIMEOUT) as response:
        data = json.load(response).get(app_id, {})
    if data.get("success"):
        return data.get("data", {}).get("name")
    return None


def lookup_app_name(app_id: str, extra_roots: list[Path]) -> str | None:
    """The game's name from its install manifest or the Steam store. None when both fail."""
    for lookup in (lambda: _from_manifest(app_id, extra_roots), lambda: _from_store(app_id)):
        try:
            name = lookup()
        except Exception:  # missing folders, no network, odd files, all mean "try the next one"
            name = None
        if name:
            return name
    return None
