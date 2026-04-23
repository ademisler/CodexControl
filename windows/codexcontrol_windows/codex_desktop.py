from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path, PureWindowsPath

from .file_locations import APP_SUPPORT_DIRECTORY, DESKTOP_SESSION_STATE_ENTRIES, codex_desktop_session_root, ensure_directories


DEFAULT_RESTART_DELAY_SECONDS = 0.8
RESTART_LOG_PATH = APP_SUPPORT_DIRECTORY / "codex-desktop-restart.log"
RESTART_SCRIPT_PATH = APP_SUPPORT_DIRECTORY / "codex-desktop-restart.ps1"
POWERSHELL_EXE = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


class CodexDesktopControlError(RuntimeError):
    """Friendly Codex Desktop control error."""


def build_restart_script(
    delay_seconds: float = DEFAULT_RESTART_DELAY_SECONDS,
    session_root: Path | None = None,
    backup_destination: Path | None = None,
    restore_source: Path | None = None,
) -> str:
    delay_ms = max(0, int(round(delay_seconds * 1000)))
    log_path = _powershell_literal_path(RESTART_LOG_PATH)
    effective_session_root = session_root or codex_desktop_session_root()
    session_root_literal = _powershell_path_or_null(effective_session_root)
    backup_destination_literal = _powershell_path_or_null(backup_destination)
    restore_source_literal = _powershell_path_or_null(restore_source)
    session_entries_literal = _powershell_string_array(DESKTOP_SESSION_STATE_ENTRIES)

    return f"""
$ErrorActionPreference = 'Stop'
$logPath = {log_path}
$sessionRoot = {session_root_literal}
$backupDestination = {backup_destination_literal}
$restoreSource = {restore_source_literal}
$sessionEntries = {session_entries_literal}
New-Item -ItemType Directory -Path ([System.IO.Path]::GetDirectoryName($logPath)) -Force | Out-Null
function Write-Log([string]$message) {{
    Add-Content -LiteralPath $logPath -Value ("[{{0}}] {{1}}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'), $message)
}}
function Clear-SessionEntry([string]$root, [string]$relativePath) {{
    if (-not $root) {{
        return
    }}
    $targetPath = Join-Path $root $relativePath
    if (Test-Path -LiteralPath $targetPath) {{
        Remove-Item -LiteralPath $targetPath -Recurse -Force -ErrorAction Stop
    }}
}}
function Copy-SessionEntry([string]$sourceRoot, [string]$destinationRoot, [string]$relativePath) {{
    if (-not $sourceRoot -or -not $destinationRoot) {{
        return
    }}
    $sourcePath = Join-Path $sourceRoot $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath)) {{
        return
    }}
    $destinationPath = Join-Path $destinationRoot $relativePath
    $parentPath = [System.IO.Path]::GetDirectoryName($destinationPath)
    if ($parentPath) {{
        New-Item -ItemType Directory -Path $parentPath -Force | Out-Null
    }}
    $item = Get-Item -LiteralPath $sourcePath -Force
    if ($item.PSIsContainer) {{
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Recurse -Force
        return
    }}
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
}}
function Sync-DesktopSessionState() {{
    if (-not $sessionRoot) {{
        Write-Log 'Desktop session root was not detected.'
        return
    }}
    Write-Log ("Desktop session root: " + $sessionRoot)
    Write-Log ("Backup destination: " + $(if ($backupDestination) {{ $backupDestination }} else {{ '<none>' }}))
    Write-Log ("Restore source: " + $(if ($restoreSource) {{ $restoreSource }} else {{ '<none>' }}))
    if (-not (Test-Path -LiteralPath $sessionRoot)) {{
        Write-Log ("Desktop session root is missing: " + $sessionRoot)
        return
    }}
    if ($backupDestination) {{
        New-Item -ItemType Directory -Path $backupDestination -Force | Out-Null
        foreach ($relativePath in $sessionEntries) {{
            try {{
                Clear-SessionEntry $backupDestination $relativePath
                Copy-SessionEntry $sessionRoot $backupDestination $relativePath
                Write-Log ("Backed up session entry: " + $relativePath)
            }} catch {{
                Write-Log ("Failed to back up session entry " + $relativePath + ": " + $_.Exception.Message)
            }}
        }}
        Write-Log ("Backed up desktop session state to " + $backupDestination)
    }}
    if ($restoreSource) {{
        if (-not (Test-Path -LiteralPath $restoreSource)) {{
            Write-Log ("Restore source is missing; leaving the current desktop session in place: " + $restoreSource)
            return
        }}
        foreach ($relativePath in $sessionEntries) {{
            try {{
                Clear-SessionEntry $sessionRoot $relativePath
                Copy-SessionEntry $restoreSource $sessionRoot $relativePath
                Write-Log ("Restored session entry: " + $relativePath)
            }} catch {{
                Write-Log ("Failed to restore session entry " + $relativePath + ": " + $_.Exception.Message)
            }}
        }}
        Write-Log ("Restored desktop session state from " + $restoreSource)
    }}
}}
Write-Log 'Restart requested.'
$mainProcess = Get-CimInstance Win32_Process | Where-Object {{
    $_.Name -eq 'Codex.exe' -and
    $_.ExecutablePath -and
    $_.ExecutablePath -notlike '*\\resources\\codex.exe' -and
    $_.CommandLine -notmatch '--type='
}} | Select-Object -First 1
$launcherPath = $mainProcess.ExecutablePath
if ($launcherPath) {{
    Write-Log ("Using running launcher path: " + $launcherPath)
}}
if (-not $launcherPath) {{
    $package = Get-AppxPackage | Where-Object {{
        $_.Name -eq 'OpenAI.Codex' -or $_.PackageFamilyName -like 'OpenAI.Codex*'
    }} | Sort-Object Version -Descending | Select-Object -First 1
    if ($package -and $package.InstallLocation) {{
        $launcherPath = Join-Path $package.InstallLocation 'app\\Codex.exe'
        Write-Log ("Using package launcher path: " + $launcherPath)
    }}
}}
if (-not $launcherPath) {{
    Write-Log 'Unable to locate the Codex Desktop executable.'
    throw 'Unable to locate the Codex Desktop executable.'
}}
Start-Sleep -Milliseconds {delay_ms}
$codexProcesses = Get-CimInstance Win32_Process | Where-Object {{
    $_.Name -ieq 'Codex.exe' -or
    $_.ExecutablePath -like '*\\OpenAI.Codex_*\\app\\Codex.exe' -or
    $_.ExecutablePath -like '*\\OpenAI.Codex_*\\app\\resources\\codex.exe'
}}
Write-Log ("Found " + $codexProcesses.Count + " Codex processes to stop.")
$codexProcesses | ForEach-Object {{
    try {{
        & taskkill.exe /PID $_.ProcessId /F /T | Out-Null
        Write-Log ("taskkill succeeded for PID " + $_.ProcessId)
    }} catch {{
        Write-Log ("taskkill failed for PID " + $_.ProcessId + ": " + $_.Exception.Message)
    }}
    try {{
        Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
        Write-Log ("Stop-Process succeeded for PID " + $_.ProcessId)
    }} catch {{
        Write-Log ("Stop-Process failed for PID " + $_.ProcessId + ": " + $_.Exception.Message)
    }}
}}
$deadline = (Get-Date).AddSeconds(8)
while ((Get-Date) -lt $deadline) {{
    $remaining = Get-CimInstance Win32_Process | Where-Object {{
        $_.Name -ieq 'Codex.exe' -or
        $_.ExecutablePath -like '*\\OpenAI.Codex_*\\app\\Codex.exe' -or
        $_.ExecutablePath -like '*\\OpenAI.Codex_*\\app\\resources\\codex.exe'
    }}
    if (-not $remaining) {{
        Write-Log 'All Codex processes exited.'
        break
    }}
    Write-Log ("Still waiting for " + $remaining.Count + " Codex processes to exit.")
    $remaining | ForEach-Object {{
        try {{
            & taskkill.exe /PID $_.ProcessId /F /T | Out-Null
        }} catch {{}}
    }}
    Start-Sleep -Milliseconds 250
}}
if (Get-CimInstance Win32_Process | Where-Object {{
    $_.Name -ieq 'Codex.exe' -or
    $_.ExecutablePath -like '*\\OpenAI.Codex_*\\app\\Codex.exe' -or
    $_.ExecutablePath -like '*\\OpenAI.Codex_*\\app\\resources\\codex.exe'
}}) {{
    Write-Log 'Continuing with relaunch after timeout while some Codex processes still appear alive.'
}}
Sync-DesktopSessionState
Start-Sleep -Milliseconds 700
Start-Process -FilePath $launcherPath
Write-Log 'Codex Desktop relaunched.'
""".strip()


