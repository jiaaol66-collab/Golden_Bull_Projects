from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path


IMPORT_MARKER = "## 导入..."
SUCCESS_MARKER = "print('success')"


def read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def build_script(template: str, body: str) -> str:
    if template.count(IMPORT_MARKER) != 1:
        raise ValueError(f"模板必须且只能包含一个锚点：{IMPORT_MARKER}")
    if template.count(SUCCESS_MARKER) != 1:
        raise ValueError(f"模板必须且只能包含一个锚点：{SUCCESS_MARKER}")
    if IMPORT_MARKER in body or SUCCESS_MARKER in body:
        raise ValueError("主体文件不得包含模板锚点。")

    prefix = template.split(IMPORT_MARKER, 1)[0] + IMPORT_MARKER + "\n"
    suffix = SUCCESS_MARKER + template.split(SUCCESS_MARKER, 1)[1]
    body = body.strip()
    return prefix + body + "\n\n" + suffix.lstrip("\n")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="把奖项步骤主体嵌入当前 default_code.py 并同步到多个目标。"
    )
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--body", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        action="append",
        required=True,
        help="可重复传入；通常同时指定资料源码和步骤部署文件。",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检查目标内容，不写文件。",
    )
    args = parser.parse_args()

    expected = build_script(read_utf8(args.template), read_utf8(args.body))

    if args.check:
        failed = False
        for output in args.output:
            if not output.exists():
                print(f"[FAIL] 不存在：{output}")
                failed = True
                continue
            if read_utf8(output) != expected:
                print(f"[FAIL] 与模板+主体不一致：{output}")
                failed = True
            else:
                print(f"[PASS] {output}")
        return 1 if failed else 0

    for output in args.output:
        atomic_write(output, expected)
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
