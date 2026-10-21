# -*- coding: utf-8 -*-
"""绿联蓝牙助手 —— 医疗设备 BLE 连接演示 App。

界面结构（底部三个一级模块，随时可切换）：
    「控制」蓝牙连接 / 显示屏 / 8 个圆形功能键
    「记录」蓝牙日志（最近 5 次登录的显示屏内容）/ 诊断记录（预留）
    「登录」用户登录（登录前只有这一项可用；控制、记录被灰色遮罩挡住）

未登录时「控制」「记录」覆盖一层半透明灰并提示"登录后即可使用"，
登录成功后自动解锁。
"""

import json
import os
import time

from kivy.app import App
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.graphics import (Color, Ellipse, InstructionGroup, Line, Rectangle,
                           RoundedRectangle)
from kivy.graphics.texture import Texture
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.metrics import dp, sp
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             ObjectProperty, StringProperty)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform

from accounts import AccountStore
from protocol import (MAX_PAYLOAD, RxFrameParser, decode_text, to_hex)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
KV_FILE = os.path.join(APP_DIR, 'ui.kv')
FONT_FILE = os.path.join(APP_DIR, 'assets', 'fonts', 'NotoSansSC-Regular.ttf')
BADGE_FILE = os.path.join(APP_DIR, 'assets', 'badge.png')

# 系统中文字体兜底路径（未打包字体文件时使用）
SYSTEM_FONTS = [
    '/system/fonts/NotoSansCJK-Regular.ttc',
    '/system/fonts/NotoSansSC-Regular.otf',
    '/system/fonts/DroidSansFallbackFull.ttf',
    '/system/fonts/DroidSansFallback.ttf',
]

# 等宽字体（数字用）：安卓系统自带几种等宽字体，找不到就退回中文字体
SYSTEM_MONO_FONTS = [
    '/system/fonts/RobotoMono-Regular.ttf',
    '/system/fonts/DroidSansMono.ttf',
    '/system/fonts/CutiveMono.ttf',
    'C:\\Windows\\Fonts\\consola.ttf',
]


# ----------------------------------------------------------------------
# 主题色：医疗科技感（浅灰蓝背景 + 白色卡片 + 深青主色 + 医疗蓝辅助）
# ----------------------------------------------------------------------
COLOR_PRIMARY = [0.043, 0.431, 0.431, 1.0]       # #0B6E6E 深青
COLOR_PRIMARY_DARK = [0.027, 0.318, 0.318, 1.0]  # #074F4F
COLOR_BLUE = [0.184, 0.502, 0.929, 1.0]          # #2F80ED 医疗蓝
COLOR_BG = [0.965, 0.973, 0.980, 1.0]            # #F6F8FA 背景
COLOR_CARD = [1.000, 1.000, 1.000, 1.0]          # #FFFFFF 卡片
COLOR_LINE = [0.894, 0.906, 0.925, 1.0]          # #E4E7EC 分割线
COLOR_TEXT = [0.086, 0.125, 0.165, 1.0]          # #16202A 主文本
COLOR_TEXT_WEAK = [0.357, 0.420, 0.478, 1.0]     # #5B6B7A 次文本
COLOR_DANGER = [0.851, 0.176, 0.125, 1.0]        # #D92D20 报错
COLOR_WARN_HIGH = [0.969, 0.565, 0.035, 1.0]     # #F79009 高
COLOR_WARN_MID = [0.992, 0.690, 0.133, 1.0]      # #FDB022 中
COLOR_OK = [0.071, 0.718, 0.416, 1.0]            # #12B76A 提示/正常
COLOR_DISABLED = [0.596, 0.635, 0.702, 1.0]      # #98A2B3 禁用

# 渐变配色（线性渐变，两端颜色）
GRAD_NAVY_A = [0.043, 0.098, 0.145, 1.0]         # 开发者显示屏（深墨青）
GRAD_NAVY_B = [0.043, 0.431, 0.431, 1.0]
GRAD_TEAL_A = [0.027, 0.318, 0.318, 1.0]         # 页头卡片（深青）
GRAD_TEAL_B = [0.043, 0.514, 0.514, 1.0]

# ======================================================================
# ESP32 通信配置 —— 只改这一段就能适配你的固件
# ======================================================================
# 写入特征的 UUID。
# 服务 UUID 留空表示"在所有服务里查找这个特征"，多数情况下更省事。
# 不确定 UUID 时：先连接设备，再点界面上的「服务/特征」按钮，
# 手机上会列出该设备暴露的全部服务与特征及其属性，
# 找到属性里带 WRITE 的那一条，把它的 UUID 填到下面即可。
ESP32_WRITE_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'   # 必须等于 sketch 里的 CHAR_RX_UUID
ESP32_SERVICE_UUID = ''

# 回传（ESP32 → 手机）用的通知特征 UUID。必须等于 sketch 里的 CHAR_TX_UUID。
ESP32_NOTIFY_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'

# 模块自带的 AT 指令通道 UUID（只走蓝牙、不经过串口）
# 用于「服务/特征」里的"模块信息"：读模块的固件版本/角色/波特率/状态显示/鉴权/名称。
ESP32_AT_UUID = '6e400004-b5a3-f393-e0a9-e50e24dcca9e'

# 自动兜底开关：默认关闭（要确定性）。
# 打开它意味着"按 UUID 找不到就随便挑一个可写的特征"——曾经因为安卓 GATT 表里
# Generic Access 的 Device Name(2A00) 也是可写的，命令被写进了设备名里，
# 出现"App 显示发送成功、但设备串口毫无反应"的假成功。别开。
# 如果 UUID 填错，App 会直接告诉你设备上实际有哪些可写/可通知特征。
ESP32_AUTO_PICK_WRITE = False
ESP32_AUTO_PICK_NOTIFY = False

# 命令字（CMD_* / REPLY_*）与帧格式都在 protocol.py 里约定
# 命令帧格式：[0xAA][0x55][命令字][数据长度][数据...][异或校验]
# 「启动」「停止」两个命令包不走这个帧格式，是直接以十六进制原文下发的。

# 通知订阅状态（与 ble_android.py / BleHelper.java 保持一致）
NOTIFY_OFF, NOTIFY_SUBSCRIBING, NOTIFY_SUBSCRIBED, NOTIFY_FAILED = 0, 1, 2, 3
_NOTIFY_STATE_TEXT = {NOTIFY_OFF: '未订阅', NOTIFY_SUBSCRIBING: '订阅中',
                      NOTIFY_SUBSCRIBED: '已订阅', NOTIFY_FAILED: '订阅失败'}

# 各功能按钮对应的命令字见 protocol.py 的 CMD_FUNC_1

# 命令帧格式：[0xAA][0x55][命令字][数据长度][数据...][异或校验]
# 帧的拼装/解析实现在 protocol.py（两端共用的唯一实现），
# 要换格式只改 protocol.py 里的 build_frame()，ESP32 端照着同步即可。

# 单次写入的载荷上限（20 字节）见 protocol.py 的 MAX_PAYLOAD

# 写入结果等待超时（秒）
WRITE_TIMEOUT = 3.0
# 发出命令后等「回传命令包」的窗口（秒）。给模块留足时间（功能一的第二条回传要 3 秒）
RETURN_TIMEOUT = 3.5

WRITE_IDLE, WRITE_SENDING, WRITE_SUCCESS, WRITE_FAILED = 0, 1, 2, 3

# 显示屏最多保留多少行（超过就丢掉最早的）
MAX_DISPLAY_LINES = 200

# 每次连上模块后，App 自动通过蓝牙 AT 通道锁定的模块配置
#   —— 不需要任何电脑端脚本参与
# 只锁串口波特率；**不再自动改模块名称**（名称跟「患者信息」走，由用户确认后下发，
# 避免每次连接都把用户设好的设备名冲掉）
MODULE_TARGET_BAUD = 9600
MODULE_SETUP_COMMANDS = ('AT+UART=%d' % MODULE_TARGET_BAUD,)
# 开发者模式「信息复原」用的模块名
RESET_MODULE_NAME = 'HFUT.BLE'

# 「记录」页固定 4 条待办任务
DEFAULT_TASKS = ('待确认参数', '待更换耗材', '待处理告警', '患者不适上报')

# 控制页 9 个功能键：名称 -> (命令包, 设备动作, 渐进倒计时秒数)
FUNCTION_SPECS = (
    ('充气', '5401084630', 'pump1_on', 0),
    ('渐进充气', '5401008031', 'pump1_on', 5),
    ('停止充气', '54010140F0', 'pump1_off', 0),
    ('放气', '54010241B0', 'pump2_on', 0),
    ('渐进放气', '5401044330', 'pump2_on', 5),
    ('停止放气', '5401038171', 'pump2_off', 0),
    ('急停', '54010583F1', 'stop', 0),
    ('复位', '54010682B1', 'reset', 0),
    ('刷新监测', '5401074270', 'refresh', 0),
)
FUNCTION_BY_NAME = dict((name, (hex_data, action, seconds))
                        for name, hex_data, action, seconds in FUNCTION_SPECS)

APP_VERSION = 'C_V1.0'
APP_NAME = '合安智护'
APP_SUBTITLE = '医疗设备蓝牙控制平台'


def spaced_hex(hex_text):
    """'5401008031' -> '54 01 00 80 31'（只用于界面显示）。"""
    return ' '.join(hex_text[i:i + 2] for i in range(0, len(hex_text), 2))


def fit_text_width(text, width):
    """按可用宽度把一行截断（中文按 1 个字宽、ASCII 按 0.55 估）。

    为什么要截断：这些列表每行高度是固定的，如果文字自动换行，第二行会被
    裁掉且**看不出来**。截断后一定单行显示，"看不全"是明确可见的。
    """
    if width <= 0:
        return text
    limit = max(8.0, width / float(sp(11)))
    cost = 0.0
    out = []
    for char in text:
        cost += 1.0 if ord(char) > 0x2E80 else 0.55
        if cost > limit:
            return ''.join(out) + '…'
        out.append(char)
    return ''.join(out)


# 帧的拼装与解析统一在 protocol.py 里实现（App、桌面模拟器、测试脚本共用同一份，
# 避免两边规则漂移），这里只做导入。要改帧格式就改 protocol.py 的 build_frame()。



def register_cjk_font():
    """注册中文字体，避免中文显示成方框。"""
    for path in [FONT_FILE] + SYSTEM_FONTS:
        if os.path.exists(path):
            try:
                LabelBase.register(name='CJK', fn_regular=path)
                return 'CJK'
            except Exception:
                Logger.exception('BleAssistant: 字体注册失败 %s', path)
    return 'Roboto'


def register_mono_font():
    """注册等宽字体（数字对齐用）；找不到就沿用中文字体。"""
    for path in SYSTEM_MONO_FONTS:
        if os.path.exists(path):
            try:
                LabelBase.register(name='Mono', fn_regular=path)
                return 'Mono'
            except Exception:
                Logger.exception('BleAssistant: 等宽字体注册失败 %s', path)
    return 'CJK'


