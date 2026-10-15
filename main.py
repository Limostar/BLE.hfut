# -*- coding: utf-8 -*-
"""绿联蓝牙助手 —— 医疗设备 BLE 连接演示 App。

界面结构（底部三个一级模块，随时可切换）：
    「控制」蓝牙连接 / 显示屏 / 8 个圆形功能键
    「记录」蓝牙日志（最近 5 次登录的显示屏内容）/ 诊断记录（预留）
    「登录」用户登录（登录前只有这一项可用；控制、记录被灰色遮罩挡住）

未登录时「控制」「记录」覆盖一层半透明灰并提示"登录后即可使用"，
登录成功后自动解锁。
"""

import os
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.graphics import (Color, Ellipse, Line, Rectangle, RoundedRectangle,
                           StencilPop, StencilPush, StencilUnUse, StencilUse)
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
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform

from accounts import AccountStore
from protocol import (CMD_FUNC_1, CMD_PRESETS, MAX_PAYLOAD, RxFrameParser,
                      build_frame, decode_text, example_by_name, to_hex)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
KV_FILE = os.path.join(APP_DIR, 'ui.kv')
FONT_FILE = os.path.join(APP_DIR, 'assets', 'fonts', 'NotoSansSC-Regular.ttf')

# 系统中文字体兜底路径（未打包字体文件时使用）
SYSTEM_FONTS = [
    '/system/fonts/NotoSansCJK-Regular.ttc',
    '/system/fonts/NotoSansSC-Regular.otf',
    '/system/fonts/DroidSansFallbackFull.ttf',
    '/system/fonts/DroidSansFallback.ttf',
]


# ----------------------------------------------------------------------
# 主题色：医疗场景的活力绿
# ----------------------------------------------------------------------
COLOR_PRIMARY = [0.000, 0.784, 0.325, 1.0]       # #00C853
COLOR_PRIMARY_DARK = [0.000, 0.545, 0.239, 1.0]  # #008B3D
COLOR_BG = [0.953, 0.988, 0.965, 1.0]            # #F3FCF6
COLOR_CARD = [1.000, 1.000, 1.000, 1.0]
COLOR_LINE = [0.831, 0.902, 0.855, 1.0]          # #D4E6DA
COLOR_TEXT = [0.075, 0.196, 0.118, 1.0]
COLOR_TEXT_WEAK = [0.427, 0.522, 0.455, 1.0]
COLOR_DANGER = [0.855, 0.208, 0.271, 1.0]
COLOR_DISABLED = [0.776, 0.839, 0.796, 1.0]

# 渐变配色（线性渐变，两端颜色）
GRAD_NAVY_A = [0.043, 0.098, 0.263, 1.0]         # 深蓝（显示屏左上）
GRAD_NAVY_B = [0.055, 0.271, 0.478, 1.0]         # 亮蓝（显示屏右下）
GRAD_LINK_A = [0.000, 0.412, 0.361, 1.0]         # 深绿（连接类按钮）
GRAD_LINK_B = [0.290, 0.871, 0.647, 1.0]         # 苹果绿
GRAD_FUNC_A = [0.180, 0.412, 0.118, 1.0]         # 草绿深
GRAD_FUNC_B = [0.612, 0.800, 0.396, 1.0]         # 草绿浅
GRAD_LOG_A = [0.106, 0.278, 0.541, 1.0]          # 日志按钮蓝
GRAD_LOG_B = [0.310, 0.651, 0.902, 1.0]
GRAD_TAB_A = [0.000, 0.545, 0.239, 1.0]          # 底部导航
GRAD_TAB_B = [0.000, 0.784, 0.325, 1.0]

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

# 回传命令字 REPLY_FUNC_1、下发命令字 CMD_FUNC_1 都在 protocol.py 里约定

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

WRITE_IDLE, WRITE_SENDING, WRITE_SUCCESS, WRITE_FAILED = 0, 1, 2, 3

