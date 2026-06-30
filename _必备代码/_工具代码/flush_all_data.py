import sys, os, time
from pathlib import Path

""" 冲洗工作区，后续重设‘出厂设置’ """

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
            exec(f"from {target_package}.tools import *")

            print("成功调用工具包函数")
        else:
            print("无法找到包，请检查目录结构")
            sys.exit(0)

tof = []


confirm = custom_dialog('警告','此操作无法挽回！将清除本工作区所有的输出数据,确认吗？','confirm',
                        '是的', '不敢')

if not confirm:
    print('用户不确定。')
    time.sleep(3)
    sys.exit(0)

info = pd.read_excel('资料/代码/工作区设置/文件结构.xlsx', sheet_name='工作区')

info = info.fillna('.')[info['步骤']!='.']
output = info[(info['子文件夹1'] == '输出文件') | (info['子文件夹2'] == '输出文件')].copy()

output_list = []

for idx, row in output.iterrows():
    step_underscore = f"step_{row['步骤']}_{row['工作区文件夹']}"
    step_space = f"step_{row['步骤']} {row['工作区文件夹']}"
    path_underscore = f"{step_underscore}/{row['子文件夹1']}/{row['子文件夹2']}/{row['子文件夹3']}/"
    path_space = f"{step_space}/{row['子文件夹1']}/{row['子文件夹2']}/{row['子文件夹3']}/"
    path = path_underscore if os.path.exists(path_underscore) else path_space
    output_list.append(path)
    

for path in output_list:
    tof.append(delete_file(path))

tof.append(delete_file('参评信息',1))

tof.append(delete_file('重要文件',1))

if not all(tof):
    tag_False = 1
else:
    tag_False = 0

if tag_False == 0:
    custom_dialog('提示', '已清除所有数据..', 'info')
else:
    custom_dialog('错误', '未能全部清除,请检查!', 'error')