class PatientStore(object):
    """患者信息（【患者身份】+ 蓝牙设备名）按账号保存在本机。

    登出再登录不会丢；新账号没有任何记录，显示"未绑定"。
    """

    def __init__(self, path):
        self._path = path
        self._items = {}
        self._load()

    def _load(self):
        try:
            with open(self._path, 'r', encoding='utf-8') as handle:
                raw = json.load(handle)
        except Exception:                                       # noqa: BLE001
            return
        if isinstance(raw, dict):
            self._items = raw

    def _save(self):
        try:
            with open(self._path, 'w', encoding='utf-8') as handle:
                json.dump(self._items, handle, ensure_ascii=False)
        except Exception:                                       # noqa: BLE001
            Logger.exception('BleAssistant: 保存患者信息失败')

    def get(self, username):
        item = self._items.get(username) or {}
        return {'label': str(item.get('label') or ''),
                'ble_name': str(item.get('ble_name') or '')}

    def save(self, username, label, ble_name):
        if not username:
            return
        self._items[username] = {'label': label, 'ble_name': ble_name}
        self._save()

    def clear(self, username):
        if username and username in self._items:
            del self._items[username]
            self._save()


def create_ble_manager():
    """按运行平台选择 BLE 实现。"""
    if platform == 'android':
        from ble_android import AndroidBleManager
        return AndroidBleManager()
    from ble_sim import SimulatedBleManager
    return SimulatedBleManager()


# ----------------------------------------------------------------------
# 控件
# ----------------------------------------------------------------------
# 渐变纹理只生成一次，之后按颜色组合缓存复用
_GRADIENT_CACHE = {}


def gradient_texture(color_a, color_b, steps=48, vertical=False):
    """生成一条线性渐变纹理（同一组颜色只生成一次）。"""
    key = (tuple(color_a), tuple(color_b), steps, vertical)
    cached = _GRADIENT_CACHE.get(key)
    if cached is not None:
        return cached
    texture = Texture.create(size=(steps, steps), colorfmt='rgba')
    buffer = bytearray()
    for y in range(steps):
        for x in range(steps):
            t = (y / (steps - 1.0)) if vertical else (x / (steps - 1.0))
            for index in range(4):
                value = color_a[index] + (color_b[index] - color_a[index]) * t
                buffer.append(max(0, min(255, int(value * 255))))
    texture.blit_buffer(bytes(buffer), colorfmt='rgba', bufferfmt='ubyte')
    texture.mag_filter = 'linear'
    texture.min_filter = 'linear'
    _GRADIENT_CACHE[key] = texture
    return texture


class _GradientCanvas(object):
    """渐变底图绘制逻辑（供 FloatLayout / 按钮复用）。

    关键点：底图必须画在**自己的一个 InstructionGroup** 里，不能用
    `self.canvas.clear()` —— Kivy 会把子部件的 canvas 挂到父部件的 canvas 下，
    一旦 clear() 就会把子 Label 的 canvas 一起清掉，字就全不显示了。
    """

    def _init_gradient(self):
        self._bg = InstructionGroup()
        self.canvas.add(self._bg)
        self.bind(pos=self._draw_gradient, size=self._draw_gradient)
        self.bind(color_a=self._draw_gradient, color_b=self._draw_gradient,
                  circle=self._draw_gradient, radius=self._draw_gradient,
                  border_color=self._draw_gradient)
        self._draw_gradient()

    def _shape_rect(self):
        """circle=True 时返回居中的正方形，保证画出来是正圆。"""
        side = min(self.width, self.height)
        return (self.center_x - side / 2.0, self.center_y - side / 2.0, side, side)

    def _draw_gradient(self, *args):
        group = getattr(self, '_bg', None)
        if group is None:
            return
        group.clear()
        if self.width <= 0 or self.height <= 0:
            return
        texture = gradient_texture(self.color_a, self.color_b)
        if self.circle:
            x, y, width, height = self._shape_rect()
        else:
            x, y, width, height = self.x, self.y, self.width, self.height
        group.add(Color(1, 1, 1, 1))
        if self.circle:
            # Ellipse 本身就能带纹理，不需要模板缓冲（stencil），更稳
            group.add(Ellipse(texture=texture, pos=(x, y), size=(width, height)))
        else:
            group.add(RoundedRectangle(texture=texture, pos=(x, y),
                                       size=(width, height), radius=[self.radius]))
        if self.border_color[3] > 0:
            group.add(Color(*self.border_color))
            if self.circle:
                group.add(Line(circle=(x + width / 2.0, y + height / 2.0,
                                       width / 2.0 - dp(1.5)), width=dp(2)))
            else:
                group.add(Line(rounded_rectangle=(x, y, width, height, self.radius),
                               width=dp(1.2)))


class GradientPanel(BoxLayout, _GradientCanvas):
    """带线性渐变背景的容器。

    必须用 BoxLayout：这个 Kivy 版本里，自定义 FloatLayout 型容器会把子部件的
    局部坐标设成**父容器自己的坐标**（双重偏移），导致内容整体错位——显示屏内容
    下移约 250dp、按钮文字被推出按钮外。BoxLayout 没有这个问题。
    """

    color_a = ListProperty(GRAD_NAVY_A)
    color_b = ListProperty(GRAD_NAVY_B)
    radius = NumericProperty(0)
    circle = BooleanProperty(False)
    border_color = ListProperty([0, 0, 0, 0])

    def __init__(self, **kwargs):
        kwargs.setdefault('orientation', 'vertical')
        super(GradientPanel, self).__init__(**kwargs)
        self._init_gradient()


class SquareButton(Button):
    """方形圆角按钮 —— 全 App 统一用它，不再有任何圆形按钮。

    filled=True 是实心（accent 为底色、白字）；filled=False 是白卡片 + accent 描边。
    """

    accent = ListProperty(COLOR_PRIMARY)
    filled = BooleanProperty(True)

    def on_state(self, _widget, value):
        self.opacity = 0.86 if value == 'down' else 1.0


class TabButton(SquareButton):
    """底部导航按钮（方形圆角，选中时实心）。"""

    active = BooleanProperty(False)


class StatusBar(BoxLayout):
    """顶部全局状态条：【患者身份】/ 断联记录 / 红色告警横幅。"""


class TaskRow(ButtonBehavior, BoxLayout):
    """「记录」页的一条待办：方形勾选框 + 标题（点整行切换勾选）。"""

    checked = BooleanProperty(False)

    def __init__(self, title, checked=False, on_toggle=None, **kwargs):
        super(TaskRow, self).__init__(orientation='horizontal',
                                      size_hint_y=None, height=dp(54),
                                      padding=(dp(48), 0, dp(12), 0), **kwargs)
        self.checked = checked
        self._on_toggle = on_toggle
        self._title = title
        self._bg = InstructionGroup()
        self.canvas.before.add(self._bg)
        self.bind(pos=self._draw, size=self._draw, checked=self._draw,
                  disabled=self._draw)
        app = App.get_running_app()
        self._label = Label(
            text=title, font_name=app.font_name if app else 'Roboto',
            font_size=sp(16), color=COLOR_TEXT, halign='left',
            valign='middle', size_hint_x=1)
        self._label.bind(size=lambda w, v: setattr(w, 'text_size', (v[0], v[1])))
        self.add_widget(self._label)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and not self.disabled:
            return True
        return super(TaskRow, self).on_touch_down(touch)

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos) and not self.disabled:
            if self._on_toggle is not None:
                self._on_toggle()
            return True
        return super(TaskRow, self).on_touch_up(touch)

    def _draw(self, *args):
        self._bg.clear()
        if self.width <= 0 or self.height <= 0:
            return
        # 行底：白色圆角卡片
        self._bg.add(Color(*COLOR_CARD))
        self._bg.add(RoundedRectangle(pos=self.pos, size=self.size,
                                      radius=[dp(12)]))
        self._bg.add(Color(*COLOR_LINE))
        self._bg.add(Line(rounded_rectangle=(self.x, self.y, self.width,
                                             self.height, dp(12)), width=1))
        # 勾选框：方形圆角 + 选中打勾
        side = dp(24)
        box_x = self.x + dp(12)
        box_y = self.center_y - side / 2.0
        if self.checked:
            self._bg.add(Color(*COLOR_OK))
            self._bg.add(RoundedRectangle(pos=(box_x, box_y), size=(side, side),
                                          radius=[dp(7)]))
            self._bg.add(Color(1, 1, 1, 1))
            self._bg.add(Line(points=(box_x + dp(6), box_y + side * 0.5,
                                      box_x + side * 0.44, box_y + dp(7),
                                      box_x + side - dp(5), box_y + side - dp(6)),
                              width=dp(2), joint='miter'))
        else:
            self._bg.add(Color(1, 1, 1, 1))
            self._bg.add(RoundedRectangle(pos=(box_x, box_y), size=(side, side),
                                          radius=[dp(7)]))
            self._bg.add(Color(*COLOR_DISABLED))
            self._bg.add(Line(rounded_rectangle=(box_x, box_y, side, side, dp(7)),
                              width=1.4))


class ScreenLine(Label):
    """显示屏里的一行白色提示文字。"""


class GateOverlay(FloatLayout):
    """未登录时盖在模块上的半透明灰色遮罩。

    注意：Kivy 里"什么都不画的容器"是**不消费触摸**的，点击会直接穿透到
    下面的按钮。所以这里必须显式把落在自己范围内的触摸吃掉。
    """

    def gate_active(self):
        """未登录时遮罩生效（显示 + 挡点击）。"""
        try:
            return not App.get_running_app().logged_in
        except Exception:                                       # noqa: BLE001
            return True

    def on_touch_down(self, touch):
        if self.gate_active() and self.collide_point(*touch.pos):
            return True                 # 吃掉点击，不再往下传
        return super(GateOverlay, self).on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.gate_active() and self.collide_point(*touch.pos):
            return True
        return super(GateOverlay, self).on_touch_move(touch)

    def on_touch_up(self, touch):
        if self.gate_active() and self.collide_point(*touch.pos):
            return True
        return super(GateOverlay, self).on_touch_up(touch)


class LogEntryRow(Label):
    """日志详情弹窗里的一行。"""


class DisplayPanel(BoxLayout):
    """深蓝渐变"显示屏"：白字日志（拖拽屏幕本身即可滚动，不再有右侧滑块）。

    这里刻意用 **BoxLayout** 而不是自定义的 FloatLayout 容器：
    实测把内容放进 FloatLayout 型渐变容器里时，背景画在正确位置、
    内容却整体下移约 250dp（面板上方留白、文字挤到中部）。换成 BoxLayout
    后由 Kivy 常规布局接管，位置稳定。
    渐变底图在 ui.kv 的 canvas.before 里用 app.navy_gradient 画。
    """

    def on_kv_post(self, _base_widget):
        self._last_width = -1.0
        # 可见宽度变了要按新宽度重新截断（第一次渲染时可能还没排版过）
        self.ids.dp_scroll.bind(width=self._on_view_width)
        App.get_running_app().bind(display_lines=self._render)
        self._render()

    def _on_view_width(self, _widget, value):
        if abs(value - self._last_width) < 1:
            return          # 只有宽度真的变了才重排，避免和布局互相触发
        self._last_width = value
        self._render()

    @staticmethod
    def fit_width(text, width):
        return fit_text_width(text, width)

    def text_width(self):
        """日志文字的可用宽度；还没排版时先估一个（宽度定了会再渲染一次）。"""
        width = self.ids.dp_scroll.width - dp(6)
        return width if width >= dp(120) else dp(280)

    def _render(self, *args):
        box = self.ids.dp_lines
        box.clear_widgets()
        width = self.text_width()
        lines = list(App.get_running_app().display_lines)
        if not lines:
            box.add_widget(ScreenLine(
                text=self.fit_width('（暂无信息：连接设备后，收发记录都在这里）', width)))
            return
        # 按时间顺序加入 → 最早的在最上面、最新的在最下面（像终端一样）
        for line in lines:
            box.add_widget(ScreenLine(text=self.fit_width(line, width)))
        # 每次都把最新一条滚到可见处（终端式）
        Clock.schedule_once(self._scroll_to_bottom, 0)
        Clock.schedule_once(self._scroll_to_bottom, 0.15)

    def _scroll_to_bottom(self, _dt):
        try:
            scroll = self.ids.dp_scroll
            rows = self.ids.dp_lines.children
            if rows:
                # rows[0] 是最后加入的那条 = 最新一条
                scroll.scroll_to(rows[0], padding=0, animate=False)
            else:
                scroll.scroll_y = 0.0
        except Exception:                                       # noqa: BLE001
            pass

