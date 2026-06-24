# -*- coding: utf-8 -*-
"""
金牛奖工作区清单解析器（验证用，挂在 Golden_Bull_Projects 根目录）

职责（只做这两件，不含任何界面/计算代码）：
  1. 解析配置文件 文件结构.xlsx  -> 得到“蓝图”：按 运行顺序 排好的可执行步骤 + 声明的核验目录
  2. 与真实工作区目录核对          -> 标注每个脚本/目录是否真的存在、核验目录里有几个文件

蓝图来自配置（顺序、路径、奖项均由 xlsx 决定），存在性来自磁盘。
两者合起来就是“步骤列表 + 单跑 + 产物面板”所需的全部数据结构。
"""

import os
from openpyxl import load_workbook
from award_config import AWARD_FOLDER_MAP

# 验证脚本只需要扫描奖项总根目录，银行理财在这里统一落到共同父目录。
AWARD_SCAN_ROOT = {
    "私募": AWARD_FOLDER_MAP["私募"],
    "公募": AWARD_FOLDER_MAP["公募"],
    "银行理财": os.path.dirname(AWARD_FOLDER_MAP["银行理财(产品奖)"]),
}


def _clean(v):
    """把 '.'、None、'None' 统一当成空串。"""
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s in (".", "None") else s


def _is_step_id(v):
    """步骤号：0 / 0_5 / 1 / 1_5 / ... / 6（'.' 之类返回 False）。"""
    s = _clean(v)
    return bool(s) and s.replace("_", "").isdigit()


def _step_folder(step, folder):
    """
    把配置里的“工作区文件夹”还原成磁盘上的真实文件夹名。
    步骤行 -> 'step_{步骤} {文件夹}'（如 step_0 前期准备 / step_1_5 净值对齐可视化）
    非步骤行（参评信息、重要文件等）-> 原样
    """
    folder = _clean(folder)
    if not folder:
        return ""
    if _is_step_id(step):
        return "step_{} {}".format(_clean(step), folder)
    return folder


def _rel_dir(folder, *subs):
    """folder + 子文件夹1..4，过滤空段，拼成相对目录。"""
    parts = [folder] + [_clean(s) for s in subs]
    parts = [p for p in parts if p]
    return os.path.join(*parts) if parts else ""


def build_workspace_manifest(blueprint_xlsx, workspace_root, award="私募"):
    """
    解析配置 -> 蓝图清单（不碰文件系统）。

    workspace_root: 该工作区在磁盘上的根，如 私募金牛奖步骤/2026私募_260616_1
    award:          奖项，对应 xlsx 的“工作区名”列
    """
    wb = load_workbook(blueprint_xlsx, data_only=True)
    ws = wb["工作区"]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    col = {name: i for i, name in enumerate(header)}

    AWARD = col["工作区名"]
    STEP = col["步骤"]
    FOLDER = col["工作区文件夹"]
    SUB = [col["子文件夹1"], col["子文件夹2"], col["子文件夹3"], col["子文件夹4"]]
    ORDER = col["运行顺序"]
    SCRIPT = col["相应代码和说明文件"]
    KIND = col["代码/说明"]
    BACKUP = col["保存在资料中的名称"]
    NOTE = col["备注"]

    data = [list(r) for r in rows[1:]]

    # “工作区名”是合并单元格，只在每个奖项块首行有值 -> 向下填充
    cur_award = ""
    for r in data:
        a = _clean(r[AWARD])
        if a:
            cur_award = a
        r[AWARD] = cur_award

    steps, verify = [], []
    for r in data:
        if r[AWARD] != award:
            continue
        folder = _step_folder(r[STEP], r[FOLDER])
        rel_dir = _rel_dir(folder, *[r[i] for i in SUB])
        script = _clean(r[SCRIPT])
        order = r[ORDER]

        # 可执行步骤：运行顺序为数字 + 代码 + .py（排除 ipynb / docx / 可视化无顺序项）
        is_pipeline = (
            isinstance(order, (int, float))
            and _clean(r[KIND]) == "代码"
            and script.endswith(".py")
        )
        if is_pipeline:
            steps.append({
                "order": int(order),
                "step": _clean(r[STEP]),
                "script_name": script,                 # 工作区内中文运行名
                "backup_name": _clean(r[BACKUP]),      # 备份/英文名（对照用）
                "rel_path": os.path.join(rel_dir, script) if rel_dir else script,
            })
            continue

        # 核验目录：路径里带“机构筛选数据”的目录声明行（非脚本行）
        if not script and "机构筛选数据" in rel_dir.replace(os.sep, "/"):
            verify.append({
                "step": _clean(r[STEP]),
                "rel_path": rel_dir,
                "note": _clean(r[NOTE]),
            })

    steps.sort(key=lambda s: s["order"])
    return {
        "award": award,
        "workspace_root": workspace_root,
        "steps": steps,
        "verify_folders": verify,
    }


