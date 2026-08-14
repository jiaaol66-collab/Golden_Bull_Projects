from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from modern_terminal.legacy_bridge import _LegacyBridgeMixin


class _InventoryHarness(_LegacyBridgeMixin):
    def get_fixed_backup_code_item(self, workspace_root):
        path = Path(workspace_root) / "资料" / "代码" / "code_backup.py"
        return {
            "name": path.name,
            "display_label": "代码备份",
            "rel_path": "资料/代码/code_backup.py",
            "abs_path": str(path),
            "exists": path.is_file(),
        }


class LegacyManualCodeTests(unittest.TestCase):
    def test_manual_inventory_is_whitelisted_and_supports_notebooks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "tool.py").write_text("print('ok')", encoding="utf-8")
            (root / "step_1" ).mkdir()
            (root / "step_1" / "helper.ipynb").write_text("{}", encoding="utf-8")
            (root / "资料" / "代码").mkdir(parents=True)
            (root / "资料" / "代码" / "code_backup.py").write_text("", encoding="utf-8")
            harness = object.__new__(_InventoryHarness)
            manifest = {
                "workspace_root": str(root),
                "other_root_codes": [
                    {"rel_path": "tool.py", "name": "tool.py", "exists": True},
                    {"rel_path": "../outside.py", "name": "outside.py", "exists": True},
                ],
                "step_code_folders": [
                    {
                        "display_label": "步骤 1",
                        "async_files": [
                            {"rel_path": "step_1/helper.ipynb", "name": "helper.ipynb", "exists": True}
                        ],
                    }
                ],
            }

            items = harness._bridge_manual_code_items(manifest)

        ids = {item["id"] for item in items}
        self.assertIn("tool.py", ids)
        self.assertIn("step_1/helper.ipynb", ids)
        self.assertIn("资料/代码/code_backup.py", ids)
        self.assertNotIn("../outside.py", ids)
        self.assertTrue(all(Path(item["abs_path"]).is_absolute() for item in items))

    def test_snapshot_versions_all_loaded_tabs_and_reports_real_parallel_policy(self):
        class SnapshotHarness(_LegacyBridgeMixin):
            def _bridge_active_tab_id(self):
                return "tab_b"

            def _bridge_workspace_snapshot(self, tab_id):
                return {
                    "tab_id": tab_id,
                    "workspace": {"id": f"ws_{tab_id}", "name": tab_id},
                    "session_id": "",
                    "status": "running" if tab_id == "tab_a" else "idle",
                    "current_step": {},
                    "selected": [],
                    "finished": [],
                    "progress": {},
                    "timers": {},
                    "processes": {"main_running": tab_id == "tab_a", "async_running": False},
                    "latest_log": "",
                    "logs": [],
                    "error": {},
                    "timeline": [],
                    "manual_codes": [],
                }

        harness = object.__new__(SnapshotHarness)
        harness._bridge_revision = 0
        harness._bridge_visible = False
        harness._bridge_last_command = {}
        harness.active_tabs_data = {"tab_a": {}, "tab_b": {}}

        snapshot = harness._bridge_build_snapshot()

        self.assertEqual(snapshot["workspace"]["id"], "ws_tab_b")
        self.assertEqual(len(snapshot["workspaces"]), 2)
        self.assertEqual(snapshot["loaded_workspaces_state"]["schema_version"], 1)
        self.assertEqual(snapshot["loaded_workspaces_state"]["items"], snapshot["workspaces"])
        self.assertTrue(snapshot["capabilities"]["parallel_workspace_runs"])
        self.assertTrue(snapshot["capabilities"]["workspace_run_mutex"])
        self.assertEqual(
            snapshot["loaded_workspaces_state"]["parallel_capability"]["scope"],
            "different_workspaces",
        )
        self.assertFalse(snapshot["loaded_workspaces_state"]["parallel_capability"]["same_workspace"])


if __name__ == "__main__":
    unittest.main()
