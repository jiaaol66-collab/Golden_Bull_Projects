import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
import pandas as pd
from tqdm import tqdm

os.chdir(os.path.dirname(__file__))

def _now():
    return datetime.now().isoformat(timespec='seconds')


def _sanitize_table_name(name):
    name = str(name).strip()
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'[^0-9a-zA-Z_\u4e00-\u9fa5]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    if not name:
        name = 'sheet'
    if re.match(r'^\d', name):
        name = f't_{name}'
    return name.lower()


def _drop_unnamed_columns(df):
    drop_cols = [c for c in df.columns if str(c).strip().lower().startswith('unnamed:')]
    if drop_cols:
        df = df.drop(columns=drop_cols)
    return df


def _normalize_code_series(s):
    s = s.astype('string')
    s = s.str.strip()
    s = s.str.replace('\u3000', ' ', regex=False)
    s = s.str.replace(r'\.0$', '', regex=True)
    return s


def _normalize_name_series(s):
    s = s.astype('string')
    s = s.str.strip()
    s = s.str.replace('\u3000', ' ', regex=False)
    return s


def _basic_clean(df):
    df = _drop_unnamed_columns(df)
    df.columns = [str(c).strip() for c in df.columns]

    for col in df.columns:
        col_name = str(col).strip()
        if '名称' in col_name:
            df[col] = _normalize_name_series(df[col])
        if '编号' in col_name:
            df[col] = _normalize_code_series(df[col])

    return df


def _nav_raw_clean(df):
    df = df.copy()
    df.columns = [str(c) for c in df.columns]
    for col in df.columns:
        if '编号' in str(col):
            df[col] = _normalize_code_series(df[col])
    return df


def _is_nav_sheet(sheet_name):
    sheet_name = str(sheet_name).strip()
    return re.match(r'^净值信息(?:[\(（]\d+[\)）])?$', sheet_name) is not None


def _nav_sheet_order(sheet_name):
    sheet_name = str(sheet_name).strip()
    m = re.search(r'[\(（](\d+)[\)）]$', sheet_name)
    if m:
        return int(m.group(1))
    if sheet_name == '净值信息':
        return 0
    return 999999


def _build_ingest_plan(sheet_names):
    nav_sheets = sorted([s for s in sheet_names if _is_nav_sheet(s)], key=_nav_sheet_order)
    other_sheets = [s for s in sheet_names if s not in nav_sheets]
    plan = [{'kind': 'sheet', 'sheet': s, 'label': s} for s in other_sheets]
    if nav_sheets:
        plan.append({
            'kind': 'merged_nav',
            'sheet_names': nav_sheets,
            'label': f"净值信息合并({len(nav_sheets)}张)"
        })
    return plan


def _find_latest_request(base_dir: Path):
    candidates = []
    candidates.extend(base_dir.glob('**/原始数据集/ingestion_request.json'))
    if not candidates:
        return None
    candidates = list({p.resolve(): p for p in candidates}.values())
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _load_request(base_dir: Path, request_path=None):
    if request_path:
        p = Path(request_path)
        if p.is_dir():
            p1 = p / 'ingestion_request.json'
            p2 = p / '原始数据集' / 'ingestion_request.json'
            for candidate in [p1, p2]:
                if candidate.exists():
                    p = candidate
                    break
        if p.exists():
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f), p

    p = _find_latest_request(base_dir)
    if not p:
        return None, None
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f), p


def _get_db_path(base_dir: Path, yr: int):
    db_dir = base_dir / '数据库' / str(yr)
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / 'DB_PRIVATE.duckdb'


def _write_table(con, df, table_name):
    con.register('df_ingest', df)
    con.execute(f'create or replace table {table_name} as select * from df_ingest')
    con.unregister('df_ingest')


def _log_ingest(con, excel_path, sheet, table_name, rows):
    con.execute(
        'insert into ingest_log values (?, ?, ?, ?, ?)',
        [_now(), str(excel_path), sheet, table_name, int(rows)]
    )


def _format_seconds(seconds):
    seconds = max(0, int(seconds))
    mm, ss = divmod(seconds, 60)
    hh, mm = divmod(mm, 60)
    if hh:
        return f'{hh:02d}:{mm:02d}:{ss:02d}'
    return f'{mm:02d}:{ss:02d}'


