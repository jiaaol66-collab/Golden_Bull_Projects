from __future__ import annotations

import os
from pathlib import Path


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def resolve_private_db_path(current_file, yr):
    name = _clean_text(os.getenv("PRIVATE_DB_NAME")) or "DB_PRIVATE.duckdb"

    direct = _clean_text(os.getenv("PRIVATE_DB_PATH"))
    if direct:
        direct_path = Path(os.path.expandvars(os.path.expanduser(direct))).resolve()
        if direct_path.exists():
            return direct_path

    root = _clean_text(os.getenv("PRIVATE_DB_ROOT"))
    if root:
        root_path = Path(os.path.expandvars(os.path.expanduser(root))).resolve()
        candidate = (root_path / "数据库" / str(yr) / name).resolve()
        if candidate.exists():
            return candidate

    current_path = Path(current_file).resolve()
    candidates = []
    seen = set()
    for parent in current_path.parents:
        candidate = (parent / "数据库" / str(yr) / name).resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
        if candidate.exists():
            return candidate

    candidate_text = "\n".join(str(p) for p in candidates[:10])
    raise FileNotFoundError(f"未找到 {name}，可检查以下路径:\n{candidate_text}")

