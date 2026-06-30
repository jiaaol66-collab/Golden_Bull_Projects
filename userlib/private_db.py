from pathlib import Path

import os
import shutil
import tempfile
import time
import pandas as pd


def _quote_ident(name):
    return '"' + str(name).replace('"', '""') + '"'


def _quote_table_name(table_name):
    parts = str(table_name).split('.')
    return '.'.join(_quote_ident(part) for part in parts)


def _quote_sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def find_private_db(current_file, yr):
    name = str(os.getenv("PRIVATE_DB_NAME") or "").strip() or "DB_PRIVATE.duckdb"

    direct = str(os.getenv("PRIVATE_DB_PATH") or "").strip()
    if direct:
        direct_path = Path(os.path.expandvars(os.path.expanduser(direct))).resolve()
        if direct_path.exists():
            return direct_path

    root = str(os.getenv("PRIVATE_DB_ROOT") or "").strip()
    if root:
        root_path = Path(os.path.expandvars(os.path.expanduser(root))).resolve()
        candidate = (root_path / "数据库" / str(yr) / name).resolve()
        if candidate.exists():
            return candidate

    current_path = Path(current_file).resolve()
    candidates = []
    seen = set()

    for parent in current_path.parents:
        candidate = (parent / "数据库" / str(yr) / name).resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
        if candidate.exists():
            return candidate

    candidate_text = "\n".join(str(p) for p in candidates[:10])
    raise FileNotFoundError(f"未找到 {name}，可检查以下路径:\n{candidate_text}")


_LOGGED_DB_PATHS = set()


def _truthy_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    v = str(v).strip().lower()
    if v in ('0', 'false', 'no', 'off', ''):
        return False
    return True


