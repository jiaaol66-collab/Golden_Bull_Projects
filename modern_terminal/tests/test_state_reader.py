import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpyxl import Workbook

from modern_terminal.api import TerminalBridge
from modern_terminal.state_reader import TerminalStateReader


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_test_blueprint(workspace_root, rows):
    blueprint = workspace_root / "资料" / "代码" / "工作区设置" / "文件结构.xlsx"
    blueprint.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "工作区"
    header = [
        "工作区名",
        "步骤",
        "工作区文件夹",
        "子文件夹1",
        "子文件夹2",
        "子文件夹3",
        "子文件夹4",
        "运行顺序",
        "相应代码和说明文件",
        "代码/说明",
    ]
    sheet.append(header)
    for row in rows:
        sheet.append([row.get(name) for name in header])
    workbook.save(blueprint)
    workbook.close()
    return blueprint


class TerminalStateReaderTests(unittest.TestCase):
    def test_empty_snapshot_is_versioned_and_serializable(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = TerminalStateReader(folder).snapshot()
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["status"], "idle")
        self.assertEqual(snapshot["timers"]["async_seconds"], 0.0)
        json.dumps(snapshot, ensure_ascii=False)

    def test_complete_manifest_is_separate_from_single_step_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026测试"
            rows = [
                {
                    "工作区名": "测试",
                    "步骤": 0,
                    "工作区文件夹": "准备",
                    "运行顺序": 0,
                    "相应代码和说明文件": "setup.py",
                    "代码/说明": "代码",
                },
                {
                    "步骤": 1,
                    "工作区文件夹": "清洗",
                    "运行顺序": 1,
                    "相应代码和说明文件": "clean.ipynb",
                    "代码/说明": "代码",
                },
                {
                    "步骤": 2,
                    "工作区文件夹": "计算",
                    "运行顺序": 2,
                    "相应代码和说明文件": "score.py",
                    "代码/说明": "代码",
                },
            ]
            write_test_blueprint(workspace_root, rows)
            for rel_path in (
                Path("step_0_准备/setup.py"),
                Path("step_1_清洗/clean.ipynb"),
                Path("step_2_计算/score.py"),
            ):
                path = workspace_root / rel_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}" if path.suffix == ".ipynb" else "", encoding="utf-8")
            write_json(
                workspace_root / ".gb_workspace.json",
                {"workspace_id": "ws_manifest", "workspace_name": workspace_root.name},
            )
            write_json(
                workspace_root / "参评信息" / "gui_state.json",
                {
                    "selected_step_orders": [1, 2],
                    "step_states": {"0": "pending", "1": "success", "2": "pending"},
                    "workspace_stepper_selected_orders_snapshot": [1],
                    "workspace_stepper_snapshot_active": True,
                },
            )
            log_root = root / "logs" / "GB_Test" / "ws_manifest"
            run_root = log_root / "run"
            session_id = "session_single"
            summary = {
                "session_id": session_id,
                "status": "success",
                "selected_step_total": 1,
                "started_at": "2026-08-11 10:00:00",
                "ended_at": "2026-08-11 10:00:05",
            }
            write_json(
                log_root / "workspace.json",
                {
                    "workspace_id": "ws_manifest",
                    "award": "测试流程",
                    "workspace_name": workspace_root.name,
                    "workspace_root": str(workspace_root),
                    "run_root": str(run_root),
                },
            )
            write_json(run_root / "index.json", [summary])
            write_json(run_root / session_id / "summary.json", summary)
            write_json(
                run_root / session_id / "records_summary.json",
                [
                    {
                        "rel_path": "step_1_清洗/clean.ipynb",
                        "label": "1_step_1_clean",
                        "axis": "main",
                        "status": "done",
                        "duration_seconds": 5,
                    }
                ],
            )

            reader = TerminalStateReader(root)
            workspace = next(item for item in reader.discover_workspaces() if item["name"] == workspace_root.name)
            disk_snapshot = reader.snapshot(workspace["id"])
            disk_bridge = TerminalBridge(root)
            frontend = disk_bridge._frontend_snapshot(disk_snapshot)
            disk_bridge.set_selected_steps({"workspace_id": workspace["id"], "orders": []})
            cleared_frontend = disk_bridge._frontend_snapshot(disk_snapshot)
            legacy_frontend = TerminalBridge(root)._frontend_from_legacy(
                {
                    "version": 1,
                    "revision": 1,
                    "captured_at": "2026-08-11T10:00:06",
                    "workspace": {
                        "id": "ws_manifest",
                        "name": workspace_root.name,
                        "workspace_root": str(workspace_root),
                    },
                    "status": "done",
                    "steps": [
                        {"order": 0, "label": "0_step_0_setup", "rel_path": "step_0_准备/setup.py", "state": "pending"},
                        {"order": 1, "label": "1_step_1_clean", "rel_path": "step_1_清洗/clean.ipynb", "state": "success"},
                        {"order": 2, "label": "2_step_2_score", "rel_path": "step_2_计算/score.py", "state": "pending"},
                    ],
                    "selected_orders": [1, 2],
                    "selected": [
                        {"order": 1, "label": "1_step_1_clean", "rel_path": "step_1_清洗/clean.ipynb", "state": "success"}
                    ],
                    "progress": {"selected_total": 1, "finished_total": 1},
                    "timers": {},
                    "timeline": [],
                }
            )

        self.assertEqual([item["order"] for item in disk_snapshot["manifest_steps"]], [0, 1, 2])
        self.assertEqual(disk_snapshot["configured_step_orders"], [1, 2])
        self.assertEqual([item["order"] for item in frontend["steps"]], [0, 1, 2])
        self.assertEqual([item["order"] for item in frontend["steps"] if item["selected"]], [1, 2])
        self.assertEqual([item["order"] for item in cleared_frontend["steps"] if item["selected"]], [])
        self.assertEqual([item["order"] for item in legacy_frontend["steps"]], [0, 1, 2])
        self.assertEqual([item["order"] for item in legacy_frontend["steps"] if item["selected"]], [1, 2])

    def test_reads_completed_attempt_timeline_and_log(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026测试"
            workspace_root.mkdir(parents=True)
            log_root = root / "logs" / "GB_Test" / "ws_demo"
            run_root = log_root / "run"
            session_id = "session_demo"
            attempt_root = run_root / session_id
            write_json(
                log_root / "workspace.json",
                {
                    "workspace_id": "ws_demo",
                    "award_dir_name": "GB_Test",
                    "workspace_name": "2026测试",
                    "workspace_root": str(workspace_root),
                    "run_root": str(run_root),
                },
            )
            summary = {
                "session_id": session_id,
                "status": "success",
                "status_label": "已完成",
                "started_at": "2026-08-10 10:00:00",
                "ended_at": "2026-08-10 10:02:00",
                "main_timer_seconds": 115,
                "selected_step_total": 1,
            }
            write_json(run_root / "index.json", [summary])
            write_json(attempt_root / "summary.json", summary)
            write_json(
                attempt_root / "records_summary.json",
                [
                    {
                        "run_id": "run_1",
                        "rel_path": "step_1/测试.py",
                        "label": "测试",
                        "axis": "main",
                        "status": "done",
                        "started_at": "2026-08-10 10:00:00",
                        "ended_at": "2026-08-10 10:01:55",
                        "duration_seconds": 115,
                    }
                ],
            )
            log_path = attempt_root / "main" / "测试.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_bytes("第一行\n完成\n".encode("utf-8"))

            snapshot = TerminalStateReader(root).snapshot("ws_demo")

        self.assertEqual(snapshot["status"], "done")
        self.assertEqual(snapshot["progress"]["percent"], 100.0)
        self.assertEqual(snapshot["timers"]["main_seconds"], 115.0)
        self.assertEqual(snapshot["entries"][0]["rel_path"], "step_1/测试.py")
        self.assertEqual(snapshot["logs"][-1], "完成")

    def test_reads_live_workspace_timeline_when_archive_is_not_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026测试"
            workspace_root.mkdir(parents=True)
            log_root = root / "logs" / "GB_Test" / "ws_live"
            run_root = log_root / "run"
            session_id = "session_live"
            summary = {
                "session_id": session_id,
                "status": "running",
                "started_at": "2026-08-10 10:00:00",
                "selected_step_total": 2,
            }
            write_json(
                log_root / "workspace.json",
                {
                    "workspace_id": "ws_live",
                    "workspace_name": "2026测试",
                    "workspace_root": str(workspace_root),
                    "run_root": str(run_root),
                },
            )
            write_json(run_root / "index.json", [summary])
            write_json(run_root / session_id / "summary.json", summary)
            timeline = workspace_root / "参评信息" / "时间记录.log"
            timeline.parent.mkdir(parents=True)
            timeline.write_text(
                "GB_TIMELINE "
                + json.dumps(
                    {
                        "event": "start",
                        "run_id": "run_live",
                        "session_id": session_id,
                        "rel_path": "step_1/运行.py",
                        "axis": "main",
                        "ts": "2026-08-10 10:00:01",
                        "pid": 1234,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            reader = TerminalStateReader(root)
            with mock.patch.object(reader, "_is_pid_running", return_value=True):
                snapshot = reader.snapshot("ws_live")

        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(snapshot["current_step"]["label"], "运行")
        self.assertEqual(snapshot["current_step"]["status"], "running")

    def test_can_read_a_specific_historical_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            log_root = root / "logs" / "GB_Test" / "ws_history"
            run_root = log_root / "run"
            workspace_root = root / "GB_Test" / "2026测试"
            workspace_root.mkdir(parents=True)
            write_json(
                log_root / "workspace.json",
                {
                    "workspace_id": "ws_history",
                    "workspace_name": "2026测试",
                    "workspace_root": str(workspace_root),
                    "run_root": str(run_root),
                },
            )
            newest = {"session_id": "new", "status": "success", "started_at": "2026-08-11 10:00:00"}
            older = {"session_id": "old", "status": "failed", "started_at": "2026-08-10 10:00:00"}
            write_json(run_root / "index.json", [older, newest])
            write_json(run_root / "new" / "summary.json", newest)
            write_json(run_root / "old" / "summary.json", older)
            write_json(
                run_root / "old" / "records_summary.json",
                [{"run_id": "old_step", "label": "旧尝试步骤", "axis": "main", "status": "failed", "duration_seconds": 8}],
            )

            snapshot = TerminalStateReader(root).snapshot("ws_history", attempt_id="old")

        self.assertEqual(snapshot["session_id"], "old")
        self.assertEqual(snapshot["entries"][0]["label"], "旧尝试步骤")

    def test_created_at_uses_metadata_then_directory_creation_and_drives_latest_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old_root = root / "GB_Test" / "2025旧工作区"
            new_root = root / "GB_Test" / "2026新工作区"
            for workspace_root in (old_root, new_root):
                workspace_root.mkdir(parents=True)

            write_json(old_root / ".gb_workspace.json", {"created_at": "2025-01-02T03:04:05"})
            write_json(
                root / "logs" / "GB_Test" / "ws_old" / "workspace.json",
                {
                    "workspace_id": "ws_old",
                    "workspace_name": old_root.name,
                    "workspace_root": str(old_root),
                    "created_at": "2024-01-01T00:00:00",
                },
            )
            write_json(
                root / "logs" / "GB_Test" / "ws_old" / "run" / "index.json",
                [{"status": "success", "ended_at": "2030-12-31T23:59:59"}],
            )
            write_json(
                root / "logs" / "GB_Test" / "ws_new" / "workspace.json",
                {
                    "workspace_id": "ws_new",
                    "workspace_name": new_root.name,
                    "workspace_root": str(new_root),
                    "created_at": "2026-02-03T04:05:06",
                },
            )
            write_json(
                root / "logs" / "GB_Test" / "ws_new" / "run" / "index.json",
                [{"status": "success", "ended_at": "2026-02-03T05:00:00"}],
            )
            workspaces = TerminalStateReader(root).discover_workspaces()
            by_name = {item["name"]: item for item in workspaces}

            fallback_project = root / "legacy_project"
            fallback_root = fallback_project / "GB_Test" / "2024旧格式工作区"
            fallback_root.mkdir(parents=True)
            write_json(
                fallback_project / "logs" / "GB_Test" / "ws_fallback" / "workspace.json",
                {
                    "workspace_id": "ws_fallback",
                    "workspace_name": fallback_root.name,
                    "workspace_root": str(fallback_root),
                },
            )
            fallback = TerminalStateReader(fallback_project).discover_workspaces()[0]

        self.assertEqual([item["name"] for item in workspaces], [new_root.name, old_root.name])
        self.assertEqual(by_name[old_root.name]["created_at"], "2025-01-02T03:04:05")
        self.assertNotEqual(fallback["created_at"], "")
        self.assertGreater(by_name[old_root.name]["updated_at"], by_name[new_root.name]["updated_at"])

    def test_sidebar_selection_is_compatible_and_preserves_unknown_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026恢复工作区"
            workspace_root.mkdir(parents=True)
            write_json(
                root / "logs" / "GB_Test" / "ws_restore" / "workspace.json",
                {
                    "workspace_id": "ws_restore",
                    "award": "测试奖",
                    "workspace_name": workspace_root.name,
                    "workspace_root": str(workspace_root),
                },
            )
            write_json(
                root / ".terminal_sidebar_state.json",
                {
                    "award_name": "测试奖",
                    "year_text": "2026",
                    "workspace_name": workspace_root.name,
                    "future_field": {"keep": True},
                },
            )
            reader = TerminalStateReader(root)

            restored = reader.read_sidebar_selection()
            workspace = reader.discover_workspaces()[0]
            persisted = reader.persist_sidebar_selection(workspace)
            raw = json.loads((root / ".terminal_sidebar_state.json").read_text(encoding="utf-8"))

        self.assertTrue(restored["resolved"])
        self.assertEqual(restored["workspace_id"], workspace["id"])
        self.assertTrue(persisted["resolved"])
        self.assertEqual(raw["future_field"], {"keep": True})
        self.assertEqual(raw["workspace"], workspace_root.name)

    def test_bad_sidebar_json_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".terminal_sidebar_state.json").write_text("{broken", encoding="utf-8")
            state = TerminalStateReader(root).read_sidebar_selection()
        self.assertEqual(state["read_status"], "invalid")
        self.assertFalse(state["resolved"])


class TerminalBridgeTests(unittest.TestCase):
    def test_diagnostics_and_bootstrap_are_json_serializable(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge = TerminalBridge(folder)
            json.dumps(bridge.diagnostics(), ensure_ascii=False)
            json.dumps(bridge.get_bootstrap_state(), ensure_ascii=False)

    def test_sidebar_selection_prefills_but_does_not_claim_workspace_loaded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026预填工作区"
            workspace_root.mkdir(parents=True)
            write_json(
                root / "logs" / "GB_Test" / "ws_prefill" / "workspace.json",
                {
                    "workspace_id": "ws_prefill",
                    "award": "测试奖",
                    "workspace_name": workspace_root.name,
                    "workspace_root": str(workspace_root),
                },
            )
            write_json(
                root / ".terminal_sidebar_state.json",
                {"award": "测试奖", "year": "2026", "workspace": workspace_root.name, "saved_at": "old"},
            )

            snapshot = TerminalBridge(root).bootstrap()

        self.assertTrue(snapshot["selection_context"]["resolved"])
        self.assertEqual(snapshot["active_workspace_id"], "")
        self.assertEqual(snapshot["loaded_workspaces"], [])

    def test_successful_mount_projects_all_real_loaded_workspaces_and_parallel_contract(self):
        class FakeController:
            def __init__(self, snapshot):
                self.snapshot = snapshot
                self.calls = []
                self.mounted = False

            def is_running(self):
                return True

            def mount(self, workspace):
                self.calls.append(("mount", workspace))
                self.mounted = True
                return "mount-request"

            def activate(self, workspace, show=False, mount=False):
                self.calls.append(("activate", workspace, show, mount))
                return "activate-request"

            def wait_for_command(self, _request_id):
                return self.snapshot

            def get_snapshot(self, latest=True):
                return self.snapshot if self.mounted else None

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            roots = [root / "GB_Test" / "2025运行中", root / "GB_Test" / "2026目标"]
            for index, workspace_root in enumerate(roots, start=1):
                workspace_root.mkdir(parents=True)
                write_json(
                    root / "logs" / "GB_Test" / f"ws_{index}" / "workspace.json",
                    {
                        "workspace_id": f"ws_{index}",
                        "award": "测试奖",
                        "workspace_name": workspace_root.name,
                        "workspace_root": str(workspace_root),
                        "created_at": f"202{4 + index}-01-01T00:00:00",
                    },
                )
            bridge = TerminalBridge(root)
            by_name = {item["name"]: item for item in bridge.reader.discover_workspaces()}
            target_id = by_name[roots[1].name]["id"]
            snapshot = {
                "version": 1,
                "revision": 7,
                "captured_at": "2026-08-11T12:00:00",
                "active_tab_id": "tab-target",
                "workspace": {"id": "ws_2", "name": roots[1].name, "workspace_root": str(roots[1])},
                "status": "idle",
                "timers": {},
                "progress": {},
                "last_command": {"request_id": "mount-request", "ok": True},
                "capabilities": {"parallel_workspace_runs": True, "workspace_run_mutex": True},
                "workspaces": [
                    {
                        "tab_id": "tab-running",
                        "workspace": {"id": "ws_1", "name": roots[0].name, "workspace_root": str(roots[0])},
                        "status": "running",
                        "timers": {"attempt_seconds": 12},
                        "progress": {"selected_total": 2, "finished_total": 1},
                        "processes": {"main_running": True, "async_running": False},
                        "latest_log": "仍在运行",
                    },
                    {
                        "tab_id": "tab-target",
                        "workspace": {"id": "ws_2", "name": roots[1].name, "workspace_root": str(roots[1])},
                        "status": "idle",
                        "timers": {},
                        "progress": {},
                        "processes": {"main_running": False, "async_running": False},
                    },
                ],
            }
            controller = FakeController(snapshot)
            bridge._legacy_controller = controller

            result = bridge.set_active_workspace({"workspace_id": target_id})
            raw_sidebar = json.loads((root / ".terminal_sidebar_state.json").read_text(encoding="utf-8"))

        self.assertEqual(controller.calls[0][0], "mount")
        self.assertTrue(result["load_result"]["loaded"])
        self.assertEqual(len(result["loaded_workspaces"]), 2)
        running = next(item for item in result["loaded_workspaces"] if item["status"] == "running")
        self.assertEqual(running["latest_log"], "仍在运行")
        self.assertTrue(result["parallel_capability"]["supported"])
        self.assertEqual(result["parallel_capability"]["scope"], "different_workspaces")
        self.assertFalse(result["parallel_capability"]["same_workspace"])
        self.assertEqual(raw_sidebar["workspace"], roots[1].name)

    def test_floating_bridge_reads_shared_loaded_workspace_registry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026悬浮监控"
            workspace_root.mkdir(parents=True)
            write_json(
                root / "logs" / "GB_Test" / "ws_float" / "workspace.json",
                {
                    "workspace_id": "ws_float",
                    "workspace_name": workspace_root.name,
                    "workspace_root": str(workspace_root),
                },
            )
            main_bridge = TerminalBridge(root)
            workspace_id = main_bridge.reader.discover_workspaces()[0]["id"]
            main_bridge._record_loaded_workspaces({workspace_id})
            with mock.patch.dict("os.environ", {"GOLDEN_BULL_MODERN_SESSION_ID": main_bridge._session_id}):
                floating = TerminalBridge(root, mode="floating", workspace_id=workspace_id)
                snapshot = floating.bootstrap()

        self.assertEqual([item["id"] for item in snapshot["loaded_workspaces"]], [workspace_id])
        self.assertEqual(snapshot["loaded_workspaces_state"]["schema_version"], 1)

    def test_open_path_rejects_outside_project(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge = TerminalBridge(folder)
            result = bridge.open_path(str(Path(folder).parent))
        self.assertFalse(result["ok"])

    def test_select_attempt_persists_across_polling(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            log_root = root / "logs" / "GB_Test" / "ws_history"
            run_root = log_root / "run"
            workspace_root = root / "GB_Test" / "2026测试"
            workspace_root.mkdir(parents=True)
            write_json(
                log_root / "workspace.json",
                {
                    "workspace_id": "ws_history",
                    "workspace_name": "2026测试",
                    "workspace_root": str(workspace_root),
                    "run_root": str(run_root),
                },
            )
            newest = {"session_id": "new", "status": "success", "started_at": "2026-08-11 10:00:00"}
            older = {"session_id": "old", "status": "failed", "started_at": "2026-08-10 10:00:00"}
            write_json(run_root / "index.json", [older, newest])
            write_json(run_root / "new" / "summary.json", newest)
            write_json(run_root / "old" / "summary.json", older)
            write_json(
                run_root / "old" / "records_summary.json",
                [{"run_id": "old_step", "label": "旧尝试步骤", "axis": "main", "status": "failed", "duration_seconds": 8}],
            )
            bridge = TerminalBridge(root)
            bridge.select_workspace(bridge.reader.discover_workspaces()[0]["id"])

            selected = bridge.select_attempt({"attempt_id": "old"})
            polled = bridge.get_state()

        self.assertEqual(selected["run"]["attempt_id"], "old")
        self.assertEqual(polled["run"]["attempt_id"], "old")
        self.assertEqual(polled["timeline"][0]["label"], "旧尝试步骤")

    def test_stale_log_metadata_does_not_resurrect_deleted_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_json(
                root / "logs" / "GB_Test" / "ws_deleted" / "workspace.json",
                {
                    "workspace_id": "ws_deleted",
                    "workspace_name": "2026已删除",
                    "workspace_root": str(root / "GB_Test" / "2026已删除"),
                },
            )

            workspaces = TerminalStateReader(root).discover_workspaces()

        self.assertEqual(workspaces, [])

    def test_workspace_id_is_stable_when_legacy_metadata_id_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026稳定ID"
            workspace_root.mkdir(parents=True)
            metadata_path = root / "logs" / "GB_Test" / "ws_first" / "workspace.json"
            base = {"workspace_name": "2026稳定ID", "workspace_root": str(workspace_root)}
            write_json(metadata_path, {**base, "workspace_id": "ws_first"})
            reader = TerminalStateReader(root)
            first = reader.discover_workspaces()[0]
            write_json(metadata_path, {**base, "workspace_id": "ws_changed"})
            second = reader.discover_workspaces()[0]

        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(first["legacy_workspace_id"], second["legacy_workspace_id"])

    def test_legacy_snapshot_is_mapped_back_to_stable_workspace_id(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026稳定映射"
            workspace_root.mkdir(parents=True)
            write_json(
                root / "logs" / "GB_Test" / "ws_random" / "workspace.json",
                {
                    "workspace_id": "ws_random",
                    "workspace_name": "2026稳定映射",
                    "workspace_root": str(workspace_root),
                },
            )
            bridge = TerminalBridge(root)
            stable_id = bridge.reader.discover_workspaces()[0]["id"]

            snapshot = bridge._frontend_from_legacy(
                {
                    "workspace": {
                        "id": "ws_random",
                        "name": "2026稳定映射",
                        "workspace_root": str(workspace_root),
                    },
                    "status": "idle",
                    "timers": {},
                    "progress": {},
                }
            )

        self.assertEqual(snapshot["active_workspace_id"], stable_id)
        self.assertEqual(snapshot["workspace"]["id"], stable_id)
        self.assertEqual(snapshot["workspace"]["legacy_workspace_id"], "ws_random")

    def test_failed_legacy_mount_rolls_back_selected_workspace(self):
        class FailingController:
            def is_running(self):
                return True

            def mount(self, workspace):
                return "request"

            def wait_for_command(self, request_id):
                return {"last_command": {"request_id": request_id, "ok": False, "message": "挂载失败"}}

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first_root = root / "GB_Test" / "2025旧工作区"
            second_root = root / "GB_Test" / "2026新工作区"
            first_root.mkdir(parents=True)
            second_root.mkdir(parents=True)
            for index, workspace_root in enumerate((first_root, second_root), start=1):
                write_json(
                    root / "logs" / "GB_Test" / f"ws_{index}" / "workspace.json",
                    {
                        "workspace_id": f"ws_{index}",
                        "workspace_name": workspace_root.name,
                        "workspace_root": str(workspace_root),
                    },
                )
            bridge = TerminalBridge(root)
            by_name = {item["name"]: item for item in bridge.reader.discover_workspaces()}
            previous_id = by_name[first_root.name]["id"]
            target_id = by_name[second_root.name]["id"]
            bridge._selected_workspace_id = previous_id
            bridge._legacy_controller = FailingController()

            result = bridge.set_active_workspace({"workspace_id": target_id})

        self.assertFalse(result["ok"])
        self.assertEqual(bridge._selected_workspace_id, previous_id)

    def test_log_cursors_survive_tail_poll_and_rotate_on_truncation(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge = TerminalBridge(folder)

            first = bridge._frontend_logs(["一", "二"], "ws", "session")
            appended = bridge._frontend_logs(["一", "二", "三"], "ws", "session")
            shifted = bridge._frontend_logs(["二", "三", "四"], "ws", "session")
            rotated = bridge._frontend_logs(["新文件"], "ws", "session")

        self.assertEqual([item["cursor"] for item in first], [1, 2])
        self.assertEqual([item["cursor"] for item in appended], [1, 2, 3])
        self.assertEqual([item["cursor"] for item in shifted], [2, 3, 4])
        self.assertEqual(rotated[0]["cursor"], 1)
        self.assertNotEqual(shifted[0]["stream_id"], rotated[0]["stream_id"])

    def test_floating_window_can_resize_and_close_without_touching_scheduler(self):
        class FakeWindow:
            def __init__(self):
                self.sizes = []
                self.destroyed = False

            def resize(self, width, height):
                self.sizes.append((width, height))

            def destroy(self):
                self.destroyed = True

        with tempfile.TemporaryDirectory() as folder:
            bridge = TerminalBridge(folder, mode="floating")
            window = FakeWindow()
            bridge.attach_window(window)

            expanded = bridge.set_floating_mode({"mode": "expanded"})
            mini = bridge.set_floating_mode({"mode": "mini"})
            closed = bridge.close_floating_monitor()

        self.assertTrue(expanded["ok"] and mini["ok"] and closed["ok"])
        self.assertEqual(window.sizes, [(330, 314), (300, 132)])
        self.assertTrue(window.destroyed)

    def test_manual_code_selection_and_run_use_only_code_id(self):
        class FakeController:
            def __init__(self):
                self.called = None

            def is_running(self):
                return True

            def get_snapshot(self, latest=True):
                return None

            def run_manual_code(self, workspace, code_id):
                self.called = (workspace, code_id)
                return "request"

            def wait_for_command(self, request_id):
                return {
                    "last_command": {
                        "request_id": request_id,
                        "ok": True,
                        "message": "已启动",
                        "data": {"code_id": "inherit.py"},
                    }
                }

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026测试"
            workspace_root.mkdir(parents=True)
            write_json(
                root / "logs" / "GB_Test" / "ws_test" / "workspace.json",
                {
                    "workspace_id": "ws_test",
                    "workspace_name": "2026测试",
                    "workspace_root": str(workspace_root),
                },
            )
            bridge = TerminalBridge(root)
            workspace_id = bridge.reader.discover_workspaces()[0]["id"]
            controller = FakeController()
            bridge._legacy_controller = controller
            bridge._legacy_snapshot = {
                "workspace": {"id": "ws_test", "name": "2026测试", "workspace_root": str(workspace_root)},
                "status": "idle",
                "manual_codes": [{"id": "inherit.py", "label": "inherit.py", "rel_path": "inherit.py", "exists": True}],
            }

            selection = bridge.management_action({"action": "run-unarranged-code", "workspace_id": workspace_id})
            with mock.patch.object(bridge, "_legacy_workspace_payload", return_value={"workspace_root": str(workspace_root)}):
                result = bridge.run_manual_code({"workspace_id": workspace_id, "code_id": "inherit.py", "abs_path": "C:/forged.py"})

        self.assertTrue(selection["requires_selection"])
        self.assertEqual(selection["manual_codes"][0]["id"], "inherit.py")
        self.assertTrue(result["ok"])
        self.assertEqual(controller.called, ({"workspace_root": str(workspace_root)}, "inherit.py"))

    def test_manual_code_api_uses_workspace_root_and_whitelisted_code_id(self):
        class FakeController:
            def __init__(self):
                self.calls = []

            def is_running(self):
                return True

            def run_manual_code(self, workspace, code_id):
                self.calls.append((workspace, code_id))
                return "request"

            def wait_for_command(self, request_id):
                return {
                    "last_command": {
                        "request_id": request_id,
                        "ok": True,
                        "message": "已启动",
                        "data": {"code_id": "inherit.py"},
                    }
                }

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026测试"
            workspace_root.mkdir(parents=True)
            write_json(
                root / "logs" / "GB_Test" / "ws_legacy" / "workspace.json",
                {
                    "workspace_id": "ws_legacy",
                    "award": "测试流程",
                    "workspace_name": "2026测试",
                    "workspace_root": str(workspace_root),
                },
            )
            bridge = TerminalBridge(root)
            workspace_id = bridge.reader.discover_workspaces()[0]["id"]
            controller = FakeController()
            bridge._legacy_controller = controller

            result = bridge.run_manual_code({"workspace_id": workspace_id, "code_id": "inherit.py"})

        self.assertTrue(result["ok"])
        sent_workspace, sent_code = controller.calls[0]
        self.assertEqual(sent_code, "inherit.py")
        self.assertEqual(Path(sent_workspace["workspace_root"]), workspace_root)
        self.assertNotIn("workspace_id", sent_workspace)

    def test_resource_picker_persists_dataset_and_rule_for_selected_year(self):
        class FakeWindow:
            def __init__(self, selections):
                self.selections = list(selections)
                self.calls = []

            def create_file_dialog(self, dialog_type, **kwargs):
                self.calls.append((dialog_type, kwargs))
                return (str(self.selections.pop(0)),)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026测试"
            workspace_root.mkdir(parents=True)
            dataset_root = root / "datasets" / "2026"
            dataset_root.mkdir(parents=True)
            rule_path = root / "rules" / "2026方案.docx"
            rule_path.parent.mkdir(parents=True)
            rule_path.write_bytes(b"rule")
            resource_path = root / "GB_Test" / "奖项资料配置.json"
            write_json(
                resource_path,
                {
                    "version": 1,
                    "years": {
                        "2025": {
                            "dataset_path": "保留的2025数据集",
                            "rule_path": "保留的2025方案",
                        },
                        "2026": {
                            "config_json_path": "保留的配置路径",
                            "extension_field": "保留的扩展字段",
                        },
                    },
                    "extension_root": "保留的顶层扩展字段",
                },
            )
            write_json(
                root / "logs" / "GB_Test" / "ws_legacy" / "workspace.json",
                {
                    "workspace_id": "ws_legacy",
                    "award": "测试流程",
                    "workspace_name": "2026测试",
                    "workspace_root": str(workspace_root),
                },
            )
            bridge = TerminalBridge(root)
            workspace_id = bridge.reader.discover_workspaces()[0]["id"]
            window = FakeWindow([dataset_root, rule_path])
            bridge.attach_window(window)
            fake_webview = mock.Mock(
                FileDialog=mock.Mock(FOLDER="folder", OPEN="open"),
                FOLDER_DIALOG="legacy-folder",
                OPEN_DIALOG="legacy-open",
            )

            with mock.patch("modern_terminal.api.get_award_folder", return_value="GB_Test"), mock.patch.dict(
                "sys.modules", {"webview": fake_webview}
            ):
                entry_result = bridge.management_action(
                    {"action": "configure-resources", "workspace_id": workspace_id}
                )
                dataset_result = bridge.choose_resource({"workspace_id": workspace_id, "kind": "dataset"})
                rule_result = bridge.choose_resource({"workspace_id": workspace_id, "kind": "rule"})
                current = bridge.get_resource_config({"workspace_id": workspace_id})

            saved = json.loads(resource_path.read_text(encoding="utf-8"))

        self.assertTrue(entry_result["requires_resource_config"])
        self.assertTrue(dataset_result["ok"])
        self.assertTrue(rule_result["ok"])
        self.assertEqual(dataset_result["resource_config"]["dataset_path"], str(dataset_root.resolve()))
        self.assertEqual(rule_result["resource_config"]["rule_path"], str(rule_path.resolve()))
        self.assertEqual(dataset_result["snapshot"]["workspace"]["id"], workspace_id)
        self.assertEqual(current["dataset_path"], str(dataset_root.resolve()))
        self.assertEqual(current["rule_path"], str(rule_path.resolve()))
        self.assertEqual(saved["years"]["2025"]["dataset_path"], "保留的2025数据集")
        self.assertEqual(saved["years"]["2026"]["dataset_path"], str(dataset_root.resolve()))
        self.assertEqual(saved["years"]["2026"]["rule_path"], str(rule_path.resolve()))
        self.assertEqual(saved["years"]["2026"]["config_json_path"], "保留的配置路径")
        self.assertEqual(saved["years"]["2026"]["extension_field"], "保留的扩展字段")
        self.assertEqual(saved["extension_root"], "保留的顶层扩展字段")
        self.assertEqual([call[0] for call in window.calls], ["folder", "open"])

    def test_management_entries_dispatch_to_exact_legacy_surfaces(self):
        class FakeController:
            def __init__(self):
                self.calls = []

            def is_running(self):
                return True

            def open_file_structure(self, workspace):
                self.calls.append(("file_structure", workspace))
                return "file_request"

            def open_config_editor(self, workspace):
                self.calls.append(("config", workspace))
                return "config_request"

            def initialize_award_workspace(self, workspace):
                self.calls.append(("initialize", workspace))
                return "initialize_request"

            def wait_for_command(self, request_id):
                return {
                    "last_command": {
                        "request_id": request_id,
                        "ok": True,
                        "message": "已打开目标界面",
                        "data": {"target_surface": request_id},
                    }
                }

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026私募"
            workspace_root.mkdir(parents=True)
            config_path = root / "userlib" / "configs" / "private_config.py"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("YEAR = 2026\n", encoding="utf-8")
            write_json(
                root / "logs" / "GB_Test" / "ws_private" / "workspace.json",
                {
                    "workspace_id": "ws_private",
                    "award": "私募金牛奖",
                    "workspace_name": workspace_root.name,
                    "workspace_root": str(workspace_root),
                },
            )
            bridge = TerminalBridge(root)
            workspace_id = bridge.reader.discover_workspaces()[0]["id"]
            controller = FakeController()
            bridge._legacy_controller = controller

            file_result = bridge.management_action(
                {"action": "edit-file-structure", "workspace_id": workspace_id}
            )
            initialize_result = bridge.management_action(
                {"action": "initialize-workspace", "workspace_id": workspace_id}
            )
            with mock.patch("modern_terminal.api.get_award_config_file", return_value=str(config_path)):
                config_result = bridge.management_action(
                    {"action": "open-configs", "workspace_id": workspace_id}
                )

        self.assertTrue(file_result["opened"])
        self.assertTrue(initialize_result["opened"])
        self.assertTrue(config_result["opened"])
        self.assertEqual([name for name, _workspace in controller.calls], ["file_structure", "initialize", "config"])
        self.assertTrue(all(Path(workspace["workspace_root"]) == workspace_root for _name, workspace in controller.calls))

    def test_cancelled_resource_picker_does_not_change_config(self):
        class CancelWindow:
            def create_file_dialog(self, _dialog_type, **_kwargs):
                return None

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026测试"
            workspace_root.mkdir(parents=True)
            resource_path = root / "GB_Test" / "奖项资料配置.json"
            original = {
                "version": 1,
                "years": {"2026": {"dataset_path": "原有路径", "rule_path": "原有规则"}},
            }
            write_json(resource_path, original)
            write_json(
                root / "logs" / "GB_Test" / "ws_legacy" / "workspace.json",
                {
                    "workspace_id": "ws_legacy",
                    "award": "测试流程",
                    "workspace_name": "2026测试",
                    "workspace_root": str(workspace_root),
                },
            )
            bridge = TerminalBridge(root)
            workspace_id = bridge.reader.discover_workspaces()[0]["id"]
            bridge.attach_window(CancelWindow())
            fake_webview = mock.Mock(
                FileDialog=mock.Mock(FOLDER="folder", OPEN="open"),
                FOLDER_DIALOG="legacy-folder",
                OPEN_DIALOG="legacy-open",
            )

            with mock.patch("modern_terminal.api.get_award_folder", return_value="GB_Test"), mock.patch.dict(
                "sys.modules", {"webview": fake_webview}
            ):
                result = bridge.management_action(
                    {"action": "select-dataset", "workspace_id": workspace_id}
                )

            saved = json.loads(resource_path.read_text(encoding="utf-8"))

        self.assertFalse(result["ok"])
        self.assertTrue(result["cancelled"])
        self.assertEqual(saved, original)

    def test_resource_picker_refuses_to_overwrite_malformed_config(self):
        class FakeWindow:
            def __init__(self, selection):
                self.selection = selection

            def create_file_dialog(self, _dialog_type, **_kwargs):
                return (str(self.selection),)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace_root = root / "GB_Test" / "2026测试"
            workspace_root.mkdir(parents=True)
            dataset_root = root / "datasets" / "2026"
            dataset_root.mkdir(parents=True)
            resource_path = root / "GB_Test" / "奖项资料配置.json"
            resource_path.parent.mkdir(parents=True, exist_ok=True)
            original_bytes = b'{"years": '
            resource_path.write_bytes(original_bytes)
            write_json(
                root / "logs" / "GB_Test" / "ws_legacy" / "workspace.json",
                {
                    "workspace_id": "ws_legacy",
                    "award": "测试流程",
                    "workspace_name": "2026测试",
                    "workspace_root": str(workspace_root),
                },
            )
            bridge = TerminalBridge(root)
            workspace_id = bridge.reader.discover_workspaces()[0]["id"]
            bridge.attach_window(FakeWindow(dataset_root))
            fake_webview = mock.Mock(FileDialog=mock.Mock(FOLDER="folder", OPEN="open"))

            with mock.patch("modern_terminal.api.get_award_folder", return_value="GB_Test"), mock.patch.dict(
                "sys.modules", {"webview": fake_webview}
            ):
                result = bridge.management_action(
                    {"action": "select-dataset", "workspace_id": workspace_id}
                )

            saved_bytes = resource_path.read_bytes()
            temp_files = list(resource_path.parent.glob(f".{resource_path.name}.*.tmp"))

        self.assertFalse(result["ok"])
        self.assertIn("保护原文件", result["message"])
        self.assertEqual(saved_bytes, original_bytes)
        self.assertEqual(temp_files, [])


if __name__ == "__main__":
    unittest.main()
