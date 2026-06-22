from tools import copy_file

projects = {'私募金牛奖步骤': 'userlib',
            '券商资管金牛奖步骤': 'userlib',
            '银行理财金牛奖步骤': 'userlib',
            '分析师金牛奖客观评价步骤': 'userlib',
            '公募金牛奖步骤': 'userlib'}

for k, v in projects.items():
    copy_file('fillna_func.py',f'../{k}/{v}/fillna_func.py', 1)
    copy_file('tools.py', f'../{k}/{v}/tools.py',1)

input('输入任何字符继续..')