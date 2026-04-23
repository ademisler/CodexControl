from __future__ import annotations

import base64
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from codexcontrol_windows.account_manager import CodexAccountManager
from codexcontrol_windows.models import StoredAccount, StoredAccountSource


def _write_auth(home_path: Path, email: str, account_id: str) -> None:
    payload = {
        "email": email,
        "sub": f"auth0|{account_id}",
        "https://api.openai.com/auth": {
            "chatgpt_plan_type": "team",
            "chatgpt_account_id": account_id,
        },
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    auth_payload = {
        "tokens": {
            "access_token": f"access-{account_id}",
            "refresh_token": f"refresh-{account_id}",
            "id_token": f"header.{encoded}.signature",
            "account_id": account_id,
        },
        "last_refresh": "2026-04-23T00:00:00Z",
    }
    (home_path / "auth.json").write_text(json.dumps(auth_payload, indent=2), encoding="utf-8")


class CodexAccountManagerTests(unittest.TestCase):
    def test_switch_active_account_updates_global_state_creator_id(self) -> None:
        old_account_id = "1ea93d04-5c50-42e3-857b-3db850785967"
        new_account_id = "83c5ae92-f5ee-41f8-9528-199110d1d0f9"
        now = datetime(2026, 4, 23, tzinfo=timezone.utc)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ambient_home = root / ".codex"
            backups_dir = root / "auth-backups"
            managed_homes_dir = root / "managed-homes"
            target_home = managed_homes_dir / "target"
            desktop_session_root = root / "package-session"

            ambient_home.mkdir(parents=True)
            backups_dir.mkdir(parents=True)
            target_home.mkdir(parents=True)
            desktop_session_root.mkdir(parents=True)

            _write_auth(ambient_home, "old@example.com", old_account_id)
            _write_auth(target_home, "new@example.com", new_account_id)
            target_session_dir = target_home / "desktop-session" / "Network"
            target_session_dir.mkdir(parents=True)
            (target_session_dir / "Cookies").write_text("cookie-data", encoding="utf-8")

            global_state = {
                "electron-persisted-atom-state": {
                    "environment": {
                        "creator_id": f"user-e9H3MsspGTF7UZJ8uaXuML55__{old_account_id}",
                    }
                }
            }
            for file_name in (".codex-global-state.json", ".codex-global-state.json.bak"):
                (ambient_home / file_name).write_text(json.dumps(global_state, indent=2), encoding="utf-8")

            manager = CodexAccountManager()
            target_account = StoredAccount(
                id=uuid4(),
                nickname=None,
                email_hint="new@example.com",
                auth_subject=f"auth0|{new_account_id}",
                provider_account_id=new_account_id,
                codex_home_path=str(target_home),
                source=StoredAccountSource.MANAGED_BY_APP,
                created_at=now,
                updated_at=now,
                last_authenticated_at=now,
            )

            def ensure_dirs() -> None:
                ambient_home.mkdir(parents=True, exist_ok=True)
                backups_dir.mkdir(parents=True, exist_ok=True)
                managed_homes_dir.mkdir(parents=True, exist_ok=True)

            with (
                patch("codexcontrol_windows.account_manager.AMBIENT_CODEX_HOME", ambient_home),
                patch("codexcontrol_windows.account_manager.AUTH_BACKUPS_DIRECTORY", backups_dir),
                patch("codexcontrol_windows.account_manager.MANAGED_HOMES_DIRECTORY", managed_homes_dir),
                patch("codexcontrol_windows.account_manager.codex_desktop_session_root", return_value=desktop_session_root),
                patch("codexcontrol_windows.account_manager.ensure_directories", side_effect=ensure_dirs),
            ):
                result = manager.switch_active_account(target_account, [target_account])

            ambient_auth = json.loads((ambient_home / "auth.json").read_text(encoding="utf-8"))
            self.assertEqual(ambient_auth["tokens"]["account_id"], new_account_id)
            self.assertEqual(result.ambient_account.provider_account_id, new_account_id)
            self.assertEqual(result.materialized_account.provider_account_id, old_account_id)
            self.assertEqual(
                Path(result.desktop_session_backup_path),
                Path(result.materialized_account.codex_home_path) / "desktop-session",
            )
            self.assertEqual(Path(result.desktop_session_restore_path), target_home / "desktop-session")
            self.assertTrue(result.desktop_session_restore_exists)

            backup_files = list(backups_dir.glob("ambient-auth-*.json"))
            self.assertEqual(len(backup_files), 1)
            self.assertEqual(json.loads(backup_files[0].read_text(encoding="utf-8"))["tokens"]["account_id"], old_account_id)

            for file_name in (".codex-global-state.json", ".codex-global-state.json.bak"):
                payload = json.loads((ambient_home / file_name).read_text(encoding="utf-8"))
                creator_id = payload["electron-persisted-atom-state"]["environment"]["creator_id"]
                self.assertEqual(creator_id, f"user-e9H3MsspGTF7UZJ8uaXuML55__{new_account_id}")


if __name__ == "__main__":
    unittest.main()
