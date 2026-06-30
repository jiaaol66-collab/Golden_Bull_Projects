import sys, os, time
from pathlib import Path

os.chdir(os.path.dirname(__file__))
""" 私募金牛奖全流程的自动化运行脚本 """
print(sys.executable)
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


rel = '参评信息/'
make_dir(rel, 1)

processed = find_rel(__file__, '已处理')
mtr = find_rel(__file__, '资料')

start = datetime.now()
with open(f'{rel}时间记录.txt','a',encoding='utf-8') as f:
    f.write('\n'+'~~**~~'*10+'\n')
    f.write(f'\n运行脚本--开始时间:<<{start}>>\n')

start_time = time.time()

if not (os.path.exists('参评信息/年份信息.txt') and (os.path.exists('参评信息/是否采用机构数据.txt'))):  # 判断是否存在年份指示文件
    tag = '0'
else:
    tag = '1'


tof = []
tag_initialize = 0
if tag == '0':
    tof.append(run('运行此文件.py', 'step_0_前期准备'))
    tag_initialize = 1
    start_time1 = time.time()
impt = find_rel(__file__, '重要文件')
if tag_initialize == 0: pass
else: start_time = start_time1

yr = get_year(rel)

info = pd.read_excel('资料/代码/工作区设置/文件结构.xlsx',sheet_name='工作区')
title = info['工作区名'].unique()[0]
info = info.fillna('.')
info = info[info['运行顺序']!='.']
info['运行顺序'] = info['运行顺序'].astype(int)
code = info[info['运行顺序']>=1].sort_values('运行顺序').reset_index(drop=True)

# print('脚本的运行路径')
# print(__file__)
# print('脚本运行时的环境变量')
# print(sys.path)
""" ------------------------------- 自定义代码块 --------------------------------"""
if tag_initialize != 1: # 如果初始化已完成，则提示进行测试集全量数据的切换
    run('switch_type.py')

with open(f'{rel}是否采用机构数据.txt', 'r', encoding = 'utf-8') as f: ins = f.readlines()[-1]
if ins == '否': tag_ins = 0
else: tag_ins = 1

print(code[['步骤', '工作区文件夹', '运行顺序', '相应代码和说明文件']].head(50))

tag_goto = False
custom_start = custom_dialog(f'{title}全步骤脚本', '是否自定义起始步骤?', 'confirm', '是', '否')
start_from_order = 1

if custom_start:
    fields = [
        {
            'label': '起始运行顺序',
            'default': '1',
            'hint': f'请输入脚本开始运行的顺序编号 (1-{code["运行顺序"].max()})',
            'validate': lambda v: validate_numeric(v, lower=1, upper=code["运行顺序"].max() + 1, type_='int')
        }
    ]
    res = custom_input_dialog('起始步骤设置', fields)
    if res:
        start_from_order = int(res['起始运行顺序'])
    else:
        custom_start = False # 用户取消

if not custom_start:
    if tag_ins == 0:                                   # 修改
        tag_goto = custom_dialog(f'{title}全步骤脚本', '可选择从净值填充步骤(第6步, 预计省时1h30min)开始',
                                 'confirm', '是的, 直接从第5步开始', '不, 我想从头开始')
""" 自定义代码块 """
# if tag_ins == 0 and tag_goto:
#     copy_file(f'{processed}{yr}/净值数据_已整合.csv', f'{impt}全量数据/净值数据_已整合.csv')
#     copy_file(f'{processed}{yr}/产品信息已样本处理版(适用规模).xlsx', f'{impt}全量数据/输出文件/产品信息已样本处理版(适用规模).xlsx')
#     copy_file(f'{processed}{yr}/产品信息已样本处理版.xlsx', f'{impt}全量数据/输出文件/产品信息已样本处理版.xlsx')
#     copy_file(f'{processed}{yr}/产品信息终版.xlsx', f'{impt}全量数据/输出文件/产品信息终版.xlsx')
#     copy_file(f'{processed}{yr}/基金经理_产品信息(股票).xlsx', f'{impt}全量数据/输出文件/基金经理_产品信息(股票).xlsx')
#     copy_file(f'{processed}{yr}/基金经理_产品信息(股票)_全样本.xlsx', f'{impt}全量数据/输出文件/基金经理_产品信息(股票)_全样本.xlsx')
#     copy_file(f'{processed}{yr}/平均规模已样本处理版.xlsx', f'{impt}全量数据/输出文件/平均规模已样本处理版.xlsx')
#     copy_file(f'{processed}{yr}/平均规模.xlsx', f'{impt}全量数据/输出文件/平均规模.xlsx')
#     copy_file(f'{processed}{yr}/经理规模已样本处理版.xlsx', f'{impt}全量数据/输出文件/经理规模已样本处理版.xlsx')
#     copy_file(f'{processed}{yr}/经理规模.xlsx', f'{impt}全量数据/输出文件/经理规模.xlsx')
#     copy_file(f'{processed}{yr}/净值可视化/1_初始净值/全量数据', 'step_0_5 初步清洗可视化/输出文件/全量数据',1)
#     copy_file(f'{processed}{yr}/净值可视化/2_净值对齐/全量数据', 'step_1_5 净值对齐可视化/输出文件/全量数据',1)

""" 自定义代码块 """

for idx, row in code.iterrows():
    """ 自定义跳过步骤 """
    step_order = int(row['运行顺序'])
    if custom_start:
        if step_order < start_from_order:
            continue
    else:
        step = idx + 1
        if step == 1:
            if ins == '否': continue
            else:
                if os.path.exists(f'{impt}机构筛选数据'):  continue#"""

        if tag_goto:
            if tag_ins == 0 and yr == 2025:
                if step in [1, 2, 3, 4, 5]:
                    continue

    num = int(row['步骤']) if isinstance(row['步骤'], int) else row['步骤']
    if row['工作区文件夹'] == '可视化':
        open_file(f'step_{int(num)+1}_信息汇总/1_信息汇总.py')
        open_file(f'step_{int(num)+1}_信息汇总/2_净值汇总.py')
    """ 自定义跳过、加入运行代码 """

    start = time.time()
    beh = run(row['相应代码和说明文件'],
              os.path.normpath(f"step_{row['步骤']}_{row['工作区文件夹']}/{row['子文件夹1']}/{row['子文件夹2']}"))

    tof.append(beh)
    end = time.time()
    print()
    path = f"step_{row['步骤']}_{row['工作区文件夹']}/{row['子文件夹1']}/{row['子文件夹2']}/{row['相应代码和说明文件']}"
    path = os.path.normpath(path)
    print(f"{path}用时{round(end - start, 3)}秒".center(80, '-'))
    if not beh:
        custom_dialog('错误!', row['相应代码和说明文件'] + "出错了！", 'error', 'ok')
        break
    print()

end = datetime.now()
end_time = time.time()
print('\n\n')
due_time = end_time - start_time
with open(f'{rel}时间记录.txt', 'a', encoding='utf-8') as f:
    f.write(f'\n\n 脚本结束时间:<<{end}>>\n')
    f.write(f'\n总共用时{round(due_time,3)}秒\n')
    f.write('~~**~~'*10)


if all(tof):
    custom_dialog('完成！',f'已成功完成{title}脚本的运行!用时{due_time//3600}小时,{round((due_time % 3600)/60.0,3)}分钟',
              'info')
    run('update_all_code.py')
else:
    custom_dialog('中途出现错误',f'{title}脚本中途出现错误, 请检查。用时{due_time//60.0}分钟，{round((due_time % 60)/60.0,3)}秒',
                  'error')