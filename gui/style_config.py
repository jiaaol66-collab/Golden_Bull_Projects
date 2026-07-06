"""
`style_config.py` 是 terminal GUI 的统一样式配置文件。

这里集中维护 4 类内容:
1. 主题与字体入口: 控制整个界面的基础外观和字号。
2. 颜色常量: 对应边栏、按钮、卡片、错误高亮、文本等视觉颜色。
3. 尺寸常量: 对应圆角、高度、宽度、换行宽度、控制台高度等布局参数。
4. 样式 helper: 对应主按钮、次按钮、Tab、滚动区、输入框、复选框等组件模板。

改界面样式时，优先修改本文件，再由 `terminal.py` 统一引用。

本版视觉基调(Ink & Azure 高级冷灰):
- 设计取向: 高级感来自"克制"而非更多颜色。整屏是高级冷灰中性体系，
  只在主按钮/选中态这一个点上使用沉稳靛蓝，作为产品身份色。
- 中性色: 一套带极弱蓝调的冷灰阶(近白底 / 白色内容面 / 发丝级边框)，
  既保留"蓝"的身份，又避免饱和亮蓝带来的消费级、廉价观感。
- 语义色: 成功/失败/警告统一降饱和，在白底上清晰但不喧哗，更显沉稳。
- 圆角: 整体收紧一档(外层 14 / 面板 12 / 卡片 10 / 按钮 8)，更专业、更"技术"，
  避免大圆角带来的圆润消费级气质。
- 边框: 卡片/面板用近乎不可见的发丝线分层，替代纯色块堆叠。
- 字体: 统一显式中文字族；配合 `motion.py` 的平滑悬停与平滑滚动，观感更"丝滑"。
"""

import customtkinter as ctk


# 全局主题入口:
# 对应整个 terminal 窗口的外观模式和基础主题。
# 注: 颜色常量目前为单一亮色值，固定 Light 外观可避免系统切暗色时样式半坏。
def apply_theme():
    ctk.set_appearance_mode("Light")
    ctk.set_default_color_theme("blue")


# 统一字族:
# 对应所有标题、正文、按钮文本。Windows 下优先用雅黑 UI，中英文混排更精致；
# 若系统缺失该字族，Tk 会自动回退到默认字体，不影响运行。
FONT_FAMILY = "Microsoft YaHei UI"


# 字体工厂:
# 对应所有标题、正文、按钮文本的统一字号入口。
def ui_font(size, weight=None):
    kwargs = {"size": size, "family": FONT_FAMILY}
    if weight:
        kwargs["weight"] = weight
    return ctk.CTkFont(**kwargs)


# 样式合并工具:
# 对应按钮/卡片/helper 的默认样式 + 局部覆写。
def _style(base, **overrides):
    style = dict(base)
    style.update({k: v for k, v in overrides.items() if v is not None})
    return style


# 页面基础底色:
# 对应主窗口背景、白色容器卡片、浅蓝色面板卡片、左侧边栏背景。
# Ink & Azure: 一套带极弱蓝调的冷灰阶，白色内容面在近白冷底上更突出、更高级。
APP_BG = "#ECF1F8"  # 整个 terminal 主窗口背景色(冷调近白)
SURFACE_BG = "#FFFFFF"  # 白色主容器背景，如左/中/右主区域与内容行
PANEL_BG = "#F4F7FB"  # 浅冷灰面板背景，如说明卡片、输出卡片、数据库卡片
SIDEBAR_BG = "#E7EDF6"  # 左侧边栏背景色(克制冷灰，不饱和)

# 卡片与面板边框:
# 用近乎不可见的发丝线分层，替代纯色块堆叠，结构干净而克制。
CARD_BORDER = "#E8ECF3"  # 白色内容卡片(文件行/文档行)发丝级描边
PANEL_BORDER = "#DCE3EC"  # 外层主面板与浅色面板的发丝级描边

