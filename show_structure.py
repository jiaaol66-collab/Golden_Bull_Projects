from pathlib import Path
from datetime import datetime

# 修改这里：目标文件夹的绝对路径
FOLDER = Path(input("输入对应文件夹的绝对路径："))
OUTPUT = FOLDER / "文件结构.txt"

# 不想展示的文件夹名称；不排除任何目录就保持为空
EXCLUDE_DIRS = set()  # 例如 {".git", "__pycache__", "node_modules"}


def build_tree(folder, prefix=""):
    try:
        entries = [
            p for p in folder.iterdir()
            if p != OUTPUT
            and not (p.is_dir() and p.name in EXCLUDE_DIRS)
        ]
        entries.sort(key=lambda p: (not p.is_dir(), p.name.casefold()))
    except OSError as exc:
        return [f"{prefix}[无法读取：{exc}]"]

    lines = []
    for index, entry in enumerate(entries):
        last = index == len(entries) - 1
        branch = "└── " if last else "├── "
        is_dir = entry.is_dir()

        # 不进入符号链接或 Windows 目录联接，避免循环遍历
        is_link = entry.is_symlink() or (
            hasattr(entry, "is_junction") and entry.is_junction()
        )
        label = entry.name + ("/" if is_dir else "")
        if is_link:
            label += " [链接，不展开]"

        lines.append(prefix + branch + label)

        if is_dir and not is_link:
            next_prefix = prefix + ("    " if last else "│   ")
            lines.extend(build_tree(entry, next_prefix))

    return lines


if not FOLDER.is_absolute():
    raise ValueError("请填写绝对路径。")
if not FOLDER.is_dir():
    raise NotADirectoryError(f"文件夹不存在：{FOLDER}")

content = [
    f"目录：{FOLDER}",
    f"update_at：{datetime.now():%Y-%m-%d %H:%M:%S}",
    "",
    FOLDER.name + "/",
    *build_tree(FOLDER),
]

OUTPUT.write_text("\n".join(content) + "\n", encoding="utf-8-sig")
print(f"已输出：{OUTPUT}")