def reconcile_filesystem(manifest):
    """蓝图 + 磁盘状态：标注脚本是否存在、核验目录是否存在及文件数。"""
    root = manifest["workspace_root"]
    for s in manifest["steps"]:
        p = os.path.join(root, s["rel_path"])
        s["abs_path"] = p
        s["exists"] = os.path.isfile(p)
    for v in manifest["verify_folders"]:
        p = os.path.join(root, v["rel_path"])
        v["abs_path"] = p
        v["exists"] = os.path.isdir(p)
        v["n_files"] = len(os.listdir(p)) if v["exists"] else 0
    return manifest


def print_manifest(m):
    mark = lambda ok: "✓" if ok else "✗"
    print("=" * 78)
    print("奖项: {}   工作区: {}".format(m["award"], os.path.basename(m["workspace_root"])))
    print("=" * 78)
    print("\n[可执行管线步骤]  (按运行顺序)")
    for s in m["steps"]:
        ok = s.get("exists")
        tag = "  " if ok is None else " [{}]".format(mark(ok))
        print("  {:>2}.{} {:<22} ({})".format(
            s["order"], tag, s["script_name"], s["backup_name"]))
    print("\n[机构筛选核验目录]")
    for v in m["verify_folders"]:
        if v.get("exists") is None:
            print("  - {}".format(v["rel_path"]))
        else:
            print("  - [{}] {:<3}files  {}".format(
                mark(v["exists"]), v["n_files"], v["rel_path"]))


if __name__ == "__main__":
    # 在 Golden_Bull_Projects 根目录下运行
    AWARD = "私募"
    award_root_dir = AWARD_SCAN_ROOT[AWARD]
    
    ignore_dirs = {"数据库", "代码备份", "工作区设置", "__pycache__"}
    
    print("正在扫描 [{}] 根目录: {} ...\n".format(AWARD, award_root_dir))
    
    for folder_name in os.listdir(award_root_dir):
        workspace_path = os.path.join(award_root_dir, folder_name)
        
        if os.path.isdir(workspace_path) and folder_name not in ignore_dirs:
            # 动态寻找当前工作区内部的文件结构.xlsx
            blueprint_path = os.path.join(workspace_path, "资料", "代码", "工作区设置", "文件结构.xlsx")
            
            # 如果上面路径不对，尝试备用路径
            if not os.path.exists(blueprint_path):
                blueprint_path = os.path.join(workspace_path, "工作区设置", "文件结构.xlsx")
                
            # 如果还是找不到，说明不是标准工作区，直接跳过
            if not os.path.exists(blueprint_path):
                print("跳过 {}: 未找到 文件结构.xlsx".format(folder_name))
                continue
                
            try:
                m = build_workspace_manifest(blueprint_path, workspace_path, award=AWARD)
                reconcile_filesystem(m)
                print_manifest(m)
                print("\n" + "*"*78 + "\n")
            except Exception as e:
                print("解析工作区 {} 时发生错误: {}".format(folder_name, e))