# 主交互色:
# 对应主按钮、Tab 选中态、筛选高亮、输出面板中的主要可点击动作。
# Ink & Azure: 仅在此一个点位使用沉稳靛蓝，作为产品身份色，整屏其余皆为中性。
ACCENT = "#3556D4"  # 主按钮与主强调色(沉稳靛蓝)
ACCENT_HOVER = "#2A45B5"  # 主按钮悬停色
ACCENT_DEEP = "#22399A"  # 下拉按钮深色悬停状态
ACCENT_SOFT = "#C9D5F6"  # 弱化主按钮底色，如"全不选"(浅靛蓝，配深色文字)
ACCENT_SOFT_HOVER = "#B4C5F1"  # 弱化主按钮悬停色
ACCENT_SEGMENT_BG = "#E6EAF2"  # Tab/分段按钮未选中背景(中性冷灰，不与主色争抢)
ACCENT_SEGMENT_HOVER = "#D8DEEA"  # Tab/分段按钮未选中悬停色
ACCENT_GROUP_BG = "#EFF3FA"  # 输出分组卡片背景色(极浅冷灰)

# 语义状态色:
# 对应成功、失败、警告、次级按钮等状态提示。
# Ink & Azure: 语义色统一降饱和，在白底上清晰可辨但不喧哗，整体更沉稳。
SUCCESS = "#2E9E6E"  # 成功态颜色(降饱和翠绿)，如运行成功、绿色按钮、计时成功态
SUCCESS_HOVER = "#24805A"  # 成功态悬停色
DANGER = "#D64949"  # 失败/危险态颜色(降饱和砖红)，如停止、错误提示
DANGER_HOVER = "#B83A3A"  # 失败/危险态悬停色
WARNING = "#E0A82E"  # 警告态颜色(柔和黄金)，如重置代码按钮
WARNING_HOVER = "#C28E1E"  # 警告态悬停色
BACKUP = "#E08A2E"  # 备份类动作颜色(琥珀)，如代码备份、说明备份，与警告黄区分
BACKUP_HOVER = "#C2731E"  # 备份类动作悬停色
SECONDARY = "#465062"  # 次级按钮颜色(冷调石墨灰)，如刷新、日志、数据库辅助动作
SECONDARY_HOVER = "#333B4D"  # 次级按钮悬停色

# 文本色:
# 对应标题、说明、副文本、深色按钮上的反白文字。
TEXT_PRIMARY = "#1A2333"  # 主标题和主要正文颜色(冷调墨黑)
TEXT_MUTED = "#66728A"  # 次要说明文字颜色(冷调石板灰)
TEXT_INVERSE = "#FFFFFF"  # 深色按钮上的反白文字

# 边框与滚动条:
# 对应输入框边框、分割线、复选框边框、滚动条按钮。
# Ink & Azure: 边框/滚动条统一走冷灰，安静克制，与冷调底色协调。
BORDER = "#D3DBE6"  # 输入框与文本框边框颜色
DIVIDER = "#E4E9F1"  # 区域分隔线颜色
CHECKBOX_BORDER = "#97A3B6"  # 步骤复选框边框颜色
SCROLLBAR_BUTTON = "#C4CDDC"  # 滚动条按钮默认颜色
SCROLLBAR_BUTTON_HOVER = "#A9B5C9"  # 滚动条按钮悬停颜色

# 输入区与错误高亮:
# 对应日志框、数据库结果框、错误文件夹卡片、错误文件按钮。
INPUT_BG = "#F6F8FC"  # 日志框、数据库结果框、输入框背景(极浅冷灰)
ITEM_HOVER = "#EEF2F8"  # 普通文件项/按钮的浅冷灰悬停色
ERROR_SURFACE = "#FBEAEA"  # 错误文件夹卡片背景
ERROR_ITEM_BG = "#F2ABAB"  # 错误文件按钮背景
ERROR_ITEM_HOVER = "#EC8C8C"  # 错误文件按钮悬停色
TAB_CLOSE_HOVER_BG = "#FAE3E3"  # 标签页悬浮关闭按钮的极浅红悬停底色