def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _float_env(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return float(str(v).strip())
    except Exception:
        return default


def _connect_readonly_with_retry(duckdb, db_path: Path, log: bool):
    retries = max(0, _int_env('PRIVATE_DB_READ_RETRIES', 8))
    base_sleep = max(0.0, _float_env('PRIVATE_DB_READ_RETRY_SLEEP', 1.0))
    for i in range(retries + 1):
        try:
            return duckdb.connect(str(db_path), read_only=True)
        except Exception as e:
            if i >= retries:
                raise
            if log:
                wait_s = round(base_sleep * (i + 1), 3)
                print(f'[DB] 读取连接失败，重试 {i + 1}/{retries}，等待 {wait_s} 秒: {e}')
            time.sleep(base_sleep * (i + 1))


def _connect_write_with_retry(duckdb, db_path: Path, log: bool):
    retries = max(0, _int_env('PRIVATE_DB_WRITE_RETRIES', 8))
    base_sleep = max(0.0, _float_env('PRIVATE_DB_WRITE_RETRY_SLEEP', 1.0))
    for i in range(retries + 1):
        try:
            return duckdb.connect(str(db_path), read_only=False)
        except Exception as e:
            if i >= retries:
                raise
            if log:
                wait_s = round(base_sleep * (i + 1), 3)
                print(f'[DB] 写入连接失败，重试 {i + 1}/{retries}，等待 {wait_s} 秒: {e}')
            time.sleep(base_sleep * (i + 1))


def read_private_table(current_file, yr, table_name, columns=None, where=None, dtype=None, log=None):
    try:
        import duckdb
    except Exception as e:
        raise ImportError('未检测到 duckdb 包，请先安装 duckdb') from e

    db_path = find_private_db(current_file, yr)
    if log is None:
        log = _truthy_env('PRIVATE_DB_LOG', True)

    if log and str(db_path) not in _LOGGED_DB_PATHS:
        print(f'[DB] 使用数据库: {db_path}')
        _LOGGED_DB_PATHS.add(str(db_path))

    con = _connect_readonly_with_retry(duckdb, db_path, log)

    try:
        if columns:
            select_cols = ', '.join(_quote_ident(c) for c in columns)
        else:
            select_cols = '*'

        sql = f'SELECT {select_cols} FROM {_quote_table_name(table_name)}'
        if where:
            sql += f' WHERE {where}'

        if log:
            cols_label = '*' if not columns else f'{len(columns)}列'
            where_label = '' if not where else f' WHERE {where}'
            print(f'[DB] 读取: {table_name} ({cols_label}){where_label}')
        t0 = time.perf_counter()
        df = con.execute(sql).df()
        t1 = time.perf_counter()
        if log:
            print(f'[DB] 完成: {table_name} 行数={len(df)} 用时={round(t1 - t0, 3)}秒')
    finally:
        con.close()

    if dtype:
        if isinstance(dtype, dict):
            for col, t in dtype.items():
                if col in df.columns:
                    df[col] = df[col].astype(t)
        else:
            df = df.astype(dtype)

    return df


def _looks_like_numpy_ndarray(value) -> bool:
    t = type(value)
    return getattr(t, "__module__", "") == "numpy" and getattr(t, "__name__", "") == "ndarray"


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

    object_cols = [c for c in df.columns if str(df[c].dtype) == "object"]
    if not object_cols:
        return df

    df_out = df
    for col in object_cols:
        s = df_out[col]
        sample = s.dropna().head(50).tolist()
        if not sample:
            continue
        need = any(_looks_like_numpy_ndarray(v) or isinstance(v, tuple) for v in sample)
        if not need:
            continue
        if df_out is df:
            df_out = df.copy()
        df_out[col] = df_out[col].map(_normalize_cell_for_duckdb)

    return df_out


def write_private_table(current_file, yr, table_name, df, replace=True, log=None):
    try:
        import duckdb
    except Exception as e:
        raise ImportError('未检测到 duckdb 包，请先安装 duckdb') from e

    db_path = find_private_db(current_file, yr)
    if log is None:
        log = _truthy_env('PRIVATE_DB_LOG', True)

    if log and str(db_path) not in _LOGGED_DB_PATHS:
        print(f'[DB] 使用数据库: {db_path}')
        _LOGGED_DB_PATHS.add(str(db_path))

    parts = str(table_name).split('.')
    if len(parts) == 2:
        schema_name = parts[0]
    else:
        schema_name = 'main'

    quoted_table = _quote_table_name(table_name)
    mode = '覆盖' if replace else '新建'
    rows = len(df) if hasattr(df, '__len__') else ''
    cols = df.shape[1] if hasattr(df, 'shape') else ''
    if log:
        print(f'[DB] 写入: {table_name} ({mode}) 行数={rows} 列数={cols}')

    def _ensure_schema(con):
        if schema_name != 'main':
            con.execute(f'create schema if not exists {_quote_ident(schema_name)}')

    t0 = time.perf_counter()
    con = _connect_write_with_retry(duckdb, db_path, log)
    try:
        _ensure_schema(con)
        df_to_write = _normalize_object_columns_for_duckdb(df)
        con.register('df_private_write', df_to_write)
        try:
            if replace:
                con.execute(f'create or replace table {quoted_table} as select * from df_private_write')
            else:
                con.execute(f'create table {quoted_table} as select * from df_private_write')
        finally:
            try:
                con.unregister('df_private_write')
            except Exception:
                pass
    except Exception as e:
        try:
            con.close()
        except Exception:
            pass
        err_text = str(e).lower()
        if 'out of memory' not in err_text and 'allocation failure' not in err_text:
            raise
        if log:
            print(f'[DB] 直接写入内存不足，改走临时 Parquet 落盘入库: {e}')

        tmp_dir = Path(tempfile.mkdtemp(prefix='private_db_write_', dir=str(db_path.parent)))
        tmp_path = tmp_dir / 'data.parquet'
        try:
            df.to_parquet(tmp_path, index=False)
            con = _connect_write_with_retry(duckdb, db_path, log)
            try:
                _ensure_schema(con)
                parquet_sql = _quote_sql_string(tmp_path.as_posix())
                if replace:
                    con.execute(f'create or replace table {quoted_table} as select * from read_parquet({parquet_sql})')
                else:
                    con.execute(f'create table {quoted_table} as select * from read_parquet({parquet_sql})')
            finally:
                con.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        con.close()

    t1 = time.perf_counter()
    if log:
        print(f'[DB] 完成: {table_name} 用时={round(t1 - t0, 3)}秒')


def safe_write_private_table(current_file, yr, table_name, df, template_columns=None, replace=True, log=None):
    if df is None:
        df = pd.DataFrame()

    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)

    if df.shape[1] == 0:
        if template_columns:
            df = pd.DataFrame({col: pd.Series(dtype='object') for col in template_columns})
        else:
            return

    write_private_table(current_file, yr, table_name, df, replace=replace, log=log)


def table_exists(current_file, yr, table_name):
    try:
        import duckdb
    except Exception as e:
        raise ImportError('未检测到 duckdb 包，请先安装 duckdb') from e

    db_path = find_private_db(current_file, yr)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        parts = str(table_name).split('.')
        if len(parts) == 2:
            schema_name, obj_name = parts
        else:
            schema_name, obj_name = 'main', parts[0]

        sql = """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = ? AND table_name = ?
        """
        count = con.execute(sql, [schema_name, obj_name]).fetchone()[0]
        return count > 0
    finally:
        con.close()