class DeviceRow(ButtonBehavior, Label):
    """设备列表中的一行。"""


class ServiceRow(Label):
    """服务 / 特征列表中的一行。"""


class PopupRow(Label):
    """弹窗正文的一行。

    重要：弹窗里的文字一律用"一行一个固定高度标签"来渲染。
    这种写法在你的手机上已验证可正常显示（服务列表、设备列表都是它）；
    而"整块高度跟着文字纹理自适应"的标签在手机上会拿不到有效尺寸，显示成空白。
    """


class RootTabs(BoxLayout):
    """根容器：上面是页面，下面是常驻的底部导航栏。"""

    def on_kv_post(self, _base_widget):
        # 子页面都挂好之后再定位到「登录」模块
        # （不能在 KV 里写 current:，那时页面还没加进去）
        self.ids.sm.current = 'mine'

    def switch_tab(self, name):
        app = App.get_running_app()
        app.active_tab = name
        self.ids.sm.current = name


def show_info(title, message):
    # 正文按行渲染（每行一个固定高度标签）。超过可见范围的部分主动截断，
    # 避免"内容显示不全"看起来像坏了。
    text = message
    if len(text) > 600:
        text = text[:600] + '\n…（内容过长，已截断）'
    popup = InfoPopup(title=title, message=text)
    popup.open()
    return popup


class InfoPopup(Popup):
    """提示弹窗：正文一行一个固定高度标签。"""

    def __init__(self, title='', message='', **kwargs):
        super(InfoPopup, self).__init__(title=title, **kwargs)
        self.set_message(message)

    def set_message(self, message):
        try:
            box = self.ids.info_lines
        except Exception:                                       # noqa: BLE001
            return
        box.clear_widgets()
        for line in (message or '').split('\n'):
            box.add_widget(PopupRow(text=clip_line(line)))


class FavoriteStore(object):
    """「我的收藏」：连接成功的设备自动归档，支持取消收藏。

    存成一个 JSON 文件（放在 App 的私有目录里），重启 App 不会丢。
    """

    def __init__(self, path):
        self._path = path
        self._items = []
        self._load()

    def _load(self):
        try:
            with open(self._path, 'r', encoding='utf-8') as handle:
                raw = json.load(handle)
        except Exception:                                       # noqa: BLE001
            return
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict):
                continue
            address = str(item.get('address') or '').strip()
            if not address:
                continue
            self._items.append({'address': address,
                                'name': str(item.get('name') or '').strip()})

    def _save(self):
        try:
            with open(self._path, 'w', encoding='utf-8') as handle:
                json.dump(self._items, handle, ensure_ascii=False)
        except Exception:                                       # noqa: BLE001
            Logger.exception('BleAssistant: 保存收藏设备失败')

    def items(self):
        return [dict(item) for item in self._items]

    def has(self, address):
        return any(item['address'] == address for item in self._items)

    def add(self, device):
        """归档一台设备；已存在时只更新名字。返回是否是新收藏。"""
        address = str((device or {}).get('address') or '').strip()
        if not address:
            return False
        name = str((device or {}).get('name') or '').strip()
        for item in self._items:
            if item['address'] == address:
                if name and item['name'] != name:
                    item['name'] = name
                    self._save()
                return False
        self._items.append({'address': address, 'name': name or '未命名设备'})
        self._save()
        return True

    def remove(self, address):
        before = len(self._items)
        self._items = [item for item in self._items
                       if item['address'] != address]
        if len(self._items) != before:
            self._save()
            return True
        return False


class DevicePopup(Popup):
    """搜索并选择附近 BLE 设备的弹窗。

    列表每 3 秒刷新一次（以前是 0.6 秒，设备会"忽闪忽闪"根本点不中）。
    """

    REFRESH_INTERVAL = 3.0

    def __init__(self, ble, on_pick, **kwargs):
        super(DevicePopup, self).__init__(**kwargs)
        self._ble = ble
        self._on_pick = on_pick
        self._poll = None
        self._known = None

    def on_open(self, *args):
        super(DevicePopup, self).on_open(*args)
        self._known = None
        self._ble.start_scan()
        self._poll = Clock.schedule_interval(self._refresh, self.REFRESH_INTERVAL)
        self._refresh(0)

    def on_dismiss(self, *args):
        super(DevicePopup, self).on_dismiss(*args)
        if self._poll is not None:
            self._poll.cancel()
            self._poll = None
        self._ble.stop_scan()

    def open_favorites(self):
        """打开「我的收藏」（扫描继续在后台跑，收藏里只列当前扫得到的设备）。"""
        FavoritePopup(ble=self._ble, on_pick=self._pick).open()

    def _refresh(self, dt):
        title, detail, _connected = self._ble.status()
        self.ids.popup_status.text = '%s · %s' % (title, detail.split('\n')[0])
        self.ids.popup_diag.text = self._ble.diagnostics()

        devices = self._ble.devices()
        signature = tuple(device['address'] for device in devices)
        if signature == self._known:
            return
        self._known = signature

        box = self.ids.device_list
        box.clear_widgets()
        if not devices:
            box.add_widget(DeviceRow(text='正在搜索附近的 BLE 设备…',
                                     disabled=True))
            return
        for device in devices:
            name = (device.get('name') or '').strip()
            if not name or name.lower() in ('n/a', 'unknown', 'null', '(null)'):
                name = '未命名设备'
            row = DeviceRow()
            row.text = '%s\nMAC %s   信号 %d dBm' % (name, device['address'],
                                                     device['rssi'])
            row.bind(on_release=lambda widget, dev=device: self._pick(dev))
            box.add_widget(row)

    def _pick(self, device):
        self.dismiss()
        self._on_pick(device)

    def restart_scan(self):
        """重新发起一次扫描（授权后、或长时间搜不到时用）。"""
        self._known = None
        self._ble.start_scan()


class FavoritePopup(Popup):
    """「我的收藏」：只列出**当前扫描得到**的收藏设备，可取消收藏。

    收藏是"连接成功过的设备自动归档"，所以列表里的设备一定是你连过的；
    没在广播的设备不显示（连不上，显示了也没意义）。
    """

    def __init__(self, ble, on_pick, **kwargs):
        super(FavoritePopup, self).__init__(**kwargs)
        self._ble = ble
        self._on_pick = on_pick
        self._poll = None
        self._known = None
        self.refresh_list()

    def on_open(self, *args):
        super(FavoritePopup, self).on_open(*args)
        self._known = None
        self.refresh_list()
        self._poll = Clock.schedule_interval(self.refresh_list, 3.0)

    def on_dismiss(self, *args):
        super(FavoritePopup, self).on_dismiss(*args)
        if self._poll is not None:
            self._poll.cancel()
            self._poll = None

    def refresh_list(self, *args):
        app = App.get_running_app()
        store = app.favorites
        if store is None:
            return
        visible = dict((device['address'], device) for device in self._ble.devices())
        rows = []
        for item in store.items():
            device = visible.get(item['address'])
            if device is None:
                continue        # 没扫描到就不显示
            name = (device.get('name') or item.get('name') or '未命名设备').strip()
            rows.append((item['address'], name, int(device.get('rssi') or 0)))

        signature = tuple(row[0] for row in rows)
        if signature == self._known:
            return
        self._known = signature

        self.ids.fav_state.text = ('扫描到的收藏设备 %d 台（未扫描到的设备不显示）'
                                   % len(rows) if rows else '扫描到的设备里暂无收藏')
        box = self.ids.fav_list
        box.clear_widgets()
        if not rows:
            # 一行一个固定高度标签（多行写在同一个标签里会被行高裁掉）
            for text in ('还没有扫到收藏过的设备。',
                         '先在设备列表里连接一次，连接成功的设备会自动进入收藏；',
                         '设备在附近、正在搜索时才会显示在这里。'):
                box.add_widget(PopupRow(text=text))
            return
        for address, name, rssi in rows:
            box.add_widget(self._build_row(address, name, rssi))

    def _build_row(self, address, name, rssi):
        app = App.get_running_app()
        row = BoxLayout(orientation='horizontal', size_hint_y=None,
                        height=dp(60), spacing=dp(6))
        device_row = DeviceRow()
        device_row.size_hint_x = 1
        device_row.text = '%s\nMAC %s   信号 %d dBm' % (name, address, rssi)
        device_row.bind(on_release=lambda widget, addr=address: self._pick(addr))
        row.add_widget(device_row)

        # 取消收藏：只删这一台，别的收藏不受影响
        # 用默认按钮底图 + 红色着色，保证按下去有可见的红色块
        remove = Button(text='取消\n收藏', font_name=app.font_name,
                        font_size=sp(11), size_hint=(None, 1), width=dp(62),
                        background_color=COLOR_DANGER, color=(1, 1, 1, 1))
        remove.bind(on_release=lambda widget, addr=address: self._remove(addr))
        row.add_widget(remove)
        return row

    def _pick(self, address):
        device = None
        for item in self._ble.devices():
            if item['address'] == address:
                device = item
                break
        if device is None:
            return
        self.dismiss()
        self._on_pick(device)

    def _remove(self, address):
        app = App.get_running_app()
        if app.favorites is not None:
            app.favorites.remove(address)
            app.log_line('☆ 已取消收藏：%s' % address)
        self._known = None
        self.refresh_list()


