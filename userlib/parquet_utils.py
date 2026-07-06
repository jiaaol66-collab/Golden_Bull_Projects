# -*- coding: utf-8 -*-
"""
Parquet IO ???? - ??????????
?????? CSV/Excel ?? Parquet??????????
"""

import os
import numbers
import pandas as pd


def _prepare_for_parquet(df):
    """
    ?????? object ???? pyarrow ? str/float ??????
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
            # ?????????????????????????????
            if original_count > 0 and numeric_count / original_count >= 0.5:
                df[col] = numeric_series
                continue

        df[col] = series.astype('string')

    return df


def to_parquet(df, path, verbose=True, **kwargs):
    """
    ? DataFrame ??? Parquet ?????????
    :param df: DataFrame
    :param path: ????
    :param kwargs: ??? pd.to_parquet ?????
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df = _prepare_for_parquet(df)
    df.to_parquet(path, index=False, **kwargs)
    if verbose:
        print(f'  ??? Parquet: {os.path.basename(path)} ({len(df)} ?)')


def read_parquet(path, verbose=True, **kwargs):
    """
    ?? Parquet ??
    :param path: ????
    :param kwargs: ??? pd.read_parquet ?????
    :return: DataFrame
    """
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
        print(f'  ??? Parquet: {os.path.basename(path)} ({len(df)} ?)')
    return df


def auto_save_df(df, path_csv, path_parquet, use_parquet=True):
    """
    ????????? Parquet??????? CSV
    :param df: DataFrame
    :param path_csv: CSV ?? (?????)
    :param path_parquet: Parquet ??
    :param use_parquet: ???? Parquet
    """
    if use_parquet:
        to_parquet(df, path_parquet)
    else:
        df.to_csv(path_csv, index=False)
        print(f'  ??? CSV: {os.path.basename(path_csv)}')


def auto_read_df(path_csv, path_parquet, use_parquet=True, **kwargs):
    """
    ????????? Parquet???? CSV
    :param path_csv: CSV ??
    :param path_parquet: Parquet ??
    :param use_parquet: ???? Parquet
    :param kwargs: ??? read_parquet/read_csv ?????
    :return: DataFrame
    """
    if use_parquet and os.path.exists(path_parquet):
        return read_parquet(path_parquet, **kwargs)
    elif os.path.exists(path_csv):
        print(f'  ???? CSV: {os.path.basename(path_csv)}')
        return pd.read_csv(path_csv, **kwargs)
    else:
        raise FileNotFoundError(f'?????: {path_parquet} ? {path_csv}')


def csv_path_to_parquet(path_csv):
    """
    ? CSV ????? Parquet ??
    :param path_csv: CSV ??
    :return: Parquet ??
    """
    if path_csv.endswith('.csv'):
        return path_csv[:-4] + '.parquet'
    return path_csv + '.parquet'


def excel_path_to_parquet(path_excel, sheet_name=None):
    """
    ? Excel ????? Parquet ??
    :param path_excel: Excel ??
    :param sheet_name: Sheet ??????????? Sheet?
    :return: Parquet ??
    """
    if sheet_name:
        base = path_excel.replace('.xlsx', '').replace('.xls', '')
        return f'{base}_{sheet_name}.parquet'
    return path_excel.replace('.xlsx', '.parquet').replace('.xls', '.parquet')


def read_excel_or_parquet(path_excel, path_parquet=None, verbose=True, **kwargs):
    """
    ???? Parquet???? Excel
    :param path_excel: Excel ??
    :param path_parquet: Parquet ????????? Excel ????
    :param kwargs: ??? read_parquet/read_excel ?????
    :return: DataFrame
    """
    if path_parquet is None:
        path_parquet = excel_path_to_parquet(path_excel)

    if os.path.exists(path_parquet):
        return read_parquet(path_parquet, verbose=verbose, **kwargs)

    if verbose:
        print(f'  ???? Excel: {os.path.basename(path_excel)}')
    return pd.read_excel(path_excel, **kwargs)


def save_parquet_mirror(df, legacy_path, verbose=True, sheet_name=None, **kwargs):
    """
    ???????? parquet ?????
    :param df: DataFrame
    :param legacy_path: ?? csv/xlsx ??
    :param sheet_name: Excel sheet ?????
    :return: parquet ??
    """
    lower_path = legacy_path.lower()
    if lower_path.endswith('.csv'):
        parquet_path = csv_path_to_parquet(legacy_path)
    elif lower_path.endswith('.xlsx') or lower_path.endswith('.xls'):
        parquet_path = excel_path_to_parquet(legacy_path, sheet_name=sheet_name)
    elif lower_path.endswith('.parquet'):
        parquet_path = legacy_path
    else:
        parquet_path = legacy_path + '.parquet'

    to_parquet(df, parquet_path, verbose=verbose, **kwargs)
    return parquet_path