# 显示屏最多保留多少行（超过就丢掉最早的）
MAX_DISPLAY_LINES = 200
# 「记录」里最多保存几次登录的日志
MAX_SESSION_LOGS = 5
# 「启动」「停止」两个预制命令包
PRESET_HEX = dict(CMD_PRESETS)

# 每次连上模块后，App 自动通过蓝牙 AT 通道锁定的模块配置
#   —— 不需要任何电脑端脚本参与
MODULE_TARGET_BAUD = 115200
MODULE_TARGET_NAME = 'HFUT.BLE'
MODULE_SETUP_COMMANDS = ('AT+UART=%d' % MODULE_TARGET_BAUD,
                         'AT+NAME=0,%s' % MODULE_TARGET_NAME)


def spaced_hex(hex_text):
    """'5401008031' -> '54 01 00 80 31'（只用于界面显示）。"""
    return ' '.join(hex_text[i:i + 2] for i in range(0, len(hex_text), 2))


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
    """渐变底图绘制逻辑（供 FloatLayout / 按钮复用）。"""

    def _init_gradient(self):
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
        self.canvas.clear()
        if self.width <= 0 or self.height <= 0:
            return
        texture = gradient_texture(self.color_a, self.color_b)
        x, y, width, height = self._shape_rect() if self.circle else \
            (self.x, self.y, self.width, self.height)
        with self.canvas:
            Color(1, 1, 1, 1)
            if self.circle:
                StencilPush()
                Ellipse(pos=(x, y), size=(width, height))
                StencilUse()
                Rectangle(texture=texture, pos=(x, y), size=(width, height))
                StencilUnUse()
                StencilPop()
            else:
                RoundedRectangle(texture=texture, pos=(x, y), size=(width, height),
                                 radius=[self.radius])
            if self.border_color[3] > 0:
                Color(*self.border_color)
                if self.circle:
                    Line(circle=(x + width / 2.0, y + height / 2.0,
                                 width / 2.0 - dp(1.5)), width=dp(2))
                else:
                    Line(rounded_rectangle=(x, y, width, height, self.radius),
                         width=dp(1.2))


class GradientPanel(FloatLayout, _GradientCanvas):
    """带线性渐变背景的容器；子部件用 pos_hint / size_hint 自由摆放。"""

    color_a = ListProperty(GRAD_NAVY_A)
    color_b = ListProperty(GRAD_NAVY_B)
    radius = NumericProperty(0)
    circle = BooleanProperty(False)
    border_color = ListProperty([0, 0, 0, 0])

    def __init__(self, **kwargs):
        super(GradientPanel, self).__init__(**kwargs)
        self._init_gradient()


class CircleButton(ButtonBehavior, GradientPanel):
    """圆形渐变按钮（按下时整体变淡，便于看清反馈）。"""

    text = StringProperty('')
    font_size_hint = NumericProperty(sp(13))

    def on_state(self, _widget, value):
        self.opacity = 0.72 if value == 'down' else 1.0


class TabButton(ButtonBehavior, GradientPanel):
    """底部导航按钮。"""

    text = StringProperty('')
    active = BooleanProperty(False)


class ScreenLine(Label):
    """显示屏里的一行白色提示文字。"""


class GateOverlay(FloatLayout):
    """未登录时盖在模块上的半透明灰色遮罩。"""


class LogEntryRow(Label):
    """日志详情弹窗里的一行。"""