class ServicesPopup(Popup):
    """列出已连接设备暴露的服务与特征，并显示模块自身信息。

    模块信息（固件版本/角色/波特率/状态显示/鉴权/名称）走模块自带的
    AT 指令通道读取——只走蓝牙、不经过串口，打开弹窗时会自动读一次。
    """

    def __init__(self, ble, **kwargs):
        super(ServicesPopup, self).__init__(**kwargs)
        self._ble = ble
        self._diag = None
        # 同上：建好先填一次服务列表，别等 on_open
        self.refresh_list()

    def on_open(self, *args):
        super(ServicesPopup, self).on_open(*args)
        self.refresh_list()
        self.refresh_module_info()

    def on_dismiss(self, *args):
        self._stop_diag()
        super(ServicesPopup, self).on_dismiss(*args)

    def _stop_diag(self):
        if self._diag is not None:
            self._diag.stop()
            self._diag = None

    def refresh_module_info(self, _retry=0):
        """读一次模块自身信息，填到弹窗下面的 6 行里。

        某一项查不到或格式不对，该行显示「输出异常」。
        刚连上时 App 可能正在自动锁定模块配置（同样占用 AT 通道），
        这时先等它做完，避免两边的 AT 回复互相抢。
        """
        app = App.get_running_app()
        if getattr(app, '_at_busy', False) and _retry < 10:
            self._set_module_state('模块信息（AT 通道读取）：等待自动配置完成…')
            Clock.schedule_once(
                lambda _dt: self.refresh_module_info(_retry + 1), 0.6)
            return

        self._stop_diag()
        self._diag = ModuleDiagRunner(
            ble=self._ble,
            on_lines=self._set_diag_lines,
            on_progress=self._set_module_state)
        if not self._diag.start():
            self._set_module_state('模块信息（AT 通道读取）：读取失败')

    def _set_diag_lines(self, lines):
        for index, text in enumerate(lines[:6], start=1):
            try:
                label = self.ids['svc_diag_%d' % index]
            except Exception:                                   # noqa: BLE001
                continue
            label.text = clip_line(text, 40)

    def _set_module_state(self, text):
        try:
            self.ids.module_state.text = clip_line(text, 30)
        except Exception:                                       # noqa: BLE001
            pass

    def retry_discovery(self):
        """手动重新发起服务发现，1 秒后刷新列表。"""
        self._ble.ensure_services(force=True)
        Clock.schedule_once(lambda dt: self.refresh_list(), 1.0)

    def copy_list(self):
        """把服务表原文复制到剪贴板，方便直接贴出来排查。"""
        count, message = self._ble.discovery_state()
        notify_state, notify_message = self._ble.notify_state()
        lines = ['已发现服务 %d 个 · %s' % (count, message or '—'),
                 '回传订阅：%s（%s）' % (_NOTIFY_STATE_TEXT.get(notify_state, '未知'),
                                        notify_message or '—'),
                 '缓存清理：%s' % (self._ble.cache_refresh_result() or '—'),
                 'App 配置的写入特征：%s' % ESP32_WRITE_UUID,
                 'App 配置的通知特征：%s' % ESP32_NOTIFY_UUID,
                 '']
        for item in self._ble.services_info():
            if item['characteristic']:
                lines.append('特征 %s  [%s]' % (item['characteristic'],
                                               item['properties'] or '未知'))
            else:
                lines.append('服务 %s' % item['service'])
        text = '\n'.join(lines)
        try:
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(text)
            show_info('已复制', '服务表内容已复制到剪贴板，直接粘贴出来即可。')
        except Exception:
            Logger.exception('BleAssistant: 复制服务表失败')
            show_info('复制失败', text)

    def refresh_list(self):
        count, message = self._ble.discovery_state()
        notify_state, notify_message = self._ble.notify_state()
        cache = self._ble.cache_refresh_result()
        self.ids.service_state.text = (
            '已发现服务 %d 个 · %s\n回传订阅：%s（%s）\n缓存清理：%s'
            % (count, message or '—',
               _NOTIFY_STATE_TEXT.get(notify_state, '未知'), notify_message or '—',
               cache or '—'))

        box = self.ids.service_list
        box.clear_widgets()
        items = self._ble.services_info()
        if not items:
            box.add_widget(ServiceRow(
                text='服务列表为空（服务发现未成功）。\n'
                     '点下面的「重新发现服务」重试；仍不行就断开重连，\n'
                     '或把手机蓝牙关一下再打开（清掉安卓的 GATT 缓存）后重试。'))
            return
        for item in items:
            row = ServiceRow()
            if item['characteristic']:
                row.text = '特征  %s\n属性  %s' % (item['characteristic'],
                                                  item['properties'] or '未知')
            else:
                row.text = '服务  %s' % item['service']
            box.add_widget(row)


