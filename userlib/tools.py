print(f'已调用工具{__file__}')
import sys, os, subprocess, shutil, time, re, platform, ast, threading, json, uuid, urllib.request
import pandas as pd, numpy as np
from pathlib import Path
from collections import OrderedDict
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment, PatternFill
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ==============================================================================
# 一、互相引用 / 有依赖关系的函数   (文件路径·拷贝删除·弹窗·日期解析·公式解析等成组，互为调用)
# ==============================================================================

def run_command(command, working_directory=None):
    """
    运行一个命令并等待其完成，可选地在指定的工作目录下运行。

    :param command: 要运行的命令，可以是列表或字符串。
    :param working_directory: 命令的工作目录。如果省略，则使用当前工作目录。
    :return: None
    """
    if working_directory:
        if not os.path.isdir(working_directory):
            print(f"警告: {working_directory} 不是一个有效的目录。")
            working_directory = None

    if working_directory:
        command_description = f'在目录 {os.path.normpath(working_directory)} 下执行 {command}'
    else:
        command_description = f'正在执行 {command}'

    print('\n')
    print(command_description.center(80, '='))
    print()
    try:
        result = subprocess.run(command, check=True, cwd=working_directory)
        print(f"{command} 执行成功。")
        return True
    except subprocess.CalledProcessError as e:
        print(f"执行 {command} 失败: {e}")
        return False

def run(file, dir=''):
    # 直接获取子进程是否成功运行的状态，并返回。
    print(f'正在运行{dir}{file}...')
    if not dir:
        dir = None
    return run_command([sys.executable, file], dir)

def find_info(target_name, start_path=None, max_depth=5):
    """
    向上搜索目标文件夹
    :param target_name: 目标文件夹名（如"参评信息"）
    :param start_path: 起始路径（默认为当前目录）
    :param max_depth: 最大回溯深度
    :return: 匹配的绝对路径（未找到时返回''）
    """
    current_dir = Path(start_path or os.getcwd()).resolve()

    for _ in range(max_depth):
        # 检查当前目录是否存在目标文件夹
        target_path = current_dir / target_name
        if target_path.exists() and target_path.is_dir():
            return str(target_path)

        # 回溯到上一级目录
        if current_dir == current_dir.parent:  # 到达根目录停止
            break
        current_dir = current_dir.parent

    return __file__

def get_path(n, path):
    """ 找到path第n层级的相对路径

    :param n: 层级
    :param path: 选择的路径
    :param tag_: 如选中1, 则只生成文件夹路径, 默认生成basename, 可忽略
    :return: {
        "n": parent_dir(文件夹路径)
        "rlp": relative_path(相对路径)
        "fp": full_path(全路径)}
    """
    # 获取绝对路径
    current_file_path = os.path.abspath(path)

    # 计算上n级目录的路径
    parent_dir = current_file_path
    for _ in range(n):
        parent_dir = (os.path.dirname(parent_dir))
        if parent_dir == os.path.dirname(parent_dir):  # 防止超出根目录
            break

    # 获取相对于上n级目录的路径
    relative_path = os.path.relpath(current_file_path, parent_dir)

    # 组合路径
    full_path = os.path.join(parent_dir, relative_path)

    # 输出字典
    return {
        "n": parent_dir+'/',
        "rlp": relative_path,
        "fp": full_path
    }

def make_dir(path, silence=0):
    """ 创建文件夹

     :param path: 创建文件夹的路径 - (字符串/Path对象)
     :param silence: 数字参数 1 - 静默进行，忽略则进行提示"""
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        if silence != 1:
            print(f'已创建{path}..')
    else:
        if silence != 1:
            print(f'{path}已存在，不进行创建..')

def find_rel(src, target):
    return os.path.relpath(find_info(target, src, 10), get_path(1, src)['n'])+'/'


# if __name__ == '__main__':
#     rel = find_rel('参评信息')
#     print(rel)

def numer_dates(date_series):
    """
    仅处理5位数字的 Excel 序列日期，其他值设为空。

    说明:
    - 5位数字按 Excel 序列日期解析。
    - 不再自动解析6位数字，避免将类似 401798 误拆成 40179.8 天，
      进而生成 2009-12-29 19:12:00 这类带时分秒的伪日期。
    参数:
        date_series: pandas.Series, 包含日期字符串或数值的序列
    返回:
        pandas.Series, 转换后的datetime64[ns]类型（非5位数字为NaT）
    """
    # 创建结果容器（初始化为NaT）
    result = pd.Series(pd.NaT, index=date_series.index)
    # 基准日期 (1899-12-30)
    base_date = pd.Timestamp('1899-12-30')

    # 步骤1：识别严格5位数字格式
    is_5digit = date_series.astype(str).str.fullmatch(r'\d{5}')

    # 步骤2：仅处理5位数字的情况
    if is_5digit.any():
        # 提取数字并计算日期
        digits = pd.to_numeric(date_series[is_5digit], errors='coerce')
        result[is_5digit] = base_date + pd.to_timedelta(digits, unit='D')

    # 非5位数字保持为NaT（不进行任何处理）
    return result

# if __name__ == '__main__':
#     se = pd.Series(['40951','34252','2022/1/23','20210305','2045~6~14','sbd','2024-12-31'])
#     se_pro = parse_dates(se,['%Y~%m~%d'])
#     print(se, se_pro)

def parse_dates(date_series, formats=None):
    """
    清洗日期函数，无法处理的日期元素将返回空值\n
    示例: df[‘date_cleaned'] = parse_date(df['date'],['%Y~%m~%d'])

    :param date_series: 指定清洗的日期序列，必须是series，dataframe的一列
    :param formats: formats是列表形式，可自定义添加存在的字符串格式, 可省略
    :return: 清洗后的日期序列"""
    date_formats = ['%Y-%m-%d', '%Y.%m.%d', '%Y%m%d', '%Y/%m/%d']
    if formats is None:
        formats = []
    if not isinstance(formats, list):
        print('Parameter "formats" must be list type')
    date_formats += formats
    # 优先处理数字型
    parsed_dates = numer_dates(date_series)
    date_series = date_series.mask(parsed_dates.notna(), parsed_dates)
    for fmt in date_formats:
        # 尝试解析日期
        parsed_dates = pd.to_datetime(date_series, format=fmt, errors='coerce')
        # 合并成功解析的日期
        date_series = date_series.mask(parsed_dates.notna(), parsed_dates)

    return pd.to_datetime(date_series, errors='coerce')

def is_file_locked(path):
    """检测文件是否被占用"""
    if not os.path.exists(path):  # 若文件不存在，则直接返回False
        return False
    try:
        if sys.platform == 'win32':
            # Windows方案：重命名测试
            try:
                os.rename(path, path)
                return False
            except (PermissionError, OSError):
                return True
        else:
            # Unix方案：lsof检测
            output = subprocess.check_output(
                ['lsof', '-t', os.path.abspath(path)],
                stderr=subprocess.DEVNULL
            )
            return bool(output.strip())
    except subprocess.CalledProcessError:
        return False
    except Exception as e:
        messagebox.showerror("检测异常", f"错误: {str(e)}")
        return False

def replacement_log(src, dst, replacement = 0):
    dt = datetime.now()
    log_path = '_log'
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    make_dir(log_path, 1)
    if_update = ' '*10 + '更新至'.center(10,'-')+'\n' if replacement == 1 else\
        ' '*10 + '复制到'.center(10,'-')+'\n'
    with open(f'{log_path}/file_logger.txt', 'a', encoding='utf-8') as f:
        f.write(f'{dt}'.center(30,'=')+'\n')
        f.write(f'{src}\n')
        f.write(if_update)
        f.write(f'{dst}\n')
        f.write(''.center(30,'='))
        f.write('\n\n')

def create_empty_file(file_path, silence=0):
    """
    安全创建空文件（覆盖已存在文件）

    :param file_path: 文件路径(支持相对/绝对路径)
    :param silence: 数字参数 1, 静默生成，忽略则生成提示
    :return: 创建成功返回True，失败返回False
    """
    try:
        # 规范化路径并创建父目录
        normalized_path = os.path.abspath(file_path)
        parent_dir = os.path.dirname(normalized_path)

        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        # 创建空文件
        with open(normalized_path, 'w') as f:
            pass  # 不写入任何内容
        if silence != 1:
            print(f"空文件创建成功: {normalized_path}")
        return True
    except PermissionError:
        print(f"权限不足，无法创建文件: {normalized_path}")
    except Exception as e:
        print(f"创建文件失败: {str(e)}")
    return False

""" 判断一个文件的存在性 """


def is_included(file, dst):
    files = os.listdir(dst)
    for fe in files:
        if file in fe:
            return True
    return False

# 全局根窗口管理
import customtkinter as ctk

_root = None

def get_root():
    global _root
    if not _root:
        _root = ctk.CTk()      # 原来是 tk.Tk()
        _root.withdraw()
    return _root

def close_dialog(dialog, result, value):
    """ 关闭对话框的辅助函数 """
    result['value'] = value
    dialog.grab_release()
    dialog.destroy()

"""
安全弹窗组件（CustomTkinter 版本）

外部依赖（沿用你原有实现，本文件不重新定义）:
    - get_root()                              返回主窗口 root
    - close_dialog(dialog, result, value)     关闭弹窗并写回 result['value']
    - validate_numeric / validate_whatever 等  字段验证函数

全局外观（可选，一般在程序入口调用一次）:
    ctk.set_appearance_mode("system")   # "light" / "dark" / "system"
    ctk.set_default_color_theme("blue")
"""


