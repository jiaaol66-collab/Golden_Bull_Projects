import sys, os, time, warnings
from pathlib import Path

os.chdir(os.path.dirname(__file__))
""" 将母工作区的代码和说明继承至新工作区，自此所做的修改在两个区域中互不干涉 """

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
        exec(f"from {target_package}.tools import *")

        print("成功调用工具包函数")
    else:
        print("无法找到包，请检查目录结构")
        sys.exit(0)

if 'to_be_deleted.txt' not in os.listdir(get_path(1,__file__)['n']):
    run('update_all_code.py')

if os.path.exists('参评信息/年份信息.txt'):
    with open(f'参评信息/年份信息.txt', 'r') as f:
        yr = int(f.readlines()[0])
else:
    yr = datetime.now().year

now = datetime.now().strftime('%Y%m%d')[2:]

info = pd.read_excel('资料/代码/工作区设置/文件结构.xlsx', sheet_name='工作区')
title = info['工作区名'].unique()[0]

for j in range(0, 10):
    path_t = os.path.join('..', f'{title}_test_{j}')
    if os.path.exists(path_t):
        continue
    else:
        break

make_dir(path_t, 1)
copy_file('step_0 前期准备', path_t + r'/step_0 前期准备')

"""—————————————————————————— 自定义keep_files ——————————————————————————————"""
delete_except(path_t + '/step_0 前期准备', ['运行此文件.py'])
copy_file('资料', path_t + r'/资料')

run('运行此文件.py', path_t+'/step_0 前期准备/')

if os.path.exists(path_t + '/参评信息/年份信息.txt'):
    with open(path_t + '/参评信息/年份信息.txt', 'r') as f:
        yr = int(f.readlines()[0])
else:
    yr = '未指定年份' # 防止出错

""" 自定义新增参数 """

path_t_orig = path_t

if 'to_be_deleted.txt' in os.listdir(path_t_orig):
    delete_file(path_t_orig,1)
else:
    for j in range(10):
        """—————————————————————————— 自定义rename工作区名 ——————————————————————————————"""
        path_t = get_path(1, path_t_orig)['n'] + f'{yr}{title}_{now}_{j}'
        if os.path.exists(path_t):
            continue
        else:
            break
    os.rename(path_t_orig, path_t)
    print(f'{path_t_orig}已更名为{path_t}')

# open_file(path_t)

# con = custom_dialog('确认',f'是否直接开始运行{title}脚本?','confirm','是',
#                     '否')
# if con: run(f'[script]{title}脚本.py', path_t)

