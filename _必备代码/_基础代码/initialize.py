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
    fields = [
        {
            'label': 'codes', 'default': '', 'hint': f'存在 {list(code_dir.keys())} 的代码, 建议选择最新代码',
            'validate': lambda v: validate_numeric(v, lower=min(code_dir), upper=max(code_dir)+1, type_='int')
        },
        {
            'label': 'instructions', 'default': '', 'hint': f'存在 {list(ins_dir.keys())} 的说明, 建议选择最新说明',
            'validate': lambda v: validate_numeric(v, lower=min(ins_dir), upper=max(ins_dir)+1, type_='int')
        },
    ]
    chose = custom_input_dialog('请选择代码和说明', fields)
    code = code_dir[int(chose['codes'])]
    inst = ins_dir[int(chose['instructions'])]

print(code)
print(inst)

info = pd.read_excel(f'代码备份/{code}/工作区设置/文件结构.xlsx', sheet_name='工作区').fillna('.')
info0 = info[info['步骤'] == 0].copy()
print(info0[['工作区文件夹','代码/说明','相应代码和说明文件','保存在资料中的名称']].head())

make_dir(path_t)
make_dir(path_t + '/step_0_前期准备')
make_dir(path_t + '/资料')
make_dir(path_t + '/资料/代码/notebook')

copy_file(f'代码备份/{code}', f'{path_t}/资料/代码')
copy_file(f'代码备份/{inst}', f'{path_t}/资料/说明')

# 更新工具/默认代码到新工作区—————————————————————————————————————————————————————————————————
tool_py = ['update_all_code.py', 'test.py', 'flush_all_data.py', 'reset_all_code.py']
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
for i, row in info0.iterrows():
    copy_file(f'{path_t}/资料/{row["代码/说明"]}/{row["代码子文件夹"]}/{row["保存在资料中的名称"]}',
              f'{path_t}/step_{row["步骤"]}_{row["工作区文件夹"]}/{row["子文件夹1"]}/{row["子文件夹2"]}/{row["子文件夹3"]}/{row["子文件夹4"]}/{row["相应代码和说明文件"]}')

create_empty_file(f'{path_t}/to_be_deleted.txt')
copy_file(f'代码备份/{code}/更新代码/test.py', f'{path_t}/test.py')

run('test.py', path_t+'/')

delete_file('temp', 1)
