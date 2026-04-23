# Account Switch Fix Notes

## Summary

The Windows app originally switched accounts by copying only `~/.codex/auth.json`.
That was not sufficient for current Codex Desktop builds.

## Root Cause

Two separate state layers were involved:

1. CLI identity state in `~/.codex`
   - `auth.json`
   - `.codex-global-state.json`
   - `.codex-global-state.json.bak`

2. Desktop browser/session state in the Codex MSIX package cache
   - `%LOCALAPPDATA%\\Packages\\OpenAI.Codex_*\\LocalCache\\Roaming\\Codex`

The original switch flow updated only `auth.json`, so Codex Desktop could reopen with:

- a stale `creator_id` in `.codex-global-state.json`, or
- stale browser/session state under the MSIX package cache.

That produced two visible failures:

- switch completed but Codex Desktop still showed the login screen
- in some cases Codex Desktop was terminated but not relaunched because the restart script failed while copying session files

## Fix

### 1. Sync global CLI state during switch

`windows/codexcontrol_windows/account_manager.py`

- After copying the target `auth.json`, the switch flow now rewrites `creator_id` in:
  - `.codex-global-state.json`
  - `.codex-global-state.json.bak`
- The rewrite is account-aware and replaces the previous provider account id with the target account id.

### 2. Discover and manage Codex Desktop session state

`windows/codexcontrol_windows/file_locations.py`

- Added discovery of the active Codex MSIX package under:
  - `%LOCALAPPDATA%\\Packages\\OpenAI.Codex*`
- Added resolution of the live desktop session root:
  - `LocalCache\\Roaming\\Codex`
- Defined the session entries that need to be preserved/restored during account switching.

### 3. Backup and restore desktop session state during restart

`windows/codexcontrol_windows/codex_desktop.py`

- The restart script now:
  - stops Codex Desktop
  - backs up the current desktop session into the managed home of the account being switched away from
  - restores the target account's saved desktop session when available
  - relaunches Codex Desktop

- The script was also hardened:
  - file-path handling for session file copies was fixed
  - backup/restore runs per entry with logging instead of failing the whole restart on the first copy error
  - when the target account has no saved desktop session yet, the script no longer wipes the current live session state

## Important Behavioral Note

If a target account does not yet have a saved `desktop-session` snapshot, the first switch to that account may still require Codex Desktop to reconcile login/session state on its own.
After that account has been active once and its desktop session has been backed up, subsequent switches are expected to behave more consistently.

## Files Changed

- `windows/codexcontrol_windows/account_manager.py`
- `windows/codexcontrol_windows/app.py`
- `windows/codexcontrol_windows/codex_desktop.py`
- `windows/codexcontrol_windows/file_locations.py`
- `windows/tests/test_account_manager.py`
- `windows/tests/test_codex_desktop.py`
