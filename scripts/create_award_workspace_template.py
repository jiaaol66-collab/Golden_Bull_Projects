import os
import re
import sys
import json
import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
os.chdir(REPO_ROOT)
# 将项目根目录添加到 sys.path，确保可以找到 award_config 等模块
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openpyxl import load_workbook

from award_config import register_award_template
from userlib.tools import (
    copy_file,
    custom_dialog,
    custom_input_dialog,
    make_dir,
)
BASIC_CODE_DIR = REPO_ROOT / "_必备代码" / "_基础代码"
TOOL_CODE_DIR = REPO_ROOT / "_必备代码" / "_工具代码"
DEFAULT_CODE_DIR = REPO_ROOT / "_必备代码" / "_默认代码"
RESULT_FILE_PATH = REPO_ROOT / ".award_template_creation_result.json"

ROOT_BASIC_FILES = ["data_ingestion.py", "initialize.py"]
UPDATE_BASIC_FILES = ["run_this.py", "main_script.py"]
ROOT_CODE_FILES = {"code_backup.py", "flush_buffer.py", "run.bat"}
README_FILES = {"readme_backup.py"}


def _clean_text(value):
    return str(value or "").strip()


def _validate_non_empty(value):
    text = _clean_text(value)
    if not text:
        return False, "不能为空"
    return True, ""


def _validate_award_english(value):
    text = _clean_text(value)
    if not text:
        return False, "不能为空"
    if text.upper().startswith("GB_"):
        return False, "这里只填英文名本体，不要带 GB_ 前缀"
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", text):
        return False, "只能使用英文、数字、下划线，且必须以英文字母开头"
    return True, ""


def _build_workspace_name(award_short_name, award_root):
    now = datetime.datetime.now()
    base_name = f"{now.year}{award_short_name}_{now.strftime('%y%m%d')}"
    candidate = base_name
    suffix = 1
    while (award_root / candidate).exists():
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    return candidate


def _copy_required_file(src, dst):
    ok = copy_file(str(src), str(dst), 1, 1, 1)
    if not ok:
        raise FileNotFoundError(f"复制失败: {src} -> {dst}")


def _write_json_file(path, payload):
    temp_path = str(path) + ".tmp"
    with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _ensure_workspace_tree(workspace_root):
    required_dirs = [
        workspace_root,
        workspace_root / "资料",
        workspace_root / "资料" / "代码",
        workspace_root / "资料" / "代码" / "notebook",
        workspace_root / "资料" / "代码" / "更新代码",
        workspace_root / "资料" / "代码" / "工作区设置",
        workspace_root / "资料" / "说明",
    ]
    for path in required_dirs:
        make_dir(str(path), 1)


def _patch_workspace_name_in_blueprint(xlsx_path, award_short_name):
    workbook = load_workbook(xlsx_path)
    worksheet = workbook["工作区"] if "工作区" in workbook.sheetnames else workbook.active
    headers = [_clean_text(worksheet.cell(row=1, column=idx).value) for idx in range(1, worksheet.max_column + 1)]
    if "工作区名" not in headers:
        workbook.save(xlsx_path)
        return
    col_map = {name: headers.index(name) + 1 for name in headers if name}
    column_index = col_map["工作区名"]
    anchor_row = None
    for row_index in range(2, worksheet.max_row + 1):
        workspace_cell = worksheet.cell(row=row_index, column=column_index)
        if _clean_text(workspace_cell.value):
            anchor_row = row_index
            break
    if anchor_row is None:
        anchor_row = 2
    for row_index in range(2, worksheet.max_row + 1):
        worksheet.cell(row=row_index, column=column_index, value=award_short_name if row_index == anchor_row else None)
    workbook.save(xlsx_path)