class DisplayPanel(GradientPanel):
    """深蓝渐变"显示屏"：白色提示文字，右侧一根可拖拽的滑块。

    内容来自 App.display_lines，所以登录/退出/清屏都能统一控制。
    """

    def on_kv_post(self, _base_widget):
        self._syncing = False
        self.ids.dp_slider.bind(value=self._on_slider)
        self.ids.dp_scroll.bind(scroll_y=self._on_scroll)
        App.get_running_app().bind(display_lines=self._render)
        self._render()

    def _on_slider(self, _widget, value):
        if self._syncing:
            return
        self._syncing = True
        self.ids.dp_scroll.scroll_y = value
        self._syncing = False

    def _on_scroll(self, _widget, value):
        if self._syncing:
            return
        self._syncing = True
        self.ids.dp_slider.value = value
        self._syncing = False

    def _render(self, *args):
        box = self.ids.dp_lines
        box.clear_widgets()
        lines = list(App.get_running_app().display_lines)
        if not lines:
            box.add_widget(ScreenLine(text='（暂无信息：连接设备后，收发记录都显示在这里）'))
            return
        # 按时间顺序加入 → 最早的在最上面、最新的在最下面（像终端一样）
        for line in lines:
            box.add_widget(ScreenLine(text=line))
        Clock.schedule_once(self._scroll_to_bottom, 0.1)

    def _scroll_to_bottom(self, _dt):
        try:
            self.ids.dp_scroll.scroll_y = 0.0       # 0 = 最底部（最新一条）
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


class DevicePopup(Popup):
    """搜索并选择附近 BLE 设备的弹窗。"""

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
        self._poll = Clock.schedule_interval(self._refresh, 0.6)
        self._refresh(0)

    def on_dismiss(self, *args):
        super(DevicePopup, self).on_dismiss(*args)
        if self._poll is not None:
            self._poll.cancel()
            self._poll = None
        self._ble.stop_scan()

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


class ServicesPopup(Popup):
    """列出已连接设备暴露的服务与特征，并显示模块自身信息。

    模块信息（固件版本/角色/波特率/状态显示/鉴权/名称）走模块自带的
    AT 指令通道读取——只走蓝牙、不经过串口，打开弹窗时会自动读一次。
    """

    def __init__(self, ble, **kwargs):
        super(ServicesPopup, self).__init__(**kwargs)
        self._ble = ble
        self._diag = None

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


# ----------------------------------------------------------------------
# 回传记录
# ----------------------------------------------------------------------
class LogDetailPopup(Popup):
    """「记录」页的日志详情：可上下拖动查看的历史内容。

    行高固定、放在 ScrollView 里（与「服务/特征」的服务列表同一套写法，
    这种写法在你的手机上已验证可正常显示）。
    """

    def __init__(self, title, lines, note='', **kwargs):
        super(LogDetailPopup, self).__init__(title=title, **kwargs)
        self._lines = list(lines)
        self._note = note

    def on_open(self, *args):
        super(LogDetailPopup, self).on_open(*args)
        self.refresh_list()

    def refresh_list(self):
        try:
            box = self.ids.log_list
        except Exception:                                       # noqa: BLE001
            return
        box.clear_widgets()
        self.ids.log_state.text = self._note or '共 %d 行' % len(self._lines)
        if not self._lines:
            box.add_widget(LogEntryRow(text='（暂无记录）'))
            return
        # 按时间顺序添加：最早的在最上面，最新的在最下面（像终端一样）
        for line in self._lines:
            box.add_widget(LogEntryRow(text=clip_line(line, 50)))
        Clock.schedule_once(self._scroll_to_bottom, 0.3)

    def _scroll_to_bottom(self, _dt):
        try:
            self.ids.log_scroll.scroll_y = 0.0
        except Exception:                                       # noqa: BLE001
            pass


