from __future__ import annotations

from pathlib import Path

from userlib.db.duckdb_helper import duckdb_table_exists
from userlib.db.duckdb_helper import execute_duckdb
from userlib.db.duckdb_helper import query_duckdb
from userlib.db.duckdb_helper import read_duckdb_table
from userlib.db.duckdb_helper import resolve_existing_db_path
from userlib.db.duckdb_helper import resolve_writable_db_path
from userlib.db.duckdb_helper import safe_write_duckdb_table as _safe_write_duckdb_table
from userlib.db.duckdb_helper import write_duckdb_table


PUBLIC_DB_NAME = "DB_PUBLIC.duckdb"
PUBLIC_DB_ENV_PREFIX = "PUBLIC"


def _default_public_db_root(current_file):
    current_path = Path(current_file).resolve()
    for parent in current_path.parents:
        if parent.name.startswith("GB_"):
            return parent
    parents = current_path.parents
    if len(parents) >= 3:
        return parents[2]
    return current_path.parent


def find_public_db(current_file, yr):
    return resolve_existing_db_path(
        current_file=current_file,
        yr=yr,
        db_name=PUBLIC_DB_NAME,
        env_prefix=PUBLIC_DB_ENV_PREFIX,
    )


def ensure_public_db_path(current_file, yr):
    return resolve_writable_db_path(
        current_file=current_file,
        yr=yr,
        db_name=PUBLIC_DB_NAME,
        env_prefix=PUBLIC_DB_ENV_PREFIX,
        db_root=_default_public_db_root(current_file),
    )


def read_public_table(current_file, yr, table_name, columns=None, where=None, dtype=None, log=None):
    return read_duckdb_table(
        current_file=current_file,
        yr=yr,
        table_name=table_name,
        columns=columns,
        where=where,
        dtype=dtype,
        db_name=PUBLIC_DB_NAME,
        env_prefix=PUBLIC_DB_ENV_PREFIX,
        log=log,
    )


def query_public_db(current_file, yr, sql, params=None, dtype=None, log=None):
    return query_duckdb(
        current_file=current_file,
        yr=yr,
        sql=sql,
        params=params,
        dtype=dtype,
        db_name=PUBLIC_DB_NAME,
        env_prefix=PUBLIC_DB_ENV_PREFIX,
        log=log,
    )


def execute_public_db(current_file, yr, sql, params=None, log=None):
    return execute_duckdb(
        current_file=current_file,
        yr=yr,
        sql=sql,
        params=params,
        db_name=PUBLIC_DB_NAME,
        env_prefix=PUBLIC_DB_ENV_PREFIX,
        db_root=_default_public_db_root(current_file),
        log=log,
    )


def write_public_table(current_file, yr, table_name, df, replace=True, log=None):
    return write_duckdb_table(
        current_file=current_file,
        yr=yr,
        table_name=table_name,
        df=df,
        replace=replace,
        db_name=PUBLIC_DB_NAME,
        env_prefix=PUBLIC_DB_ENV_PREFIX,
        db_root=_default_public_db_root(current_file),
        log=log,
    )


def safe_write_public_table(current_file, yr, table_name, df, template_columns=None, replace=True, log=None):
    return _safe_write_duckdb_table(
        current_file=current_file,
        yr=yr,
        table_name=table_name,
        df=df,
        template_columns=template_columns,
        replace=replace,
        db_name=PUBLIC_DB_NAME,
        env_prefix=PUBLIC_DB_ENV_PREFIX,
        db_root=_default_public_db_root(current_file),
        log=log,
    )


def public_table_exists(current_file, yr, table_name):
    return duckdb_table_exists(
        current_file=current_file,
        yr=yr,
        table_name=table_name,
        db_name=PUBLIC_DB_NAME,
        env_prefix=PUBLIC_DB_ENV_PREFIX,
    )


def safe_read_duckdb_table(current_file, yr, table_name, columns=None, where=None, dtype=None, log=None):
    """兼容公募项目旧模板；实际读取 DB_PUBLIC.duckdb。"""
    return read_public_table(
        current_file=current_file,
        yr=yr,
        table_name=table_name,
        columns=columns,
        where=where,
        dtype=dtype,
        log=log,
    )


def safe_write_duckdb_table(
    current_file,
    yr,
    table_name,
    df,
    template_columns=None,
    replace=True,
    log=None,
):
    """兼容公募项目旧模板；实际写入 DB_PUBLIC.duckdb。"""
    return safe_write_public_table(
        current_file=current_file,
        yr=yr,
        table_name=table_name,
        df=df,
        template_columns=template_columns,
        replace=replace,
        log=log,
    )
