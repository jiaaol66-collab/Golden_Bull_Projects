import pandas as pd
import os, sys
os.chdir(os.path.dirname(__file__))

while True:
    raw = input("请输入评奖当年：").strip()
    try:
        YR = int(raw)
        if not 1000 <= YR <= 9999:
            raise ValueError
        break
    except ValueError:
        print("请输入有效的四位数评奖年份。")

while True:
    rge = input("请输入时间跨度(年)：").strip()
    try:
        rge = int(rge)
        if not 1 <= rge <= 7:
            raise ValueError
        break
    except ValueError:
        print("请输入有效的年份(目前只支持1-7年)。")

tag = 0 
for i in range(YR - rge, YR):
    if not os.path.exists(
        f'国债/{i}年中债国债收益率曲线标准期限信息.xlsx'):
        print(f'请补充{i}年度的国债数据!')
        tag = 1

if tag != 0:
    sys.exit(-1)

df_bonds = [pd.read_excel(
    f'国债/{i}年中债国债收益率曲线标准期限信息.xlsx') 
    for i in range(YR - rge, YR)]

df_bond = pd.concat(df_bonds)

# 如果不为7, 就标上范围
if rge == 7:
    appe = ''
else:
    appe = f'({YR - rge}~{YR})'

os.mkdir(f'{YR}')

with pd.ExcelWriter(f'{YR}/国债分年期数据{appe}.xlsx') as writer:
    for term in df_bond['标准期限说明'].unique():
        df_bond[df_bond['标准期限说明'] == term].sort_values(by=['日期']).to_excel(writer, sheet_name = term, index=False)