def _create_workspace_skeleton(award_name, award_english_name, award_short_name):
    award_folder_name = f"GB_{award_english_name}"
    award_root = REPO_ROOT / award_folder_name
    workspace_name = _build_workspace_name(award_short_name, award_root)
    workspace_root = award_root / workspace_name

    make_dir(str(award_root), 1)
    make_dir(str(award_root / "原始数据集"), 1)
    _ensure_workspace_tree(workspace_root)

    for file_name in ROOT_BASIC_FILES:
        _copy_required_file(BASIC_CODE_DIR / file_name, award_root / file_name)

    for file_name in UPDATE_BASIC_FILES:
        _copy_required_file(BASIC_CODE_DIR / file_name, workspace_root / "资料" / "代码" / "更新代码" / file_name)

    for file_name in os.listdir(TOOL_CODE_DIR):
        source = TOOL_CODE_DIR / file_name
        if file_name in ROOT_CODE_FILES:
            target = workspace_root / "资料" / "代码" / file_name
        elif file_name in README_FILES:
            target = workspace_root / "资料" / "说明" / file_name
        else:
            target = workspace_root / "资料" / "代码" / "更新代码" / file_name
        _copy_required_file(source, target)

    _copy_required_file(DEFAULT_CODE_DIR / "default_code.py", workspace_root / "资料" / "代码" / "default_code.py")
    _copy_required_file(DEFAULT_CODE_DIR / "default_notebook.ipynb", workspace_root / "资料" / "代码" / "notebook" / "default_notebook.ipynb")
    _copy_required_file(DEFAULT_CODE_DIR / "readme.docx", workspace_root / "资料" / "说明" / "readme.docx")
    _copy_required_file(DEFAULT_CODE_DIR / "文件结构.xlsx", workspace_root / "资料" / "代码" / "工作区设置" / "文件结构.xlsx")
    _copy_required_file(DEFAULT_CODE_DIR / "工作区说明.docx", workspace_root / "资料" / "代码" / "工作区设置" / "工作区说明.docx")

    blueprint_path = workspace_root / "资料" / "代码" / "工作区设置" / "文件结构.xlsx"
    _patch_workspace_name_in_blueprint(str(blueprint_path), award_short_name)

    register_award_template(
        award_name=award_name,
        english_award_name=award_folder_name,
        manifest_award=award_short_name,
        project_root=str(REPO_ROOT),
    )

    return {
        "award_name": award_name,
        "award_english_name": award_english_name,
        "award_short_name": award_short_name,
        "award_folder_name": award_folder_name,
        "award_root": str(award_root),
        "workspace_name": workspace_name,
        "workspace_root": str(workspace_root),
        "blueprint_path": str(blueprint_path),
    }


def _create_step0_runner(workspace_root):
    workspace_root = Path(workspace_root)
    step0_dir = workspace_root / "step_0_前期准备"
    make_dir(str(step0_dir), 1)

    source = workspace_root / "资料" / "代码" / "更新代码" / "run_this.py"
    target = step0_dir / "运行此文件.py"
    _copy_required_file(source, target)
    return str(target)


# def _create_award_initialize_runner(award_root):
#     award_root = Path(award_root)
#     source = award_root / "initialize.py"
#     target = award_root / "运行此文件.py"
#     _copy_required_file(source, target)
#     return str(target)


def _write_creation_result(context):
    payload = {
        "award_name": context["award_name"],
        "workspace_name": context["workspace_name"],
        "workspace_root": context["workspace_root"],
        "award_root": context["award_root"],
        "year_text": str(datetime.datetime.now().year),
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    _write_json_file(RESULT_FILE_PATH, payload)


def _prompt_context():
    fields = [
        {
            "label": "奖项名",
            "default": "",
            "hint": "例如：量化CTA金牛奖",
            "validate": _validate_non_empty,
        },
        {
            "label": "奖项英文",
            "default": "",
            "hint": "不包含 GB_，例如 CTA",
            "validate": _validate_award_english,
        },
        {
            "label": "奖项简称",
            "default": "",
            "hint": "会写入 文件结构.xlsx 的“工作区名”列，例如 CTA",
            "validate": _validate_non_empty,
        },
    ]
    result = custom_input_dialog("新建奖项工作区模板", fields)
    if not result:
        return None
    return {
        "award_name": _clean_text(result.get("奖项名")),
        "award_english_name": _clean_text(result.get("奖项英文")),
        "award_short_name": _clean_text(result.get("奖项简称")),
    }


def main():
    try:
        params = _prompt_context()
        if not params:
            return 0

        context = _create_workspace_skeleton(**params)
        step0_runner_path = _create_step0_runner(context["workspace_root"])
        # initialize_runner_path = _create_award_initialize_runner(context["award_root"])
        _write_creation_result(context)
        custom_dialog(
            "工作区已创建",
            "基础骨架已经生成。\n\n"
            "terminal 会自动切换到刚创建的奖项和工作区。\n\n"
            "下一步请在 terminal 中：\n"
            "1. 点击“文件结构”按钮，自定义 文件结构.xlsx。\n"
            "2. 保存后，terminal 会按最新文件结构重新读取工作区。\n"
            "3. 如需先做奖项级初始化，可运行奖项根目录里的 运行此文件.py。\n"
            "4. 最后手动运行 step_0_前期准备 里的 运行此文件.py。\n\n"
            # f"奖项根目录初始化入口：\n{initialize_runner_path}\n\n"
            f"工作区：\n{context['workspace_root']}\n\n"
            f"step_0 运行入口：\n{step0_runner_path}",
            "info",
            "知道了",
        )
        return 0
    except Exception as exc:
        custom_dialog("创建失败", str(exc), "error", "确认")
        return 1


if __name__ == "__main__":
    sys.exit(main())