class CommandInputPopup(Popup):
    """「开发者」：用户自己输入命令包并发送，回传同时进显示屏和弹窗。

    输入框接受两种写法：
      - 示例名称：HFUT / MECH / GREAT（大小写都行，仅当 show_examples 打开时提示）
      - 直接的十六进制命令包，例如 5401008031
        （只要是偶数长度的十六进制即可，按原样写进数据通道）

    走的是数据通道（6E400002），与「启动」「停止」同一条路。
    """

    command = StringProperty('HFUT')
    state = StringProperty('输入十六进制命令包，再点「发送」。')
    show_examples = BooleanProperty(True)
    MAX_ROWS = 5

    def __init__(self, ble, on_closed=None, show_examples=True, **kwargs):
        kwargs.setdefault('show_examples', show_examples)
        super(CommandInputPopup, self).__init__(**kwargs)
        self._ble = ble
        self._on_closed = on_closed
        self._lines = []
        self._timer = None
        self._deadline = 0.0
        if show_examples:
            self.command = 'HFUT'
            self.state = '输入示例名称（HFUT / MECH / GREAT）或十六进制命令包，再点「发送」。'
        else:
            self.command = ''
            self.state = '输入十六进制命令包（偶数长度，如 5401008031），再点「发送」。'

    # ------------------------------------------------------------------
    def on_open(self, *args):
        Clock.schedule_once(self._focus_input, 0.6)

    def _focus_input(self, dt):
        try:
            self.ids.cmd_input.focus = True
        except Exception:                                       # noqa: BLE001
            pass

    def quick(self, name):
        """示例快捷按钮：填好名称后直接发送。"""
        self.command = name
        self.send()

    def _resolve(self, text):
        """输入 → (命令包十六进制, 说明)；无法识别时返回 (None, 原因)。"""
        raw = (text or '').strip()
        if not raw:
            return None, '请先输入命令内容。'
        example = example_by_name(raw) if self.show_examples else None
        if example is not None:
            cmd, _reply_cmd, reply_text = example
            return (to_hex(build_frame(cmd)),
                    '示例 %s（命令字 0x%02X，设备将回传 %s）'
                    % (raw.upper(), cmd, reply_text))
        compact = raw.replace(' ', '').replace('-', '').upper()
        if (len(compact) >= 2 and len(compact) % 2 == 0
                and all(ch in '0123456789ABCDEF' for ch in compact)):
            return compact, '自定义命令包（%d 字节）' % (len(compact) // 2)
        return None, '无法识别：请输入偶数长度的十六进制命令包。'

    def send(self):
        hex_data, note = self._resolve(self.command)
        if hex_data is None:
            self.state = note
            return
        if len(hex_data) // 2 > MAX_PAYLOAD:
            self.state = '命令包 %d 字节，超过单次写入上限 %d 字节。' % (
                len(hex_data) // 2, MAX_PAYLOAD)
            return
        self._lines = []
        self._render()
        accepted, message = self._ble.send_command(ESP32_SERVICE_UUID,
                                                   ESP32_WRITE_UUID,
                                                   hex_data,
                                                   auto_pick=ESP32_AUTO_PICK_WRITE)
        if not accepted:
            self.state = '下发失败：%s' % message
            return
        self.state = '已发送 %s，等待写入完成…' % note
        App.get_running_app().ping_module()
        self._deadline = time.monotonic() + WRITE_TIMEOUT
        if self._timer is not None:
            self._timer.cancel()
        self._timer = Clock.schedule_interval(self._poll, 0.2)

    def _poll(self, dt):
        state, message = self._ble.write_state()
        if state == WRITE_SUCCESS:
            self._stop_poll()
            self.state = '命令已写入设备，等待回传…'
            return
        if state == WRITE_FAILED:
            self._stop_poll()
            self.state = '写入失败：%s' % (message or '未知原因')
            return
        if time.monotonic() >= self._deadline:
            self._stop_poll()
            self.state = '写入超时，请检查连接后重试。'

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
    """连上模块后自动把它的配置锁定：串口波特率 115200 + 设备名 HFUT.BLE。

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
        self._timer = Clock.schedule_interval(self._step, 0.45)
        return True

    def stop(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _step(self, dt):
        self._elapsed += dt
        for chunk in self._ble.pop_received_at():
            try:
                text = bytes(bytearray.fromhex(str(chunk))).decode('utf-8', 'replace')
            except ValueError:
                continue
            self._replies.append(text)
            App.get_running_app().on_at_reply(text)
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
        self._progress('读取模块信息 0/6')
        self._emit_lines(['%s：查询中…' % name for _key, name in AT_QUERY_LABELS])
        self._timer = Clock.schedule_interval(self._step, 0.35)
        return True

    def stop(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _step(self, dt):
        self._elapsed += dt
        self._collect()
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

    def _collect(self):
        for chunk in self._ble.pop_received_at():
            try:
                raw = bytes(bytearray.fromhex(chunk))
            except ValueError:
                continue
            self._at_bytes += len(raw)
            text = raw.decode('utf-8', 'replace').replace('\r', '')
            for line in text.split('\n'):
                line = line.strip()
                if line:
                    self._replies_text.append(line)
                    App.get_running_app().on_at_reply(line)

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


class CtrlScreen(Screen):
    """「控制」：蓝牙连接 / 显示屏 / 8 个圆形功能键。

    BLE 的轮询与接收统一放在 App 上（切到别的页也不会断），
    这里只负责界面动作。
    """

    def __init__(self, **kwargs):
        super(CtrlScreen, self).__init__(**kwargs)
        self._cmd_popup = None

    def on_leave(self, *args):
        self._cmd_popup = None

    # ------------------------------------------------------------------
    # 蓝牙连接
    # ------------------------------------------------------------------
    def open_device_dialog(self):
        app = App.get_running_app()
        if app.connected:
            show_info('已连接', '当前已连接设备，如需更换请先点击「断开连接」。')
            return
        DevicePopup(ble=app.ble, on_pick=self._on_device_picked).open()

    def _on_device_picked(self, device):
        App.get_running_app().ble.connect(device['address'])

    def do_disconnect(self):
        App.get_running_app().ble.disconnect()

    def open_services_dialog(self):
        app = App.get_running_app()
        if not app.connected:
            show_info('未连接', '请先连接 BLE 设备，再查看它的服务与特征。')
            return
        ServicesPopup(ble=app.ble).open()

    # ------------------------------------------------------------------
    # 功能键
    # ------------------------------------------------------------------
    def send_preset(self, name):
        """「启动」「停止」：把预制命令包写进数据通道，结果全部进显示屏。"""
        hex_data = PRESET_HEX.get(name)
        if hex_data is None:
            return
        self.send_hex(name, hex_data)

    def open_developer(self):
        """「开发者」：自定义命令包输入框（不带示例快捷键）。"""
        app = App.get_running_app()
        if not app.connected:
            show_info('未连接', '请先连接 BLE 设备，再下发命令。')
            return
        self._cmd_popup = CommandInputPopup(ble=app.ble,
                                            on_closed=self._on_cmd_popup_closed,
                                            show_examples=False)
        self._cmd_popup.open()

    def _on_cmd_popup_closed(self):
        self._cmd_popup = None

    def send_hex(self, name, hex_data):
        """把一段十六进制命令包写进数据通道，过程与结果都写进显示屏。"""
        app = App.get_running_app()
        if not app.connected:
            show_info('未连接', '请先连接 BLE 设备，再下发命令。')
            return

        # 没有服务表就写不进去：先催一次服务发现，别让你对着"发送中…"干等
        service_count, _message = app.ble.discovery_state()
        if service_count <= 0:
            app.ble.ensure_services(force=True)
            app.log_line('✗ %s：设备服务尚未就绪，已重新发起服务发现，请 1~2 秒后再点' % name)
            return

        if len(hex_data) // 2 > MAX_PAYLOAD:
            app.log_line('✗ %s：命令 %d 字节，超过单次写入上限 %d 字节'
                         % (name, len(hex_data) // 2, MAX_PAYLOAD))
            return

        accepted, message = app.ble.send_command(ESP32_SERVICE_UUID,
                                                 ESP32_WRITE_UUID,
                                                 hex_data,
                                                 auto_pick=ESP32_AUTO_PICK_WRITE)
        if not accepted:
            app.log_line('✗ %s 下发失败：%s' % (name, message or '未知原因'))
            show_info('命令下发失败', '%s\n\n%s' % (message, self._feature_hint(app.ble)))
            return
        app.log_line('→ 已发送 %s（%d 字节）：%s'
                     % (name, len(hex_data) // 2, spaced_hex(hex_data)))
        # 顺手向模块发一条 AT 查询：它的回复会以「← 收到 AT 回复」出现在显示屏上，
        # 用来确认"模块确实在线、蓝牙链路双向都通"
        if not app.ping_module():
            app.log_line('（AT 通道未就绪，本次没有做模块在线确认）')

    def clear_screen(self):
        """一键清屏：只清显示屏里的提示信息。"""
        app = App.get_running_app()
        app.clear_display()
        app.log_line('已清屏')

    def reserved(self, name):
        show_info('功能预留', '「%s」为预留功能，后续可在此接入具体医疗设备指令。' % name)

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

    # 设备回传的统一处理在 App._on_reply 里（写进显示屏）

class LogsScreen(Screen):
    """「记录」：蓝牙日志（最近 5 次登录的显示屏内容）+ 诊断记录（预留）。"""

    def open_session(self, index):
        app = App.get_running_app()
        sessions = list(app.sessions)
        if index >= len(sessions):
            show_info('蓝牙日志 %d' % (index + 1),
                      '这一格还没有记录。\n\n每次退出登录时，会把本次登录期间'
                      '显示屏里的内容存进这里，最多保留 %d 次。' % MAX_SESSION_LOGS)
            return
        item = sessions[index]
        LogDetailPopup(title='蓝牙日志 %d · %s' % (index + 1, item.get('label', '')),
                       lines=list(item.get('lines', [])),
                       note='本次共 %d 行（可上下拖动查看）'
                            % len(item.get('lines', []))).open()

    def open_diag(self, index):
        show_info('诊断记录 %d' % (index + 1),
                  '该功能暂时预留。\n\n后续可在这里接入：模块 AT 自检结果、'
                  '连接失败原因、命令下发统计等诊断数据。')


class MineScreen(Screen):
    """「登录」：用户登录 / 紧急呼叫 / 用户信息 / 问题查询。"""

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

    def reserved(self, name):
        show_info(name, '「%s」暂时预留。' % name)


# ----------------------------------------------------------------------
# App
# ----------------------------------------------------------------------
class BleAssistantApp(App):
    title = '绿联蓝牙助手'

    font_name = StringProperty('Roboto')
    current_user = StringProperty('')
    logged_in = BooleanProperty(False)
    active_tab = StringProperty('mine')

    # 连接状态（由 App 统一轮询，切到任何页面都不会中断）
    status_text = StringProperty('未连接')
    status_detail = StringProperty('点击「蓝牙连接」搜索附近的 BLE 设备')
    connected = BooleanProperty(False)

    # 显示屏内容 / 「记录」里保存的最近几次登录日志
    display_lines = ListProperty([])
    sessions = ListProperty([])
    at_reply_count = NumericProperty(0)

    COLOR_PRIMARY = ListProperty(COLOR_PRIMARY)
    COLOR_PRIMARY_DARK = ListProperty(COLOR_PRIMARY_DARK)
    COLOR_BG = ListProperty(COLOR_BG)
    COLOR_CARD = ListProperty(COLOR_CARD)
    COLOR_LINE = ListProperty(COLOR_LINE)
    COLOR_TEXT = ListProperty(COLOR_TEXT)
    COLOR_TEXT_WEAK = ListProperty(COLOR_TEXT_WEAK)
    COLOR_DANGER = ListProperty(COLOR_DANGER)
    COLOR_DISABLED = ListProperty(COLOR_DISABLED)

    GRAD_NAVY_A = ListProperty(GRAD_NAVY_A)
    GRAD_NAVY_B = ListProperty(GRAD_NAVY_B)
    GRAD_LINK_A = ListProperty(GRAD_LINK_A)
    GRAD_LINK_B = ListProperty(GRAD_LINK_B)
    GRAD_FUNC_A = ListProperty(GRAD_FUNC_A)
    GRAD_FUNC_B = ListProperty(GRAD_FUNC_B)
    GRAD_LOG_A = ListProperty(GRAD_LOG_A)
    GRAD_LOG_B = ListProperty(GRAD_LOG_B)
    GRAD_TAB_A = ListProperty(GRAD_TAB_A)
    GRAD_TAB_B = ListProperty(GRAD_TAB_B)

    def build(self):
        self.font_name = register_cjk_font()
        self.ble = create_ble_manager()
        self.store = AccountStore(os.path.join(self.user_data_dir, 'accounts.db'))
        self._parser = RxFrameParser()
        self._notify_subscribed = False
        self._at_subscribed = False
        self._module_configured = False
        self._at_busy = False
        self._config_runner = None
        self._poll = None

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
        # 每次登录都从干净的显示屏开始
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
        # 先把本次登录的显示屏内容存档，再清屏
        self.save_session()
        self.current_user = ''
        self.logged_in = False
        self.clear_display()
        self.active_tab = 'mine'
        self.root.ids.sm.current = 'mine'
        try:
            self.screen('loginform').reset()
        except Exception:                                       # noqa: BLE001
            pass

    def save_session(self):
        """把本次登录期间显示屏的内容存进「记录」，最多保留 MAX_SESSION_LOGS 次。"""
        lines = list(self.display_lines)
        if not lines:
            return
        saved = [{'label': time.strftime('%m-%d %H:%M'), 'lines': lines}]
        saved.extend(list(self.sessions))
        del saved[MAX_SESSION_LOGS:]
        self.sessions = saved

    # ------------------------------------------------------------------
    # BLE 轮询（切页面也不停）
    # ------------------------------------------------------------------
    def _poll_ble(self, _dt):
        ble = self.ble
        title, detail, connected = ble.status()
        if title != self.status_text:
            self.status_text = title
        if detail != self.status_detail:
            self.status_detail = detail
        if connected != self.connected:
            self.connected = connected
            self.log_line('● 已连接设备' if connected else '○ 已断开连接')

        self._keep_notify(ble, connected)
        self._drain_incoming(ble)

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

        # AT 通道就绪后，自动把模块锁成 115200 + HFUT.BLE（每次连接只做一次）
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
            self.log_line('模块配置已锁定：串口 %d，设备名 %s'
                          % (MODULE_TARGET_BAUD, MODULE_TARGET_NAME))
        else:
            self.log_line('模块配置锁定没有收到 OK（模块可能不支持 AT 指令，不影响收发）')

    def _drain_incoming(self, ble):
        chunks = ble.pop_received()
        if not chunks:
            return
        data = bytearray()
        for chunk in chunks:
            try:
                data.extend(bytearray.fromhex(str(chunk)))
            except ValueError:
                Logger.warning('BleAssistant: 收到非十六进制回传数据，已跳过')
        for cmd, payload in self._parser.feed(data):
            self._on_reply(cmd, payload)

    def _on_reply(self, cmd, payload):
        """设备 → 手机：统一写进显示屏；「开发者」弹窗开着时同时显示在弹窗里。"""
        raw = bytes(bytearray(payload))
        raw_hex = to_hex(raw)
        text = decode_text(payload)
        shown = text if text.strip() else '（非文本载荷，原始 %s）' % (raw_hex or '空')
        self.log_line('← 收到 0x%02X（%d 字节）：%s' % (cmd, len(raw), shown))
        Logger.info('BleAssistant: 收到回传 cmd=0x%02X 载荷=%r 原始=%s', cmd, text, raw_hex)
        try:
            popup = getattr(self.screen('ctrl'), '_cmd_popup', None)
        except Exception:                                       # noqa: BLE001
            popup = None
        if popup is not None:
            popup.add_reply(cmd, text, raw_hex)

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