# 圆角尺寸:
# 对应极小分隔条、普通按钮、卡片、外层面板等圆角层级。
# Ink & Azure: 整体收紧一档，更专业更"技术"，避免大圆角的圆润消费级气质。
RADIUS_NONE = 0  # 无圆角，用于分隔线等直角元素
RADIUS_XS = 4  # 极小圆角，用于控制台拖拽条
RADIUS_SM = 6  # 小圆角，用于小按钮
RADIUS_MD = 8  # 中圆角，用于大部分顶部操作按钮
RADIUS_LG = 10  # 大圆角，用于文件行按钮和内容卡片
RADIUS_XL = 12  # 更大圆角，用于日志文本框
RADIUS_PANEL = 12  # 面板卡片圆角
RADIUS_OUTER = 14  # 外层主容器圆角

# 高度尺寸:
# 对应控制台拖拽条、下拉框、主按钮、小按钮、输入框、日志框、数据库结果框。
HEIGHT_DIVIDER = 1  # 横向分隔线高度
HEIGHT_SASH = 8  # 控制台拖拽条高度
HEIGHT_OPTION_MENU = 36  # 奖项/工作区选择下拉框高度
HEIGHT_BUTTON = 36  # 常规主按钮高度
HEIGHT_BUTTON_SM = 28  # 小型操作按钮高度
HEIGHT_BUTTON_XS = 22  # 卡片内超小按钮高度
HEIGHT_ACTION_BUTTON_XS = 22
HEIGHT_TOGGLE = 34  # 边栏展开/收起按钮高度
HEIGHT_INPUT = 32  # 筛选输入框高度
HEIGHT_LOG_BUTTON = 28  # 日志区按钮高度
HEIGHT_LOG_BOX = 120  # 底部日志框默认高度
HEIGHT_DB_RESULT = 220  # 数据库结果框高度

# 宽度尺寸:
# 对应侧栏开关、顶部动作按钮、打开文件夹按钮、筛选按钮、查询按钮等。
WIDTH_SIDEBAR_TOGGLE_BAR = 42  # 边栏开关所在窄条宽度
WIDTH_SIDEBAR_TOGGLE_BUTTON = 32  # 边栏开关按钮宽度
WIDTH_ACTION_BUTTON = 100  # 右侧工具区常规动作按钮宽度
WIDTH_ACTION_BUTTON_SM = 90  # 小号动作按钮宽度
WIDTH_ACTION_BUTTON_XS = 32  # 超小动作按钮宽度
WIDTH_CLOSE_TAB_BUTTON = 112  # "删除工作区"按钮宽度
WIDTH_OPEN_FOLDER_BUTTON = 92  # "打开文件夹/打开根目录"按钮宽度
WIDTH_OPEN_INFO_BUTTON = 110  # "打开参评信息/打开数据库目录"按钮宽度
WIDTH_OPEN_STEP_BUTTON = 112  # "打开步骤文件夹"按钮宽度
WIDTH_LOG_DIR_BUTTON = 126  # "打开完整日志目录"按钮宽度
WIDTH_SELECT_TOGGLE_BUTTON = 74  # "全选/全不选"按钮宽度
WIDTH_FILTER_BUTTON = 70  # "筛选"按钮宽度
WIDTH_QUERY_BUTTON = 76  # "查行数/前20行"按钮宽度
WIDTH_ATTEMPT_MENU = 320  # 流水线页"尝试"下拉框宽度
WIDTH_STEP_CONTROL_PANEL = 248  # 步骤页左侧控制列宽度
WIDTH_STEP_COUNT_BADGE = 38  # 步骤列表运行次数小方块宽度
WIDTH_STEP_OPEN_BUTTON = 52  # 步骤列表"打开"按钮宽度