def encode_powershell_script(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def restart_codex_desktop(
    delay_seconds: float = DEFAULT_RESTART_DELAY_SECONDS,
    session_root: Path | None = None,
    backup_destination: Path | None = None,
    restore_source: Path | None = None,
) -> None:
    ensure_directories()
    RESTART_SCRIPT_PATH.write_text(
        build_restart_script(
            delay_seconds,
            session_root=session_root,
            backup_destination=backup_destination,
            restore_source=restore_source,
        ),
        encoding="utf-8",
    )

    try:
        _launch_hidden_powershell(RESTART_SCRIPT_PATH)
    except OSError as error:
        raise CodexDesktopControlError("Failed to restart Codex Desktop.") from error


def _powershell_literal_path(path: Path) -> str:
    normalized_path = str(PureWindowsPath(str(path)))
    return "'" + normalized_path.replace("'", "''") + "'"


def _powershell_path_or_null(path: Path | None) -> str:
    if path is None:
        return "$null"
    return _powershell_literal_path(path)


def _powershell_string_array(values: tuple[str, ...]) -> str:
    quoted = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
    return f"@({quoted})"


def build_restart_command(script_path: Path = RESTART_SCRIPT_PATH) -> list[str]:
    powershell_exe = str(PureWindowsPath(str(POWERSHELL_EXE)))
    normalized_script_path = str(PureWindowsPath(str(script_path)))
    return [
        powershell_exe,
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        normalized_script_path,
    ]


def _launch_hidden_powershell(script_path: Path) -> None:
    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup_info.wShowWindow = 0

    creation_flags = 0
    creation_flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    creation_flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    subprocess.Popen(
        build_restart_command(script_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=startup_info,
        creationflags=creation_flags,
        close_fds=True,
    )
