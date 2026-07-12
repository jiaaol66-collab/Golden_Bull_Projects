from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

import pandas as pd


_LOGGED_DB_PATHS = set()


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _env_key(prefix: str | None, suffix: str) -> str:
    prefix = _clean_text(prefix).upper()
    suffix = _clean_text(suffix).upper()
    return f"{prefix}_{suffix}" if prefix else suffix


def _get_env(prefix: str | None, suffix: str, fallback_key: str | None = None):
    keys = [_env_key(prefix, suffix)]
    if fallback_key:
        keys.append(str(fallback_key).upper())
    for key in keys:
        value = os.getenv(key)
        if value is not None:
            return value
    return None


def _truthy_env(prefix: str | None, suffix: str, default: bool, fallback_key: str | None = None) -> bool:
    value = _get_env(prefix, suffix, fallback_key=fallback_key)
    if value is None:
        return default
    value = str(value).strip().lower()
    if value in ("0", "false", "no", "off", ""):
        return False
    return True


def _int_env(prefix: str | None, suffix: str, default: int, fallback_key: str | None = None) -> int:
    value = _get_env(prefix, suffix, fallback_key=fallback_key)
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _float_env(prefix: str | None, suffix: str, default: float, fallback_key: str | None = None) -> float:
    value = _get_env(prefix, suffix, fallback_key=fallback_key)
    if value is None:
        return default
    try:
        return float(str(value).strip())
    except Exception:
        return default


def _quote_ident(name):
    return '"' + str(name).replace('"', '""') + '"'


def _quote_table_name(table_name):
    parts = str(table_name).split(".")
    return ".".join(_quote_ident(part) for part in parts)


def _quote_sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def build_db_path(db_root, yr, db_name="DB.duckdb", search_dir_name="数据库", create_parent=False):
    root_path = Path(db_root).resolve()
    db_path = (root_path / str(search_dir_name) / str(yr) / str(db_name)).resolve()
    if create_parent:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def _candidate_db_paths(current_file, yr, db_name, search_dir_name="数据库"):
    current_path = Path(current_file).resolve()
    candidates = []
    seen = set()
    for parent in current_path.parents:
        candidate = (parent / str(search_dir_name) / str(yr) / str(db_name)).resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
    return candidates


def resolve_existing_db_path(
    current_file,
    yr,
    db_name="DB.duckdb",
    env_prefix=None,
    direct_path=None,
    db_root=None,
    search_dir_name="数据库",
):
    name = _clean_text(_get_env(env_prefix, "DB_NAME")) or str(db_name)

    direct = _clean_text(direct_path) or _clean_text(_get_env(env_prefix, "DB_PATH"))
    if direct:
        direct_resolved = Path(os.path.expandvars(os.path.expanduser(direct))).resolve()
        if direct_resolved.exists():
            return direct_resolved

    root = _clean_text(db_root) or _clean_text(_get_env(env_prefix, "DB_ROOT"))
    if root:
        candidate = build_db_path(root, yr, db_name=name, search_dir_name=search_dir_name, create_parent=False)
        if candidate.exists():
            return candidate

    candidates = _candidate_db_paths(current_file, yr, name, search_dir_name=search_dir_name)
    for candidate in candidates:
        if candidate.exists():
            return candidate

    candidate_text = "\n".join(str(p) for p in candidates[:10])
    raise FileNotFoundError(f"未找到 {name}，可检查以下路径:\n{candidate_text}")


