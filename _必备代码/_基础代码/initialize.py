import sys, time, os, warnings
from pathlib import Path
from collections import defaultdict
os.chdir(os.path.dirname(__file__))

def find_and_add_package_path(
        package_name: str,
        search_depth: int = 5,
        root_dir: Path = None
) -> bool:
    """
    在文件系统中搜索指定包并添加到 Python 路径

    :param package_name: 要搜索的包名称 (如 'banklib')
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
                (root_dir / up_parents / 'userlib').resolve()
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


if __name__ == '__main__':
    target_package = "userlib"

    try:
        from userlib.tools import *

        print(f"{target_package} 已存在")
    except ImportError:
        print(f"尝试搜索并添加 {target_package}...")
        # 执行搜索
        found = find_and_add_package_path(
            package_name=target_package,
            search_depth=5,
            root_dir=Path(__file__).resolve().parent
        )

        if found:
            # 尝试使用导入
            from userlib.tools import *

            print("成功调用工具包函数")
        else:
            print("无法找到包，请检查目录结构")
            sys.exit(0)

rel = find_rel(__file__, '_必备代码')
code_dirs = os.listdir('代码备份')
print(code_dirs)
code_dir = {int(d.split('v')[1]): d for d in code_dirs if '代码' in d}
ins_dir = {int(d.split('v')[1]): d for d in code_dirs if '说明' in d}

code = code_dir[max(code_dir)]
inst = ins_dir[max(ins_dir)]

info = pd.read_excel(f'代码备份/{code}/工作区设置/文件结构.xlsx', sheet_name='工作区')
title = info['工作区名'].unique()[0]

path_t = 'temp'

if custom_dialog('Configuration', f'即将生成{title}新工作区(基于{code}和{inst})，是否确定？', 'confirm', '是的', '不，选择别的'):
    pass
else:
    chose = custom_backup_selection_dialog('请选择代码和说明', '代码备份')
    if chose is None:
        print('已取消创建新工作区。')
        sys.exit(0)
    code = chose['code']
    inst = chose['instruction']

print(code)
print(inst)

info = pd.read_excel(f'代码备份/{code}/工作区设置/文件结构.xlsx', sheet_name='工作区').fillna('.')
step_numbers = pd.to_numeric(info['步骤'], errors='coerce')
info0 = info[step_numbers.eq(0)].copy()
step_separator = detect_workspace_step_separator(info, f'代码备份/{code}')
step0_dir = f'step_0{step_separator}前期准备'
print(f'工作区目录格式: {step0_dir}（根据 {code} 自动识别）')
print(info0[['工作区文件夹','代码/说明','相应代码和说明文件','保存在资料中的名称']].head())

make_dir(path_t)
make_dir(f'{path_t}/{step0_dir}')
make_dir(path_t + '/资料')
make_dir('已处理')

copy_file(f'代码备份/{code}', f'{path_t}/资料/代码')
copy_file(f'代码备份/{inst}', f'{path_t}/资料/说明')
make_dir(path_t + '/资料/代码/notebook')

# 更新工具/默认代码到新工作区—————————————————————————————————————————————————————————————————
tool_py = ['update_all_code.py', 'inherit.py', 'flush_all_data.py', 'reset_all_code.py']
backup_py = ['code_backup.py', 'readme_backup.py']

for py in os.listdir(rel+'_工具代码'):
    if py in tool_py:
        copy_file(f'{rel}_工具代码/{py}', f'{path_t}/资料/代码/更新代码/{py}', 1)
    else:
        if py in backup_py:
            if py == 'readme_backup.py':
                copy_file(f'{rel}_工具代码/{py}', f'{path_t}/资料/说明/{py}',1)
            else:
                copy_file(f'{rel}_工具代码/{py}', f'{path_t}/资料/代码/{py}',1)
for py in os.listdir(rel+'_默认代码'):
    if py == 'default_code.py':
        copy_file(f'{rel}_默认代码/{py}', f'{path_t}/资料/代码/{py}',1)
    elif py == 'default_notebook.ipynb':
        copy_file(f'{rel}_默认代码/{py}', f'{path_t}/资料/代码/notebook/{py}',1)
    else:
        copy_file(f'{rel}_默认代码/{py}', f'{path_t}/资料/说明/{py}',1)
# ————————————————————————————————————————————————————————————————————————————————————————————
def normalize_structure_part(value):
    value = str(value).strip()
    return '' if value in ('', '.', 'nan', 'None') else value


folder_columns = ['子文件夹1', '子文件夹2', '子文件夹3', '子文件夹4']
for i, row in info0.iterrows():
    destination_dir = os.path.join(
        path_t,
        step0_dir,
        *(part for part in (normalize_structure_part(row[column]) for column in folder_columns) if part),
    )
    destination_name = normalize_structure_part(row['相应代码和说明文件'])

    if not destination_name:
        make_dir(destination_dir)
        continue

    make_dir(destination_dir, 1)
    source_area = normalize_structure_part(row['代码/说明'])
    source_subdir = normalize_structure_part(row['代码子文件夹'])
    source_name = normalize_structure_part(row['保存在资料中的名称'])
    if not source_area or not source_name:
        print(f'文件结构第 {i} 行源文件配置不完整，跳过复制: {destination_name}')
        continue

    source_path = os.path.join(path_t, '资料', source_area)
    if source_subdir:
        source_path = os.path.join(source_path, source_subdir)
    copy_file(os.path.join(source_path, source_name), os.path.join(destination_dir, destination_name))

create_empty_file(f'{path_t}/to_be_deleted.txt')
inherit_source = f'代码备份/{code}/更新代码/inherit.py'
if not os.path.exists(inherit_source):
    inherit_source = f'代码备份/{code}/更新代码/test.py'
copy_file(inherit_source, f'{path_t}/inherit.py')

run('inherit.py', path_t+'/')

delete_file('temp', 1)
