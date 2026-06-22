# 金牛奖 MySQL 数据库部署指南

## 快速启动

```bash
# 1. 启动数据库（首次会自动建库建表）
docker-compose up -d

# 2. 验证
docker ps                                    # 确认容器运行
mysql -h 127.0.0.1 -P 3306 -u jinniu -p     # 密码: jinniu_pass

# 3. 查看所有数据库
SHOW DATABASES LIKE 'prifund_%';   -- 所有私募年份
SHOW DATABASES LIKE '%_2026';      -- 2026年所有奖项
```

## 数据库层级设计

MySQL 没有原生的"数据库组"，但通过命名规范实现等价的三级层级：

```
MySQL 实例 (jinniu_mysql:3306)
├── jinniu_meta          ← 注册表：索引所有年份/奖项
│   └── award_registry   ← 元数据表
│
├── prifund_2026         ← 私募金牛 2026（当前活跃）
│   ├── product
│   ├── nav_weekly
│   ├── scale
│   ├── manager
│   ├── term_judgement
│   └── evaluation_result
│
├── prifund_2025         ← 私募金牛 2025（已归档）
│   └── ...（同结构）
│
├── pubfund_2026         ← 公募金牛 2026
│   └── ...（自定义结构）
│
└── pubfund_2025         ← 公募金牛 2025
    └── ...
```

**分库不混年**：每个 `{奖项}_{年份}` 是独立数据库，表结构相同但数据完全隔离。
好处：
- 不会跨年污染数据
- 可以独立备份/恢复/删除某一年
- `DROP DATABASE prifund_2024` 一行清掉历史年份
- `mysqldump prifund_2026 > backup.sql` 单年备份

## Python 用法

```python
# pip install pymysql sqlalchemy --break-system-packages

from jinniu_db import get_engine, save_df, load_df, ensure_database

# 确保数据库存在（幂等，脚本开头调用一次）
engine = ensure_database('prifund', 2026, rules_date='20260610')

# 写入
save_df(product_df, 'product', 'prifund', 2026)
save_df(nav_df,     'nav_weekly', 'prifund', 2026)

# 读取
df = load_df('product', 'prifund', 2026, where="产品策略='股票策略'")

# 直接用 engine 做复杂查询
import pandas as pd
df = pd.read_sql('''
    SELECT p.产品名称, n.净值日期, n.累计净值
    FROM product p
    JOIN nav_weekly n ON p.产品编号 = n.产品编号
    WHERE p.产品策略 = '股票策略' AND n.年份 = 2025
    ORDER BY n.净值日期
''', engine)
```

## 与 prifund_config.py 集成

在 config 的 DEFAULT 中添加：

```python
DEFAULT = {
    # ... 现有配置 ...

    # ---- 数据库 ----
    'db_award_type': 'prifund',   # 奖项前缀
    # 连接参数走环境变量（见 jinniu_db.py），不硬编码密码
}
```

脚本中使用：
```python
from jinniu_db import ensure_database
engine = ensure_database(CFG.db_award_type, yr, rules_date='20260610')
```

## 管理命令

```bash
# 停止
docker-compose down

# 停止并清除数据（慎用）
docker-compose down -v

# 查看日志
docker-compose logs -f mysql

# 备份某年数据
docker exec jinniu_mysql mysqldump -u jinniu -pjinniu_pass prifund_2026 > prifund_2026_backup.sql

# 恢复
docker exec -i jinniu_mysql mysql -u jinniu -pjinniu_pass prifund_2026 < prifund_2026_backup.sql
```

## 环境变量（可选）

在 `.env` 文件中自定义：

```env
MYSQL_ROOT_PASSWORD=your_root_password
MYSQL_PASSWORD=your_user_password
JINNIU_DB_HOST=127.0.0.1
JINNIU_DB_PORT=3306
JINNIU_DB_USER=jinniu
JINNIU_DB_PASSWORD=your_user_password
```