# 文本换行宽度:
# 对应左栏提示、代码文件夹说明、说明文档卡片、右侧输出/数据库卡片中的说明文字。
WRAP_LEFT_HINT = 280  # 左侧步骤区与代码文件夹区提示文案换行宽度
WRAP_ROOT_CARD = 260  # 根目录工具卡片与参评信息卡片换行宽度
WRAP_FOLDER_CARD = 250  # 步骤文件夹卡片与说明标题换行宽度
WRAP_DOC_EMPTY = 240  # 说明文档缺失提示换行宽度
WRAP_DOC_ITEM = 220  # 单个说明文档名称/备注换行宽度
WRAP_PANEL_MD = 320  # 右侧中等宽度卡片说明文本换行宽度
WRAP_PANEL_LG = 360  # 右侧大卡片说明文本换行宽度

# 布局宽度:
# 对应中间说明栏、左侧步骤栏的最小/最大宽度、边栏在窄屏和宽屏时的宽度。
WIDTH_MIDDLE_PANEL = 300  # 中间"说明文档区"固定宽度，主界面里约占 30%
WIDTH_LEFT_PANEL_MIN = 420  # 左侧步骤栏最小宽度
WIDTH_LEFT_PANEL_MAX = 860  # 左侧步骤栏最大宽度
WIDTH_SIDEBAR_NARROW = 180  # 窄窗口下边栏宽度
WIDTH_SIDEBAR_WIDE = 220  # 宽窗口下边栏宽度

# 控制台高度:
# 对应底部日志控制台的最小高度，以及随窗口高度变化时的默认高度档位。
CONSOLE_MIN_HEIGHT = 110  # 底部日志控制台最小高度
CONSOLE_DEFAULT_SM = 140  # 小窗口下日志控制台默认高度
CONSOLE_DEFAULT_MD = 180  # 中窗口下日志控制台默认高度
CONSOLE_DEFAULT_LG = 240  # 大窗口下日志控制台默认高度

# 线条和高亮边框:
# 对应分隔线高度、错误文件夹卡片的红色描边宽度。
ERROR_BORDER_WIDTH = 2  # 错误文件夹/错误卡片的红色描边宽度
TAB_CLOSE_BUTTON_SIZE = 14  # 标签页悬浮关闭按钮尺寸
TAB_CLOSE_OFFSET_X = 10  # 标签页悬浮关闭按钮相对右上角的横向偏移
TAB_CLOSE_OFFSET_Y = -4  # 标签页悬浮关闭按钮相对右上角的纵向偏移

# 流水线页尺寸:
# 对应新版流水线泳道图中的时间列、主步骤列、异步列、表头高度和最小画布高度。
TIMELINE_TIME_COL_WIDTH = 88  # 流水线左侧时间刻度列宽度
TIMELINE_MAIN_COL_WIDTH = 220  # 流水线中间主步骤列宽度
TIMELINE_ASYNC_COL_MIN_WIDTH = 156  # 流水线右侧单个异步泳道最小宽度
TIMELINE_HEADER_HEIGHT = 46  # 流水线列标题区高度
TIMELINE_MIN_BODY_HEIGHT = 420  # 流水线主体最小画布高度
TIMELINE_SECOND_PIXELS = 18  # 流水线每秒对应的基础像素高度
TIMELINE_TICK_PIXELS = 84  # 流水线每个主刻度区间对应的像素高度
TIMELINE_RUNNING_TICK_SECONDS = 300  # 流水线运行中默认按 300 秒为一个主刻度区间
TIMELINE_TARGET_TICK_COUNT = 10  # 流水线结束后自适应刻度时的目标主刻度数量
TIMELINE_MIN_TICK_COUNT = 8  # 流水线结束后允许的最少主刻度数量
TIMELINE_MAX_TICK_COUNT = 14  # 流水线结束后允许的最多主刻度数量
TIMELINE_BLOCK_PAD_X = 8  # 流水线代码块左右留白
TIMELINE_BLOCK_MIN_HEIGHT = 30  # 流水线代码块最小高度

