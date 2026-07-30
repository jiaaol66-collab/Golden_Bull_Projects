import sys, os, time
from pathlib import Path
from collections import defaultdict

os.chdir(os.path.dirname(__file__))
""" 将资料\代码中的代码or说明文件<<替换>>工作区部署的代码or说明文件(谨慎) """

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


tag_False = 0
def rev_copy_file(dst, src, replace=0):       # 从源路径（dst)复制一个文件到目标路径(src)，
    global tag_False
    update = 0
    if not os.path.exists(src):
        print(f'源文件{src}不存在！无法复制。')
        tag_False = 1
        return False
    else:
        if replace == 1:  # 当replace = 1时，如果文件已存在则进行替换(多为输出的文件)，其中代码和说明文件不进行替换。(除了更新文件)
            if os.path.exists(dst):
                update = 1
                os.remove(dst)
        if not os.path.exists(dst):
            shutil.copyfile(src, dst)
            if replace == 1:
                if update == 1:
                    print(f'已更新{src} ---> {dst}')
                else:
                    print(f'已复制{src} ---> {dst}')
            else:
                print(f'已复制{src} ---> {dst}')
        else:
            print(f'{dst}已有文件，不进行复制')
        return True


if os.path.exists('inherit.py'):
    if not os.path.exists('参评信息/保存修改信息.txt'):
        ready = custom_dialog('Confirm',
                              '即将把保存的资料/代码更新到工作的步骤文件夹内，确认吗？(此操作仅能通过查询备份文件挽回!)',
                              'confirm')
    else:
        with open('参评信息/保存修改信息.txt', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        lines = [l[:2] for l in lines if l != '\n']
        print(lines)
        position_dict = defaultdict(list)
        for idx, item in enumerate(lines):
            position_dict[item].append(idx)

        save = position_dict['保存']
        update = position_dict['更新']

        if update and update[-1] == len(lines) - 1:
            ready = custom_dialog('Confirm',
                                  '在更新代码后未进行保存, 确定要再次更新代码吗？(未保存的已修改代码无法保留!)',
                                  'confirm','是的, 确定更新', '不, 我稍后进行保存')
        else:
            ready = custom_dialog('Confirm',
                                  '即将把保存的资料/代码更新到工作的步骤文件夹内，确认吗？(此操作仅可通过查询备份文件挽回!)',
                                  'confirm', '是的', '我再想想')

else:
    custom_dialog('Error', '请至少保存一次工作区的代码(运行update_all_code.py)再进行此操作！','error')
    ready = False

make_dir('参评信息', 1)
if not ready:
    print('用户不确定')
    exit_(3)
else:
    with open('参评信息/保存修改信息.txt', 'a', encoding='utf-8') as f:
        f.write(f'\n更新代码_时间：<<{datetime.now()}>>')

info = pd.read_excel('资料/代码/工作区设置/文件结构.xlsx',sheet_name='工作区')

print('\n')

info = info.fillna('.')
code = info[info['保存在资料中的名称']!='.'][['步骤', '工作区文件夹', '子文件夹1', '子文件夹2', '相应代码和说明文件', '代码/说明', '代码子文件夹', '保存在资料中的名称']].copy()
default = {'代码':'default_code.py', '说明':'readme.docx'}
for idx, row in code.iterrows():
    dst_name = row['相应代码和说明文件']
    sub_dir1 = row['子文件夹1']
    sub_dir2 = row['子文件夹2']
    sav_name = row['保存在资料中的名称']
    sub_code = row['代码子文件夹']
    code_istr = row['代码/说明']
    step_underscore = 'step_' + str(row['步骤']) + '_' + row['工作区文件夹'] if row['步骤'] != '.' else '.'
    step_space = 'step_' + str(row['步骤']) + ' ' + row['工作区文件夹'] if row['步骤'] != '.' else '.'
    dst_path_underscore = f'{step_underscore}/{sub_dir1}/{sub_dir2}/{dst_name}'
    dst_path_space = f'{step_space}/{sub_dir1}/{sub_dir2}/{dst_name}'
    dst_dir_underscore = os.path.dirname(dst_path_underscore)
    dst_path = dst_path_underscore if os.path.exists(dst_dir_underscore) else dst_path_space

    copied = rev_copy_file(dst_path, f'资料/{code_istr}/{sub_code}/{sav_name}', 1)
    if not copied:
        default_code = default[code_istr]
        rev_copy_file(dst_path, f'资料/{code_istr}/{sub_code}/{default_code}', 1)
        

with open('参评信息/保存修改信息.txt', 'a', encoding='utf-8') as f:
    if tag_False == 1:
        custom_dialog('错误','有个别未能更新,请检查文件存在性','error')
        f.write(f'     ❌有部分代码未成功更新..\n')
    else:
        custom_dialog('提示','已全部更新','info')
        f.write(f'     成功更新全部代码..\n')
