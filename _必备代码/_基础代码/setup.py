import sys, os, time, json
from pathlib import Path

os.chdir(os.path.dirname(__file__))
"""工作区 step_0 前期准备入口。"""

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


rel = '../参评信息/'
make_dir(rel, 1)
start = insert_bookmark(__file__, 0, rel)
org = find_rel(__file__, '原始数据集')
mtr = find_rel(__file__, '资料')


""" 建立工作区文件夹 """
info = pd.read_excel(f'{mtr}代码/工作区设置/文件结构.xlsx',sheet_name='工作区')
info = info[info['备注'].isna()].fillna('.')

subdir = info.drop_duplicates(subset=['工作区文件夹','子文件夹1','子文件夹2','子文件夹3','子文件夹4'])[
    ['步骤', '工作区文件夹', '子文件夹1', '子文件夹2', '子文件夹3', '子文件夹4']].copy()

print(f'创建工作区文件夹.. {datetime.now()}'.center(80,'-'))
for idx, row in subdir.iterrows():
    base_dir = 'step_' + str(row['步骤']) + '_' +row['工作区文件夹'] if row['步骤'] != '.' else row['工作区文件夹']
    sub_dir1 = row['子文件夹1']
    sub_dir2 = row['子文件夹2']
    sub_dir3 = row['子文件夹3']
    sub_dir4 = row['子文件夹4']
    make_dir(f'../{base_dir}/{sub_dir1}/{sub_dir2}/{sub_dir3}/{sub_dir4}',1)

impt = find_rel(__file__, '重要文件')
tag_year = 0
now = datetime.now()
upper_year = now.year + 1


"""—————————————————————————— 自定义代码块 ——————————————————————————————"""

if not os.path.exists(f'{rel}年份信息.txt'):

    """ 自定义field """
    field = [
            {
                'label': '评奖年份',
                'default': f'{now.year}',
                'hint': f'请输入2024-{upper_year}之间的年份(包括2024)',
                'validate': lambda v: validate_numeric(v, lower=2024, upper=upper_year, type_='int')
            },

            # {
            #     'label': '是否全量数据',
            #     'default': '',
            #     'hint': '只能输入0或者1，0代表机构筛选，1代表全量',
            #     'validate': lambda v: validate_numeric(v, lower=0, upper=2, type_='int')
            # }
        ]

    result = custom_input_dialog('请输入新工作区的必需内容', field)
    tag_year = 1
    yr = int(result['评奖年份'])

    with open(f'{rel}年份信息.txt', 'w', encoding='utf-8') as f:
        f.write(f'{yr}')


    print('评奖年份:', yr)
    make_dir(f'{org}/{yr}', 1)
    make_dir(f'{org}/{yr + 1}', 1)

    """↓ 自定义代码块，目的是与原始数据集产生连接，在此可以自定义操作 ↓"""
    # 检查原始数据的存在性
    if not os.listdir(f'{org}/{yr}/') or f'{yr}' not in os.listdir(org):
        do = custom_dialog(f'No file exists in {yr}!',
                           '没有指定年份的原始数据，建议重启工作区！\n打开工作区后运行inherit.py',
                           'info', '好的')
    else:
        do = False

    if do:
        create_empty_file('../to_be_deleted.txt')
        copy_file(f'{mtr}/代码/更新代码/inherit.py', '../inherit.py')
        copy_file(f'{mtr}/代码/run.bat', '../run.bat')
        copy_file(f'{mtr}/代码/更新代码/update_all_code.py', '../update_all_code.py')
        if custom_dialog('Confirm to proceed', '直接重启本工作区吗?', 'confirm', '是的', '否的'):
            run('inherit.py', '../.')
        sys.exit(0)
    if not os.path.exists(f'{rel}是否采用机构数据.txt'):
        # 是否采用测试数据修改
        with open(f'{rel}是否采用机构数据.txt', 'w', encoding='utf-8') as f:
            # confirm = result['是否全量数据']
            # if confirm == '0':
            #     f.write('\n是')
            #     print()
            # else:
            #     f.write('\n否')
            #     test = ''
            f.write('\n')
    else:
        test = ''

    # files = os.listdir(f'{org}/{yr}')
    # print(files)
    # for file in files:
    #     if '私募参评数据' in file:
    #         break  # 可优化

    # copy_file(f'{org}/{yr}/{file}',  # 修改
    #           f'{impt}原始数据集/私募参评数据.xlsx')
    # copy_file(f'{org}/{yr}/trade_days.xlsx',
    #           f'{impt}其他文件/trade_days.xlsx')
    # copy_file(f'{org}/{yr}/私募金牛奖计算结果反馈模板{yr}.xlsx',
    #           f'{impt}其他文件/私募金牛奖计算结果反馈模板.xlsx')

    # if yr == 2025:
    #     # copy_file(f'{org}/2025/机构信息.xlsx',
    #     #           f'{impt}原始数据集/机构信息.xlsx')
    #     copy_file(f'{org}/2025/指数周度回报.xlsx',
    #               f'{impt}其他文件/指数周度回报.xlsx')
    #     copy_file(f'{org}/2025/指数月度回报.xlsx',
    #               f'{impt}其他文件/指数月度回报.xlsx')
    #     copy_file(f'{org}/2025/指数周度年度收益率.xlsx',
    #               f'{impt}其他文件/指数周度年度收益率.xlsx')
    #     copy_file(f'{org}/2025/指数月度年度收益率.xlsx',
    #               f'{impt}其他文件/指数月度年度收益率.xlsx')

    # if os.path.exists(f'{mtr}{yr}私募金牛奖结果.xlsx'):
    #     copy_file(f'{mtr}{yr}私募金牛奖结果.xlsx',
    #               f'{impt}/其他文件/{yr}私募金牛奖结果.xlsx')