# 流水线页颜色:
# 对应新版流水线泳道图中的时间列底色、主步骤列底色、异步列底色和网格线颜色。
TIMELINE_TIME_BG = "#F4F7FB"  # 流水线左侧时间刻度背景
TIMELINE_MAIN_BG = "#D7E0F6"  # 流水线主步骤泳道背景(浅靛蓝，克制)
TIMELINE_ASYNC_BG = "#EEF2FA"  # 流水线异步泳道背景
TIMELINE_GRID = "#DDE4EE"  # 流水线网格线颜色


# 主按钮:
# 对应"挂载至右侧面板""打开根目录""打开文件夹"等主要动作。
def button_primary_style(**overrides):
    # fg_color: 主按钮底色; hover_color: 鼠标悬停色; text_color: 反白文字
    return _style({"fg_color": ACCENT, "hover_color": ACCENT_HOVER, "text_color": TEXT_INVERSE}, **overrides)


# 次按钮:
# 对应"刷新说明""刷新数据库""打开完整日志目录"等次级动作。
def button_secondary_style(**overrides):
    # fg_color: 次按钮底色; hover_color: 次按钮悬停色; text_color: 反白文字
    return _style({"fg_color": SECONDARY, "hover_color": SECONDARY_HOVER, "text_color": TEXT_INVERSE}, **overrides)


# 成功按钮:
# 对应"一键运行""更新代码"等强调完成/执行的动作。
def button_success_style(**overrides):
    # fg_color: 成功按钮底色; hover_color: 成功按钮悬停色; text_color: 反白文字
    return _style({"fg_color": SUCCESS, "hover_color": SUCCESS_HOVER, "text_color": TEXT_INVERSE}, **overrides)


# 危险按钮:
# 对应"卸载并关闭""暂停"等可能中断流程的动作。
def button_danger_style(**overrides):
    # fg_color: 危险按钮底色; hover_color: 危险按钮悬停色; text_color: 反白文字
    return _style({"fg_color": DANGER, "hover_color": DANGER_HOVER, "text_color": TEXT_INVERSE}, **overrides)


# 警告按钮:
# 对应"重置代码"这类需要提醒但不属于错误的动作。
def button_warning_style(**overrides):
    # fg_color: 警告按钮底色; hover_color: 警告按钮悬停色; text_color: 深色正文
    return _style({"fg_color": WARNING, "hover_color": WARNING_HOVER, "text_color": TEXT_PRIMARY}, **overrides)


# 浅色按钮:
# 对应"全不选"等需要弱化显示的补充动作。
def button_soft_style(**overrides):
    # fg_color: 弱化按钮底色; hover_color: 弱化按钮悬停色; text_color: 深色正文
    return _style({"fg_color": ACCENT_SOFT, "hover_color": ACCENT_SOFT_HOVER, "text_color": TEXT_PRIMARY}, **overrides)


# 面板卡片:
# 对应说明区卡片、输出文件卡片、数据库卡片、参评信息卡片。
# 现代化: 默认加 1px 细描边，浅色面板与背景之间有明确边界。
def panel_card_style(**overrides):
    # fg_color: 浅色面板底色; corner_radius: 面板级圆角; border_*: 细描边
    return _style(
        {"fg_color": PANEL_BG, "corner_radius": RADIUS_PANEL, "border_width": 1, "border_color": PANEL_BORDER},
        **overrides,
    )


# 白色内容卡片:
# 对应卡片内部的文件行、文档行、数据库表项行。
# 现代化: 默认加极浅描边，呈现"列表卡片"质感(错误高亮等覆写仍会优先生效)。
def surface_card_style(**overrides):
    # fg_color: 白色内容底色; corner_radius: 内容卡片圆角; border_*: 极浅描边
    return _style(
        {"fg_color": SURFACE_BG, "corner_radius": RADIUS_LG, "border_width": 1, "border_color": CARD_BORDER},
        **overrides,
    )


