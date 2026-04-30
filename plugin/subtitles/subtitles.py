from typing import Any, Callable, Optional, Sequence, Type

from talon import Module, app, cron, ctrl, settings, ui
from talon.canvas import Canvas
from talon.skia.canvas import Canvas as SkiaCanvas
from talon.skia.imagefilter import ImageFilter
from talon.types import Rect

mod = Module()


def setting(
    name: str, type: Type, desc: str, *, default: Optional[Any] = None
) -> Callable[[], type]:
    mod.setting(f"subtitles_{name}", type, default=default, desc=f"Subtitles: {desc}")
    return lambda: settings.get(f"user.subtitles_{name}")


setting_show = setting(
    "show",
    bool,
    "If true show (custom) subtitles",
    default=False,
)
setting_screens = setting(
    "screens",
    str,
    "Show on which screens: 'all', 'main', 'cursor', 'focus'",
)
setting_size = setting(
    "size",
    int,
    "Subtitle size in pixels",
)
setting_color = setting(
    "color",
    str,
    "Subtitle color",
)
setting_color_outline = setting(
    "color_outline",
    str,
    "Subtitle outline color",
)
setting_timeout_per_char = setting(
    "timeout_per_char",
    int,
    "For each character in the subtitle extend the timeout by this amount in ms",
)
setting_timeout_min = setting(
    "timeout_min",
    int,
    "Minimum time for a subtitle to show in ms",
)
setting_timeout_max = setting(
    "timeout_max",
    int,
    "Maximum time for a subtitle to show in ms",
)
setting_y = setting(
    "y",
    float,
    "Percentage of screen hight to show subtitle at. 0=top, 1=bottom",
)
setting_x = setting(
    "x",
    float,
    "Percentage of screen width to right-align subtitle to. 0=left, 1=right. Unset = centered.",
)

mod = Module()
# Persistent canvases keyed by screen index — never closed, redrawn empty to avoid macOS slide animation
_canvases: dict[int, Canvas] = {}
_current_text: str = ""
_hide_job = None


def show_subtitle(text: str):
    """Show subtitle"""
    global _current_text, _hide_job
    if not setting_show():
        return
    if _hide_job:
        cron.cancel(_hide_job)
        _hide_job = None
    _current_text = text
    _sync_canvases(get_screens())
    timeout = calculate_timeout(text)
    _hide_job = cron.after(f"{timeout}ms", _hide_subtitle)


def _hide_subtitle():
    global _current_text, _hide_job
    _current_text = ""
    _hide_job = None
    for canvas in _canvases.values():
        canvas.freeze()


def _sync_canvases(screens: Sequence[ui.Screen]):
    all_screens = ui.screens()
    needed = {all_screens.index(s) for s in screens}
    for idx in list(_canvases.keys()):
        if idx not in needed:
            _canvases.pop(idx).close()
    for screen in screens:
        idx = all_screens.index(screen)
        if idx not in _canvases:
            canvas = Canvas.from_screen(screen)
            canvas.register("draw", lambda c, s=screen: on_draw(c, s))
            _canvases[idx] = canvas
    for canvas in _canvases.values():
        canvas.freeze()


def get_screens() -> Sequence[ui.Screen]:
    screen = setting_screens()
    match screen:
        case "main":
            return [ui.main_screen()]
        case "all":
            return ui.screens()
        case "cursor":
            x, y = ctrl.mouse_pos()
            return [ui.screen_containing(x, y)]
        case "focus":
            return [ui.active_window().screen]
        case _:
            raise ValueError(f"Unknown screen setting: {screen}")


def on_draw(c: SkiaCanvas, screen: ui.Screen):
    if not _current_text:
        return
    scale = screen.scale if app.platform != "mac" else 1
    size = setting_size() * scale
    rect = set_text_size_and_get_rect(c, size, _current_text)
    x_frac = setting_x()
    if x_frac is None:
        x = c.rect.center.x - rect.center.x
    else:
        target = c.rect.x + x_frac * c.rect.width
        x = max(
            c.rect.x - rect.left,
            min(c.rect.x + c.rect.width - rect.right, target - rect.right),
        )
    # Clamp coordinate to make sure entire text is visible
    y = max(
        min(
            c.rect.y + setting_y() * c.rect.height + c.paint.textsize / 2,
            c.rect.bot - rect.bot,
        ),
        c.rect.top - rect.top,
    )

    c.paint.imagefilter = ImageFilter.drop_shadow(2, 2, 1, 1, "000000")
    c.paint.style = c.paint.Style.FILL
    c.paint.color = setting_color()
    c.draw_text(_current_text, x, y)

    # Outline
    c.paint.imagefilter = None
    c.paint.style = c.paint.Style.STROKE
    c.paint.color = setting_color_outline()
    c.draw_text(_current_text, x, y)


def calculate_timeout(text: str) -> int:
    ms_per_char = setting_timeout_per_char()
    ms_min = setting_timeout_min()
    ms_max = setting_timeout_max()
    return min(ms_max, max(ms_min, len(text) * ms_per_char))


def set_text_size_and_get_rect(c: SkiaCanvas, size: int, text: str) -> Rect:
    while True:
        c.paint.textsize = size
        rect = c.paint.measure_text(text)[1]
        if rect.width < c.width * 0.8:
            return rect
        size *= 0.9