else:
    yr = get_year(rel)

# if not os.path.exists(f'../../数据库/{yr}'):
#     source_excel = ''
#     try:
#         files = os.listdir(f'{org}/{yr}')
#         for file in files:
#             if '私募参评数据' in file and file.lower().endswith(('.xlsx', '.xls')):
#                 source_excel = os.path.abspath(os.path.join(org, str(yr), file))
#                 break
#     except Exception:
#         source_excel = ''
#
#     request = {
#         'yr': int(yr),
#         'source_excel': source_excel,
#         'workspace_root': os.path.abspath(os.path.join(os.path.dirname(__file__), '..')),
#         'created_at': datetime.now().isoformat(timespec='seconds')
#     }
#     try:
#         with open(f'{org}ingestion_request.json', 'w', encoding='utf-8') as f:
#             json.dump(request, f, ensure_ascii=False, indent=2)
#     except Exception:
#         pass
#     run('data_ingestion.py', os.path.normpath('../../'))
# 无需清除缓冲区的步骤, 默认为'.'
step_folders = ['.', '净值对齐', '净值填充', '年期判定', '计算']

"""—————————————————————————— 自定义代码块 ——————————————————————————————"""

# print(f'正在下载机构信息.. {datetime.now()}'.center(80, '-'))
# xls = pd.ExcelFile(f'{impt}原始数据集/私募参评数据.xlsx')
# inst = pd.read_excel(xls, sheet_name='机构信息', dtype={'机构编号':str})
# inst = inst.sort_values(by='机构编号').reset_index(drop=True)
# inst['机构名称'] = inst['机构名称'].str.strip()
# inst.to_excel(f'{impt}原始数据集/机构信息.xlsx',index=False)

""" 部署代码 """
print()
print(f'正在部署代码.. {datetime.now()}'.center(80,'-'))
code = info[info['保存在资料中的名称']!='.'][['步骤', '工作区文件夹','子文件夹1', '子文件夹2', '相应代码和说明文件', '代码/说明',
                                              '代码子文件夹','保存在资料中的名称']].copy()

code = code.fillna('.')
for idx, row in code.iterrows():
    step = 'step_' + str(row['步骤']) + '_' + row['工作区文件夹'] if row['步骤'] != '.' else '.'
    dst_name = row['相应代码和说明文件']
    sav_name = row['保存在资料中的名称']
    sub_dir1 = row['子文件夹1']
    sub_dir2 = row['子文件夹2']
    sub_code = row['代码子文件夹']
    code_istr = row['代码/说明']

    tof = copy_file(f'{mtr}{code_istr}/{sub_code}/{sav_name}', f'../{step}/{sub_dir1}/{sub_dir2}/{dst_name}', 0, 0, 1)
    if not tof:
        if code_istr == '代码':
            if sub_code == 'notebook':
                copy_file(f'{mtr}{code_istr}/{sub_code}/default_notebook.ipynb', f'../{step}/{sub_dir1}/{sub_dir2}/{dst_name}')
            else:
                copy_file(f'{mtr}{code_istr}/default_code.py', f'../{step}/{sub_dir1}/{sub_dir2}/{dst_name}')
        elif code_istr == '说明':
            copy_file(f'{mtr}{code_istr}/readme.docx', f'../{step}/{sub_dir1}/{sub_dir2}/{dst_name}')
        else:
            pass

    copy_file(f'{mtr}代码/run.bat', f'../{step}/{sub_dir1}/{sub_dir2}/run.bat', 0, 1)
    # if row['工作区文件夹'] not in step_folders and not (row['工作区文件夹'] == '前期准备' and row['子文件夹1']=='.'):
    #     copy_file(f'{mtr}代码/flush_buffer.py', f'../{step}/{sub_dir1}/{sub_dir2}/flush_buffer.py', 0, 1)

print()
insert_bookmark(__file__, 1, rel, start)
