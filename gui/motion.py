"""
`motion.py` 是 terminal GUI 的微动效工具模块。

它只做三件事，让原本"瞬切"的界面变得丝滑:
1. 平滑悬停: 给所有 CTkButton 的 hover 加一段 ~90ms 的颜色补间，鼠标移入移出时颜色淡入淡出，而不是硬切。
2. 平滑滚动: 把"跳到当前运行步骤 / 跳到错误文件"从瞬移改成带缓动的滚动。
3. 颜色补间底座: 通用的 RGB 插值 + 缓动函数，供上面两项和后续动效复用。

设计原则:
- 全部基于 tkinter 的 `after()` 实现，不引入任何第三方依赖。
- 任意一步出错都会 **安全降级** 回原生瞬切行为，绝不影响主流程或运行链路。
- 动效集中在本文件，业务代码只调用入口函数，不散落动画细节。

接入方式:
- `enable_smooth_hover()`: 在创建任何按钮之前调用一次（terminal.py 在 `apply_theme()` 后调用），
  一次性给 `CTkButton` 打补丁，之后所有按钮自动获得平滑悬停。
- `smooth_scroll_to(canvas, fraction)`: 在需要滚动定位的地方替换原来的 `canvas.yview_moveto(fraction)`。
"""

import customtkinter as ctk


# ============================================================
# 一、颜色与缓动底座
# ============================================================

def _hex_to_rgb(value):
    # 把 "#RRGGBB" 解析成 (r, g, b) 整数三元组。
    text = str(value).lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _rgb_to_hex(rgb):
    # 把 (r, g, b) 还原成 "#RRGGBB"，并夹紧到 0~255。
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def blend(color_a, color_b, t):
    # 在两个十六进制颜色之间按比例 t(0~1) 线性插值，t=0 取 a，t=1 取 b。
    ra, ga, ba = _hex_to_rgb(color_a)
    rb, gb, bb = _hex_to_rgb(color_b)
    return _rgb_to_hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def ease_out_cubic(t):
    # 先快后慢的缓动，用于悬停淡入与滚动收尾，体感更自然。
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    # 两端慢、中间快的缓动，用于较长距离的平滑滚动。
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def _resolve_color(widget, color):
    # 把 CTk 颜色(可能是单值，也可能是 (亮色, 暗色) 元组、或 "transparent")解析成当前外观模式下的十六进制色。
    try:
        if color == "transparent":
            color = getattr(widget, "_bg_color", "#FFFFFF")
        resolved = widget._apply_appearance_mode(color)
        # 解析后必须是 "#RRGGBB" 才能参与插值，否则交给上层降级。
        _hex_to_rgb(resolved)
        return resolved
    except Exception:
        return None


# ============================================================
# 二、平滑悬停 (对 CTkButton 打补丁)
# ============================================================

HOVER_DURATION_MS = 90   # 悬停颜色补间总时长
HOVER_STEPS = 6          # 补间帧数(帧越多越平滑，但太多会增加调度负担)

_ORIGINAL_ON_ENTER = None
_ORIGINAL_ON_LEAVE = None
_HOVER_PATCHED = False


def _paint_button_inner(button, hex_color):
    # 按 CTkButton 内部画法，把按钮内部色块与文字/图标背景统一刷成指定颜色。
    button._canvas.itemconfig("inner_parts", outline=hex_color, fill=hex_color)
    if getattr(button, "_text_label", None) is not None:
        button._text_label.configure(bg=hex_color)
    if getattr(button, "_image_label", None) is not None:
        button._image_label.configure(bg=hex_color)


def _cancel_button_motion(button):
    # 取消按钮上仍在进行的悬停补间，避免移入移出过快时颜色打架。
    job = getattr(button, "_motion_job", None)
    if job:
        try:
            button.after_cancel(job)
        except Exception:
            pass
    button._motion_job = None