def _format_size(num_bytes):
    size = float(num_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024 or unit == 'TB':
            return f'{size:.1f}{unit}'
        size /= 1024


def _ingest_excel_to_duckdb(con, excel_path: Path, schema: str = 'raw'):
    con.execute(f'create schema if not exists {schema}')
    con.execute('create table if not exists ingest_log(ts varchar, source_excel varchar, sheet varchar, table_name varchar, rows bigint)')

    print(f'步骤 1/4: 正在打开 Excel 工作簿并扫描 sheet...')
    open_started = time.perf_counter()
    xls = pd.ExcelFile(excel_path)
    open_elapsed = time.perf_counter() - open_started
    print(f'步骤 1/4 完成: 已识别 {len(xls.sheet_names)} 个 sheet, 耗时 {_format_seconds(open_elapsed)}')

    print('步骤 2/4: 正在生成导入计划...')
    plan = _build_ingest_plan(xls.sheet_names)
    nav_count = sum(1 for task in plan if task['kind'] == 'merged_nav')
    raw_nav_sheets = sum(len(task['sheet_names']) for task in plan if task['kind'] == 'merged_nav')
    print(f'步骤 2/4 完成: 共 {len(plan)} 个导入任务, 其中普通表 {len(plan) - nav_count} 个, 净值分表 {raw_nav_sheets} 张')

    total = len(plan)
    imported_rows = 0
    started = time.perf_counter()

    print('步骤 3/4: 开始逐表读取并写入 DuckDB...')
    with tqdm(total=total, unit='表', dynamic_ncols=True, desc='导入进度') as pbar:
        for idx, task in enumerate(plan, start=1):
            step_started = time.perf_counter()
            pbar.set_description(f"导入中 {idx}/{total}: {task['label']}")

            if task['kind'] == 'sheet':
                sheet = task['sheet']
                print(f"  正在读取 sheet: {sheet}")
                df = pd.read_excel(xls, sheet_name=sheet)
                df = _basic_clean(df)
                table_name = f'{schema}.__{_sanitize_table_name(sheet)}'
                print(f"  正在写入 DuckDB: {table_name}")
                _write_table(con, df, table_name)
                _log_ingest(con, excel_path, sheet, table_name, len(df))
                rows = len(df)
            else:
                dfs = []
                nav_total = len(task['sheet_names'])
                print(f"  正在合并净值分表: {nav_total} 张 -> {schema}.__净值信息")
                for nav_idx, sheet in enumerate(task['sheet_names'], start=1):
                    print(f"    读取净值分表 {nav_idx}/{nav_total}: {sheet}")
                    df = pd.read_excel(xls, sheet_name=sheet)
                    df = _nav_raw_clean(df)
                    dfs.append(df)
                merged = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
                table_name = f'{schema}.__净值信息'
                print(f"  正在写入 DuckDB: {table_name}")
                _write_table(con, merged, table_name)
                _log_ingest(con, excel_path, ' | '.join(task['sheet_names']), table_name, len(merged))
                rows = len(merged)

            imported_rows += rows
            elapsed = time.perf_counter() - started
            avg = elapsed / idx if idx else 0
            remaining = avg * (total - idx)
            step_elapsed = time.perf_counter() - step_started
            pbar.set_postfix(rows=rows, total_rows=imported_rows, step=f'{step_elapsed:.1f}s', eta=_format_seconds(remaining))
            pbar.update(1)
            print(f"[{idx}/{total}] 已导入 {task['label']} -> {table_name} ({rows} 行), 累计 {imported_rows} 行, 预计剩余 {_format_seconds(remaining)}")

    total_elapsed = time.perf_counter() - started
    print('步骤 4/4: 导入完成，输出汇总...')
    print(f'导入汇总: 共 {total} 个导入任务, 总行数 {imported_rows}, 总耗时 {_format_seconds(total_elapsed)}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--yr', type=int, default=None)
    parser.add_argument('--src', type=str, default=None)
    parser.add_argument('--request', type=str, default=None)
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    request, request_file = _load_request(base_dir, args.request)

    yr = args.yr
    src = args.src
    if request:
        if yr is None:
            yr = int(request.get('yr') or 0) or None
        if not src:
            src = request.get('source_excel') or ''

    if yr is None:
        print('未提供 yr。可用参数: --yr 2026')
        if request_file:
            print(f'已检测到 request: {request_file}')
        sys.exit(1)

    if not src:
        print('未提供 source_excel。可用参数: --src \"...私募参评数据....xlsx\"')
        if request_file:
            print(f'已检测到 request: {request_file}')
        sys.exit(1)

    excel_path = Path(src)
    if not excel_path.exists():
        print(f'源文件不存在: {excel_path}')
        sys.exit(1)

    try:
        import duckdb
    except Exception:
        print('未检测到 duckdb 包，请先安装: pip install duckdb')
        sys.exit(1)

    db_path = _get_db_path(base_dir, yr)
    con = duckdb.connect(str(db_path))
    con.execute("pragma disable_progress_bar")

    print(f'写入数据库: {db_path}')
    print(f'源文件: {excel_path}')
    try:
        print(f'源文件大小: {_format_size(excel_path.stat().st_size)}')
    except Exception:
        pass
    _ingest_excel_to_duckdb(con, excel_path, schema='raw')
    con.close()

    print('导入完成')


if __name__ == '__main__':
    main()