class CommandInputPopup(Popup):
    """「开发者」：用户自己输入命令包并发送。

    输入框只接受**十六进制命令包**（偶数长度，例如 5401008031），按原样写进数据通道。
    发送过程与模块的 AT 回复都会同步显示在「控制」页的显示屏上。

    注意：这里已经**没有** HFUT / MECH / GREAT 示例快捷键了 —— 之前只是把它们
    的 opacity 设成 0，按钮本身还在原位、依然能点到，所以直接不再创建它们。
    """

    command = StringProperty('')
    state = StringProperty('输入十六进制命令包（偶数长度，如 5401008031），再点「发送」。')
    MAX_ROWS = 5

    def __init__(self, ble, on_closed=None, **kwargs):
        super(CommandInputPopup, self).__init__(**kwargs)
        self._ble = ble
        self._on_closed = on_closed
        self._lines = []
        self._timer = None
        self._deadline = 0.0

    # ------------------------------------------------------------------
    def on_open(self, *args):
        Clock.schedule_once(self._focus_input, 0.6)

    def _focus_input(self, dt):
        try:
            self.ids.cmd_input.focus = True
        except Exception:                                       # noqa: BLE001
            pass

    def _resolve(self, text):
        """输入 → (命令包十六进制, 说明)；无法识别时返回 (None, 原因)。"""
        raw = (text or '').strip()
        if not raw:
            return None, '请先输入命令内容。'
        compact = raw.replace(' ', '').replace('-', '').upper()
        if (len(compact) >= 2 and len(compact) % 2 == 0
                and all(ch in '0123456789ABCDEF' for ch in compact)):
            return compact, '自定义命令包（%d 字节）' % (len(compact) // 2)
        return None, '无法识别：请输入偶数长度的十六进制命令包（如 5401008031）。'

    def send(self):
        app = App.get_running_app()
        hex_data, note = self._resolve(self.command)
        if hex_data is None:
            self.state = note
            return
        if len(hex_data) // 2 > MAX_PAYLOAD:
            self.state = '命令包 %d 字节，超过单次写入上限 %d 字节。' % (
                len(hex_data) // 2, MAX_PAYLOAD)
            return
        if not app.connected:
            self.state = '未连接设备：请先回「控制」页连接 BLE 设备。'
            return

        self._lines = []
        self._render()
        accepted, message = self._ble.send_command(ESP32_SERVICE_UUID,
                                                   ESP32_WRITE_UUID,
                                                   hex_data,
                                                   auto_pick=ESP32_AUTO_PICK_WRITE)
        if not accepted:
            self.state = '下发失败：%s' % message
            app.log_line('✗ 开发者 下发失败：%s' % (message or '未知原因'))
            return

        # 和「启动」「停止」一样：发送动作本身也要在显示屏上留痕
        app.log_line('→ 已发送 开发者（%d 字节）：%s'
                     % (len(hex_data) // 2, spaced_hex(hex_data)))
        app.expect_return()
        self.state = '已发送 %s，等待写入完成…' % note
        if not app.ping_module():
            app.log_line('（AT 通道未就绪，本次没有做模块在线确认）')
        self._deadline = time.monotonic() + WRITE_TIMEOUT
        if self._timer is not None:
            self._timer.cancel()
        self._timer = Clock.schedule_interval(self._poll, 0.2)

    def _poll(self, dt):
        state, message = self._ble.write_state()
        if state == WRITE_SUCCESS:
            self._stop_poll()
            self.state = '命令已写入设备，等待模块回复…'
            App.get_running_app().log_line('开发者：命令已写入设备')
            return
        if state == WRITE_FAILED:
            self._stop_poll()
            self.state = '写入失败：%s' % (message or '未知原因')
            App.get_running_app().log_line('✗ 开发者 写入失败：%s'
                                           % (message or '未知原因'))
            return
        if time.monotonic() >= self._deadline:
            self._stop_poll()
            self.state = '写入超时，请检查连接后重试。'
            App.get_running_app().log_line('✗ 开发者 写入超时')

    def add_reply(self, cmd, text, raw_hex):
        """把收到的设备回传追加进弹窗（由主界面转发过来）。"""
        if text.strip():
            shown = text.strip()
        else:
            shown = '（非文本载荷，原始：%s）' % (raw_hex or '空')
        self._lines.append(clip_line('回传 0x%02X：%s' % (cmd, shown), 46))
        self._render()
        self.state = '收到设备回传：%s' % clip_line(shown, 16)

    def _stop_poll(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _render(self):
        box = self.ids.cmd_reply
        box.clear_widgets()
        lines = self._lines[-self.MAX_ROWS:] or ['（还没有收到回传）']
        # 按时间顺序加入：Kivy 的 BoxLayout 会把最后加入的放在最上面，
        # 所以最新的回传显示在最上方（与「查看回传记录」用同一套写法）。
        for line in lines:
            box.add_widget(PopupRow(text=line))

    def on_dismiss(self, *args):
        self._stop_poll()
        if self._on_closed is not None:
            self._on_closed()


class BaudRatePopup(Popup):
    """「波特率」：输入框 + 9600 / 115200 两个预置值，用 AT+UART 实时改模块串口波特率。

    AT+UART 是"立即生效、掉电保存"的（手册第 54 页）；它改的是模块与单片机之间
    的串口速率，不影响 BLE 链路，所以模块的 AT 回复照样能收到。
    每次连接 App 会自动把模块锁成 MODULE_TARGET_BAUD（9600）。
    """

    value = StringProperty('')
    state = StringProperty('输入波特率后点「发送」；也可以直接点下面的预置值。')
    MAX_ROWS = 4
    MIN_BAUD, MAX_BAUD = 1200, 1000000

    def __init__(self, ble, **kwargs):
        super(BaudRatePopup, self).__init__(**kwargs)
        self._ble = ble
        self._lines = []
        self._render()
        # 模块的回复由 App 统一从 AT 通道取出来再分发（和「服务/特征」同一套机制）
        try:
            App.get_running_app().register_at_sink(self.on_at_chunk)
        except Exception:                                       # noqa: BLE001
            Logger.exception('BleAssistant: 波特率弹窗登记 AT 回复失败')

    def on_dismiss(self, *args):
        try:
            App.get_running_app().unregister_at_sink(self.on_at_chunk)
        except Exception:                                       # noqa: BLE001
            pass
        super(BaudRatePopup, self).on_dismiss(*args)

    # ------------------------------------------------------------------
    def on_at_chunk(self, text):
        """模块对 AT+UART 的回复。"""
        flat = ' '.join((text or '').split())
        if not flat:
            return
        self._lines.append(clip_line(flat, 46))
        self._render()
        self.state = '模块回复：%s' % clip_line(flat, 22)

    def choose(self, baud):
        """点预置值：填进输入框并立即下发。"""
        self.value = str(baud)
        self.send()

    def send(self):
        raw = (self.value or '').strip()
        if not raw.isdigit():
            self.state = '请输入数字波特率（例如 9600）。'
            return
        baud = int(raw)
        if baud < self.MIN_BAUD or baud > self.MAX_BAUD:
            self.state = '波特率范围 %d ~ %d。' % (self.MIN_BAUD, self.MAX_BAUD)
            return
        app = App.get_running_app()
        if not app.connected:
            self.state = '未连接设备：请先回「控制」页连接 BLE 设备。'
            return
        if not getattr(app, '_at_subscribed', False):
            self.state = 'AT 通道未就绪，请等连接完成后再试。'
            return

        command = 'AT+UART=%d' % baud
        accepted, message = self._ble.send_command(
            '', ESP32_AT_UUID, to_hex((command + '\r\n').encode('utf-8')))
        if not accepted:
            self.state = '下发失败：%s' % (message or '未知原因')
            app.log_line('✗ 波特率 下发失败：%s' % (message or '未知原因'))
            return
        app.log_line('→ 已发送 波特率：%s' % command)
        self._lines.append('→ ' + command)
        self._render()
        self.state = '已下发 %s，等待模块回复…' % command

    def _render(self):
        box = self.ids.baud_reply
        box.clear_widgets()
        lines = self._lines[-self.MAX_ROWS:] or ['（模块回复会显示在这里）']
        for line in lines:
            box.add_widget(PopupRow(text=line))


def clip_hint(text):
    """卡片/弹窗里的灰色提示行（固定高度，不会被裁掉）。"""
    app = App.get_running_app()
    label = Label(text=text, font_name=app.font_name if app else 'Roboto',
                  font_size=sp(14), color=COLOR_TEXT_WEAK, halign='left',
                  valign='middle', size_hint_y=None, height=dp(40))
    label.bind(size=lambda w, v: setattr(w, 'text_size', (v[0], v[1])))
    return label


class DoneRow(Label):
    """「已完成」折叠区里的一行。"""

    def __init__(self, title, **kwargs):
        app = App.get_running_app()
        super(DoneRow, self).__init__(
            text='✓  %s' % title,
            font_name=app.font_name if app else 'Roboto',
            font_size=sp(15), color=COLOR_TEXT_WEAK, halign='left',
            valign='middle', size_hint_y=None, height=dp(40), **kwargs)
        self.bind(size=lambda w, v: setattr(w, 'text_size', (v[0], v[1])))


class ConfirmPopup(Popup):
    """二次确认弹窗（批量确认等）。"""

    message = StringProperty('')

    def __init__(self, title='', message='', on_yes=None, **kwargs):
        super(ConfirmPopup, self).__init__(title=title, **kwargs)
        self.message = message
        self._on_yes = on_yes

    def confirm(self):
        self.dismiss()
        if self._on_yes is not None:
            self._on_yes()


class PatientPopup(Popup):
    """患者信息：上一块任意文本（患者身份），下一块只能英文 + 数字（蓝牙模块名）。"""

    label_text = StringProperty('')
    name_text = StringProperty('')
    state_text = StringProperty('')

    def __init__(self, app, **kwargs):
        super(PatientPopup, self).__init__(**kwargs)
        self._app = app
        data = app.patients.get(app.current_user)
        self.label_text = data.get('label') or ''
        self.name_text = data.get('ble_name') or ''
        editing = bool(self.label_text or self.name_text)
        self.title = '患者信息修改' if editing else '患者信息'
        self.state_text = ('修改后需点「确认」才会生效' if editing
                           else '第一行填患者姓名/床号，第二行只能英文和数字')

    def confirm(self):
        label = (self.label_text or '').strip()
        name = (self.name_text or '').strip()
        if not label:
            self.state_text = '第一行不能为空：请填写患者姓名 / 床号'
            return
        if not name or not all(ch.isascii() and ch.isalnum() for ch in name):
            self.state_text = '第二行只能包含英文字母和数字，请重填'
            return
        self.dismiss()
        self._app.apply_patient(label, name)


# ----------------------------------------------------------------------
# 模块诊断（AT 指令通道，只走蓝牙）
# ----------------------------------------------------------------------
AT_QUERIES = ['AT+VERSION', 'AT+ROLE?', 'AT+UART?', 'AT+STATUS?', 'AT+AUTH?', 'AT+NAME?']

AT_QUERY_LABELS = (('AT+VERSION', '固件版本'), ('AT+ROLE', '设备角色'),
                   ('AT+UART', '串口波特率'), ('AT+STATUS', '状态显示'),
                   ('AT+AUTH', '用户鉴权'), ('AT+NAME', '设备名称'))

# 每行最多这么多字符：保证一行放得下、不会被折行后截掉（手机上字体被放大也不会出问题）
LINE_LIMIT = 40


def clip_line(text, limit=LINE_LIMIT):
    """把过长的行截断，保证"一行一个固定高度标签"永远放得下。"""
    if len(text) <= limit:
        return text
    return text[:limit - 1] + '…'


# 某一项 AT 查询没有回复、或回复格式不对时，该行统一显示这个
BAD_OUTPUT = '输出异常'


class ModuleConfigRunner(object):
    """连上模块后自动把它的配置锁定：串口波特率 9600 + 设备名 HFUT.BLE。

    走模块自带的 AT 指令通道（6E400004，只走蓝牙、不经过串口），
    因此完全不需要电脑端脚本参与。
    """

    def __init__(self, ble, on_done=None):
        self._ble = ble
        self._on_done = on_done
        self._replies = []
        self._sent = 0
        self._elapsed = 0.0
        self._timer = None
        self._finished = False

    def start(self):
        state, _message = self._ble.at_notify_state()
        if state != NOTIFY_SUBSCRIBED:
            return False
        self._elapsed = 0.0
        App.get_running_app().register_at_sink(self.on_at_chunk)
        self._timer = Clock.schedule_interval(self._step, 0.45)
        return True

    def stop(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        try:
            App.get_running_app().unregister_at_sink(self.on_at_chunk)
        except Exception:                                       # noqa: BLE001
            pass

    def on_at_chunk(self, text):
        self._replies.append(text)

    def _step(self, dt):
        self._elapsed += dt
        if self._sent < len(MODULE_SETUP_COMMANDS):
            command = MODULE_SETUP_COMMANDS[self._sent]
            self._sent += 1
            self._ble.send_command('', ESP32_AT_UUID,
                                   to_hex((command + '\r\n').encode('utf-8')))
            return
        if self._elapsed > len(MODULE_SETUP_COMMANDS) * 0.45 + 1.6:
            self.stop()
            self._done()

    def _done(self):
        if self._finished:
            return
        self._finished = True
        if self._on_done is not None:
            self._on_done(self.ok())

    def ok(self):
        return 'OK' in ''.join(self._replies)


class ModuleDiagRunner(object):
    """按节奏发送 6 条 AT 查询、收集回复，结果交给回调显示。

    用于「服务/特征」弹窗里的"模块信息"：查不到或格式不对的那一项会显示
    「输出异常」。走模块自带的 AT 指令通道（6E400004），只走蓝牙、不经过串口。
    """

    def __init__(self, ble, on_lines=None, on_progress=None):
        self._ble = ble
        self._on_lines = on_lines
        self._on_progress = on_progress
        self._replies_text = []
        self._timer = None
        self._sent = 0
        self._elapsed = 0.0
        self._at_bytes = 0
        self._finished = False

    def start(self):
        state, _message = self._ble.at_notify_state()
        if state != NOTIFY_SUBSCRIBED:
            self._progress('AT 通道未订阅，读取失败')
            self._emit_lines(['%s：%s' % (name, BAD_OUTPUT)
                              for _key, name in AT_QUERY_LABELS])
            return False
        App.get_running_app().register_at_sink(self.on_at_chunk)
        self._progress('读取模块信息 0/6')
        self._emit_lines(['%s：查询中…' % name for _key, name in AT_QUERY_LABELS])
        self._timer = Clock.schedule_interval(self._step, 0.35)
        return True

    def stop(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        try:
            App.get_running_app().unregister_at_sink(self.on_at_chunk)
        except Exception:                                       # noqa: BLE001
            pass

    def on_at_chunk(self, text):
        """收到一段模块 AT 回复（由 App 统一分发过来）。"""
        self._at_bytes += len(text.encode('utf-8', 'replace'))
        for line in text.replace('\r', '').split('\n'):
            line = line.strip()
            if line:
                self._replies_text.append(line)

    def _step(self, dt):
        self._elapsed += dt
        self._emit_lines()
        if self._sent < len(AT_QUERIES):
            query = AT_QUERIES[self._sent]
            self._sent += 1
            self._ble.send_command('', ESP32_AT_UUID,
                                   to_hex((query + '\r\n').encode('utf-8')))
            self._progress('读取模块信息 %d/6' % self._sent)
            return
        if self._elapsed > len(AT_QUERIES) * 0.35 + 2.5:
            self.stop()
            self._done()

    def value_of(self, key):
        for text in self._replies_text:
            if text.startswith(key):
                return text
        return ''

    def lines(self):
        """6 行检验结果；某一项查不到或格式不对，该行显示"输出异常"。"""
        out = []
        for key, name in AT_QUERY_LABELS:
            value = self.value_of(key)
            if not value or not value.startswith(key + '='):
                out.append('%s：%s' % (name, BAD_OUTPUT))
            else:
                out.append(clip_line('%s：%s' % (name, value.split(' OK')[0].strip()), 40))
        return out

    def _emit_lines(self, lines=None):
        if self._on_lines is not None:
            self._on_lines(self.lines() if lines is None else lines)

    def _progress(self, text):
        if self._on_progress is not None:
            self._on_progress(text)

    def _done(self):
        if self._finished:              # 防止重复收尾
            return
        self._finished = True
        self._emit_lines()
        self._progress('模块信息（AT 通道读取）')


# ----------------------------------------------------------------------
# 页面
# ----------------------------------------------------------------------
class LoginScreen(Screen):
    message = StringProperty('')
    message_ok = BooleanProperty(False)

    def reset(self):
        self.ids.username.text = ''
        self.ids.password.text = ''
        self.message = ''
        self.message_ok = False

    def prepare(self, username, hint):
        """注册成功后回到登录页时调用。"""
        self.ids.username.text = username
        self.ids.password.text = ''
        self.message = hint
        self.message_ok = True

    def do_login(self):
        app = App.get_running_app()
        username = self.ids.username.text
        ok, msg = app.store.verify(username, self.ids.password.text)
        self.message = msg
        self.message_ok = ok
        if not ok:
            return
        self.ids.password.text = ''
        app.login_succeeded(username.strip())

    def goto_register(self):
        self.message = ''
        self.message_ok = False
        self.manager.current = 'register'


class RegisterScreen(Screen):
    message = StringProperty('')
    message_ok = BooleanProperty(False)

    def reset(self):
        self.ids.username.text = ''
        self.ids.password.text = ''
        self.ids.confirm.text = ''
        self.message = ''
        self.message_ok = False

    def do_register(self):
        app = App.get_running_app()
        username = self.ids.username.text.strip()
        ok, msg = app.store.register(self.ids.username.text,
                                     self.ids.password.text,
                                     self.ids.confirm.text)
        self.message = msg
        self.message_ok = ok
        if not ok:
            return
        app.screen('loginform').prepare(username, msg)
        self.reset()
        self.manager.current = 'loginform'

    def back_to_login(self):
        self.reset()
        self.manager.current = 'loginform'


class _BleActions(object):
    """控制页 / 开发者页共用的蓝牙动作（两页共用同一个 App 状态，互相继承）。"""

    def open_device_dialog(self):
        app = App.get_running_app()
        if app.connected:
            show_info('已连接', '当前已连接设备，如需更换请先点击「断开连接」。')
            return
        DevicePopup(ble=app.ble, on_pick=self._on_device_picked).open()

    def _on_device_picked(self, device):
        app = App.get_running_app()
        # 连接成功后自动归档到「我的收藏」（真正连上时才记，见 App._poll_ble）
        app.pending_favorite = device
        app.ble.connect(device['address'])

    def do_disconnect(self):
        app = App.get_running_app()
        app.ble.disconnect()
        app.note_manual_disconnect()


class CtrlScreen(_BleActions, Screen):
    """「控制」：设备监测卡 + 9 个功能键 + 蓝牙/患者/开发者。

    BLE 的轮询与接收统一放在 App 上（切到别的页也不会断），这里只负责界面动作。
    """

    def press_function(self, name):
        app = App.get_running_app()
        if not app.connected:
            show_info('未连接', '请先连接 BLE 设备，再使用该功能。')
            return
        spec = FUNCTION_BY_NAME.get(name)
        if spec is None:
            return
        hex_data, action, seconds = spec
        if not self.send_hex(name, hex_data):
            return
        app.apply_device_action(action, seconds)

    def open_patient(self):
        app = App.get_running_app()
        if not app.connected:
            show_info('未连接', '请先连接 BLE 设备，再填写患者信息（需要用 AT 指令改模块名称）。')
            return
        PatientPopup(app).open()

    def open_developer(self):
        App.get_running_app().enter_dev_mode()

    def send_hex(self, name, hex_data):
        """把一段十六进制命令包写进数据通道；返回是否已受理。"""
        app = App.get_running_app()
        if not app.connected:
            show_info('未连接', '请先连接 BLE 设备，再下发命令。')
            return False

        # 没有服务表就写不进去：先催一次服务发现，别让你对着"发送中…"干等
        service_count, _message = app.ble.discovery_state()
        if service_count <= 0:
            app.ble.ensure_services(force=True)
            app.log_line('✗ %s：设备服务尚未就绪，已重新发起服务发现，请 1~2 秒后再点' % name)
            return False

        if len(hex_data) // 2 > MAX_PAYLOAD:
            app.log_line('✗ %s：命令 %d 字节，超过单次写入上限 %d 字节'
                         % (name, len(hex_data) // 2, MAX_PAYLOAD))
            return False

        accepted, message = app.ble.send_command(ESP32_SERVICE_UUID,
                                                 ESP32_WRITE_UUID,
                                                 hex_data,
                                                 auto_pick=ESP32_AUTO_PICK_WRITE)
        if not accepted:
            app.log_line('✗ %s 下发失败：%s' % (name, message or '未知原因'))
            show_info('命令下发失败', '%s\n\n%s' % (message, self._feature_hint(app.ble)))
            return False
        app.log_line('→ 已发送 %s（%d 字节）：%s'
                     % (name, len(hex_data) // 2, spaced_hex(hex_data)))
        # 等模块的回传命令包；一直没收到就明确写"0字节，未读取到有效信息"
        app.expect_return()
        # 顺手向模块发一条 AT 查询，确认模块在线、蓝牙链路双向都通
        if not app.ping_module():
            app.log_line('（AT 通道未就绪，本次没有做模块在线确认）')
        return True

    def clear_screen(self):
        """一键清屏：只清显示屏里的提示信息。"""
        app = App.get_running_app()
        app.clear_display()
        app.log_line('已清屏')

    def _feature_hint(self, ble):
        """列出设备上可写 / 可通知的特征，UUID 填错时一眼知道该填什么。"""
        writable = []
        notify_able = []
        for item in ble.services_info():
            uuid = item['characteristic']
            if not uuid:
                continue
            properties = item['properties'] or ''
            if 'WRITE' in properties:
                writable.append(uuid)
            if 'NOTIFY' in properties or 'INDICATE' in properties:
                notify_able.append(uuid)

        lines = ['App 里配置的写入特征：%s' % ESP32_WRITE_UUID,
                 'App 里配置的通知特征：%s' % ESP32_NOTIFY_UUID,
                 '',
                 '设备上可写的特征：']
        if writable:
            lines.extend('  %s' % uuid for uuid in writable)
        else:
            lines.append('  （无）')
        lines.append('')
        lines.append('设备上可通知的特征：')
        if notify_able:
            lines.extend('  %s' % uuid for uuid in notify_able)
        else:
            lines.append('  （无）')
        return '\n'.join(lines)


class DevScreen(_BleActions, Screen):
    """「开发者模式」：滚动显示屏 + 蓝牙键 + 信息复原 + 退出。"""

    def clear_screen(self):
        app = App.get_running_app()
        app.clear_display()
        app.log_line('已清屏')

    def restore_info(self):
        """信息复原：患者身份清空为未绑定，模块名改回 HFUT.BLE。"""
        App.get_running_app().restore_patient()

    def exit_dev(self):
        App.get_running_app().exit_dev_mode()

    # 设备回传的统一处理在 App._on_reply 里（写进显示屏）

class LogsScreen(Screen):
    """「记录」：待办任务 + 已完成折叠区 + 交接班摘要。"""

    def __init__(self, **kwargs):
        super(LogsScreen, self).__init__(**kwargs)
        self._done_open = False

    def on_pre_enter(self, *args):
        self.refresh()

    def refresh(self):
        app = App.get_running_app()
        try:
            box = self.ids.task_list
        except Exception:                                       # noqa: BLE001
            return
        box.clear_widgets()
        pending = [(index, item) for index, item in enumerate(list(app.tasks))
                   if not item.get('done')]
        for index, item in pending:
            box.add_widget(TaskRow(
                item['title'], checked=False,
                on_toggle=lambda i=index: self.toggle_task(i)))
        if not pending:
            box.add_widget(clip_hint('全部待办已处理完毕'))
        box.height = max(box.minimum_height, dp(1))
        self._refresh_done(app)
        self._refresh_summary(app)

    def _refresh_done(self, app):
        done = [item for item in app.tasks if item.get('done')]
        try:
            self.ids.done_header.text = '已完成（%d）  %s' % (
                len(done), '▼' if self._done_open else '▶')
            box = self.ids.done_list
        except Exception:                                       # noqa: BLE001
            return
        box.clear_widgets()
        if not self._done_open:
            box.height = 0
            box.opacity = 0
            box.disabled = True
            return
        box.opacity = 1
        box.disabled = False
        if not done:
            box.add_widget(clip_hint('还没有已完成的任务'))
        for item in done:
            box.add_widget(DoneRow(item['title']))
        box.height = max(box.minimum_height, dp(1))

    def _refresh_summary(self, app):
        pending = len([item for item in app.tasks if not item.get('done')])
        try:
            self.ids.summary.text = (
                '本班患者名称：%s\n处理告警 %d 条、待跟进 %d 项'
                % (app.patient_label, app.alarm_count, pending))
        except Exception:                                       # noqa: BLE001
            pass

    def toggle_done(self):
        self._done_open = not self._done_open
        self.refresh()

    def toggle_task(self, index):
        app = App.get_running_app()
        tasks = [dict(item) for item in app.tasks]
        if index >= len(tasks):
            return
        tasks[index]['done'] = not tasks[index]['done']
        app.tasks = tasks
        app.log_line(('✓ 已完成：' if tasks[index]['done'] else '↺ 恢复待办：')
                     + tasks[index]['title'])
        self.refresh()

    def confirm_all(self):
        app = App.get_running_app()
        if app.tasks and all(item.get('done') for item in app.tasks):
            show_info('批量确认', '当前没有未完成的待办任务。')
            return
        ConfirmPopup(
            title='批量确认',
            message='确认把全部待办任务标记为已完成？\n\n该操作会同时更新交接班摘要。',
            on_yes=self._do_confirm_all).open()

    def _do_confirm_all(self):
        app = App.get_running_app()
        app.tasks = [dict(item, done=True) for item in app.tasks]
        app.log_line('✓ 批量确认：全部待办标记为已完成')
        app.show_notice('批量确认完成')
        self.refresh()


class MineScreen(Screen):
    """「登录」：用户登录 / 紧急呼叫 / 患者信息 / 常见问题 / 版本信息。"""

    def open_login(self):
        app = App.get_running_app()
        if app.logged_in:
            show_info('当前账号',
                      '当前用户：%s\n\n'
                      '如需切换账号，请点下面的「退出登录」。\n'
                      '退出后「控制」「记录」会重新上锁。' % (app.current_user or '-'))
            return
        app.active_tab = 'mine'
        self.manager.current = 'loginform'

    def do_logout(self):
        App.get_running_app().logout()

    def open_patient(self):
        app = App.get_running_app()
        if not app.logged_in:
            show_info('患者信息', '请先登录。')
            return
        data = app.patients.get(app.current_user)
        show_info('患者信息',
                  '患者身份：%s\n蓝牙模块名称：%s\n\n'
                  '如需修改，请到「控制」页点「患者信息」（需先连接蓝牙）。'
                  % (app.patient_label, data.get('ble_name') or '未绑定'))

    def open_faq(self):
        show_info('常见问题',
                  '1. 搜索不到设备？\n'
                  '   确认蓝牙已打开、设备在附近，并已允许「附近的设备」权限。\n\n'
                  '2. 连接后按钮是灰的？\n'
                  '   说明蓝牙未连上，请重新点「蓝牙连接」。\n\n'
                  '3. 下发命令无回传？\n'
                  '   显示屏会写「0字节，未读取到有效信息」，请检查模块与串口。')

    def open_version(self):
        show_info('版本信息', '%s\n%s\n\n当前版本：%s'
                  % (APP_NAME, APP_SUBTITLE, APP_VERSION))

    def reserved(self, name):
        show_info(name, '「%s」暂时预留。' % name)


# ----------------------------------------------------------------------
# App
# ----------------------------------------------------------------------
class BleAssistantApp(App):
    title = APP_NAME

    font_name = StringProperty('Roboto')
    mono_font = StringProperty('Roboto')
    current_user = StringProperty('')
    logged_in = BooleanProperty(False)
    active_tab = StringProperty('mine')
    dev_mode = BooleanProperty(False)

    # 连接状态（由 App 统一轮询，切到任何页面都不会中断）
    status_text = StringProperty('未连接')
    status_detail = StringProperty('点击「蓝牙连接」搜索附近的 BLE 设备')
    connected = BooleanProperty(False)

    # 顶部全局状态条：【患者身份】/ 断联记录 / 告警横幅
    patient_label = StringProperty('未绑定')
    bar_mode = StringProperty('patient')      # patient / notice / alarm
    bar_message = StringProperty('')
    bar_opacity = NumericProperty(1.0)

    # 设备监测卡
    battery_text = StringProperty('NA')
    pressure_text = StringProperty('NA')
    temp_text = StringProperty('NA')
    ble_state_text = StringProperty('未连接')
    pump1 = StringProperty('关')
    pump2 = StringProperty('关')
    device_state_text = StringProperty('泵1 关 · 泵2 关')
    countdown_text = StringProperty('')

    # 显示屏内容 / 待办任务 / 告警计数
    display_lines = ListProperty([])
    tasks = ListProperty([])
    at_reply_count = NumericProperty(0)
    alarm_count = NumericProperty(0)

    COLOR_PRIMARY = ListProperty(COLOR_PRIMARY)
    COLOR_PRIMARY_DARK = ListProperty(COLOR_PRIMARY_DARK)
    COLOR_BLUE = ListProperty(COLOR_BLUE)
    COLOR_BG = ListProperty(COLOR_BG)
    COLOR_CARD = ListProperty(COLOR_CARD)
    COLOR_LINE = ListProperty(COLOR_LINE)
    COLOR_TEXT = ListProperty(COLOR_TEXT)
    COLOR_TEXT_WEAK = ListProperty(COLOR_TEXT_WEAK)
    COLOR_DANGER = ListProperty(COLOR_DANGER)
    COLOR_WARN_HIGH = ListProperty(COLOR_WARN_HIGH)
    COLOR_WARN_MID = ListProperty(COLOR_WARN_MID)
    COLOR_OK = ListProperty(COLOR_OK)
    COLOR_DISABLED = ListProperty(COLOR_DISABLED)

    GRAD_NAVY_A = ListProperty(GRAD_NAVY_A)
    GRAD_NAVY_B = ListProperty(GRAD_NAVY_B)
    GRAD_TEAL_A = ListProperty(GRAD_TEAL_A)
    GRAD_TEAL_B = ListProperty(GRAD_TEAL_B)

    # 渐变底图（在 KV 的 canvas.before 里用，避免自定义布局类的定位问题）
    navy_gradient = ObjectProperty(None, allownone=True)
    teal_gradient = ObjectProperty(None, allownone=True)
    # 设备徽章图片（eg.png 里显示屏右侧那张，直接打包进来显示）
    badge_source = StringProperty('')
    # 开发者自定义包弹窗（回传要转发给它）
    cmd_popup = ObjectProperty(None, allownone=True)

    def build(self):
        self.font_name = register_cjk_font()
        self.mono_font = register_mono_font()
        self.ble = create_ble_manager()
        self.navy_gradient = gradient_texture(GRAD_NAVY_A, GRAD_NAVY_B)
        self.teal_gradient = gradient_texture(GRAD_TEAL_A, GRAD_TEAL_B)
        self.badge_source = BADGE_FILE if os.path.exists(BADGE_FILE) else ''
        self.store = AccountStore(os.path.join(self.user_data_dir, 'accounts.db'))
        self.patients = PatientStore(
            os.path.join(self.user_data_dir, 'patient.json'))
        self.favorites = FavoriteStore(
            os.path.join(self.user_data_dir, 'favorites.json'))
        self.pending_favorite = None
        self._patient_ble_name = ''
        self._parser = RxFrameParser()
        self._notify_subscribed = False
        self._at_subscribed = False
        self._module_configured = False
        self._at_busy = False
        self._at_sinks = []
        self._config_runner = None
        self._poll = None
        # 回传命令包：收到的包数 + "发出后等回传"的超时定时器
        self._rx_packets = 0
        self._return_timer = None
        self._return_base = 0
        # GATT 偶发报断开时的防抖计数
        self._disconnect_streak = 0
        # 顶部状态条 / 倒计时
        self._bar_event = None
        self._countdown_event = None
        self._countdown_left = 0
        self._manual_disconnect = False
        self.last_snapshot = []

        Window.bind(on_keyboard=self._on_keyboard)
        Builder.load_file(KV_FILE)
        root = RootTabs()
        Clock.schedule_once(self._start_poll, 0.5)
        return root

    # ------------------------------------------------------------------
    # 通用
    # ------------------------------------------------------------------
    def screen(self, name):
        """按名字取页面（页面都在 RootTabs 里的 ScreenManager 下）。"""
        return self.root.ids.sm.get_screen(name)

    def _start_poll(self, _dt):
        if self._poll is None:
            self._poll = Clock.schedule_interval(self._poll_ble, 0.4)

    # ------------------------------------------------------------------
    # 显示屏
    # ------------------------------------------------------------------
    def log_line(self, text):
        """往显示屏追加一行（带时间戳，最多保留 MAX_DISPLAY_LINES 行）。"""
        lines = list(self.display_lines)
        lines.append('[%s] %s' % (time.strftime('%H:%M:%S'), text))
        if len(lines) > MAX_DISPLAY_LINES:
            del lines[:-MAX_DISPLAY_LINES]
        self.display_lines = lines

    def clear_display(self):
        self.display_lines = []

    # ------------------------------------------------------------------
    # 登录 / 退出
    # ------------------------------------------------------------------
    def login_succeeded(self, username):
        self.current_user = username
        self.logged_in = True
        self._load_patient(username)
        # 待办按账号隔离，且只对本次登录有效：每次登录都从全部未勾选开始
        self.tasks = [{'title': title, 'done': False} for title in DEFAULT_TASKS]
        self.alarm_count = 0
        self.dev_mode = False
        self._reset_monitor()
        self.bar_mode = 'patient'
        self.clear_display()
        self.log_line('登录成功：%s' % username)
        self.log_line('点「蓝牙连接」选择设备，连接成功后即可下发命令')
        self.active_tab = 'ctrl'
        self.root.ids.sm.current = 'ctrl'

    def logout(self):
        try:
            self.ble.disconnect()
        except Exception:
            Logger.exception('BleAssistant: 退出登录时断开连接失败')
        self.current_user = ''
        self.logged_in = False
        self.patient_label = '未绑定'
        self._patient_ble_name = ''
        self.tasks = []
        self.alarm_count = 0
        self.dev_mode = False
        self._reset_monitor()
        self.bar_mode = 'patient'
        self.clear_display()
        self.active_tab = 'mine'
        self.root.ids.sm.current = 'mine'
        try:
            self.screen('loginform').reset()
        except Exception:                                       # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 患者信息（按账号保存，登出再登录不丢）
    # ------------------------------------------------------------------
    def _load_patient(self, username):
        data = self.patients.get(username)
        self._patient_ble_name = data.get('ble_name') or ''
        self.patient_label = data.get('label') or '未绑定'

    def apply_patient(self, label, ble_name):
        """确认患者信息：存到账号下，并把第二块内容写成蓝牙模块名称。"""
        self.patients.save(self.current_user, label, ble_name)
        self.patient_label = label or '未绑定'
        self._patient_ble_name = ble_name
        self.log_line('患者信息已更新：%s（模块名 %s）' % (label, ble_name))
        ok, message = self.rename_module(ble_name)
        if not ok:
            self.log_line('✗ 模块改名未下发：%s' % (message or '未知原因'))
        self.show_notice('患者信息已保存')

    def restore_patient(self):
        """开发者模式「信息复原」：患者身份抹回未绑定，模块名改回 HFUT.BLE。"""
        if self.current_user:
            self.patients.clear(self.current_user)
        self.patient_label = '未绑定'
        self._patient_ble_name = ''
        self.log_line('信息复原：患者身份已清空，模块名恢复为 %s' % RESET_MODULE_NAME)
        ok, message = self.rename_module(RESET_MODULE_NAME)
        if ok:
            self.show_notice('信息复原完成')
        else:
            self.show_notice('信息已清空（模块改名未下发）')
            self.log_line('✗ 模块改名未下发：%s' % (message or '未知原因'))

    def rename_module(self, name):
        """用 AT 指令把连接的蓝牙模块改名（AT+NAME=0,<name>）。"""
        if not self.connected:
            return False, '未连接设备'
        if not self._at_subscribed:
            return False, 'AT 通道未就绪'
        command = 'AT+NAME=0,%s' % name
        accepted, message = self.ble.send_command(
            '', ESP32_AT_UUID, to_hex((command + '\r\n').encode('utf-8')))
        if accepted:
            self.log_line('→ 已发送 模块改名：%s' % command)
        return accepted, message

    # ------------------------------------------------------------------
    # 顶部全局状态条
    # ------------------------------------------------------------------
    def show_alarm(self, text, duration=3.0):
        """红色告警横幅：3 秒后自动回到【患者身份】。"""
        self.bar_message = text
        self.bar_mode = 'alarm'
        self.bar_opacity = 0.35
        Animation(bar_opacity=1.0, d=0.2).start(self)
        self._schedule_bar_reset(duration)

    def show_notice(self, text, duration=3.0):
        """普通提示：同样显示在顶部，3 秒后回到【患者身份】。"""
        self.bar_message = text
        self.bar_mode = 'notice'
        self._schedule_bar_reset(duration)

    def _schedule_bar_reset(self, duration):
        if self._bar_event is not None:
            self._bar_event.cancel()
            self._bar_event = None
        if duration > 0:
            self._bar_event = Clock.schedule_once(self._reset_bar, duration)

    def _reset_bar(self, _dt):
        self._bar_event = None
        self.bar_mode = 'patient'
        self.bar_message = ''
        self.bar_opacity = 1.0

    # ------------------------------------------------------------------
    # 设备监测 / 功能键状态
    # ------------------------------------------------------------------
    def _reset_monitor(self):
        self.battery_text = 'NA'
        self.pressure_text = 'NA'
        self.temp_text = 'NA'
        self.pump1 = '关'
        self.pump2 = '关'
        self.device_state_text = '泵1 关 · 泵2 关'
        self.ble_state_text = '已连接' if self.connected else '未连接'
        self.stop_countdown()

    def apply_device_action(self, action, seconds=0):
        """按下功能键后同步"设备状态"与 5 秒倒计时。"""
        if action == 'pump1_on':
            self.pump1 = '开'
            self._start_countdown(seconds)
        elif action == 'pump1_off':
            self.pump1 = '关'
            self.stop_countdown()
        elif action == 'pump2_on':
            self.pump2 = '开'
            self._start_countdown(seconds)
        elif action == 'pump2_off':
            self.pump2 = '关'
            self.stop_countdown()
        elif action in ('stop', 'reset'):
            self.pump1 = '关'
            self.pump2 = '关'
            self.stop_countdown()
        self.device_state_text = '泵1 %s · 泵2 %s' % (self.pump1, self.pump2)

    def _start_countdown(self, seconds):
        self.stop_countdown()
        if not seconds:
            return
        self._countdown_left = int(seconds)
        self.countdown_text = '剩余时间 %ds' % self._countdown_left
        self._countdown_event = Clock.schedule_interval(self._tick_countdown, 1.0)

    def _tick_countdown(self, _dt):
        self._countdown_left -= 1
        if self._countdown_left <= 0:
            self.stop_countdown()
            return
        self.countdown_text = '剩余时间 %ds' % self._countdown_left

    def stop_countdown(self):
        if self._countdown_event is not None:
            self._countdown_event.cancel()
            self._countdown_event = None
        self._countdown_left = 0
        self.countdown_text = ''

    # ------------------------------------------------------------------
    # 开发者模式
    # ------------------------------------------------------------------
    def enter_dev_mode(self):
        if not self.logged_in:
            return
        self.dev_mode = True
        self.log_line('已进入开发者模式')
        self.root.ids.sm.current = 'dev'

    def exit_dev_mode(self):
        self.dev_mode = False
        self.active_tab = 'ctrl'
        self.root.ids.sm.current = 'ctrl'

    # ------------------------------------------------------------------
    # 开发者模式底部三个功能键
    # ------------------------------------------------------------------
    def open_services(self):
        if not self.connected:
            show_info('未连接', '请先连接 BLE 设备，再查看它的服务与特征。')
            return
        ServicesPopup(ble=self.ble).open()

    def open_baudrate(self):
        if not self.connected:
            show_info('未连接', '请先连接 BLE 设备，再修改模块波特率。')
            return
        BaudRatePopup(ble=self.ble).open()

    def open_command(self):
        if not self.connected:
            show_info('未连接', '请先连接 BLE 设备，再下发命令。')
            return
        self.cmd_popup = CommandInputPopup(ble=self.ble,
                                           on_closed=self._on_cmd_closed)
        self.cmd_popup.open()

    def _on_cmd_closed(self):
        self.cmd_popup = None

    # ------------------------------------------------------------------
    # BLE 轮询（切页面也不停）
    # ------------------------------------------------------------------
    def _poll_ble(self, _dt):
        ble = self.ble
        title, detail, connected = ble.status()
        if connected:
            self._disconnect_streak = 0
        elif self.connected:
            # 防抖：GATT 偶尔会先报一次 disconnected（下一轮又回到已连接），
            # 界面立刻改成"已断开"就会出现"显示断开了、其实还连着"。
            # 连续两轮（约 0.8 秒）都报断开才真的认为断开。
            self._disconnect_streak += 1
            if self._disconnect_streak < 2:
                connected = True
                title, detail = self.status_text, self.status_detail
        if title != self.status_text:
            self.status_text = title
        if detail != self.status_detail:
            self.status_detail = detail
        if connected != self.connected:
            self.connected = connected
            self.log_line('● 已连接设备' if connected else '○ 已断开连接')
            if connected:
                self._manual_disconnect = False
                self.ble_state_text = '已连接'
                self._remember_favorite()
            else:
                manual = self._manual_disconnect
                self._manual_disconnect = False
                self.pending_favorite = None
                self.ble_state_text = '未连接'
                self._reset_monitor()
                self._save_snapshot()
                if manual:
                    self.show_notice('蓝牙已断开 · 本次记录已保存')
                else:
                    self.alarm_count += 1
                    self.show_alarm('蓝牙意外断开！请检查设备连接')
                    self.log_line('⚠ 蓝牙意外断开，已记录本次会话')

        self._keep_notify(ble, connected)
        self._drain_at(ble)
        self._drain_incoming(ble)

    def _save_snapshot(self):
        """蓝牙断联即记录：保存本次会话的显示屏内容。"""
        self.last_snapshot = list(self.display_lines)
        self.log_line('○ 本次蓝牙记录已保存（%d 行）' % len(self.last_snapshot))

    def _remember_favorite(self):
        """真正连上之后，把设备归档进「我的收藏」。"""
        device = self.pending_favorite
        self.pending_favorite = None
        if not device or self.favorites is None:
            return
        if self.favorites.add(device):
            name = (device.get('name') or device.get('address') or '').strip()
            self.log_line('★ 已加入我的收藏：%s' % name)

    def note_manual_disconnect(self):
        """用户主动点「断开连接」：不等防抖，界面立刻显示已断开。"""
        self.pending_favorite = None
        self._disconnect_streak = 0
        self._manual_disconnect = True
        if self.connected:
            self.connected = False
            self.ble_state_text = '未连接'
            self._reset_monitor()
            self.log_line('○ 已断开连接')
            self._save_snapshot()
            self.show_notice('蓝牙已断开 · 本次记录已保存')

    # ------------------------------------------------------------------
    # AT 通道：始终有人读，收到就上显示屏
    # ------------------------------------------------------------------
    def register_at_sink(self, callback):
        """把"正在等 AT 回复"的组件登记进来（自动锁定配置、服务页读模块信息）。"""
        if callback not in self._at_sinks:
            self._at_sinks.append(callback)

    def unregister_at_sink(self, callback):
        if callback in self._at_sinks:
            self._at_sinks.remove(callback)

    def _drain_at(self, ble):
        """AT 通道只有一个读口，统一在这里取，再分发给登记的组件。

        之前是由各个组件自己去 pop_received_at()，结果没有组件在跑的时候
        （比如自动配置做完之后）模块回的 AT 回复就没人取，显示屏上永远看不到
        「收到 AT 回复」。
        """
        chunks = ble.pop_received_at()
        if not chunks:
            return
        for chunk in chunks:
            try:
                text = bytes(bytearray.fromhex(str(chunk))).decode('utf-8', 'replace')
            except ValueError:
                Logger.warning('BleAssistant: 收到非十六进制 AT 数据，已跳过')
                continue
            self.on_at_reply(text)
            for sink in list(self._at_sinks):
                try:
                    sink(text)
                except Exception:                               # noqa: BLE001
                    Logger.exception('BleAssistant: AT 回复分发失败')

    def _keep_notify(self, ble, connected):
        """连上就自动订阅回传通知与 AT 通道；订阅幂等，没成功会在下一轮重试。"""
        if not connected:
            self._notify_subscribed = False
            self._at_subscribed = False
            self._module_configured = False
            self._at_busy = False
            return
        # 服务发现是异步的，而且刚连上经常一次不成功：
        # 还没拿到服务表就先催一次，别急着去订阅/写特征
        count, _message = ble.discovery_state()
        if count <= 0:
            ble.ensure_services()
            return

        if not self._notify_subscribed:
            state, _message = ble.notify_state()
            if state == NOTIFY_SUBSCRIBED:
                self._notify_subscribed = True
            elif state != NOTIFY_SUBSCRIBING:
                ble.enable_notify(ESP32_SERVICE_UUID, ESP32_NOTIFY_UUID,
                                  auto_pick=ESP32_AUTO_PICK_NOTIFY)

        # 数据通道就绪后，顺便订阅模块的 AT 指令通道
        # （既用于「服务/特征」里的模块信息，也用于自动锁定模块配置）
        if self._notify_subscribed and not self._at_subscribed:
            state, _message = ble.at_notify_state()
            if state == NOTIFY_SUBSCRIBED:
                self._at_subscribed = True
            elif state != NOTIFY_SUBSCRIBING:
                ble.enable_at_notify('', ESP32_AT_UUID)

        # AT 通道就绪后，自动把模块锁成 9600 + HFUT.BLE（每次连接只做一次）
        if (self._at_subscribed and not self._module_configured
                and not self._at_busy):
            runner = ModuleConfigRunner(ble, on_done=self._on_module_configured)
            if runner.start():
                self._config_runner = runner
                self._at_busy = True
            else:
                self._module_configured = True

    def _on_module_configured(self, ok):
        self._at_busy = False
        self._module_configured = True
        if ok:
            self.log_line('模块配置已锁定：串口 %d' % MODULE_TARGET_BAUD)
        else:
            self.log_line('模块配置锁定没有收到 OK（模块可能不支持 AT 指令，不影响收发）')

    def _drain_incoming(self, ble):
        """读模块的回传命令包（通知通道 6E400003）。

        不管它是不是约定的 AA55 帧格式，**收到什么就在显示屏上显示什么**：
        以前只把能拼成帧的字节显示出来，模块用自定格式回传时就会被静默丢掉。
        """
        chunks = ble.pop_received()
        if not chunks:
            return
        data = bytearray()
        for chunk in chunks:
            try:
                data.extend(bytearray.fromhex(str(chunk)))
            except ValueError:
                Logger.warning('BleAssistant: 收到非十六进制回传数据，已跳过')
        if not data:
            return
        self._rx_packets += 1

        raw = bytes(data)
        frames = self._parser.feed(data)
        if frames:
            for cmd, payload in frames:
                self._on_reply(cmd, payload)
            return
        # 不是约定帧格式：按原始字节显示（字节数 + 内容）
        self.log_line('← 回传命令包（%d 字节）：%s'
                      % (len(raw), self.describe_bytes(raw)))

    @staticmethod
    def describe_bytes(raw):
        """把一段回传字节转成显示屏上的"内容"：能当文本读就读文本，否则给十六进制。"""
        try:
            text = raw.decode('utf-8')
        except Exception:                                       # noqa: BLE001
            text = ''
        if text.strip() and all(ch.isprintable() or ch in '\r\n\t' for ch in text):
            return ' '.join(text.split())
        return spaced_hex(to_hex(raw))

    def _on_reply(self, cmd, payload):
        """设备 → 手机：统一写进显示屏；「开发者」弹窗开着时同时显示在弹窗里。"""
        raw = bytes(bytearray(payload))
        raw_hex = to_hex(raw)
        text = decode_text(payload)
        shown = text if text.strip() else '（非文本载荷，原始 %s）' % (raw_hex or '空')
        self.log_line('← 回传命令包 0x%02X（%d 字节）：%s'
                      % (cmd, len(raw), shown))
        Logger.info('BleAssistant: 收到回传 cmd=0x%02X 载荷=%r 原始=%s', cmd, text, raw_hex)
        popup = self.cmd_popup
        if popup is not None:
            popup.add_reply(cmd, text, raw_hex)

    # ------------------------------------------------------------------
    # 回传命令包：发出后等一会儿，没收到就明确写"0字节"
    # ------------------------------------------------------------------
    def expect_return(self, delay=RETURN_TIMEOUT):
        """发完命令后开一个等待窗口：窗口内一条回传都没收到，就写"0字节，未读取到有效信息"。"""
        if self._return_timer is not None:
            self._return_timer.cancel()
            self._return_timer = None
        self._return_base = self._rx_packets
        self._return_timer = Clock.schedule_once(self._check_return, delay)

    def _check_return(self, _dt):
        self._return_timer = None
        if self._rx_packets <= self._return_base:
            self.log_line('← 回传命令包：0字节，未读取到有效信息')

    # ------------------------------------------------------------------
    # 模块固件自己的 AT 回复 → 显示屏
    # ------------------------------------------------------------------
    def on_at_reply(self, text):
        """模块固件回了一条 AT 数据，就把原文标到显示屏上。

        这是**模块自己产生**的回复（不是 App 编的），所以只要它出现，
        就说明"模块在线、蓝牙链路双向都通"。任何发起 AT 指令的地方
        （自动锁定配置、服务页读模块信息、命令后的在线确认）都会调用这里。
        """
        flat = ' '.join((text or '').split())
        if not flat:
            return
        self.at_reply_count += 1
        self.log_line('← 收到 AT 回复：%s' % flat)

    def ping_module(self):
        """发一条轻量 AT 查询，让模块回一句，用于确认链路真的通。"""
        if not self._at_subscribed:
            return False
        query = 'AT+UART?'
        return self.ble.send_command('', ESP32_AT_UUID,
                                     to_hex((query + '\r\n').encode('utf-8')))[0]

    # ------------------------------------------------------------------
    def _on_keyboard(self, window, key, scancode, codepoint, modifiers):
        # Android 返回键（27）与桌面 ESC 一致
        if key == 27:
            current = self.root.ids.sm.current
            if current == 'dev':
                self.exit_dev_mode()
                return True
            if current == 'register':
                self.screen('register').back_to_login()
                return True
            if current == 'loginform':
                self.active_tab = 'mine'
                self.root.ids.sm.current = 'mine'
                return True
        return False

    def on_pause(self):
        try:
            self.ble.stop_scan()
        except Exception:
            pass
        return True


if __name__ == '__main__':
    BleAssistantApp().run()
