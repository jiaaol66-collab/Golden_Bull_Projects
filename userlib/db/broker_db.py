from __future__ import annotations

from pathlib import Path
import re

import pandas as pd

from userlib.db.duckdb_helper import duckdb_table_exists
from userlib.db.duckdb_helper import execute_duckdb
from userlib.db.duckdb_helper import query_duckdb
from userlib.db.duckdb_helper import read_duckdb_table
from userlib.db.duckdb_helper import resolve_existing_db_path
from userlib.db.duckdb_helper import resolve_writable_db_path
from userlib.db.duckdb_helper import safe_write_duckdb_table
from userlib.db.duckdb_helper import write_duckdb_table


BROKER_DB_NAME = "DB_BROKER.duckdb"
BROKER_DB_ENV_PREFIX = "BROKER"

_EXCEL_META_COLUMNS = [
    "__工作表",
    "__工作表序号",
    "__行序号",
    "__空工作表",
    "__源文件路径",
    "__源文件修改时间_ns",
    "__源文件大小",
]


def broker_step_table_name(step, name):
    """构造带来源 step 的表名，例如 step3.__规模信息。"""
    match = re.search(r"\d+", str(step))
    if match is None:
        raise ValueError(f"无法识别 step: {step}")
    schema = f"step{int(match.group())}"
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", str(name)).strip() or "未命名表"
    return f"{schema}.__{safe_name}"


def _default_broker_db_root(current_file):
    current_path = Path(current_file).resolve()
    for parent in current_path.parents:
        if parent.name.startswith("GB_"):
            return parent
    parents = current_path.parents
    if len(parents) >= 3:
        return parents[2]
    return current_path.parent


def find_broker_db(current_file, yr):
    return resolve_existing_db_path(
        current_file=current_file,
        yr=yr,
        db_name=BROKER_DB_NAME,
        env_prefix=BROKER_DB_ENV_PREFIX,
    )


def ensure_broker_db_path(current_file, yr):
    return resolve_writable_db_path(
        current_file=current_file,
        yr=yr,
        db_name=BROKER_DB_NAME,
        env_prefix=BROKER_DB_ENV_PREFIX,
        db_root=_default_broker_db_root(current_file),
    )


def read_broker_table(current_file, yr, table_name, columns=None, where=None, dtype=None, log=None):
    return read_duckdb_table(
        current_file=current_file,
        yr=yr,
        table_name=table_name,
        columns=columns,
        where=where,
        dtype=dtype,
        db_name=BROKER_DB_NAME,
        env_prefix=BROKER_DB_ENV_PREFIX,
        log=log,
    )


def query_broker_db(current_file, yr, sql, params=None, dtype=None, log=None):
    return query_duckdb(
        current_file=current_file,
        yr=yr,
        sql=sql,
        params=params,
        dtype=dtype,
        db_name=BROKER_DB_NAME,
        env_prefix=BROKER_DB_ENV_PREFIX,
        log=log,
    )


def execute_broker_db(current_file, yr, sql, params=None, log=None):
    return execute_duckdb(
        current_file=current_file,
        yr=yr,
        sql=sql,
        params=params,
        db_name=BROKER_DB_NAME,
        env_prefix=BROKER_DB_ENV_PREFIX,
        db_root=_default_broker_db_root(current_file),
        log=log,
    )


def write_broker_table(current_file, yr, table_name, df, replace=True, log=None):
    return write_duckdb_table(
        current_file=current_file,
        yr=yr,
        table_name=table_name,
        df=df,
        replace=replace,
        db_name=BROKER_DB_NAME,
        env_prefix=BROKER_DB_ENV_PREFIX,
        db_root=_default_broker_db_root(current_file),
        log=log,
    )


def safe_write_broker_table(current_file, yr, table_name, df, template_columns=None, replace=True, log=None):
    return safe_write_duckdb_table(
        current_file=current_file,
        yr=yr,
        table_name=table_name,
        df=df,
        template_columns=template_columns,
        replace=replace,
        db_name=BROKER_DB_NAME,
        env_prefix=BROKER_DB_ENV_PREFIX,
        db_root=_default_broker_db_root(current_file),
        log=log,
    )


def broker_table_exists(current_file, yr, table_name):
    try:
        return duckdb_table_exists(
            current_file=current_file,
            yr=yr,
            table_name=table_name,
            db_name=BROKER_DB_NAME,
            env_prefix=BROKER_DB_ENV_PREFIX,
        )
    except FileNotFoundError:
        return False


def read_broker_step_table(current_file, yr, step, name, columns=None, where=None, dtype=None, log=None):
    return read_broker_table(
        current_file=current_file,
        yr=yr,
        table_name=broker_step_table_name(step, name),
        columns=columns,
        where=where,
        dtype=dtype,
        log=log,
    )


