from __future__ import annotations

import os
import shutil
from pathlib import Path


def appdata_directory() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata)
    return Path.home() / "AppData" / "Roaming"


def localappdata_directory() -> Path:
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return Path(localappdata)
    return Path.home() / "AppData" / "Local"


APP_SUPPORT_DIRECTORY = appdata_directory() / "CodexControl"
LEGACY_APP_SUPPORT_DIRECTORIES = [
    appdata_directory() / "".join(["Codex", "Gauge"]),
    appdata_directory() / "".join(["Codex", "Accounts"]),
]
ACCOUNTS_FILE = APP_SUPPORT_DIRECTORY / "accounts.json"
SNAPSHOTS_FILE = APP_SUPPORT_DIRECTORY / "snapshots.json"
MANAGED_HOMES_DIRECTORY = APP_SUPPORT_DIRECTORY / "managed-homes"
AUTH_BACKUPS_DIRECTORY = APP_SUPPORT_DIRECTORY / "auth-backups"
AMBIENT_CODEX_HOME = Path.home() / ".codex"
DESKTOP_SESSION_SNAPSHOT_DIRECTORY_NAME = "desktop-session"
DESKTOP_SESSION_STATE_ENTRIES = (
    "blob_storage",
    "DIPS",
    "DIPS-wal",
    "Local State",
    "Local Storage",
    "Network",
    "Partitions",
    "Preferences",
    "Session Storage",
    "SharedStorage",
    "SharedStorage-wal",
    "shared_proto_db",
)


def codex_desktop_package_directories() -> list[Path]:
    packages_root = localappdata_directory() / "Packages"
    if not packages_root.exists():
        return []

    candidates = [path for path in packages_root.glob("OpenAI.Codex*") if path.is_dir()]
    return sorted(candidates, key=lambda path: (path.name.lower(), str(path)))


def codex_desktop_session_root() -> Path | None:
    for package_directory in codex_desktop_package_directories():
        session_root = package_directory / "LocalCache" / "Roaming" / "Codex"
        if session_root.exists():
            return session_root
    return None


def ensure_directories() -> None:
    if not APP_SUPPORT_DIRECTORY.exists():
        for legacy_directory in LEGACY_APP_SUPPORT_DIRECTORIES:
            if legacy_directory.exists():
                shutil.move(str(legacy_directory), str(APP_SUPPORT_DIRECTORY))
                break

    APP_SUPPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    MANAGED_HOMES_DIRECTORY.mkdir(parents=True, exist_ok=True)
    AUTH_BACKUPS_DIRECTORY.mkdir(parents=True, exist_ok=True)
