# -*- coding: utf-8 -*-
"""
Parquet IO 工具函数 - 用于高速读写中间数据
将中间文件从 CSV/Excel 改为 Parquet，可大幅提升读写速度
"""

import os
import numbers
import pandas as pd


def _prepare_for_parquet(df):
    """
    统一清洗混合 object 列，避免 pyarrow 因 str/float 混合类型报错
    """
    df = df.copy()

    for col in df.columns:
        series = df[col]
        if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
            continue

        non_null = series.dropna()
        if non_null.empty:
            continue

        type_set = {type(x) for x in non_null}
        if len(type_set) <= 1:
            continue

        has_numeric = any(isinstance(x, numbers.Number) for x in non_null)
        if has_numeric:
            numeric_series = pd.to_numeric(series, errors='coerce')
            numeric_count = numeric_series.notna().sum()
            original_count = non_null.shape[0]
            # 大部分非空值可转为数值时，保留为数值列；否则退化为字符串列
            if original_count > 0 and numeric_count / original_count >= 0.5:
                df[col] = numeric_series
                continue

        df[col] = series.astype('string')

    return df


def to_parquet(df, path, verbose=True, **kwargs):
    """
    将 DataFrame 保存为 Parquet 格式，自动创建目录
    :param df: DataFrame
    :param path: 输出路径
    :param kwargs: 传递给 pd.to_parquet 的其他参数
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df = _prepare_for_parquet(df)
    df.to_parquet(path, index=False, **kwargs)
    if verbose:
        print(f'  已保存 Parquet: {os.path.basename(path)} ({len(df)} 行)')


def read_parquet(path, verbose=True, **kwargs):
    """
    读取 Parquet 文件
    :param path: 输入路径
    :param kwargs: 传递给 pd.read_parquet 的其他参数
    :return: DataFrame
    """
    # 提取 dtype（parquet 不支持），读完后手动转换
    dtype = kwargs.pop('dtype', None)
    usecols = kwargs.pop('usecols', None)
    if usecols and 'columns' not in kwargs:
        kwargs['columns'] = usecols
    for drop_key in ['parse_dates', 'encoding']:
        kwargs.pop(drop_key, None)

    df = pd.read_parquet(path, **kwargs)

    if dtype:
        for col, t in dtype.items():
            if col in df.columns:
                df[col] = df[col].astype(t)

    if verbose:
        print(f'  已读取 Parquet: {os.path.basename(path)} ({len(df)} 行)')
    return df


def auto_save_df(df, path_csv, path_parquet, use_parquet=True):
    """
    智能保存：优先保存 Parquet，可选同时保存 CSV
    :param df: DataFrame
    :param path_csv: CSV 路径 (兼容旧代码)
    :param path_parquet: Parquet 路径
    :param use_parquet: 是否使用 Parquet
    """
    if use_parquet:
        to_parquet(df, path_parquet)
    else:
        df.to_csv(path_csv, index=False)
        print(f'  已保存 CSV: {os.path.basename(path_csv)}')


def auto_read_df(path_csv, path_parquet, use_parquet=True, **kwargs):
    """
    智能读取：优先读取 Parquet，回退到 CSV
    :param path_csv: CSV 路径
    :param path_parquet: Parquet 路径
    :param use_parquet: 是否使用 Parquet
    :param kwargs: 传递给 read_parquet/read_csv 的其他参数
    :return: DataFrame
    """
    if use_parquet and os.path.exists(path_parquet):
        return read_parquet(path_parquet, **kwargs)
    elif os.path.exists(path_csv):
        print(f'  回退读取 CSV: {os.path.basename(path_csv)}')
        return pd.read_csv(path_csv, **kwargs)
    else:
        raise FileNotFoundError(f'文件不存在: {path_parquet} 或 {path_csv}')


def csv_path_to_parquet(path_csv):
    """
    将 CSV 路径转换为 Parquet 路径
    :param path_csv: CSV 路径
    :return: Parquet 路径
    """
    if path_csv.endswith('.csv'):
        return path_csv[:-4] + '.parquet'
    return path_csv + '.parquet'


def excel_path_to_parquet(path_excel, sheet_name=None):
    """
    将 Excel 路径转换为 Parquet 路径
    :param path_excel: Excel 路径
    :param sheet_name: Sheet 名（可选，用于区分不同 Sheet）
    :return: Parquet 路径
    """
    if sheet_name:
        base = path_excel.replace('.xlsx', '').replace('.xls', '')
        return f'{base}_{sheet_name}.parquet'
    return path_excel.replace('.xlsx', '.parquet').replace('.xls', '.parquet')
