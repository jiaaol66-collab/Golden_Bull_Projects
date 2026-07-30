# Workspace blueprint

Inspect the live `setup.py` before relying on this reference. The current
project convention uses one `工作区` sheet with these columns:

1. `工作区名`
2. `步骤`
3. `工作区文件夹`
4. `子文件夹1`
5. `子文件夹2`
6. `子文件夹3`
7. `子文件夹4`
8. `运行顺序`
9. `相应代码和说明文件`
10. `代码/说明`
11. `代码子文件夹`
12. `保存在资料中的名称`
13. `备注`
14. `index`
15. `其他`
16. `输出文件`
17. `对应代码`
18. `只运行一次`

## Row roles

- Use `步骤='.'` for workspace-root/shared directories and root utilities.
- Use numeric `步骤` for `step_<步骤>_<工作区文件夹>`.
- Use `运行顺序` only for executable entry points.
- Use `相应代码和说明文件` for the deployed filename.
- Use `代码/说明`, `代码子文件夹`, and `保存在资料中的名称`
  together to resolve the source under `资料`.
- Use directory-only rows when no file should be deployed.
- Use `备注` only according to the current setup filter. In the current
  setup implementation, nonblank remarks can suppress a row.

## Minimal shared structure

Create only what the new award needs. Typical candidates are:

- `参评信息`
- `重要文件/提取数据`
- `重要文件/清洗数据`
- `重要文件/计算结果`
- `重要文件/异常记录`
- `重要文件/评分配置`

These are not mandatory. Remove unused folders when the caller's workflow does
not consume them.

## Deployment mapping

For each executable step, keep:

- one source Python file under `资料/代码`;
- one deployed Python file under its step directory;
- one source DOCX instruction under `资料/说明` or the live convention;
- one deployed DOCX instruction in the step directory;
- `run.bat`;
- `flush_buffer.py` when the live `default_code.py` calls it.

Source and deployed Python files must be byte-identical immediately after
setup and after any manual update.

## Workbook checks

Before setup:

- sheet name is exactly what setup reads;
- all required headers exist and are unique;
- numeric steps are contiguous only when the caller requires that;
- run order matches the requested execution sequence;
- deployed destinations are unique;
- every named source file exists or has an intentional default fallback;
- no extra processing step was inherited from a reference award.

After setup:

- compare actual step folders with the written contract;
- inspect every deployed filename;
- verify directory-only rows created the intended folders;
- re-run setup to confirm it does not overwrite reviewed files.