def custom_dialog(title, message, dialog_type, button1=None, button2=None):
    """安全弹窗组件（支持四种模式）

    :param title: 对话框标题
    :param message: 显示的消息内容
    :param dialog_type: 对话框类型，支持 'error', 'info', 'retry', 'confirm'
    :param button1: 按键自定义1
    :param button2: 按键自定义2, 注意: error 和 info 模式下不会生效！
    :returns:
        - 对于 'error' 和 'info' 模式: 总是返回 False
        - 对于 'retry' 模式: 用户点击"重试"返回 True，点击"取消"返回 False
        - 对于 'confirm' 模式: 用户点击"确认"返回 True，点击"取消"返回 False
    """
    root = get_root()
    dialog = ctk.CTkToplevel(root)
    dialog.attributes('-topmost', True)
    dialog.title(title)

    # 主框架容器（fg_color="transparent" 让容器与窗口背景融为一体）
    content_frame = ctk.CTkFrame(dialog, fg_color="transparent")
    content_frame.pack(padx=20, pady=(20, 10), fill='x')

    # 错误模式：添加警告图标
    if dialog_type == 'error':
        error_label = ctk.CTkLabel(content_frame, text="⚠️",
                                   font=('Microsoft YaHei', 10, 'bold'),
                                   text_color='red')
        error_label.pack(side='left', padx=(0, 10))

    # 创建消息标签
    # 注意: wraplength 为新增项 —— ctk 的 Label 默认不自动换行，
    # 长文本会把窗口横向撑得很宽，加上后超过 320px 自动折行。如需复刻原行为可删掉它。
    ctk.CTkLabel(content_frame, text=message,
                 font=('Microsoft YaHei', 10, 'bold'),
                 wraplength=320, anchor='w'
                 ).pack(side='left', expand=True, fill='x')

    # 结果存储字典
    result = {'value': None}

    # 按钮框架
    btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_frame.pack(pady=(10, 20), padx=10, fill='x')

    if not button1:
        if dialog_type == 'retry':
            button1 = '重试'
        elif dialog_type == 'confirm':
            button1 = '是'
        elif dialog_type == 'info':
            button1 = '好的'
        elif dialog_type == 'error':
            button1 = '确认'

    if not button2:
        if dialog_type == 'retry':
            button2 = '取消'
        elif dialog_type == 'confirm':
            button2 = '否'

    if dialog_type == 'retry':
        # 重试按钮
        ctk.CTkButton(btn_frame, text=button1,
                      command=lambda: close_dialog(dialog, result, True)
                      ).pack(side='left', padx=10, fill='x', expand=True)

        # 取消按钮
        ctk.CTkButton(btn_frame, text=button2,
                      command=lambda: close_dialog(dialog, result, False)
                      ).pack(side='right', padx=10, fill='x', expand=True)

    elif dialog_type == 'confirm':
        # 确认按钮（危险操作）
        ctk.CTkButton(btn_frame, text=button1,
                      command=lambda: close_dialog(dialog, result, True)
                      ).pack(side='left', padx=10, fill='x', expand=True)

        # 取消按钮
        ctk.CTkButton(btn_frame, text=button2,
                      command=lambda: close_dialog(dialog, result, False)
                      ).pack(side='right', padx=10, fill='x', expand=True)

    else:  # info 和 error 模式
        # 单个按钮
        ctk.CTkButton(btn_frame, text=button1,
                      command=lambda: close_dialog(dialog, result, True)
                      ).pack(padx=10, fill='x', expand=True)

    # 强制居中显示
    dialog.update_idletasks()
    x = (dialog.winfo_screenwidth() - dialog.winfo_width()) // 2
    y = (dialog.winfo_screenheight() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{x}+{y}")

    # 模态对话框设置
    dialog.grab_set()
    dialog.wait_window()

    return result['value']


def custom_input_dialog(title, fields):
    """
    更新后的现代化输入对话框 (CustomTkinter版)
    """
    root = get_root()
    dialog = ctk.CTkToplevel(root)
    dialog.attributes('-topmost', True)
    dialog.title(title)
    dialog.minsize(500, 300)
    dialog.configure(bg_color='#f0f0f0') # 可根据需要调整

    # 可滚动主区域
    main_frame = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
    main_frame.pack(side='top', fill='both', expand=True, padx=10, pady=10)

    entries = {}
    valid_states = {}
    hint_labels = {}
    status_labels = {}
    all_valid = tk.BooleanVar(value=False)

    # 1. 创建输入表单 (使用 grid 布局确保对齐)
    for i, config in enumerate(fields):
        # 标签
        lbl = ctk.CTkLabel(main_frame, text=f"{config['label']}:", font=('Microsoft YaHei', 11, 'bold'))
        lbl.grid(row=i*3, column=0, sticky='w', pady=(10, 0))
        
        # 输入框
        entry_var = tk.StringVar(value=config.get('default', ''))
        entry = ctk.CTkEntry(main_frame, textvariable=entry_var)
        entry.grid(row=i*3+1, column=0, sticky='ew', pady=(5, 0))
        
        # 状态标签
        status_lbl = ctk.CTkLabel(main_frame, text="", width=30)
        status_lbl.grid(row=i*3+1, column=1, padx=5)
        
        # 提示/错误信息
        hint_lbl = ctk.CTkLabel(main_frame, text=config.get('hint', ''), font=('Microsoft YaHei', 9), text_color="gray", wraplength=400)
        hint_lbl.grid(row=i*3+2, column=0, sticky='w', pady=(0, 10))
        
        entries[config['label']] = (entry, entry_var)
        hint_labels[config['label']] = hint_lbl
        status_labels[config['label']] = status_lbl
        valid_states[config['label']] = False

    main_frame.columnconfigure(0, weight=1)

    # 2. 先定义按钮框架和按钮 (修复 UnboundLocalError 的关键)
    btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_frame.pack(side='bottom', fill='x', padx=20, pady=(10, 20))

    result = {'value': None}

    # 定义确定回调 (放在前面，方便按钮引用)
    def on_ok():
        values = {label: entries[label][1].get() for label in entries}
        result['value'] = values
        dialog.grab_release()
        dialog.destroy()

    ok_btn = ctk.CTkButton(btn_frame, text="确定", width=80, state='disabled', command=on_ok)
    ok_btn.pack(side='right', padx=5)

    cancel_btn = ctk.CTkButton(
        btn_frame, text="取消", width=80, fg_color="gray",
        command=lambda: [result.update(value=None), dialog.grab_release(), dialog.destroy()]
    )
    cancel_btn.pack(side='right', padx=5)

    # 3. 定义验证逻辑
    def validate_field(field_label):
        config = next((c for c in fields if c['label'] == field_label), None)
        if not config: return False
        
        val = entries[field_label][1].get()
        validate_func = config.get('validate')
        
        if not validate_func:
            is_valid = True
            msg = ""
        else:
            is_valid, msg = validate_func(val)

        # 更新 UI
        if val == "":
            hint_labels[field_label].configure(text=config.get('hint', ''), text_color="gray")
            status_labels[field_label].configure(text="")
            is_valid = False
        else:
            hint_labels[field_label].configure(text=msg or "输入有效", text_color="green" if is_valid else "red")
            status_labels[field_label].configure(text="✓" if is_valid else "✗", text_color="green" if is_valid else "red")

        valid_states[field_label] = is_valid
        all_valid.set(all(valid_states.values()))

    # 绑定验证
    for config in fields:
        entries[config['label']][0].bind('<KeyRelease>', lambda e, f=config['label']: validate_field(f))

    # 4. 绑定回车事件
    dialog.bind('<Return>', lambda e: on_ok() if ok_btn.cget('state') == 'normal' else None)

    # 5. 初始化触发
    all_valid.trace_add('write', lambda *args: ok_btn.configure(state='normal' if all_valid.get() else 'disabled'))
    for config in fields: validate_field(config['label'])

    dialog.update_idletasks()
    x = (dialog.winfo_screenwidth() - dialog.winfo_width()) // 2
    y = (dialog.winfo_screenheight() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{x}+{y}")
    
    dialog.grab_set()
    dialog.wait_window()
    return result['value']


def check_with_retry(path, max_retries=3):
    """完全稳定版检测逻辑"""
    for attempt in range(max_retries + 1):
        if not is_file_locked(path):
            return True

        if attempt < max_retries:
            msg = f"文件被占用:\n{os.path.abspath(path)}\n剩余重试次数: {max_retries - attempt}"
            if attempt > 1:
                msg += '\n(如未发现占用中的文件, 可直接点击取消按钮)'
            if not custom_dialog("文件被占用", msg, 'retry'):
                return False
            time.sleep(1)

    custom_dialog("错误", "无法解除文件锁定", 'error')
    return False

def delete_file(src, clear=0, silence=0):
    """ 安全删除文件
     :param src: Path or str
     :param clear: 若src是文件夹： 数字参数0 保留文件夹本身, else完全清除
     :param silence: 设置1则不会有提示。
     """
    src = os.path.normpath(src)
    if os.path.exists(src):
        try:
            if os.path.isdir(src):
                shutil.rmtree(src)  # 删除文件夹
                if clear == 0:
                    make_dir(src, 1)  # 保留空文件夹
                    if silence != 1:
                        print(f'已清空{src}')
                else:
                    if silence != 1:
                        print(f'已删除{src}')
            else:
                os.remove(src)   # 删除文件
                if silence != 1:
                    print(f'已删除{src}')
            return True
        except:
            custom_dialog('error', f'移除文件(夹){src}失败..', 'error')
            return False
    else:
        print(f'待删除文件(夹){src}已被移除..')
        return True

def copy_file(src, dst, replace=0, silence=0, checkMode=None):
    """ 从源路径（src)复制一个文件或整个文件夹到目标路径(dst)【当src为文件夹时dst必须为文件夹】

    :param src: 源文件路径 - (字符串/Path对象)
    :param dst: 目标文件路径 - (字符串/Path对象)
    :param replace: 数字参数 1 - 覆盖dst；其他或省略不进行替换,当为1时加入日志记录
    :param silence: 数字参数 1 - 静默；省略则有语句提示
    :param checkMode: 如传入非空参数 - 将返回布尔值
    """
    try:
        src = os.path.normpath(src)
    except:
        print(f'传入的{src}不合规!')
        return None

    try:
        dst = os.path.normpath(dst)
    except:
        print(f'传入的{dst}不合规!')
        return None
    tag_update = 0
    if not os.path.exists(src):
        print(f'源文件{src}不存在！无法复制。')
        if checkMode:
            return False
    else:
        path = get_path(1, dst)['n']
        if not os.path.exists(path) or not os.path.isdir(path):
            if silence != 1:
                print(f'目标路径{path}不存在！无法复制{src}到{dst}。')
                if checkMode:
                    return False
        else:
            if os.path.isdir(src):
                mtd = 1
            else:
                mtd = 0
            if replace == 1:  # 当replace = 1时，如果文件已存在则进行替换(多为输出的文件)，其中代码和说明文件不进行替换。(除了更新文件)
                if os.path.exists(dst):
                    tag_update = 1
                    check_with_retry(dst)
                    try:
                        if mtd == 0:
                            delete_file(dst,0,1)
                        elif mtd == 1:
                            try:
                                shutil.rmtree(dst)
                            except:
                                print(f'{src}为文件夹, 但目标路径{dst}不为文件夹！')
                                if checkMode:
                                    return False
                    except:
                        print('无法替换目标文件(夹)')
                        if checkMode:
                            return False
            if not os.path.exists(dst):
                if mtd == 0:
                    shutil.copyfile(src, dst)
                elif mtd == 1:
                    try:
                        shutil.copytree(src, dst)
                    except:
                        print(f'目标路径{dst}不为文件夹！')
                        if checkMode:
                            return False
                if replace == 1:
                    if tag_update == 1:
                        if silence != 1:
                            print(f'已更新{src} ---> {dst}')
                        replacement_log(src, dst, 1)
                    else:
                        if silence != 1:
                            print(f'已复制{src} ---> {dst}')
                        replacement_log(src, dst)
                else:
                    if silence != 1:
                        print(f'已复制{src} ---> {dst}')
            else:
                if silence != 1:
                    print(f'{dst}已存在，不进行复制')

            if checkMode:
                return True

TIMELINE_LOG_NAME = "时间记录.log"
TIMELINE_LEGACY_NAME = "时间记录.txt"
TIMELINE_PREFIX = "GB_TIMELINE "


def _make_timeline_id(prefix):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"


def _resolve_time_record_base(script_path, path_t):
    if not path_t:
        return ""
    script_dir = os.path.dirname(os.path.abspath(script_path))
    raw_path = str(path_t).strip()
    if not raw_path:
        return ""
    if os.path.isabs(raw_path):
        candidate = raw_path
    else:
        candidate = os.path.join(script_dir, raw_path)
    candidate = os.path.abspath(candidate)
    if os.path.splitext(candidate)[1]:
        return os.path.dirname(candidate)
    return candidate


def _get_timeline_data_scope(path_base):
    if not path_base:
        return ""
    path_ins = os.path.join(path_base, "是否采用机构数据.txt")
    if not os.path.exists(path_ins):
        return ""
    with open(path_ins, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    if not lines:
        return ""
    return "全量数据" if lines[-1] == '否' else "机构筛选数据"


def _get_env_text(name, default=""):
    return os.environ.get(name, default).strip()


def _guess_workspace_root(script_path, path_base):
    env_root = _get_env_text("GB_TIMELINE_WORKSPACE_ROOT")
    if env_root:
        return os.path.abspath(env_root)
    if path_base:
        return os.path.abspath(os.path.dirname(path_base))
    return ""


def _compute_timeline_rel_path(script_path, workspace_root):
    if workspace_root:
        try:
            return os.path.relpath(os.path.abspath(script_path), workspace_root)
        except ValueError:
            pass
    return get_path(2, script_path)["rlp"]


def _build_timeline_rel_path(script_path, workspace_root):
    env_rel = _get_env_text("GB_TIMELINE_REL_PATH")
    if env_rel:
        return env_rel.replace("/", os.sep).replace("\\", os.sep)
    return _compute_timeline_rel_path(script_path, workspace_root)


def _normalize_bookmark_context(script_path, path_base, payload):
    payload = payload or {}
    workspace_root = _guess_workspace_root(script_path, path_base)
    rel_path = payload.get("rel_path") or _build_timeline_rel_path(script_path, workspace_root)
    axis = payload.get("axis") or _get_env_text("GB_TIMELINE_AXIS")
    if not axis:
        axis = "root"
        top_folder = rel_path.split(os.sep, 1)[0] if rel_path else ""
        if top_folder.lower().startswith("step_"):
            axis = "main"
    data_scope = payload.get("data_scope") or _get_timeline_data_scope(path_base)
    return {
        "run_id": str(payload.get("run_id") or _get_env_text("GB_TIMELINE_RUN_ID") or _make_timeline_id("run")),
        "session_id": str(payload.get("session_id") or _get_env_text("GB_TIMELINE_SESSION_ID") or _make_timeline_id("session")),
        "parent_rel": str(payload.get("parent_rel") or _get_env_text("GB_TIMELINE_PARENT_REL")),
        "parent_run_id": str(payload.get("parent_run_id") or _get_env_text("GB_TIMELINE_PARENT_RUN_ID")),
        "axis": axis,
        "source": str(payload.get("source") or _get_env_text("GB_TIMELINE_SOURCE")),
        "workspace_root": workspace_root,
        "rel_path": rel_path,
        "data_scope": data_scope,
        "pid": int(payload.get("pid") or os.getpid()),
    }


def _extract_start_payload(t):
    if isinstance(t, dict):
        return dict(t)
    return {}


def _extract_started_at(t):
    if isinstance(t, dict):
        try:
            return float(t.get("started_at", 0.0))
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(t or 0.0)
    except (TypeError, ValueError):
        return 0.0


class BookmarkContext(dict):
    """兼容旧脚本把 start 当作时间戳参与运算的写法。"""

    def _started_at(self):
        return _extract_started_at(self)

    def __float__(self):
        return self._started_at()

    def __sub__(self, other):
        return self._started_at() - _extract_started_at(other)

    def __rsub__(self, other):
        return _extract_started_at(other) - self._started_at()


def _append_timeline_log(log_path, payload):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(TIMELINE_PREFIX + json.dumps(payload, ensure_ascii=False) + "\n")


def insert_bookmark(path, tag_ = 0, path_t = None, t = None):
    """插入书签, 并自动进行时间记录\n
    如已完成将显示~~completed~~，否则为~~in-processing~~

    :param path: 路径(可选用__file__或 os.path.getcwd() + filename快捷引用自身路径)
    :param tag_: 在代码开头省略，在代码结尾处使用1
    :param path_t: 时间记录文件到引用此函数.py文件的相对路径
    :param t: 传入时间，须在tag_为1时传入, 方便时间记录

    # --- 在需要时间记录的文件开始时记录 ---
    # start = insert_bookmark(__file__, 0, path_t)\n
    # --- 在需要时间记录的文件结束时记录 ---
    # insert_bookmark(__file__, 1, path_t, start)"""

    script_path = os.path.abspath(path)
    filename = os.path.basename(script_path).split('.')[0]
    now = datetime.now()
    now_ts = time.time()
    name = f'~~{filename}in-processing~~' if tag_ == 0 else f'~~{filename}completed~~'
    if tag_ == 0: # 开始时
        if os.path.exists(get_path(1, script_path)['n'] + f'~~{filename}in-processing~~'):
            pass
        elif os.path.exists(get_path(1, script_path)['n'] + f'~~{filename}completed~~'):
            os.rename(get_path(1, script_path)['n'] + f'~~{filename}completed~~',
                      get_path(1, script_path)['n'] + f'~~{filename}in-processing~~')
        else:
            create_empty_file(get_path(1, script_path)['n'] + name,1)
    else: # 结束时
        if os.path.exists(get_path(1, script_path)['n'] + f'~~{filename}completed~~'):
            pass
        elif os.path.exists(get_path(1, script_path)['n'] + f'~~{filename}in-processing~~'):
            os.rename(get_path(1, script_path)['n'] + f'~~{filename}in-processing~~',
                      get_path(1, script_path)['n'] + f'~~{filename}completed~~')
        else:
            create_empty_file(get_path(1, script_path)['n'] + name, 1)

    path_base = _resolve_time_record_base(script_path, path_t)
    data_scope = _get_timeline_data_scope(path_base)
    text = f'({data_scope})' if data_scope else ''
    if os.path.exists(get_path(1, script_path)['n']):
        with open(get_path(1, script_path)['n'] + name, 'a', encoding='utf-8') as f:
            if tag_ == 0:
                f.write(f'\n>>>运行{text}:{now}--------------\n')
            else: # tag_ == 1
                f.write(f'>>>成功{text}:{now}--------------\n')
    else:
        print('文件位置出错! 请检查！')

    if path_t:
        if os.path.exists(path_base):
            legacy_start = _extract_start_payload(t)
            context = _normalize_bookmark_context(script_path, path_base, legacy_start)
            context["data_scope"] = data_scope
            log_path = os.path.join(path_base, TIMELINE_LOG_NAME)
            with open(log_path, 'a', encoding='utf-8') as f:
                if tag_ == 0:
                    f.write('\n' + '=' * 20)
                if tag_ == 1:
                    started_at = _extract_started_at(t)
                    duration_seconds = round(max(0.0, now_ts - started_at), 3) if started_at else None
                    f.write(f'成功运行{text}:{context["rel_path"]}, 用时{duration_seconds or 0.0}秒--({now})\n')
                    end_payload = {
                        "event": "end",
                        "run_id": context["run_id"],
                        "session_id": context["session_id"],
                        "parent_rel": context["parent_rel"],
                        "parent_run_id": context["parent_run_id"],
                        "rel_path": context["rel_path"],
                        "axis": context["axis"],
                        "source": context["source"],
                        "status": "success",
                        "ts": now.isoformat(sep=" ", timespec="milliseconds"),
                        "duration": duration_seconds,
                        "pid": context["pid"],
                        "data_scope": context["data_scope"],
                    }
                    f.write(TIMELINE_PREFIX + json.dumps(end_payload, ensure_ascii=False) + '\n\n')
                else:
                    f.write(f'\n代码运行{text}:{context["rel_path"]}--({now})\n')
                    start_payload = {
                        "event": "start",
                        "run_id": context["run_id"],
                        "session_id": context["session_id"],
                        "parent_rel": context["parent_rel"],
                        "parent_run_id": context["parent_run_id"],
                        "rel_path": context["rel_path"],
                        "axis": context["axis"],
                        "source": context["source"],
                        "status": "running",
                        "ts": now.isoformat(sep=" ", timespec="milliseconds"),
                        "pid": context["pid"],
                        "data_scope": context["data_scope"],
                    }
                    f.write(TIMELINE_PREFIX + json.dumps(start_payload, ensure_ascii=False) + '\n\n')
        else:
            print('时间记录文件不存在！请检查！')
    if tag_ == 0:
        start_context = _normalize_bookmark_context(script_path, path_base, {})
        start_context["started_at"] = now_ts
        start_context["started_at_iso"] = now.isoformat(sep=" ", timespec="milliseconds")
        start_context["data_scope"] = data_scope
        return BookmarkContext(start_context)
    return t

def check_required_files(required_files, optional_files, appe = ''):
    # 1. 检查必需文件
    missing_required = {}
    for file_path, sent in required_files.items():
        if not is_included(os.path.basename(file_path), get_path(1, file_path)['n']):
            missing_required[os.path.basename(file_path)] = sent  # 只取文件名

    # 2. 检查可选文件
    missing_optional = {}
    for opt_path, sent in optional_files.items():
        if not is_included(os.path.basename(opt_path), get_path(1, opt_path)['n']):
            missing_optional[os.path.basename(opt_path)] = sent

    # 3. 生成结果信息
    if missing_required:
        result = f"错误：缺少 {len(missing_required)} 个必需文件！\n"
        required_list = '\n'.join([f'{key}-->{value}' for key, value in missing_required.items()])
        result += f"缺失文件：\n{required_list}\n"
        optional_list = '\n'.join([f'{key}-->{value}' for key, value in missing_optional.items()])
        result += f"请补充必需文件后重新提交 {optional_list}"
        return result, False
    else:
        result = "所有必需文件检查通过！"
        if missing_optional:
            result += "\n" + ','.join(missing_optional.keys())
        return result, True

def remove_short_brackets(text):
    # 找到最内层的括号对
    stack = []
    pairs = []
    for i, c in enumerate(text):
        if c == '(':
            stack.append(i)
        elif c == ')':
            if stack:
                start = stack.pop()
                pairs.append((start, i))

    # 如果没有括号，返回原文本
    if not pairs:
        return text

    # 按起始位置降序排序，以便从内到外处理
    pairs.sort(reverse=True, key=lambda x: x[0])

    # 处理每个最内层的括号对
    new_text = list(text)
    removed = False
    for start, end in pairs:
        # 计算内容长度（不包括括号本身）
        content = text[start + 1:end]
        content_length = len(content)
        if content_length <= 8:
            # 删除该括号及内容
            new_text[start:end + 1] = [''] * (end - start + 1)
            removed = True

    # 转换为字符串并递归处理
    result = ''.join(new_text)
    if removed:
        return remove_short_brackets(result)
    else:
        return result

class FormulaConverter:
    def __init__(self):
        self.var_counter = 97  # ASCII 'a'
        self.variable_map = OrderedDict()
        self.operator_set = {'+', '*', '/', '(', ')'}

    def _next_var_name(self):
        """生成连续的变量名"""
        if self.var_counter <= 122:
            var = chr(self.var_counter)
            self.var_counter += 1
            return var
        else:
            return f"a{chr(97 + (self.var_counter - 123))}"

    def _is_structural_bracket(self, formula, index):
        """判断是否为公式层级的括号"""
        if index == 0:
            return formula[index] == '('
        prev_char = formula[index - 1]
        return prev_char in self.operator_set or prev_char.isspace()

    def _tokenize(self, formula):
        """精确分词逻辑"""
        tokens = []
        i = 0
        n = len(formula)

        while i < n:
            # 跳过空格
            if formula[i].isspace():
                i += 1
                continue

            # 识别公式层级的括号
            if formula[i] == '(' and self._is_structural_bracket(formula, i):
                tokens.append('(')
                i += 1
                continue
            if formula[i] == ')':
                tokens.append(')')
                i += 1
                continue

            # 识别完整变量（包含说明性括号）
            if re.match(r'[\u4e00-\u9fa5]', formula[i]):
                j = i
                while j < n:
                    # 遇到公式层级运算符或结构括号时停止
                    if (formula[j] in self.operator_set) or \
                            (formula[j] == '(' and self._is_structural_bracket(formula, j)):
                        break
                    j += 1
                var = formula[i:j].strip()
                tokens.append(var)
                i = j
                continue

            # 识别数字和百分比
            if formula[i].isdigit() or formula[i] in './%':
                j = i
                while j < n and (formula[j].isdigit() or formula[j] in './%'):
                    j += 1
                token = formula[i:j]
                if '%' in token:
                    value = float(token[:token.find('%')]) / 100
                    tokens.append(f"{value:.4f}".rstrip('0').rstrip('.'))
                else:
                    tokens.append(token)
                i = j
                continue

            # 识别运算符
            if formula[i] in self.operator_set:
                tokens.append(formula[i])
                i += 1
                continue

            i += 1  # 容错处理

        return tokens

    def convert(self, formula):
        """执行转换"""
        self.var_counter = 97  # 重置计数器
        self.variable_map = OrderedDict()

        tokens = self._tokenize(formula)

        # 构建变量映射
        variables = [t for t in tokens if re.match(r'^[\u4e00-\u9fa5]', t)]
        for var in variables:
            if var not in self.variable_map:
                self.variable_map[var] = self._next_var_name()

        # 转换公式
        converted = []
        for token in tokens:
            if token in self.variable_map:
                converted.append(self.variable_map[token])
            elif token in self.operator_set:
                converted.append(token)
            else:
                converted.append(token)

        return {
            'formula': ' '.join(converted),
            'variables': self.variable_map
        }

def convertFormula(formula):
    converter = FormulaConverter()
    print('原始公式:', formula)
    formula = remove_short_brackets(formula.replace('[', '(').replace(']', ')'))
    print('转换括号:', formula)
    result = converter.convert(formula)
    print("转换结果:", result['formula'])  # ( a + b ) * 1/2
    print("变量映射:", result['variables'])
    return result['formula'].replace('1 b', 'b').replace('1 a', 'a').replace('1 c', 'c')


# # 验证测试
# if __name__ == "__main__":
#     convertFormula("[同期1年期银行定期存款利率(税后)+同期2年期银行定期存款利率(税后)]*1/2")

class FormulaValidator(ast.NodeVisitor):
    """增强版公式校验器"""

    def __init__(self):
        self.vars = set()

    def visit_Name(self, node):
        self.vars.add(node.id)

    def visit_Attribute(self, node):
        raise ValueError("公式中禁止使用属性访问")

    def visit_Call(self, node):
        raise ValueError("公式中禁止调用函数方法")

def parse_variables(formula):
    """解析公式中的有效变量"""
    try:
        tree = ast.parse(formula, mode='eval')
    except SyntaxError as e:
        raise ValueError(f"公式语法错误：{e}")

    validator = FormulaValidator()
    try:
        validator.visit(tree)
    except ValueError as e:
        raise e

    return validator.vars

def evaluate(formula, variables):
    """
    智能计算公式
    :param formula: 数学表达式，如 "a*0.2 + b"
    :param variables: 包含标量或Series的字典
    :return: 标量或Series
    """
    # 变量解析与校验
    required_vars = parse_variables(formula)
    missing = required_vars - variables.keys()
    if missing:
        raise ValueError(f"缺失变量：{missing}")

    # 类型处理系统
    series_container = {}
    scalars = {}
    base_index = None

    for var in required_vars:
        value = variables[var]

        # 标量处理
        if isinstance(value, (int, float, np.number)):
            scalars[var] = float(value)
            continue

        # Series处理
        if isinstance(value, pd.Series):
            # 索引校验
            if base_index is None:
                base_index = value.index
            elif not value.index.equals(base_index):
                raise ValueError(f"变量 '{var}' 索引不一致")

            series_container[var] = value
            continue

        # 类型转换尝试
        try:
            scalars[var] = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"变量 '{var}' 类型无效（需数值或Series）")

    # 混合计算环境
    eval_env = {'np': np, 'pd': pd}  # 允许使用numpy函数
    eval_env.update(scalars)
    eval_env.update(series_container)

    # 安全沙箱计算
    try:
        result = eval(formula, {'__builtins__': None}, eval_env)
    except Exception as e:
        raise ValueError(f"计算错误：{e}")

    # 结果类型校验
    if series_container:
        if not isinstance(result, (pd.Series, pd.DataFrame)):
            raise ValueError("存在Series变量时，结果必须为Series")
        if not result.index.equals(base_index):
            raise ValueError("结果索引与输入Series不一致")
    else:
        if not isinstance(result, (int, float, np.number)):
            raise ValueError("纯标量计算需返回数值")

    return result


# ==============================================================================
# 二、独立功能函数   (不调用本文件其它函数，互不依赖的工具)
# ==============================================================================

def get_year(path_):
    with open(path_+'年份信息.txt') as f:
        yr = int(f.readlines()[0])
    return yr

def exit_(parameter=2):
    """ 退出程序并暂停parameter秒

     :param parameter: 暂停秒数"""
    time.sleep(parameter)
    sys.exit(0)

def print_progress(current, total, bar_length=50, extra_text=''):
    """
    显示进度函数, 可添加提示语句\n
    示例 for i in range(k+1):
            time.sleep(0.5)\n
            print_process(i, k, k, f'输出第{i}个元素')

    :param current: 当前进度，建议在外部设置循环
    :param total: 进程总数
    :param bar_length: 想展示进度条的长度，默认50，可省略
    :param extra_text: 想在进度条后方展示的语句，建议可以在外部循环定义，可省略"""

    progress = current / total
    block = int(round(bar_length * progress))
    text = f"[{'#' * block + '-' * (bar_length - block)}] {int(progress * 100)}% | ({current}/{total}):{extra_text}"

    # 使用 '\r' 返回行首，'\033[K' 清除行内剩余字符
    sys.stdout.write(f'\r{text}\033[K')
    sys.stdout.flush()

def fill_nearest(s):
    """
    进行以日期为索引的时间序列的填充

    :param s: (org)Series
    :return: (filled)series

    填充逻辑：
    1. 连续3+NaN：首前向，尾后向，中间前向填充
    2. 连续1-2NaN：2个按时间最近的填充，1个前向填充
    """
    if not isinstance(s.index, pd.DatetimeIndex):
        raise ValueError("Series索引必须是DatetimeIndex")

    s_sorted = s.sort_index().copy()
    mask = s_sorted.isna()

    # 标记连续NaN区域
    shifted = mask.ne(mask.shift())
    groups = shifted.cumsum()
    counts = groups.map(groups.value_counts())

    # 处理连续≥3NaN的区域
    mask_3 = mask & (counts >= 3)
    for group_id in groups[mask_3].unique():
        group_idx = s_sorted.index[groups == group_id]
        if len(group_idx) < 3:
            continue

        start, end = group_idx[[0, -1]]

        # 首前向填充
        s_sorted.loc[start] = s_sorted.ffill().loc[start]
        # 尾后向填充
        s_sorted.loc[end] = s_sorted.bfill().loc[end]
        # 中间前向填充
        s_sorted.loc[start:end] = s_sorted.loc[start:end].ffill()
        # 确保尾值不被覆盖
        s_sorted.loc[end] = s_sorted.bfill().loc[end]

    # 处理剩余连续1-2NaN的区域
    mask_remaining = s_sorted.isna()
    shifted_remain = mask_remaining.ne(mask_remaining.shift())
    groups_remain = shifted_remain.cumsum()

    for group_id in groups_remain[mask_remaining].unique():
        group_idx = s_sorted.index[groups_remain == group_id]
        if len(group_idx) == 0 or len(group_idx) >= 3:
            continue

        # 仅填充最后一个NaN
        last_na = group_idx[-1]
        next_valid = s_sorted.loc[last_na:].first_valid_index()
        if next_valid:
            s_sorted.loc[last_na] = s_sorted.loc[next_valid]

    return s_sorted.ffill().reindex(s.index)

def custom_order_list(original_list, priority_order):
    """
    将指定元素按自定义顺序排列在前，其余元素保持原顺序在后

    :param original_list: 原始列表，如 ['a', 'b', 'c', 'd', 'e', 'f', 'g']
    :param priority_order: 自定义顺序列表，如 ['c', 'g', 'f', 'e']
    :return: 处理后的列表，如 ['c', 'g', 'f', 'e', 'a', 'b', 'd']
    """
    # 提取符合顺序的元素（去重且保留原列表中的出现次数）
    ordered_elements = []
    for item in priority_order:
        count = original_list.count(item)
        ordered_elements.extend([item] * count)

    # 提取剩余元素并保持原顺序
    remaining_elements = [item for item in original_list if item not in priority_order]

    return ordered_elements + remaining_elements

# if __name__ == '__main__':
# #    create_empty_file(get_path(1,'test/completed')['n']+'tryonetry')
#     insert_bookmark('test/test.xlsx',0)

# if __name__ == '__main__':
#     print(custom_order_list(['a','b','c','d','e','f','g','h','i'],['b','f','i']))

def normalize_min_max(col):
    if col.nunique() == 1:
        # 所有值相同时返回0.5避免除零
        return pd.Series(0.5, index=col.index)

    min_val = col.min()
    max_val = col.max()
    return (col - min_val) / (max_val - min_val)

# if __name__ == '__main__':
#     result = normalize_min_max(pd.DataFrame({'数值':[0,0,0,1,1,2,5,6,8,8]})['数值'])
#     print(result)
# ---------------------------------------
# 0    0.000
# 1    0.000
# 2    0.000
# 3    0.125
# 4    0.125
# 5    0.250
# 6    0.625
# 7    0.750
# 8    1.000
# 9    1.000
# Name: 数值, dtype: float64

def rank_pct(col):
    n = len(col)
    if n == 0:
        return pd.Series(dtype=float)
    if n == 1:
        return pd.Series([0.5], index=col.index)  # 单一值给0.5

    # 真实排名（相同值取最低可能排名）
    true_rank = col.rank(method='min', ascending=False)

    # 确保所有最低分获得最低排名
    min_mask = col == col.min()
    true_rank = true_rank.mask(min_mask, n)  # 将最小值排名设为n

    # 线性映射
    return 1 - (true_rank - 1) / (n - 1)

# if __name__ == '__main__':
#     result = rank_pct(pd.DataFrame({'数值': [0, 0, 0, 1, 1, 2, 5, 6, 8, 8]})['数值'])
#     print(result)
# 0    0.000000
# 1    0.000000
# 2    0.000000
# 3    0.444444
# 4    0.444444
# 5    0.555556
# 6    0.666667
# 7    0.777778
# 8    1.000000
# 9    1.000000
# Name: 数值, dtype: float64

## 数值验证
def validate_numeric(value, lower, upper, type_=None):
    if type_ == 'int':
        if not value.isdigit():
            return False, "必须输入整数"
        else:
            value = int(value)
    else:
        value = float(value)

    if lower <= value < upper:
        return True, ""
    else:
        return False, f"输入数值必须在{lower}和{upper}之间"

## 任意内容
def validate_whatever(value):
    # 接受任何输入
    return True, ""

def chunks_apart(df, size=1e6):
    """ 分割大型数据框至若干数据块(100万行为界限,可选)

    :param df: 分割的数据框 - (pd.DataFrame)
    :param size: 分割的单位, 默认1000000, 可省略"""
    mount = len(df)

    chunk_size = int(size)

    num_chunks = int(mount // chunk_size + 1)

    chunks = []
    print('number of chunks:',num_chunks)
    num = num_chunks - 1
    for i in range(num):
        chunks.append(df.iloc[chunk_size * i: chunk_size * (i + 1)])
    chunks.append(df.iloc[chunk_size * num:])

    chunk_list = [chunk.reset_index(drop=True) for chunk in chunks]

    for i, chunk in enumerate(chunk_list):
        print(f'chunk_{i + 1} shape: {chunk.shape}')
    return chunk_list

def get_sum(log, sum_columns=None, group_by=None, check=None):
    summary_rows = []
    if sum_columns is None:
        sum_columns = ['产品数量', '净值行数']
    if group_by is None:
        group_by = ['机构编号', '频率', '处理阶段']
    else:
        log = log[log['产品数量']>0]

    for name, group in log.groupby(group_by):
        new_row = {col: None for col in log.columns}

        # 对于非汇总列（固定属性），取第一行的值
        first_row = group.iloc[0].copy()

        for col in log.columns:
            # 跳过是需要求和的列
            if col in sum_columns:
                continue
            new_row[col] = first_row[col]

        if '产品策略' not in group_by:
            new_row['产品策略'] = 'sum_up'

        if check is not None:
            new_row['跟踪指数'] = None

        new_row['机构数量'] = group['机构编号'].nunique()
        new_row['具体机构'] = ', '.join(group['机构编号'].unique())

        # 对于需要求和的列，求和
        for col in sum_columns:
            new_row[col] = group[col].sum()

        print(new_row)
        # 将新行添加到summary_rows列表
        summary_rows.append(new_row)

    # 汇总为一个DataFrame
    return pd.DataFrame(summary_rows)

def delete_except(root_dir, keep_files, silence=0):
    """
    清空文件夹并保留所需文件\n
    删除 root_dir 下除 keep_files 外的所有文件和目录

    :param root_dir: 要清理的根目录路径
    :param keep_files: 要保留的文件名列表 (如 ["file1.py", "config.json"])
    :param silence: 数字参数1 - 静默删除, 忽略则保留提示
    """
    # 标准化保留文件名，确保大小写敏感问题
    keep_files = set(keep_files)
    safe_keep_files = set()  # 存储实际存在的保留文件路径

    # 收集所有需要保留的文件路径
    for foldername, subfolders, files in os.walk(root_dir):
        for file in files:
            if file in keep_files:
                full_path = os.path.join(foldername, file)
                safe_keep_files.add(os.path.normpath(full_path))  # 标准化路径格式

    # 删除不需要的文件和目录
    for foldername, subfolders, files in os.walk(root_dir, topdown=False):
        # 删除文件
        for file in files:
            file_path = os.path.normpath(os.path.join(foldername, file))
            if file_path not in safe_keep_files:
                try:
                    os.remove(file_path)
                    if silence != 1:
                        print(f"Deleted file: {file_path}")
                except PermissionError:
                    print(f"Permission denied: {file_path}")
                except Exception as e:
                    print(f"Error deleting {file_path}: {str(e)}")

        # 删除空目录 (保留包含保留文件的目录)
        for subfolder in subfolders:
            dir_path = os.path.normpath(os.path.join(foldername, subfolder))
            try:
                if not os.listdir(dir_path):  # 目录为空
                    shutil.rmtree(dir_path)
                    if silence != 1:
                        print(f"Deleted empty directory: {dir_path}")
            except Exception as e:
                print(f"Error deleting {dir_path}: {str(e)}")

def _get_async_pid_file():
    return os.environ.get("GB_ASYNC_PID_FILE", "").strip()


def _get_async_log_dir():
    return os.environ.get("GB_ASYNC_LOG_DIR", "").strip()


def _register_async_pid(pid):
    pid_file = _get_async_pid_file()
    if not pid_file:
        return
    try:
        os.makedirs(os.path.dirname(pid_file), exist_ok=True)
        with open(pid_file, "a", encoding="utf-8") as f:
            f.write(f"{pid}\n")
    except Exception:
        pass


def _unregister_async_pid(pid):
    pid_file = _get_async_pid_file()
    if not pid_file or not os.path.exists(pid_file):
        return
    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        with open(pid_file, "w", encoding="utf-8") as f:
            for line in lines:
                if line != str(pid):
                    f.write(f"{line}\n")
    except Exception:
        pass


def _build_async_log_path(abs_file_path):
    log_dir = _get_async_log_dir()
    if not log_dir:
        return ""
    try:
        os.makedirs(log_dir, exist_ok=True)
        script_name = os.path.basename(abs_file_path)
        safe_name = re.sub(r'[<>:"/\\\\|?*]', "_", script_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return os.path.join(log_dir, f"{timestamp}_{safe_name}.log")
    except Exception:
        return ""


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _debug_env_path():
    try:
        return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".dbg", "run-bat-open-fail.env"))
    except Exception:
        return ""


def _debug_server_config():
    url = ""
    session_id = "run-bat-open-fail"
    env_path = _debug_env_path()
    if env_path and os.path.isfile(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if line.startswith("DEBUG_SERVER_URL="):
                        url = line.split("=", 1)[1].strip()
                    elif line.startswith("DEBUG_SESSION_ID="):
                        session_id = line.split("=", 1)[1].strip() or session_id
        except Exception:
            pass
    return url, session_id


def _debug_report_open_file(hypothesis_id, location, msg, data=None):
    url, session_id = _debug_server_config()
    if not url:
        return
    payload = {
        "sessionId": session_id,
        "runId": "pre-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "msg": msg,
        "data": data or {},
        "ts": int(time.time() * 1000),
    }
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(request, timeout=1).read()
    except Exception:
        pass


def _build_async_ps_command(file_dir, run_expr, script_name="", launch_mode="", log_path="", pause_on_failure=False):
    lines = [
        "try { chcp 65001 > $null } catch {}",
        "Write-Host '============================================================' -ForegroundColor DarkGray",
        "Write-Host '[OPEN_FILE] 异步脚本启动中' -ForegroundColor Green",
        f"Write-Host ('[OPEN_FILE] 脚本文件: ' + {_ps_quote(script_name)}) -ForegroundColor Cyan",
        f"Write-Host ('[OPEN_FILE] 启动方式: ' + {_ps_quote(launch_mode)}) -ForegroundColor Cyan",
        "Write-Host ('[OPEN_FILE] 启动时间: ' + (Get-Date -Format \"yyyy-MM-dd HH:mm:ss\")) -ForegroundColor Cyan",
        f"Set-Location -LiteralPath {_ps_quote(file_dir)}",
        f"try {{ $Host.UI.RawUI.WindowTitle = {_ps_quote(script_name or 'open_file.py')} }} catch {{}}",
        f"Write-Host ('[OPEN_FILE] 工作目录: ' + {_ps_quote(file_dir)}) -ForegroundColor Cyan",
    ]
    if log_path:
        lines.append(f"Write-Host ('[OPEN_FILE] 日志文件: ' + {_ps_quote(log_path)}) -ForegroundColor DarkCyan")
    lines.append("Write-Host '[OPEN_FILE] 正在执行命令，请稍候...' -ForegroundColor Yellow")
    lines.append("Write-Host '============================================================' -ForegroundColor DarkGray")
    lines.append("$gbExit = 0")
    if log_path:
        lines.append(f"Start-Transcript -Path {_ps_quote(log_path)} -Append | Out-Null")
        lines.append(f"try {{ {run_expr}; $gbExit = $LASTEXITCODE }} finally {{ Stop-Transcript | Out-Null }}")
    else:
        lines.append(f"{run_expr}; $gbExit = $LASTEXITCODE")
    if pause_on_failure:
        lines.append("if ($gbExit -ne 0) { Write-Host ('[OPEN_FILE] 脚本执行失败，退出码: ' + $gbExit) -ForegroundColor Red; Write-Host '[OPEN_FILE] 按任意键关闭窗口...' -ForegroundColor Yellow; pause | Out-Null }")
    lines.append("exit $gbExit")
    return "; ".join(lines)


def _watch_async_process(proc, log_handle=None, abs_file_path=""):
    started_at = time.time()
    try:
        proc.wait()
    finally:
        if log_handle:
            try:
                log_handle.close()
            except Exception:
                pass
        # #region debug-point G:open-python-async-exit
        _debug_report_open_file(
            "G",
            "userlib/tools.py:_watch_async_process:exit",
            "[DEBUG] open_python_async child process exited",
            {
                "abs_file_path": abs_file_path,
                "pid": getattr(proc, "pid", None),
                "returncode": getattr(proc, "returncode", None),
                "duration_seconds": round(max(0.0, time.time() - started_at), 3),
            },
        )
        # #endregion
        _unregister_async_pid(proc.pid)


def open_python_async(file_path):
    print('open_python_async被调用')
    try:
        abs_file_path = os.path.abspath(file_path)
        if not os.path.exists(abs_file_path):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            abs_file_path = os.path.normpath(os.path.join(script_dir, "..", file_path))

        if not os.path.exists(abs_file_path):
            print(f"错误：Python脚本不存在 -> {abs_file_path}")
            return

        file_dir = os.path.dirname(abs_file_path)
        project_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        venv_python = os.path.join(project_root, "myenv", "Scripts", "python.exe")
        python_executable = venv_python if os.path.exists(venv_python) else sys.executable
        run_bat_path = os.path.join(file_dir, 'run.bat')
        bridge_script = os.path.join(project_root, "gb_runtime_patch", "async_console_bridge.py")
        log_path = _build_async_log_path(abs_file_path)
        log_handle = None
        child_env = os.environ.copy()
        workspace_root = _get_env_text("GB_TIMELINE_WORKSPACE_ROOT")
        if workspace_root:
            workspace_root = os.path.abspath(workspace_root)
        child_env["GB_TIMELINE_WORKSPACE_ROOT"] = workspace_root
        child_env["GB_TIMELINE_SESSION_ID"] = _get_env_text("GB_TIMELINE_SESSION_ID") or _make_timeline_id("session")
        child_env["GB_TIMELINE_RUN_ID"] = _make_timeline_id("run")
        child_env["GB_TIMELINE_PARENT_REL"] = _get_env_text("GB_TIMELINE_REL_PATH")
        child_env["GB_TIMELINE_PARENT_RUN_ID"] = _get_env_text("GB_TIMELINE_RUN_ID")
        child_env["GB_TIMELINE_AXIS"] = "async"
        child_env["GB_TIMELINE_SOURCE"] = "async_open"
        child_env["GB_TIMELINE_REL_PATH"] = _compute_timeline_rel_path(abs_file_path, workspace_root)

        print(f"[DEBUG] 异步启动Python脚本: {abs_file_path}")
        print(f"[DEBUG] 使用解释器: {python_executable}")
        if log_path:
            print(f"[DEBUG] 异步日志文件: {log_path}")

        if platform.system() == "Windows":
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            bridge_available = os.path.isfile(bridge_script)
            # #region debug-point A:open-python-async-branch
            _debug_report_open_file(
                "A",
                "userlib/tools.py:open_python_async:windows",
                "[DEBUG] open_python_async resolved launch inputs",
                {
                    "abs_file_path": abs_file_path,
                    "file_dir": file_dir,
                    "run_bat_path": run_bat_path,
                    "run_bat_exists": os.path.exists(run_bat_path),
                    "python_executable": python_executable,
                    "bridge_script": bridge_script,
                    "bridge_available": bridge_available,
                    "creationflags": creationflags,
                    "timeline_rel_path": child_env.get("GB_TIMELINE_REL_PATH", ""),
                },
            )
            # #endregion
            launch_mode = "python.exe"
            if bridge_available:
                if not log_path:
                    fallback_name = os.path.basename(abs_file_path) + ".log"
                    log_path = os.path.join(file_dir, fallback_name)
                run_expr = (
                    f"& {_ps_quote(python_executable)} "
                    f"{_ps_quote(bridge_script)} "
                    f"--python {_ps_quote(python_executable)} "
                    f"--script {_ps_quote(abs_file_path)} "
                    f"--cwd {_ps_quote(file_dir)} "
                    f"--log {_ps_quote(log_path)}"
                )
                launch_mode = "python.exe + bridge"
                # 桥接脚本自己负责写日志，避免 transcript 抄控制台导致正文缺失或中文重影。
                ps_command = _build_async_ps_command(
                    file_dir,
                    run_expr,
                    script_name=os.path.basename(abs_file_path),
                    launch_mode=launch_mode,
                    log_path="",
                    pause_on_failure=True,
                )
            else:
                run_expr = f"& {_ps_quote(python_executable)} {_ps_quote(abs_file_path)}"
                ps_command = _build_async_ps_command(
                    file_dir,
                    run_expr,
                    script_name=os.path.basename(abs_file_path),
                    launch_mode=launch_mode,
                    log_path=log_path,
                    pause_on_failure=True,
                )
            # #region debug-point C:open-python-async-python
            _debug_report_open_file(
                "C",
                "userlib/tools.py:open_python_async:python",
                "[DEBUG] open_python_async selected python.exe branch",
                {
                    "abs_file_path": abs_file_path,
                    "run_bat_path": run_bat_path,
                    "run_bat_exists": os.path.exists(run_bat_path),
                    "bridge_available": bridge_available,
                    "launch_mode": launch_mode,
                    "ps_command_preview": ps_command[:600],
                },
            )
            # #endregion
            print(f"[DEBUG] PowerShell命令已准备，黑窗会显示启动信息")
            proc = subprocess.Popen(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
                cwd=file_dir,
                creationflags=creationflags,
                env=child_env,
            )
        else:
            if os.path.exists(run_bat_path):
                terminal_cmd = ['bash', '-c', f'cd "{file_dir}" && ./run.bat "{os.path.basename(abs_file_path)}"']
            else:
                terminal_cmd = [python_executable, abs_file_path]
            proc = subprocess.Popen(terminal_cmd, cwd=file_dir, stdout=log_handle, stderr=subprocess.STDOUT, env=child_env)
        _register_async_pid(proc.pid)
        threading.Thread(target=_watch_async_process, args=(proc, log_handle, abs_file_path), daemon=True).start()
        # #region debug-point D:open-python-async-spawned
        _debug_report_open_file(
            "D",
            "userlib/tools.py:open_python_async:spawned",
            "[DEBUG] open_python_async spawned subprocess",
            {
                "abs_file_path": abs_file_path,
                "pid": getattr(proc, "pid", None),
                "log_path": log_path,
                "platform": platform.system(),
            },
        )
        # #endregion
        print(f"[DEBUG] 异步子进程 PID: {proc.pid}")
    except Exception as e:
        if 'log_handle' in locals() and log_handle:
            try:
                log_handle.close()
            except Exception:
                pass
        # #region debug-point E:open-python-async-exception
        _debug_report_open_file(
            "E",
            "userlib/tools.py:open_python_async:exception",
            "[DEBUG] open_python_async raised exception",
            {
                "file_path": file_path,
                "error": str(e),
            },
        )
        # #endregion
        print(f"异步启动Python脚本失败: {str(e)}")


def open_file(file_path):
    print('open_file被调用')
    try:
        # --- 核心修复：强制转为绝对路径 ---
        # 这样无论你在哪个目录下运行，都能准确锁定文件
        abs_file_path = os.path.abspath(file_path)

        if not os.path.exists(abs_file_path):
            print(f"错误：文件不存在 -> {abs_file_path}")
            # 如果绝对路径依然不存在，尝试拼接脚本所在目录（处理跨文件夹调用）
            script_dir = os.path.dirname(os.path.abspath(__file__))
            abs_file_path = os.path.join(script_dir, "..", file_path)  # 假设在上一级的test里
            abs_file_path = os.path.normpath(abs_file_path)

        file_extension = os.path.splitext(abs_file_path)[1].lower()
        # #region debug-point F:open-file-resolved
        _debug_report_open_file(
            "F",
            "userlib/tools.py:open_file:resolved",
            "[DEBUG] open_file resolved target path",
            {
                "input_path": file_path,
                "abs_file_path": abs_file_path,
                "exists": os.path.exists(abs_file_path),
                "file_extension": file_extension,
            },
        )
        # #endregion

        if file_extension == '.py':
            open_python_async(abs_file_path)
            return

        # 默认文件打开逻辑（针对 .xlsx 等其他文件）
        print(f"执行默认打开逻辑: {abs_file_path}")
        if sys.platform == 'win32':
            # 使用转换后的绝对路径 abs_file_path
            os.startfile(abs_file_path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', abs_file_path], check=True)
        else:
            subprocess.run(['xdg-open', abs_file_path], check=True)
        print(f"成功发起打开请求: {os.path.basename(abs_file_path)}")

    except Exception as e:
        print(f"打开文件失败: {str(e)}")

def auto_fit_columns(file_path, output_path=None, freeze_pane=None, not_fit_column=None, rev_type = None):
    """ 自动调整excel文件列宽, 可设置冻结窗格

     :param file_path: 源文件路径 - (字符串/Path对象)
     :param output_path: 输出文件路径 - (字符串/Path对象, 省略则覆盖自身)
     :param freeze_pane: 选择冻结窗格(如'B2'),可省略
     :param not_fit_column: 选择不需变化的列(如'A'),可省略，可传入列表
     :param rev_type: 数字参数 1 - 更改为not_fit_column为需变化的列，

    """
    wb = load_workbook(file_path)
    if not not_fit_column:
        rev_type = None

    for sheet in wb:
        if not freeze_pane:
            pass
        else:
            sheet.freeze_panes = freeze_pane
        for col in sheet.columns:
            if not_fit_column:
                if isinstance(not_fit_column,list):
                    pass
                else:
                    not_fit_column = [not_fit_column]
                if rev_type == 1:
                    if col[0].column_letter not in not_fit_column:
                        continue
                else:
                    if col[0].column_letter in not_fit_column:
                        continue
            max_length = 0
            column = col[0].column_letter  # 获取列字母（如A, B）
            try:
                # 首先将max_length初始化为表头长度（如果表头存在）
                header_length = len(str(col[0].value)) if col and col[0].value else 0
                max_length = header_length
                for cell in col:
                    # 然后遍历所有单元格，包括表头和数据单元格
                    cell_value = str(cell.value)
                    cell_length = len(cell_value)
                    if cell_length > max_length:
                        max_length = cell_length

                # 设置最小长度限制
                max_length = max(max_length, 8)  # 最短长度设为8
            except:
                pass

            # 设置列宽（一定的缓冲）
            adjusted_width = max_length * 1.2 + 2
            sheet.column_dimensions[column].width = adjusted_width
    output_path = file_path or output_path
    wb.save(output_path)

def format_excel_columns(file_path, styles_dict, sheet_names='all',
                         header=True, save_as=None):
    """
    使用字典格式格式化Excel工作表中的多列

    参数:
    file_path: Excel文件路径
    styles_dict: 字典格式的样式设置 {列字母(可为列表): 样式字典}
        样式字典可选参数:
        - 'bold': 是否加粗 (默认False)
        - 'center': 是否居中 (默认False)
        - 'font_color': 字体颜色 (十六进制格式，默认'000000'黑色)
        - 'bg_color': 背景填充颜色 (十六进制格式，默认无填充)
        - 'font_size': 字体大小 (默认11)
        - 'header_style': 表头特殊样式 (可选)
    sheet_names: 工作表名称列表或'all' (默认所有工作表)
    header: 是否应用表头格式 (默认True)
    save_as: 另存为文件名 (默认覆盖原文件)
    红色	FF0000
    绿色	00FF00
    蓝色	0000FF
    黄色	FFFF00
    浅蓝	00FFFF
    紫色	800080
    橙色	FF6600
    style_dict 示例：
    {'A':{'center':True}}
    {('A','B','C'):{'bold':True,'header_style':False}} #键仅可输入元组！
    """
    # 加载工作簿
    wb = load_workbook(file_path)

    # 确定目标工作表
    if sheet_names == 'all':
        target_sheets = wb.sheetnames
    elif isinstance(sheet_names, str):
        target_sheets = [sheet_names]
    else:
        target_sheets = sheet_names

    # 黑色样式默认值
    default_style = {
        'bold': False,
        'center': False,
        'font_color': '000000',  # 黑色
        'bg_color': None,
        'font_size': 11,
        'header_style': None
    }
    style_d = {}
    for k, v in styles_dict.items():
        if isinstance(k,tuple):
            for ele in k:
                style_d[ele] = v
        else:
            style_d[k] = v
    # 遍历所有目标工作表
    for sheet_name in target_sheets:
        if sheet_name not in wb.sheetnames:
            print(f"警告: 工作表 '{sheet_name}' 不存在，跳过")
            continue

        sheet = wb[sheet_name]

        # 处理表头
        if header and sheet.max_row > 0:
            for col_letter, style_spec in style_d.items():
                # 获取header_style的设置
                if 'header_style' in style_spec:
                    header_style = style_spec['header_style']
                    if header_style is None:
                        # 跳过该列的表头
                        continue
                else:
                    # 如果未提供header_style，则默认使用数据列样式
                    header_style = style_spec

                # 获取表头单元格 (第一行)
                header_cell = sheet[f"{col_letter}1"]

                # 应用表头样式
                font = Font(
                    bold=header_style.get('bold', True),
                    color=header_style.get('font_color', '000000'),
                    size=header_style.get('font_size', 11)
                )
                alignment = Alignment(
                    horizontal='center' if header_style.get('center', True) else 'general',
                    vertical='center'
                )

                header_cell.font = font
                header_cell.alignment = alignment

                if 'bg_color' in header_style:
                    header_cell.fill = PatternFill(
                        start_color=header_style['bg_color'],
                        end_color=header_style['bg_color'],
                        fill_type="solid"
                    )

        # 处理数据列
        for col_letter, style_spec in style_d.items():
            # 合并默认值和用户输入值
            style = {**default_style, **style_spec}

            # 跳过不在工作表中的列
            if col_letter not in [cell.column_letter for cell in sheet[1]]:
                print(f"警告: 列 '{col_letter}' 在工作表 '{sheet_name}' 中不存在，跳过")
                continue

            # 获取整列单元格 (从第2行开始如果是表头，否则从第1行)
            start_row = 2 if header and sheet.max_row > 1 else 1
            for row in range(start_row, sheet.max_row + 1):
                cell = sheet[f"{col_letter}{row}"]

                # 应用字体样式
                font = Font(
                    bold=style['bold'],
                    color=style['font_color'],
                    size=style['font_size']
                )
                cell.font = font

                # 应用对齐方式
                if style['center']:
                    cell.alignment = Alignment(horizontal='center', vertical='center')

                # 应用背景填充
                if style['bg_color']:
                    cell.fill = PatternFill(
                        start_color=style['bg_color'],
                        end_color=style['bg_color'],
                        fill_type="solid"
                    )

    # 保存工作簿
    output_file = save_as or file_path
    wb.save(output_file)
    print(f"成功格式化! 文件已保存: {os.path.abspath(output_file)}")
    return output_file

# if __name__ == '__main__':
#     df = pd.DataFrame({'A':[1,1,1,1,1],'B':['是2','11','22f','是','啊啊'],'C':['前期',112,32,22,331]})
#     fp = 'test/test.xlsx'
#     df.to_excel(fp)
#     open_file(fp)
#     check_with_retry(fp)
#     format_excel_columns(fp, {'A':{'bold':True, 'font_color':'FF0000','center':True,'header_style':None},
#                               'B':{'bold':True, 'font_color':'00FF00', 'header_style':None},
#                               'C':{'bold':True, 'font_color':'000000', 'center':True}})
#     open_file(fp)

# if __name__ == '__main__':
#     copy_file('test/test.xlsx','test/test2.xlsx')
#     copy_file('test/test.xlsx','test/test2.xlsx',1)
#     copy_file('test/test2.xlsx','test/test3.xlsx',1,1)

def modification_date(file_path):
    """
    获取文件的最近修改日期

    参数:
    file_path (str): 文件的完整路径

    返回:
    str: 文件的最近修改日期和时间
    """
    try:
        # 获取文件的修改时间戳
        mod_time = os.path.getmtime(file_path)

        # 将时间戳转换为可读格式
        formatted_time = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M:%S')

        return formatted_time
    except FileNotFoundError:
        return "错误：文件不存在"
    except Exception as e:
        return f"错误：{str(e)}"

def find_and_add_package_path(
        package_name: str,
        search_depth: int = 5,
        root_dir: Path = None
) -> bool:
    """
    在文件系统中搜索指定包并添加到 Python 路径

    :param package_name: 要搜索的包名称 (如 'lib')
    :param search_depth: 最大搜索深度 (默认5级)
    :param root_dir: 搜索起始目录 (默认当前目录)
    :return: 是否成功找到并添加包路径
    """
    # 设置起始搜索目录
    if root_dir is None:
        root_dir = Path(os.getcwd())

    # 检查是否已经存在该包
    try:
        __import__(package_name)
        print(f"{package_name} 已在 Python 路径中")
        return True
    except ImportError:
        pass

    # 准备包可能的标识文件名
    package_markers = [
        '__init__.py',
        '__init__.pyi',
        f'{package_name}.py'
    ]

    # 开始搜索
    found_paths = []
    print(f"正在搜索包: {package_name} ...")

    for depth in range(search_depth + 1):
        if depth == 0:
            search_dirs = [root_dir]
        else:
            # 生成搜索模式: 当前目录上溯几层目录
            up_parents = Path(os.path.join(*(['..'] * depth)))
            search_dirs = [
                (root_dir / up_parents).resolve(),
                (root_dir / up_parents / 'src').resolve(),
                (root_dir / up_parents / 'lib').resolve()
            ]

        for search_dir in search_dirs:
            # 检查目录存在性
            if not search_dir.exists() or not search_dir.is_dir():
                continue

            # 检查包目录是否存在
            package_dir = search_dir / package_name
            if package_dir.exists() and package_dir.is_dir():
                # 验证是有效Python包
                is_valid = any(
                    (package_dir / marker).exists()
                    for marker in package_markers
                )
                if is_valid:
                    found_paths.append(str(search_dir))
                    print(f"在 {search_dir} 发现包 {package_name}")

    # 添加到系统路径
    added = False
    for path in found_paths:
        if path not in sys.path:
            sys.path.insert(0, path)
            print(f"添加路径到 sys.path: {path}")
            added = True

    if added:
        # 重新尝试导入
        try:
            __import__(package_name)
            print(f"成功导入 {package_name}")
            return True
        except ImportError as e:
            print(f"导入失败: {str(e)}")

    if not found_paths:
        print(f"未能在搜索深度 {search_depth} 内找到 {package_name}")

    return added


# ==============================================================================
# 三、测试 / 示例   (仅直接运行本文件时生效，平时导入不执行)
# ==============================================================================

if __name__ == '__main__':
    # 既然 pandas 能读，我们把它的路径传进去
    target_file = 'test/test.xlsx'
    # pd.read_excel(target_file).info()
    open_file('update_tools.py')
    open_file(target_file)

"""if __name__ == '__main__':
    auto_fit_columns('test/test.xlsx','test/test.xlsx','A2', 'A')
    open_file('test/test.xlsx')
    auto_fit_columns('test/test.xlsx','test/test2.xlsx','C2',['C','B','D'])
    open_file('test/test2.xlsx')#"""

"""if __name__ == '__main__':
    ready = custom_dialog('询问','是否确认？','confirm')
    print(ready)#"""

"""
# 测试对话框
if __name__ == "__main__":
    fields = [
        {
            'label': '评奖年份',
            'default': '2024',
            'hint': '请输入2024-2026之间的年份',
            'validate': lambda v: validate_numeric(v, lower=2024, upper=2026, type_='int')
        },
        {
            'label': '算法版本',
            'default': '1',
            'hint': '请输入大于0且小于3的整数',
            'validate': lambda v: validate_numeric(v, lower=0, upper=3, type_='int')
        },

        {
            'label': '使用测试数据',
            'default': '',
            'hint': '输入任意字符表示使用测试数据，n/N表示不使用',
            'validate': validate_whatever
        }
    ]

    # 显示对话框
    results = custom_input_dialog('输入必需内容', fields)

    # 处理结果
    if results:
        year = results['评奖年份']
        algorithm = results['算法版本']
        test_data = results['使用测试数据']

        print(f"年份: {year}")
        print(f"算法: {algorithm}")
        print(f"使用测试数据: {test_data}")
        #"""

'''
if __name__ == "__main__":
    # 模拟文件状态（可以修改路径测试不同情况）
    os.makedirs("参评信息", exist_ok=True)
    open("参评信息/基本信息.txt", "w").close()  # 创建必需文件1
    open("参评信息/业绩材料.docx", "w").close()  # 创建必需文件2
    # 必需文件3缺失
    # 可选文件缺失
    required_files = {
        "参评信息/基本信息":'必须上传xlsx文件！',  # 必需文件1
        "参评信息/业绩材料":'必须上传pdf文件！',  # 必需文件2
        "参评信息/推荐信":'必须上传jpg文件！'  # 必需文件3
    }

    optional_files = {"参评信息/补充材":'随便怎么上'} # 可缺文件
    print(check_reqired_files(required_files, optional_files,'缺失不影响流程'))#'''

if __name__ == '__main__':
    target_package = "userlib"

    try:
        from userlib.tools import *

        print(f"{target_package} 已存在")
    except ImportError:
        print(f"尝试搜索并添加 {target_package}...")
        time.sleep(2)
        # 执行搜索
        found = find_and_add_package_path(
            package_name=target_package,
            search_depth=5,
            root_dir=Path(__file__).resolve().parent
        )

        if found:
            # 尝试使用导入
            exec(f"from {target_package}.tools import *")

            print("成功调用工具包函数")
        else:
            print("无法找到包，请检查目录结构")
            time.sleep(2)
            sys.exit(0)

"""if __name__ == '__main__':
    # 测试check_with_retry被占用场景
    test_file = 'test/test.xlsx'
    open_file(r'test\test.xlsx')
    time.sleep(2)
    delete_file(test_file)#"""
