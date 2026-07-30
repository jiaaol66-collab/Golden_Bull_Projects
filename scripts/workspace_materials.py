import os
import re


PROTECTED_STRUCTURE_FILE = "文件结构.xlsx"
ALL_MATERIALS_CATEGORY = "全部资料"
ROOT_MATERIALS_CATEGORY = "资料根目录"
PREFERRED_MATERIAL_CATEGORIES = (
    os.path.join("代码", "工作区设置"),
    os.path.join("代码", "notebook"),
    os.path.join("代码", "更新代码"),
    "说明",
)


def _normalized_path(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _natural_sort_key(text):
    parts = re.split(r"(\d+)", str(text).casefold())
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts if part)


def _is_link_or_junction(path):
    if os.path.islink(path):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


def is_path_within(path, root):
    """Return True only when path is inside root (root itself is included)."""
    if not path or not root:
        return False
    try:
        normalized_path = _normalized_path(path)
        normalized_root = _normalized_path(root)
        return os.path.commonpath([normalized_path, normalized_root]) == normalized_root
    except (OSError, ValueError):
        return False


def is_protected_material_file(path, protected_paths=()):
    if os.path.basename(path).casefold() == PROTECTED_STRUCTURE_FILE.casefold():
        return True
    normalized_path = _normalized_path(path)
    return any(
        protected_path and normalized_path == _normalized_path(protected_path)
        for protected_path in protected_paths
    )


def scan_materials(materials_root):
    """Return recursively discovered folders and ordinary files under 资料."""
    if not materials_root or not os.path.isdir(materials_root):
        return []

    materials_root = os.path.abspath(materials_root)
    folders = []
    for current_root, directory_names, file_names in os.walk(materials_root, followlinks=False):
        directory_names[:] = sorted(
            (
                name
                for name in directory_names
                if not _is_link_or_junction(os.path.join(current_root, name))
            ),
            key=_natural_sort_key,
        )
        rel_folder = os.path.relpath(current_root, materials_root)
        if rel_folder == ".":
            rel_folder = ""

        files = []
        for name in sorted(file_names, key=_natural_sort_key):
            abs_path = os.path.join(current_root, name)
            if _is_link_or_junction(abs_path) or not os.path.isfile(abs_path):
                continue
            try:
                size_bytes = os.path.getsize(abs_path)
            except OSError:
                size_bytes = 0
            files.append(
                {
                    "name": name,
                    "abs_path": abs_path,
                    "rel_path": os.path.relpath(abs_path, materials_root),
                    "extension": os.path.splitext(name)[1].lower(),
                    "size_bytes": size_bytes,
                }
            )

        folders.append(
            {
                "name": os.path.basename(current_root) if rel_folder else "资料根目录",
                "abs_path": current_root,
                "rel_path": rel_folder,
                "files": files,
            }
        )
    return folders


def get_material_categories(folders):
    categories = set()
    code_has_subcategory = False
    for folder in folders or ():
        rel_path = str(folder.get("rel_path", "")).strip()
        if rel_path:
            parts = rel_path.split(os.sep)
            if parts[0].casefold() == "代码".casefold() and len(parts) >= 2:
                categories.add(os.path.join(parts[0], parts[1]))
                code_has_subcategory = True
            elif parts[0].casefold() != "代码".casefold():
                categories.add(parts[0])
        elif folder.get("files"):
            categories.add(ROOT_MATERIALS_CATEGORY)

    if not code_has_subcategory and any(
        str(folder.get("rel_path", "")).casefold() == "代码".casefold()
        for folder in folders or ()
    ):
        categories.add("代码")

    preferred_order = {
        category.casefold(): index
        for index, category in enumerate(PREFERRED_MATERIAL_CATEGORIES)
    }
    sorted_categories = sorted(
        categories,
        key=lambda category: (
            0 if category.casefold() in preferred_order else 1,
            preferred_order.get(category.casefold(), 0),
            _natural_sort_key(category),
        ),
    )
    return [ALL_MATERIALS_CATEGORY, *sorted_categories]


def filter_material_folders(folders, category):
    if not category or category == ALL_MATERIALS_CATEGORY:
        return list(folders or ())
    if category == ROOT_MATERIALS_CATEGORY:
        return [folder for folder in folders or () if not folder.get("rel_path")]
    prefix = category + os.sep
    return [
        folder
        for folder in folders or ()
        if folder.get("rel_path") == category or str(folder.get("rel_path", "")).startswith(prefix)
    ]


def validate_material_file_deletion(materials_root, target_path, protected_paths=()):
    """Validate a file deletion request without mutating the filesystem."""
    if not is_path_within(target_path, materials_root):
        return False, "目标文件不在当前工作区的资料目录中。"
    if _normalized_path(target_path) == _normalized_path(materials_root):
        return False, "资料根目录不能删除。"
    if is_protected_material_file(target_path, protected_paths):
        return False, f"{PROTECTED_STRUCTURE_FILE} 属于工作区结构文件，已禁止删除。"
    if _is_link_or_junction(target_path):
        return False, "链接文件不能在资料页中删除。"
    if not os.path.isfile(target_path):
        return False, "文件不存在，可能已经被移动或删除。"
    return True, ""


def format_file_size(size_bytes):
    try:
        size = max(0.0, float(size_bytes))
    except (TypeError, ValueError):
        size = 0.0
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"