def resolve_writable_db_path(
    current_file,
    yr,
    db_name="DB.duckdb",
    env_prefix=None,
    direct_path=None,
    db_root=None,
    search_dir_name="数据库",
):
    name = _clean_text(_get_env(env_prefix, "DB_NAME")) or str(db_name)

    direct = _clean_text(direct_path) or _clean_text(_get_env(env_prefix, "DB_PATH"))
    if direct:
        direct_resolved = Path(os.path.expandvars(os.path.expanduser(direct))).resolve()
        direct_resolved.parent.mkdir(parents=True, exist_ok=True)
        return direct_resolved

    root = _clean_text(db_root) or _clean_text(_get_env(env_prefix, "DB_ROOT"))
    if root:
        return build_db_path(root, yr, db_name=name, search_dir_name=search_dir_name, create_parent=True)

    try:
        return resolve_existing_db_path(
            current_file=current_file,
            yr=yr,
            db_name=name,
            env_prefix=env_prefix,
            direct_path=direct_path,
            db_root=db_root,
            search_dir_name=search_dir_name,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"未找到可写数据库路径: {name}。请显式提供 `db_root` / `direct_path`，"
            f"或设置环境变量 `{_env_key(env_prefix, 'DB_ROOT')}` / `{_env_key(env_prefix, 'DB_PATH')}`。"
        ) from exc


def _log_db_path(db_path: Path, log: bool, log_prefix: str, env_prefix=None):
    show_path = log or _truthy_env(env_prefix, "DB_PRINT_PATH", True, fallback_key="DUCKDB_PRINT_PATH")
    if show_path and str(db_path) not in _LOGGED_DB_PATHS:
        print(f"{log_prefix} 使用数据库: {db_path}")
        _LOGGED_DB_PATHS.add(str(db_path))


def _connect_with_retry(duckdb, db_path: Path, read_only: bool, log: bool, env_prefix=None, log_prefix="[DB]"):
    if read_only:
        retries = max(0, _int_env(env_prefix, "DB_READ_RETRIES", 8, fallback_key="DUCKDB_READ_RETRIES"))
        base_sleep = max(0.0, _float_env(env_prefix, "DB_READ_RETRY_SLEEP", 1.0, fallback_key="DUCKDB_READ_RETRY_SLEEP"))
    else:
        retries = max(0, _int_env(env_prefix, "DB_WRITE_RETRIES", 8, fallback_key="DUCKDB_WRITE_RETRIES"))
        base_sleep = max(0.0, _float_env(env_prefix, "DB_WRITE_RETRY_SLEEP", 1.0, fallback_key="DUCKDB_WRITE_RETRY_SLEEP"))

    mode_label = "读取" if read_only else "写入"
    for i in range(retries + 1):
        try:
            return duckdb.connect(str(db_path), read_only=read_only)
        except Exception as e:
            if i >= retries:
                raise
            if log:
                wait_s = round(base_sleep * (i + 1), 3)
                print(f"{log_prefix} {mode_label}连接失败，重试 {i + 1}/{retries}，等待 {wait_s} 秒: {e}")
            time.sleep(base_sleep * (i + 1))


def _looks_like_numpy_ndarray(value) -> bool:
    value_type = type(value)
    return getattr(value_type, "__module__", "") == "numpy" and getattr(value_type, "__name__", "") == "ndarray"


def _normalize_cell_for_duckdb(value):
    if _looks_like_numpy_ndarray(value):
        try:
            return value.tolist()
        except Exception:
            try:
                return list(value)
            except Exception:
                return value
    if isinstance(value, tuple):
        return list(value)
    return value


