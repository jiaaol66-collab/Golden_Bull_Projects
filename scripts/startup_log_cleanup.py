# -*- coding: utf-8 -*-
"""启动时清理已不存在工作区所对应的日志归档。"""

import json
import os
import re
import shutil
import stat


WORKSPACE_ID_PATTERN = re.compile(r"^ws_[A-Za-z0-9_-]+$")


def _normalize_path(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _is_relative_to(path, root):
    try:
        return os.path.commonpath([_normalize_path(path), _normalize_path(root)]) == _normalize_path(root)
    except (OSError, ValueError):
        return False


def _is_link_or_junction(path):
    if os.path.islink(path):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is None:
        return False
    try:
        return bool(isjunction(path))
    except OSError:
        return True


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _get_directory_state(path):
    try:
        path_stat = os.stat(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unknown"
    return "directory" if stat.S_ISDIR(path_stat.st_mode) else "not_directory"


def _looks_like_workspace(path):
    if os.path.isfile(os.path.join(path, ".gb_workspace.json")):
        return True
    blueprint_paths = (
        os.path.join(path, "资料", "代码", "工作区设置", "文件结构.xlsx"),
        os.path.join(path, "工作区设置", "文件结构.xlsx"),
    )
    return any(os.path.isfile(candidate) for candidate in blueprint_paths)


def _build_active_workspace_index(award_roots):
    active_ids = set()
    active_names = set()
    active_roots = set()

    for award_root in sorted({_normalize_path(path) for path in award_roots if path}):
        if not os.path.isdir(award_root):
            continue
        try:
            names = os.listdir(award_root)
        except OSError:
            continue
        for name in names:
            workspace_root = os.path.join(award_root, name)
            if not os.path.isdir(workspace_root) or not _looks_like_workspace(workspace_root):
                continue
            active_roots.add(_normalize_path(workspace_root))
            active_names.add(os.path.normcase(name.strip()))
            metadata = _load_json(os.path.join(workspace_root, ".gb_workspace.json"))
            workspace_id = str(metadata.get("workspace_id", "")).strip()
            if WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
                active_ids.add(workspace_id)

    return active_ids, active_names, active_roots


def _directory_size(path):
    total = 0
    for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
        dirs[:] = [name for name in dirs if not _is_link_or_junction(os.path.join(root, name))]
        for name in files:
            file_path = os.path.join(root, name)
            try:
                total += os.lstat(file_path).st_size
            except OSError:
                continue
    return total


def _is_safe_workspace_log_dir(path, logs_root):
    path = _normalize_path(path)
    logs_root = _normalize_path(logs_root)
    if path == logs_root or not _is_relative_to(path, logs_root):
        return False
    if _is_link_or_junction(path):
        return False
    relative = os.path.relpath(path, logs_root)
    parts = [part for part in relative.split(os.sep) if part not in ("", ".")]
    return len(parts) == 2 and WORKSPACE_ID_PATTERN.fullmatch(parts[1]) is not None


def format_bytes(value):
    size = float(max(0, int(value or 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def cleanup_deleted_workspace_logs(logs_root, award_roots, repo_root=None, dry_run=False):
    """删除日志清单中工作区目录已不存在、且未迁移到现有工作区的归档。"""
    logs_root = _normalize_path(logs_root)
    repo_root = _normalize_path(repo_root or os.path.dirname(logs_root))
    summary = {
        "checked": 0,
        "candidates": [],
        "deleted": [],
        "failed": [],
        "skipped": [],
        "bytes_freed": 0,
        "dry_run": bool(dry_run),
    }
    if not os.path.isdir(logs_root):
        return summary

    active_ids, active_names, active_roots = _build_active_workspace_index(award_roots)
    try:
        award_dir_names = os.listdir(logs_root)
    except OSError as exc:
        summary["failed"].append({"workspace_name": "", "log_dir": logs_root, "error": str(exc)})
        return summary

    for award_dir_name in sorted(award_dir_names):
        award_log_root = os.path.join(logs_root, award_dir_name)
        if not os.path.isdir(award_log_root) or _is_link_or_junction(award_log_root):
            continue
        try:
            workspace_dir_names = os.listdir(award_log_root)
        except OSError as exc:
            summary["failed"].append({"workspace_name": "", "log_dir": award_log_root, "error": str(exc)})
            continue

        for workspace_dir_name in sorted(workspace_dir_names):
            if WORKSPACE_ID_PATTERN.fullmatch(workspace_dir_name) is None:
                continue
            log_dir = os.path.join(award_log_root, workspace_dir_name)
            if not os.path.isdir(log_dir):
                continue
            summary["checked"] += 1
            manifest_path = os.path.join(log_dir, "workspace.json")
            metadata = _load_json(manifest_path)
            workspace_id = str(metadata.get("workspace_id", "")).strip()
            workspace_name = str(metadata.get("workspace_display_name", "")).strip()
            workspace_name = workspace_name or str(metadata.get("workspace_name", "")).strip() or workspace_dir_name
            stored_workspace_root = str(metadata.get("workspace_root", "")).strip()

            if not metadata or workspace_id != workspace_dir_name or not stored_workspace_root:
                summary["skipped"].append({
                    "workspace_name": workspace_name,
                    "log_dir": log_dir,
                    "reason": "日志元数据缺失或与目录不一致",
                })
                continue

            workspace_root = stored_workspace_root
            if not os.path.isabs(workspace_root):
                workspace_root = os.path.join(repo_root, workspace_root)
            normalized_workspace_root = _normalize_path(workspace_root)
            normalized_workspace_name = os.path.normcase(str(metadata.get("workspace_name", "")).strip())

            workspace_state = _get_directory_state(workspace_root)
            if workspace_state == "unknown":
                summary["skipped"].append({
                    "workspace_name": workspace_name,
                    "log_dir": log_dir,
                    "reason": "无法确认原工作区路径是否存在",
                })
                continue
            workspace_still_exists = workspace_state == "directory"
            workspace_was_moved = (
                workspace_id in active_ids
                or normalized_workspace_root in active_roots
                or (normalized_workspace_name and normalized_workspace_name in active_names)
            )
            if workspace_still_exists or workspace_was_moved:
                continue

            item = {
                "workspace_id": workspace_id,
                "workspace_name": workspace_name,
                "workspace_root": stored_workspace_root,
                "log_dir": log_dir,
                "size_bytes": _directory_size(log_dir),
            }
            summary["candidates"].append(item)
            if dry_run:
                continue

            if not _is_safe_workspace_log_dir(log_dir, logs_root):
                failed_item = dict(item)
                failed_item["error"] = "日志目录未通过安全校验"
                summary["failed"].append(failed_item)
                continue
            try:
                shutil.rmtree(log_dir)
            except OSError as exc:
                failed_item = dict(item)
                failed_item["error"] = str(exc)
                summary["failed"].append(failed_item)
                continue

            summary["deleted"].append(item)
            summary["bytes_freed"] += item["size_bytes"]

        try:
            if os.path.isdir(award_log_root) and not os.listdir(award_log_root):
                os.rmdir(award_log_root)
        except OSError:
            pass

    return summary