# 外层主面板:
# 对应左侧步骤区、中间说明区、右侧输出/数据库区、底部控制台容器。
# 现代化: 白色大面板加细描边，在灰底上形成干净的分区轮廓。
def outer_panel_style(**overrides):
    # fg_color: 主容器底色; corner_radius: 外层大圆角; border_*: 细描边
    return _style(
        {"fg_color": SURFACE_BG, "corner_radius": RADIUS_OUTER, "border_width": 1, "border_color": PANEL_BORDER},
        **overrides,
    )


# 输入框样式:
# 对应日志框、数据库结果框，以及后续需要统一风格的输入框。
def input_box_style(**overrides):
    # fg_color: 输入区背景; border_color/border_width: 边框; text_color: 输入文字颜色
    return _style(
        {"fg_color": INPUT_BG, "border_color": BORDER, "border_width": 1, "text_color": TEXT_PRIMARY},
        **overrides,
    )


# 滚动区样式:
# 对应步骤滚动区、代码文件夹滚动区、中间说明滚动区、右侧输出滚动区。
def scrollable_style(**overrides):
    # fg_color: 滚动容器背景; corner_radius: 外轮廓圆角; scrollbar_*: 滚动条按钮颜色
    return _style(
        {"fg_color": "transparent", "corner_radius": RADIUS_NONE, "scrollbar_button_color": SCROLLBAR_BUTTON, "scrollbar_button_hover_color": SCROLLBAR_BUTTON_HOVER},
        **overrides,
    )


# Tab 容器样式:
# 对应主标签页、左侧"步骤代码/代码文件夹"Tab 容器。
def tabview_style(**overrides):
    # segmented_button_*: Tab 按钮的默认/选中/悬停配色; text_color: Tab 文本颜色
    return _style(
        {
            "fg_color": "transparent",
            "segmented_button_fg_color": ACCENT_SEGMENT_BG,
            "segmented_button_selected_color": ACCENT,
            "segmented_button_selected_hover_color": ACCENT_HOVER,
            "segmented_button_unselected_color": ACCENT_SEGMENT_BG,
            "segmented_button_unselected_hover_color": ACCENT_SEGMENT_HOVER,
            "text_color": TEXT_PRIMARY,
        },
        **overrides,
    )


# 分段按钮样式:
# 对应右侧"输出文件/数据库"切换和输出文件筛选分段按钮。
def segmented_button_style(**overrides):
    # selected_*: 当前选中项配色; unselected_*: 未选中项配色; text_color: 按钮文字颜色
    return _style(
        {
            "fg_color": ACCENT_SEGMENT_BG,
            "selected_color": ACCENT,
            "selected_hover_color": ACCENT_HOVER,
            "unselected_color": ACCENT_SEGMENT_BG,
            "unselected_hover_color": ACCENT_SEGMENT_HOVER,
            "text_color": TEXT_PRIMARY,
        },
        **overrides,
    )


# 下拉菜单样式:
# 对应奖项选择、工作区选择、输出代码筛选下拉框。
def option_menu_style(**overrides):
    # fg_color/button_*: 下拉框主体和右侧按钮配色; dropdown_*: 下拉面板配色
    return _style(
        {
            "fg_color": ACCENT,
            "button_color": ACCENT_HOVER,
            "button_hover_color": ACCENT_DEEP,
            "text_color": TEXT_INVERSE,
            "dropdown_fg_color": SURFACE_BG,
            "dropdown_hover_color": PANEL_BG,
            "dropdown_text_color": TEXT_PRIMARY,
        },
        **overrides,
    )


# 复选框样式:
# 对应步骤栏中的顺序代码勾选项。
def checkbox_style(**overrides):
    # fg_color: 勾选框底色; hover_color: 悬停色; border_color: 外框色; checkmark_color: 对勾颜色
    return _style(
        {
            "fg_color": ACCENT,
            "hover_color": ACCENT_HOVER,
            "border_color": CHECKBOX_BORDER,
            "checkmark_color": TEXT_INVERSE,
        },
        **overrides,
    )