def _normalize_object_columns_for_duckdb(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.shape[1] == 0:
        return df

    object_cols = [col for col in df.columns if str(df[col].dtype) == "object"]
    if not object_cols:
        return df

    df_out = df
    for col in object_cols:
        sample = df_out[col].dropna().head(50).tolist()
        if not sample:
            continue
        need = any(_looks_like_numpy_ndarray(v) or isinstance(v, tuple) for v in sample)
        if not need:
            continue
        if df_out is df:
            df_out = df.copy()
        df_out[col] = df_out[col].map(_normalize_cell_for_duckdb)
    return df_out


def query_duckdb(
    current_file,
    yr,
    sql,
    params=None,
    dtype=None,
    db_name="DB.duckdb",
    env_prefix=None,
    direct_path=None,
    db_root=None,
    search_dir_name="数据库",
    log=None,
    log_prefix="[DB]",
):
    try:
        import duckdb
    except Exception as e:
        raise ImportError("未检测到 duckdb 包，请先安装 duckdb") from e

    db_path = resolve_existing_db_path(
        current_file=current_file,
        yr=yr,
        db_name=db_name,
        env_prefix=env_prefix,
        direct_path=direct_path,
        db_root=db_root,
        search_dir_name=search_dir_name,
    )
    if log is None:
        log = _truthy_env(env_prefix, "DB_LOG", True, fallback_key="DUCKDB_LOG")

    _log_db_path(db_path, log, log_prefix, env_prefix=env_prefix)
    con = _connect_with_retry(duckdb, db_path, read_only=True, log=log, env_prefix=env_prefix, log_prefix=log_prefix)
    try:
        if log:
            print(f"{log_prefix} 查询SQL: {sql}")
        started = time.perf_counter()
        if params is None:
            df = con.execute(sql).df()
        else:
            df = con.execute(sql, params).df()
        ended = time.perf_counter()
        if log:
            print(f"{log_prefix} 查询完成: 行数={len(df)} 用时={round(ended - started, 3)}秒")
    finally:
        con.close()

    if dtype:
        if isinstance(dtype, dict):
            for col, target in dtype.items():
                if col in df.columns:
                    df[col] = df[col].astype(target)
        else:
            df = df.astype(dtype)
    return df


def execute_duckdb(
    current_file,
    yr,
    sql,
    params=None,
    db_name="DB.duckdb",
    env_prefix=None,
    direct_path=None,
    db_root=None,
    search_dir_name="数据库",
    log=None,
    log_prefix="[DB]",
):
    try:
        import duckdb
    except Exception as e:
        raise ImportError("未检测到 duckdb 包，请先安装 duckdb") from e

    db_path = resolve_writable_db_path(
        current_file=current_file,
        yr=yr,
        db_name=db_name,
        env_prefix=env_prefix,
        direct_path=direct_path,
        db_root=db_root,
        search_dir_name=search_dir_name,
    )
    if log is None:
        log = _truthy_env(env_prefix, "DB_LOG", True, fallback_key="DUCKDB_LOG")

    _log_db_path(db_path, log, log_prefix, env_prefix=env_prefix)
    con = _connect_with_retry(duckdb, db_path, read_only=False, log=log, env_prefix=env_prefix, log_prefix=log_prefix)
    try:
        if log:
            print(f"{log_prefix} 执行SQL: {sql}")
        if params is None:
            result = con.execute(sql)
        else:
            result = con.execute(sql, params)
    finally:
        con.close()
    return result


def read_duckdb_table(
    current_file,
    yr,
    table_name,
    columns=None,
    where=None,
    dtype=None,
    db_name="DB.duckdb",
    env_prefix=None,
    direct_path=None,
    db_root=None,
    search_dir_name="数据库",
    log=None,
    log_prefix="[DB]",
):
    if columns:
        select_cols = ", ".join(_quote_ident(col) for col in columns)
    else:
        select_cols = "*"

    sql = f"SELECT {select_cols} FROM {_quote_table_name(table_name)}"
    if where:
        sql += f" WHERE {where}"
    return query_duckdb(
        current_file=current_file,
        yr=yr,
        sql=sql,
        params=None,
        dtype=dtype,
        db_name=db_name,
        env_prefix=env_prefix,
        direct_path=direct_path,
        db_root=db_root,
        search_dir_name=search_dir_name,
        log=log,
        log_prefix=log_prefix,
    )


def write_duckdb_table(
    current_file,
    yr,
    table_name,
    df,
    replace=True,
    db_name="DB.duckdb",
    env_prefix=None,
    direct_path=None,
    db_root=None,
    search_dir_name="数据库",
    log=None,
    log_prefix="[DB]",
):
    try:
        import duckdb
    except Exception as e:
        raise ImportError("未检测到 duckdb 包，请先安装 duckdb") from e

    db_path = resolve_writable_db_path(
        current_file=current_file,
        yr=yr,
        db_name=db_name,
        env_prefix=env_prefix,
        direct_path=direct_path,
        db_root=db_root,
        search_dir_name=search_dir_name,
    )
    if log is None:
        log = _truthy_env(env_prefix, "DB_LOG", True, fallback_key="DUCKDB_LOG")

    _log_db_path(db_path, log, log_prefix, env_prefix=env_prefix)
    parts = str(table_name).split(".")
    schema_name = parts[0] if len(parts) == 2 else "main"
    quoted_table = _quote_table_name(table_name)
    mode = "覆盖" if replace else "新建"
    rows = len(df) if hasattr(df, "__len__") else ""
    cols = df.shape[1] if hasattr(df, "shape") else ""
    if log:
        print(f"{log_prefix} 写入: {table_name} ({mode}) 行数={rows} 列数={cols}")

    def _ensure_schema(con):
        if schema_name != "main":
            con.execute(f"create schema if not exists {_quote_ident(schema_name)}")

    started = time.perf_counter()
    con = _connect_with_retry(duckdb, db_path, read_only=False, log=log, env_prefix=env_prefix, log_prefix=log_prefix)
    try:
        _ensure_schema(con)
        df_to_write = _normalize_object_columns_for_duckdb(df)
        con.register("df_duckdb_write", df_to_write)
        try:
            if replace:
                con.execute(f"create or replace table {quoted_table} as select * from df_duckdb_write")
            else:
                con.execute(f"create table {quoted_table} as select * from df_duckdb_write")
        finally:
            try:
                con.unregister("df_duckdb_write")
            except Exception:
                pass
    except Exception as e:
        try:
            con.close()
        except Exception:
            pass
        err_text = str(e).lower()
        if "out of memory" not in err_text and "allocation failure" not in err_text:
            raise
        if log:
            print(f"{log_prefix} 直接写入内存不足，改走临时 Parquet 落盘入库: {e}")

        tmp_dir = Path(tempfile.mkdtemp(prefix="duckdb_helper_write_", dir=str(db_path.parent)))
        tmp_path = tmp_dir / "data.parquet"
        try:
            df.to_parquet(tmp_path, index=False)
            con = _connect_with_retry(duckdb, db_path, read_only=False, log=log, env_prefix=env_prefix, log_prefix=log_prefix)
            try:
                _ensure_schema(con)
                parquet_sql = _quote_sql_string(tmp_path.as_posix())
                if replace:
                    con.execute(f"create or replace table {quoted_table} as select * from read_parquet({parquet_sql})")
                else:
                    con.execute(f"create table {quoted_table} as select * from read_parquet({parquet_sql})")
            finally:
                con.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        con.close()

    ended = time.perf_counter()
    if log:
        print(f"{log_prefix} 完成: {table_name} 用时={round(ended - started, 3)}秒")


def safe_write_duckdb_table(
    current_file,
    yr,
    table_name,
    df,
    template_columns=None,
    replace=True,
    db_name="DB.duckdb",
    env_prefix=None,
    direct_path=None,
    db_root=None,
    search_dir_name="数据库",
    log=None,
    log_prefix="[DB]",
):
    if df is None:
        df = pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)

    if df.shape[1] == 0:
        if template_columns:
            df = pd.DataFrame({col: pd.Series(dtype="object") for col in template_columns})
        else:
            return

    write_duckdb_table(
        current_file=current_file,
        yr=yr,
        table_name=table_name,
        df=df,
        replace=replace,
        db_name=db_name,
        env_prefix=env_prefix,
        direct_path=direct_path,
        db_root=db_root,
        search_dir_name=search_dir_name,
        log=log,
        log_prefix=log_prefix,
    )


def duckdb_table_exists(
    current_file,
    yr,
    table_name,
    db_name="DB.duckdb",
    env_prefix=None,
    direct_path=None,
    db_root=None,
    search_dir_name="数据库",
):
    sql = """
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = ? AND table_name = ?
    """
    parts = str(table_name).split(".")
    schema_name, obj_name = (parts[0], parts[1]) if len(parts) == 2 else ("main", parts[0])
    df = query_duckdb(
        current_file=current_file,
        yr=yr,
        sql=sql,
        params=[schema_name, obj_name],
        db_name=db_name,
        env_prefix=env_prefix,
        direct_path=direct_path,
        db_root=db_root,
        search_dir_name=search_dir_name,
        log=False,
    )
    if df.empty:
        return False
    return int(df.iloc[0, 0]) > 0