def _animate_button_to(button, target_raw):
    # 把按钮内部色从"当前已绘制色"平滑过渡到目标色。
    end = _resolve_color(button, target_raw)
    if end is None:
        raise ValueError("无法解析目标颜色")
    # 起点优先用上一次记录的动画色，保证移入移出反复横跳时也连续。
    start = getattr(button, "_motion_color", None)
    if start is None:
        base = button._fg_color if button._fg_color != "transparent" else button._bg_color
        start = _resolve_color(button, base) or end
    _cancel_button_motion(button)

    def step(index):
        button._motion_job = None
        try:
            if not button.winfo_exists():
                return
        except Exception:
            return
        t = ease_out_cubic(index / HOVER_STEPS)
        current = blend(start, end, t)
        try:
            _paint_button_inner(button, current)
        except Exception:
            return
        button._motion_color = current
        if index < HOVER_STEPS:
            try:
                button._motion_job = button.after(HOVER_DURATION_MS // HOVER_STEPS, step, index + 1)
            except Exception:
                button._motion_job = None

    step(1)


def _patched_on_enter(self, event=None):
    # 平滑版移入: 在正常可点状态下，把内部色补间到 hover 色。
    try:
        if not (getattr(self, "_hover", False) is True and self._state == "normal"):
            return
        target = self._hover_color if self._hover_color is not None else self._fg_color
        _animate_button_to(self, target)
    except Exception:
        # 出现任何异常都回退到原生瞬切，保证按钮始终可用。
        if _ORIGINAL_ON_ENTER is not None:
            _ORIGINAL_ON_ENTER(self, event)


def _patched_on_leave(self, event=None):
    # 平滑版移出: 把内部色补间回 fg 色(透明按钮回到背景色)。
    try:
        self._click_animation_running = False
        target = self._bg_color if self._fg_color == "transparent" else self._fg_color
        _animate_button_to(self, target)
    except Exception:
        if _ORIGINAL_ON_LEAVE is not None:
            _ORIGINAL_ON_LEAVE(self, event)


def enable_smooth_hover():
    # 一次性给 CTkButton 打补丁，之后所有新建按钮自动获得平滑悬停。重复调用安全。
    global _ORIGINAL_ON_ENTER, _ORIGINAL_ON_LEAVE, _HOVER_PATCHED
    if _HOVER_PATCHED:
        return
    try:
        _ORIGINAL_ON_ENTER = ctk.CTkButton._on_enter
        _ORIGINAL_ON_LEAVE = ctk.CTkButton._on_leave
        ctk.CTkButton._on_enter = _patched_on_enter
        ctk.CTkButton._on_leave = _patched_on_leave
        _HOVER_PATCHED = True
    except Exception:
        # 打补丁失败(例如 customtkinter 内部结构变动)就保持原生行为。
        _HOVER_PATCHED = False


# ============================================================
# 三、平滑滚动
# ============================================================

SCROLL_DURATION_MS = 240   # 平滑滚动总时长
SCROLL_STEPS = 16          # 滚动补间帧数


def smooth_scroll_to(canvas, target_fraction, duration_ms=SCROLL_DURATION_MS, steps=SCROLL_STEPS):
    # 把滚动画布从当前位置缓动到目标比例位置，替代瞬移的 yview_moveto。
    if canvas is None:
        return
    target = max(0.0, min(1.0, float(target_fraction)))
    try:
        start = float(canvas.yview()[0])
    except Exception:
        # 拿不到当前位置就直接瞬移到位，保证功能不丢。
        try:
            canvas.yview_moveto(target)
        except Exception:
            pass
        return

    delta = target - start
    if abs(delta) < 0.002:
        try:
            canvas.yview_moveto(target)
        except Exception:
            pass
        return

    # 取消同一画布上未完成的滚动动画，避免两段滚动叠加抖动。
    prev = getattr(canvas, "_motion_scroll_job", None)
    if prev:
        try:
            canvas.after_cancel(prev)
        except Exception:
            pass
    canvas._motion_scroll_job = None

    interval = max(1, duration_ms // steps)

    def step(index):
        canvas._motion_scroll_job = None
        try:
            if not canvas.winfo_exists():
                return
            t = ease_in_out(index / steps)
            canvas.yview_moveto(start + delta * t)
        except Exception:
            return
        if index < steps:
            try:
                canvas._motion_scroll_job = canvas.after(interval, step, index + 1)
            except Exception:
                canvas._motion_scroll_job = None

    step(1)


# ============================================================
# 四、统一入口
# ============================================================

def enable_global_motion():
    # 应用启动时调用一次，开启所有全局微动效。
    enable_smooth_hover()
