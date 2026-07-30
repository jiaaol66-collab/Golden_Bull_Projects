from __future__ import annotations

import argparse
import ast
from pathlib import Path


IMPORT_MARKER = "## 导入..."
SUCCESS_MARKER = "print('success')"


def normalized_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def resolve_inside(workspace: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    resolved = path.resolve() if path.is_absolute() else (workspace / path).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as error:
        raise ValueError(f"路径超出工作区：{raw_path}") from error
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="审计新金牛奖工作区的步骤、模板继承和部署同步。"
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--default-code", type=Path, required=True)
    parser.add_argument(
        "--step",
        action="append",
        required=True,
        help="资料源码|部署脚本；路径相对于 workspace，可重复。",
    )
    parser.add_argument(
        "--required-step",
        action="append",
        default=[],
        help="必须存在的步骤目录名，可重复。",
    )
    parser.add_argument("--award-config", type=Path)
    parser.add_argument("--award-label")
    parser.add_argument("--results-dir")
    parser.add_argument("--expect-empty-results", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    project_root = args.project_root.resolve()
    workspace = args.workspace.resolve()
    default_code = args.default_code.resolve()

    if not project_root.is_dir():
        errors.append(f"项目根目录不存在：{project_root}")
    if not workspace.is_dir():
        errors.append(f"工作区不存在：{workspace}")
    else:
        try:
            workspace.relative_to(project_root)
        except ValueError:
            errors.append("工作区不在项目根目录内。")
    if not default_code.is_file():
        errors.append(f"default_code.py 不存在：{default_code}")

    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1

    template = normalized_text(default_code)
    if template.count(IMPORT_MARKER) != 1:
        errors.append(f"default_code.py 的 {IMPORT_MARKER} 锚点不唯一。")
    if template.count(SUCCESS_MARKER) != 1:
        errors.append(f"default_code.py 的 {SUCCESS_MARKER} 锚点不唯一。")
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1

    prefix = template.split(IMPORT_MARKER, 1)[0] + IMPORT_MARKER + "\n"
    suffix = SUCCESS_MARKER + template.split(SUCCESS_MARKER, 1)[1]
    requires_flush = "open_file('flush_buffer.py')" in suffix

    for step_pair in args.step:
        if step_pair.count("|") != 1:
            errors.append(f"--step 格式错误：{step_pair}")
            continue
        source_raw, deployed_raw = step_pair.split("|", 1)
        try:
            source = resolve_inside(workspace, source_raw)
            deployed = resolve_inside(workspace, deployed_raw)
        except ValueError as error:
            errors.append(str(error))
            continue

        if not source.is_file():
            errors.append(f"资料源码不存在：{source}")
            continue
        if not deployed.is_file():
            errors.append(f"部署脚本不存在：{deployed}")
            continue
        if source.read_bytes() != deployed.read_bytes():
            errors.append(f"资料源码与部署脚本不一致：{source} | {deployed}")

        source_text = normalized_text(source)
        if not source_text.startswith(prefix):
            errors.append(f"未继承 default_code.py 前缀：{source}")
        if not source_text.rstrip().endswith(suffix.rstrip()):
            errors.append(f"未继承 default_code.py 收尾：{source}")
        try:
            ast.parse(source_text, filename=str(source))
        except SyntaxError as error:
            errors.append(f"Python 语法错误：{source}: {error}")

        if requires_flush and not (deployed.parent / "flush_buffer.py").is_file():
            errors.append(f"缺少 flush_buffer.py：{deployed.parent}")

    for step_name in args.required_step:
        try:
            step_dir = resolve_inside(workspace, step_name)
        except ValueError as error:
            errors.append(str(error))
            continue
        if not step_dir.is_dir():
            errors.append(f"缺少步骤目录：{step_dir}")

    if args.award_config:
        config_path = args.award_config.resolve()
        if not config_path.is_file():
            errors.append(f"奖项配置不存在：{config_path}")
        else:
            config_text = normalized_text(config_path)
            try:
                ast.parse(config_text, filename=str(config_path))
            except SyntaxError as error:
                errors.append(f"奖项配置语法错误：{error}")
            if args.award_label and args.award_label not in config_text:
                errors.append(f"奖项配置中未找到标签：{args.award_label}")

    if args.results_dir:
        try:
            results_dir = resolve_inside(workspace, args.results_dir)
        except ValueError as error:
            errors.append(str(error))
        else:
            if not results_dir.is_dir():
                errors.append(f"结果目录不存在：{results_dir}")
            elif args.expect_empty_results and any(results_dir.iterdir()):
                errors.append(f"评分未确认但结果目录非空：{results_dir}")

    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        print(f"Blocking issues: {len(errors)}")
        return 1

    print("[PASS] 工作区路径与项目边界")
    print("[PASS] default_code.py 模板继承")
    print("[PASS] 资料源码与部署脚本同步")
    print("[PASS] Python 语法")
    if requires_flush:
        print("[PASS] flush_buffer.py 部署")
    print("Blocking issues: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
