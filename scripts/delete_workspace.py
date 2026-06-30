import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

from award_config import AWARD_FOLDER_MAP
from userlib.tools import delete_file

LOGS_ROOT = os.path.join(REPO_ROOT, "logs")


def is_relative_to(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def is_safe_workspace_dir(path):
    workspace_path = os.path.abspath(path)
    for root_rel in AWARD_FOLDER_MAP.values():
        root_abs = os.path.abspath(os.path.join(REPO_ROOT, root_rel))
        if not is_relative_to(workspace_path, root_abs):
            continue
        if workspace_path == root_abs:
            return False
        if os.path.dirname(workspace_path) == root_abs:
            return True
    return False


def load_workspace_metadata(workspace_path):
    meta_path = os.path.join(workspace_path, ".gb_workspace.json")
    if not os.path.isfile(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def get_workspace_log_dir(workspace_path):
    payload = load_workspace_metadata(workspace_path)
    workspace_id = str(payload.get("workspace_id", "")).strip()
    award_dir_name = str(payload.get("award_dir_name", "")).strip() or os.path.basename(os.path.dirname(workspace_path))
    if not workspace_id or not award_dir_name:
        return ""
    return os.path.abspath(os.path.join(LOGS_ROOT, award_dir_name, workspace_id))


def is_safe_log_dir(path):
    log_path = os.path.abspath(path)
    if not os.path.isdir(log_path):
        return False
    if log_path == LOGS_ROOT:
        return False
    return is_relative_to(log_path, LOGS_ROOT)


def main():
    if len(sys.argv) < 2:
        print("缺少工作区路径参数", file=sys.stderr)
        return 2

    workspace_path = os.path.abspath(sys.argv[1])
    if not os.path.exists(workspace_path):
        print(f"工作区不存在: {workspace_path}", file=sys.stderr)
        return 1

    if not os.path.isdir(workspace_path):
        print(f"目标不是工作区目录: {workspace_path}", file=sys.stderr)
        return 1

    if not is_safe_workspace_dir(workspace_path):
        print(f"拒绝删除非工作区目录: {workspace_path}", file=sys.stderr)
        return 1

    log_dir = get_workspace_log_dir(workspace_path)

    if not delete_file(workspace_path, clear=1, silence=1):
        print(f"删除工作区失败: {workspace_path}", file=sys.stderr)
        return 1

    log_deleted = False
    if log_dir and os.path.exists(log_dir):
        if not is_safe_log_dir(log_dir):
            print(f"工作区已删除，但拒绝删除非安全日志目录: {log_dir}", file=sys.stderr)
            return 1
        if not delete_file(log_dir, clear=1, silence=1):
            print(f"工作区已删除，但删除日志失败: {log_dir}", file=sys.stderr)
            return 1
        log_deleted = True

    if log_deleted:
        print(f"已删除工作区及日志: {workspace_path} | {log_dir}")
    else:
        print(f"已删除工作区: {workspace_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