def safe_write_broker_step_table(
        current_file, yr, step, name, df,
        template_columns=None, replace=True, log=None,
):
    return safe_write_broker_table(
        current_file=current_file,
        yr=yr,
        table_name=broker_step_table_name(step, name),
        df=df,
        template_columns=template_columns,
        replace=replace,
        log=log,
    )


def broker_step_table_exists(current_file, yr, step, name):
    return broker_table_exists(
        current_file=current_file,
        yr=yr,
        table_name=broker_step_table_name(step, name),
    )


def read_excel_via_broker_db(
        current_file,
        yr,
        step,
        name,
        excel_path,
        sheet_name=0,
        force_refresh=False,
        log=None,
        **read_excel_kwargs,
):
    """将外部/人工 Excel 按修改状态入库，再从 DuckDB 返回。

    Excel 文件继续保留；同一路径、修改时间和文件大小未变化时不重复解析。
    若当前工作区没有该 Excel、但数据库已有缓存，则直接返回数据库内容，
    供“从中间 step 开始运行”使用。
    ``sheet_name=None`` 返回 ``{工作表名: DataFrame}``，其余行为与
    ``pandas.read_excel`` 的常用 sheet_name 用法一致。
    """
    source_path = Path(excel_path).resolve()
    table_name = broker_step_table_name(step, name)
    source_exists = source_path.is_file()
    try:
        table_exists = broker_table_exists(current_file, yr, table_name)
    except FileNotFoundError:
        table_exists = False
    if not source_exists and not table_exists:
        raise FileNotFoundError(f"未找到待入库 Excel: {source_path}")

    stat = source_path.stat() if source_exists else None
    source_key = str(source_path)
    needs_refresh = source_exists and (force_refresh or not table_exists)

    if source_exists and not needs_refresh:
        try:
            meta = read_broker_table(
                current_file,
                yr,
                table_name,
                columns=["__源文件路径", "__源文件修改时间_ns", "__源文件大小"],
                log=False,
            ).head(1)
            needs_refresh = (
                meta.empty
                or str(meta.iloc[0]["__源文件路径"]) != source_key
                or int(meta.iloc[0]["__源文件修改时间_ns"]) != int(stat.st_mtime_ns)
                or int(meta.iloc[0]["__源文件大小"]) != int(stat.st_size)
            )
        except Exception:
            needs_refresh = True

    if needs_refresh:
        ingest_kwargs = dict(read_excel_kwargs)
        ingest_kwargs.pop("sheet_name", None)
        workbook = pd.read_excel(source_path, sheet_name=None, **ingest_kwargs)
        frames = []
        for sheet_index, (current_sheet, frame) in enumerate(workbook.items()):
            reserved = [column for column in _EXCEL_META_COLUMNS if column in frame.columns]
            if reserved:
                raise ValueError(f"Excel 含数据库保留字段 {reserved}: {source_path}")
            current = frame.copy()
            if current.empty:
                current = pd.DataFrame([{}], columns=current.columns)
                empty_sheet = True
            else:
                empty_sheet = False
            current.insert(0, "__行序号", range(len(current)))
            current.insert(0, "__工作表序号", sheet_index)
            current.insert(0, "__工作表", str(current_sheet))
            current["__空工作表"] = empty_sheet
            current["__源文件路径"] = source_key
            current["__源文件修改时间_ns"] = int(stat.st_mtime_ns)
            current["__源文件大小"] = int(stat.st_size)
            frames.append(current)
        combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(
            columns=_EXCEL_META_COLUMNS
        )
        safe_write_broker_table(
            current_file,
            yr,
            table_name,
            combined,
            replace=True,
            log=log,
        )

    stored = read_broker_table(current_file, yr, table_name, log=log)

    def _clean(frame):
        frame = frame.sort_values("__行序号", kind="stable")
        if "__空工作表" in frame.columns:
            frame = frame.loc[~frame["__空工作表"].fillna(False).astype(bool)]
        return frame.drop(columns=_EXCEL_META_COLUMNS, errors="ignore").reset_index(drop=True)

    sheet_meta = (
        stored[["__工作表", "__工作表序号"]]
        .drop_duplicates()
        .sort_values("__工作表序号", kind="stable")
    )
    sheet_names = sheet_meta["__工作表"].astype(str).tolist()
    if sheet_name is None:
        return {
            current_sheet: _clean(stored.loc[stored["__工作表"].eq(current_sheet)].copy())
            for current_sheet in sheet_names
        }
    if isinstance(sheet_name, int):
        try:
            selected_sheet = sheet_names[sheet_name]
        except IndexError as exc:
            raise ValueError(f"工作表序号越界: {sheet_name}, 文件={source_path}") from exc
    else:
        selected_sheet = str(sheet_name)
        if selected_sheet not in sheet_names:
            raise ValueError(f"未找到工作表 {selected_sheet}: {source_path}")
    return _clean(stored.loc[stored["__工作表"].eq(selected_sheet)].copy())
