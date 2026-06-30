# Style Guide

这个文件用于快速说明 `terminal.py`、`workspace_ui.py`、`pipeline_gantt.py` 和 `style_config.py` 的样式分工。

原则:
- 改颜色、圆角、尺寸、按钮模板: 优先改 `style_config.py`
- 改主界面布局结构、组件组合、显示逻辑: 优先改 `workspace_ui.py`
- 改挂载、调度、进程、刷新入口: 改 `terminal.py`
- 改流水线页结构: 改 `pipeline_gantt.py`
- 先看区域注释，再改参数，尽量不要直接在业务模块里重新写样式数字

## 文件分工

`style_config.py`
- 统一管理主题入口
- 统一管理颜色常量
- 统一管理尺寸常量
- 统一管理按钮、卡片、Tab、滚动区、输入框等样式 helper

`workspace_ui.py`
- 负责主界面三栏、底部控制台、说明区、代码文件夹页、右侧看板/数据库区的布局与渲染
- 在关键区域旁边保留了样式来源注释，统一调用 `style_config.py`

`pipeline_gantt.py`
- 负责“流水线”页的时间记录解析与甘特图渲染
- 条带颜色、卡片样式、按钮样式同样统一调用 `style_config.py`

`terminal.py`
- 负责挂载、调度、进程控制、刷新入口和异常处理
- 尽量不再承载大块 UI 渲染代码

## 改左侧边栏

想改这些:
- 边栏背景色
- 奖项下拉框、工作区下拉框
- 挂载按钮、编辑机构名单按钮
- 边栏收起/展开按钮

优先看:
- `SIDEBAR_BG`
- `option_menu_style()`
- `button_primary_style()`
- `button_secondary_style()`
- `WIDTH_SIDEBAR_*`

代码入口:
- `terminal.py` 的 `setup_layout()`

## 改主标签页和三栏外壳

想改这些:
- 主标签页外观
- 左中右三栏白色外层面板
- 底部控制台外壳

优先看:
- `tabview_style()`
- `outer_panel_style()`
- `RADIUS_OUTER`
- `WIDTH_MIDDLE_PANEL`
- `WIDTH_LEFT_PANEL_MIN`
- `WIDTH_LEFT_PANEL_MAX`

代码入口:
- `terminal.py` 的 `setup_layout()`
- `workspace_ui.py` 的 `build_tab_ui()`

## 改底部控制台

想改这些:
- 控制台拖拽条
- 实时运行简报区
- 日志文本框
- 控制台默认高度

优先看:
- `HEIGHT_SASH`
- `HEIGHT_LOG_BOX`
- `HEIGHT_LOG_BUTTON`
- `CONSOLE_*`
- `input_box_style()`
- `button_secondary_style()`

代码入口:
- `workspace_ui.py` 的 `build_tab_ui()`
- `terminal.py` 的 `get_default_console_height()`
- `terminal.py` 的 `apply_console_height()`

## 改左侧步骤栏

想改这些:
- “步骤代码 / 代码文件夹” tab
- 全选、全不选、一键运行、暂停按钮
- 步骤复选框
- 左侧提示文案宽度

优先看:
- `tabview_style()`
- `button_primary_style()`
- `button_soft_style()`
- `button_success_style()`
- `button_danger_style()`
- `checkbox_style()`
- `WRAP_LEFT_HINT`
- `WIDTH_SELECT_TOGGLE_BUTTON`

代码入口:
- `workspace_ui.py` 的 `render_tab_content()`
- `workspace_ui.py` 的 `render_step_code_tab()`

## 改代码文件夹页

想改这些:
- 参评信息卡片
- 工具代码卡片
- 步骤文件夹卡片
- 文件按钮
- 错误文件夹高亮

优先看:
- `panel_card_style()`
- `surface_card_style()`
- `button_primary_style()`
- `ERROR_SURFACE`
- `ERROR_ITEM_BG`
- `ERROR_ITEM_HOVER`
- `ERROR_BORDER_WIDTH`
- `WRAP_ROOT_CARD`
- `WRAP_FOLDER_CARD`

代码入口:
- `workspace_ui.py` 的 `render_code_folder_tab()`
- `workspace_ui.py` 的 `get_root_tool_button_meta()`

## 改说明文档区

想改这些:
- 步骤说明卡片
- 单个说明文件行
- 打开说明按钮
- 缺失提示

优先看:
- `panel_card_style()`
- `surface_card_style()`
- `button_primary_style()`
- `button_secondary_style()`
- `WRAP_DOC_ITEM`
- `WRAP_DOC_EMPTY`

代码入口:
- `workspace_ui.py` 的 `render_doc_panel()`

## 改输出文件看板

想改这些:
- 输出文件/数据库切换器
- 输出筛选分段按钮
- 输出代码下拉框
- 观察文件夹卡片
- 输出文件夹卡片和分组卡片

优先看:
- `segmented_button_style()`
- `option_menu_style()`
- `panel_card_style()`
- `surface_card_style()`
- `button_primary_style()`
- `button_secondary_style()`
- `WRAP_PANEL_MD`
- `WRAP_PANEL_LG`

代码入口:
- `workspace_ui.py` 的 `render_output_board()`
- `workspace_ui.py` 的 `render_right_panel_switcher()`

## 改数据库区

想改这些:
- 当前数据库卡片
- 常用表速查卡片
- 查询按钮
- 数据库结果文本框

优先看:
- `panel_card_style()`
- `surface_card_style()`
- `button_primary_style()`
- `button_secondary_style()`
- `input_box_style()`
- `HEIGHT_DB_RESULT`
- `WRAP_PANEL_MD`

代码入口:
- `workspace_ui.py` 的 `render_database_panel()`

## 改流水线页

想改这些:
- 流水线头部按钮
- 时间记录说明卡片
- 单条条带卡片
- 甘特条带颜色

优先看:
- `panel_card_style()`
- `button_primary_style()`
- `button_secondary_style()`
- `WRAP_PANEL_LG`
- `SUCCESS`
- `WARNING`
- `DANGER`
- `ACCENT`

代码入口:
- `pipeline_gantt.py` 的 `render_gantt_tab()`
- `pipeline_gantt.py` 的 `get_gantt_bar_color()`

## 修改建议

建议顺序:
1. 先在 `style_config.py` 找到对应常量或 helper
2. 如果只是视觉微调，只改 `style_config.py`
3. 如果是新增组件结构，再去改 `terminal.py`
3. 如果是主界面组件结构，优先改 `workspace_ui.py`
4. 如果是流程调度或进程控制，再改 `terminal.py`
5. 如果是流水线页，再改 `pipeline_gantt.py`
6. 改完后至少打开界面检查一次对应区域

避免:
- 在 `terminal.py` / `workspace_ui.py` / `pipeline_gantt.py` 里重新写新的颜色值
- 在这些业务模块里重新塞新的宽高魔法数字
- 同一个组件同时混用多套按钮风格
