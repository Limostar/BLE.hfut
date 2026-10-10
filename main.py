# -*- coding: utf-8 -*-
"""绿联蓝牙助手 —— 医疗设备 BLE 连接演示 App。

界面结构：
    登录页  ->  注册页（注册成功回到登录页）
            ->  蓝牙功能页（登录成功后进入）

蓝牙功能页：点击「蓝牙连接」搜索附近 BLE 设备并选择连接，
连接成功后解锁 8 个预留功能按钮。
"""

import os
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, StringProperty
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.utils import platform

from accounts import AccountStore
from protocol import (CMD_FUNC_1, MAX_PAYLOAD, REPLY_FUNC_1, RxFrameParser,
                      build_frame, decode_text, to_hex)

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
# 用于"模块诊断"：读模块的版本/角色/波特率/状态显示/用户鉴权等设置。
# 一旦模块开了用户鉴权(AT+AUTH=1)，App 没有鉴权密码，模块会静默丢弃手机写入的数据
# —— 现象与"串口线没接"一模一样，所以这个诊断很有用。
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
class DeviceRow(Button):
    """设备列表中的一行。"""


class ServiceRow(Label):
    """服务 / 特征列表中的一行。"""


class ReplyRow(Label):
    """回传记录列表中的一行。"""


class PopupRow(Label):
    """弹窗正文的一行。

    重要：弹窗里的文字一律用"一行一个固定高度标签"来渲染。
    这种写法在你的手机上已验证可正常显示（服务列表、回传记录都是它）；
    而"整块高度跟着文字纹理自适应"的标签在手机上会拿不到有效尺寸，显示成空白。
    """


class RootWidget(ScreenManager):
    """承载三个页面。"""


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
            row = DeviceRow()
            row.text = '%s\n%s   信号 %d dBm' % (device['name'],
                                                device['address'],
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


class CommandPopup(Popup):
    """命令下发的结果反馈：入队 → 发送中 → 成功 / 失败 / 超时。"""

    command_name = StringProperty('')
    frame_hex = StringProperty('')
    target_text = StringProperty('')
    result_text = StringProperty('')

    def __init__(self, ble, accepted, message, **kwargs):
        super(CommandPopup, self).__init__(**kwargs)
        self._ble = ble
        self._accepted = accepted
        self._message = message
        self._poll = None
        self._elapsed = 0.0
        if not accepted:
            self.result_text = '下发失败：%s' % message

    def on_open(self, *args):
        super(CommandPopup, self).on_open(*args)
        if not self._accepted:
            return
        self.result_text = '发送中…'
        self._poll = Clock.schedule_interval(self._refresh, 0.3)

    def on_dismiss(self, *args):
        super(CommandPopup, self).on_dismiss(*args)
        self._stop_poll()

    def _stop_poll(self):
        if self._poll is not None:
            self._poll.cancel()
            self._poll = None

    def _refresh(self, dt):
        self._elapsed += dt
        target = self._ble.write_target()
        if target:
            self.target_text = '实际写入特征：%s' % target
        state, message = self._ble.write_state()
        if state == WRITE_SUCCESS:
            self._finish('发送成功：%s' % (message or '已写入特征值'))
        elif state == WRITE_FAILED:
            self._finish('发送失败：%s' % (message or '未知原因'))
        elif self._elapsed > WRITE_TIMEOUT:
            # 任何"非最终状态"超时都要报出来，
            # 否则一旦 GATT 操作卡住，界面会永远停在"发送中…"
            self._ble.reset_writes()
            self._finish('超时：%.0f 秒内没有拿到写入结果'
                         '（请确认设备已连接、且该特征可写）' % WRITE_TIMEOUT)
        else:
            self.result_text = '发送中…'

    def _finish(self, text):
        self.result_text = text
        self._stop_poll()


class ServicesPopup(Popup):
    """列出已连接设备暴露的服务与特征，用来确认要写哪个 UUID。"""

    def __init__(self, ble, **kwargs):
        super(ServicesPopup, self).__init__(**kwargs)
        self._ble = ble

    def on_open(self, *args):
        super(ServicesPopup, self).on_open(*args)
        self.refresh_list()

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
class ReplyHistoryPopup(Popup):
    """本次登录期间收到的设备回传记录（可滑动查看）。"""

    def __init__(self, history, on_clear=None, **kwargs):
        super(ReplyHistoryPopup, self).__init__(**kwargs)
        self._history = list(history)
        self._on_clear = on_clear

    def on_open(self, *args):
        super(ReplyHistoryPopup, self).on_open(*args)
        self.refresh_list()

    def clear_history(self):
        if self._on_clear is not None:
            self._on_clear()
        self._history = []
        self.refresh_list()

    MAX_ROWS = 8            # 弹窗里不再使用滚动容器，所以只显示最近若干条

    def refresh_list(self):
        total = len(self._history)
        self.ids.reply_state.text = clip_line(
            '本次登录共 %d 条，下面显示最近 %d 条（最新在最上面）'
            % (total, min(total, self.MAX_ROWS)))

        box = self.ids.reply_list
        box.clear_widgets()
        visible = self._history[-self.MAX_ROWS:]
        if not visible:
            box.add_widget(ReplyRow(text='本次还没有收到设备回传'))
            return
        # 关键：按时间顺序 add（旧的先加），最后加进去的是最新的一条。
        # Kivy 的 BoxLayout 会把"最后加入的"放在最上面，这样最新记录就在最上方，
        # 不会被挤出可见区域（之前正是反着排，导致新记录被顶到看不见的地方）。
        for stamp, label, text, raw_hex in visible:
            if text.strip():
                shown = text
            else:
                shown = '（空，原始：%s）' % (raw_hex or '空')
            box.add_widget(ReplyRow(
                text=clip_line('%s %s %s' % (stamp, label, shown), 52)))


class AtDebugPopup(Popup):
    """AT 调试：从手机直接给模块发任意 AT 指令。

    走的是模块自带的 AT 指令通道（6E400004），**完全不经过串口**，
    所以即使"模块 → 电脑"那条链路一点反应都没有，也能读写模块自己的配置。

    典型用途：
        AT+AUTH?      复核用户鉴权状态
        AT+AUTH=0     关闭用户鉴权（开启时写入会被接受但不转发到串口）
        AT+ECHO=1     打开串口回显（电脑写什么、模块就回什么）
        AT+STATUS=1   打开状态显示（手机一连上，电脑端应出现 S:CONNECTED）
        AT+RESTART    重启模块
    """

    command = StringProperty('AT+VERSION')
    state = StringProperty('输入 AT 指令后点「发送」；回复显示在下方。')
    MAX_ROWS = 6

    def __init__(self, ble, **kwargs):
        super(AtDebugPopup, self).__init__(**kwargs)
        self._ble = ble
        self._lines = []
        self._timer = None
        self._deadline = 0.0

    # ------------------------------------------------------------------
    def on_open(self, *args):
        Clock.schedule_once(self._focus_input, 0.6)

    def _focus_input(self, dt):
        try:
            self.ids.at_input.focus = True
        except Exception:                                       # noqa: BLE001
            pass

    def quick(self, text):
        """快捷按钮：填好指令后直接发。"""
        self.command = text
        self.send()

    def send(self):
        cmd = (self.command or '').strip()
        if not cmd:
            self.state = '请先输入一条 AT 指令。'
            return
        state, _message = self._ble.at_notify_state()
        if state != NOTIFY_SUBSCRIBED:
            self.state = 'AT 通道未订阅：请先回主界面点一次「模块诊断」。'
            return
        self._lines = []
        self._render()
        self.state = '已发送 %s，等待回复…' % cmd
        self._ble.send_command('', ESP32_AT_UUID,
                               to_hex((cmd + '\r\n').encode('utf-8')))
        self._deadline = time.monotonic() + 2.0
        if self._timer is not None:
            self._timer.cancel()
        self._timer = Clock.schedule_interval(self._poll, 0.2)

    def _poll(self, dt):
        got = False
        for chunk in self._ble.pop_received_at():
            try:
                raw = bytes(bytearray.fromhex(chunk))
            except ValueError:
                continue
            got = True
            text = raw.decode('utf-8', 'replace').replace('\r', '')
            for line in text.split('\n'):
                line = line.strip()
                if line:
                    self._lines.append(clip_line(line, 46))
        if got:
            self._render()
        if time.monotonic() >= self._deadline:
            self._stop_poll()
            if not self._lines:
                self._lines.append('（2 秒内没有收到回复，可能指令不被支持）')
                self._render()
            self.state = '完成，收到 %d 行回复。' % len(self._lines)

    def _stop_poll(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _render(self):
        box = self.ids.at_reply
        box.clear_widgets()
        for line in self._lines[-self.MAX_ROWS:]:
            box.add_widget(PopupRow(text=line))

    def on_dismiss(self, *args):
        self._stop_poll()


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


class ModuleDiagRunner(object):
    """按节奏发送 AT 查询并收集回复（不依赖任何弹窗）。

    为什么不用弹窗：弹窗正文在你的手机上多次显示为空白，而主界面上的
    固定高度标签（状态卡那一行）是已经验证过能显示的，所以结果直接写回主界面。
    """

    def __init__(self, ble, on_lines=None, on_progress=None, on_done=None):
        self._ble = ble
        self._on_lines = on_lines
        self._on_progress = on_progress
        self._on_done = on_done
        self._replies_text = []
        self._timer = None
        self._sent = 0
        self._elapsed = 0.0
        self._at_bytes = 0
        self._finished = False

    def start(self):
        state, _message = self._ble.at_notify_state()
        if state != NOTIFY_SUBSCRIBED:
            self._progress('AT 未订阅')
            self._emit_lines(['%s：%s' % (name, BAD_OUTPUT)
                              for _key, name in AT_QUERY_LABELS])
            return False
        self._progress('诊断中…')
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
            self._progress('诊断中 %d/6' % self._sent)
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

    def summary(self):
        """一行总览（写进回传记录）。"""
        auth = self.value_of('AT+AUTH')
        status = self.value_of('AT+STATUS')
        if not auth and not status:
            return '模块诊断全部%s（已收 %d 字节）' % (BAD_OUTPUT, self._at_bytes)
        short_auth = auth.replace('AT+AUTH=', '').replace(' OK', '').strip() or BAD_OUTPUT
        short_status = status.replace('AT+STATUS=', '').replace(' OK', '').strip() or BAD_OUTPUT
        return '模块诊断：鉴权=%s 状态显示=%s 收=%d字节' % (
            short_auth, short_status, self._at_bytes)

    def _emit_lines(self, lines=None):
        if self._on_lines is not None:
            self._on_lines(self.lines() if lines is None else lines)

    def _progress(self, text):
        if self._on_progress is not None:
            self._on_progress(text)

    def _done(self):
        if self._finished:              # 防止重复收尾（重复写记录）
            return
        self._finished = True
        self._emit_lines()
        summary = self.summary()
        self._progress('模块诊断')
        if self._on_done is not None:
            self._on_done(summary, self.lines())


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
        app.current_user = username.strip()
        app.root.current = 'main'

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
        app.root.get_screen('login').prepare(username, msg)
        self.reset()
        app.root.current = 'login'

    def back_to_login(self):
        self.reset()
        self.manager.current = 'login'


class MainScreen(Screen):
    status_text = StringProperty('未连接')
    status_detail = StringProperty('点击下方「蓝牙连接」搜索附近的 BLE 设备')
    connected = BooleanProperty(False)
    user_text = StringProperty('')
    reply_label = StringProperty('查看回传记录')
    diag_button = StringProperty('模块诊断')

    def __init__(self, **kwargs):
        super(MainScreen, self).__init__(**kwargs)
        self._poll = None
        self._parser = RxFrameParser()
        self._notify_subscribed = False
        self._at_subscribed = False
        self._diag = None
        self._replies = []          # 本次登录期间收到的设备回传

    def on_enter(self, *args):
        app = App.get_running_app()
        self.user_text = '当前用户：%s' % (app.current_user or '-')
        # 每次进入本页都代表一次新的登录，先把上一次的回传记录清空
        self.clear_replies()
        self._refresh(0)
        if self._poll is None:
            self._poll = Clock.schedule_interval(self._refresh, 0.4)

    def on_leave(self, *args):
        if self._poll is not None:
            self._poll.cancel()
            self._poll = None
        if self._diag is not None:
            self._diag.stop()

    def _refresh(self, dt):
        ble = App.get_running_app().ble
        title, detail, connected = ble.status()
        if title != self.status_text:
            self.status_text = title
        if detail != self.status_detail:
            self.status_detail = detail
        if connected != self.connected:
            self.connected = connected

        self._keep_notify(ble, connected)
        self._drain_incoming(ble)

    # ------------------------------------------------------------------
    # 回传（设备 → 手机）
    # ------------------------------------------------------------------
    def _keep_notify(self, ble, connected):
        """连上就自动订阅回传通知与 AT 通道；订阅幂等，没成功会在下一轮重试。"""
        if not connected:
            self._notify_subscribed = False
            self._at_subscribed = False
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

        # 数据通道就绪后，顺便订阅模块的 AT 指令通道（供"模块诊断"使用）
        if self._notify_subscribed and not self._at_subscribed:
            state, _message = ble.at_notify_state()
            if state == NOTIFY_SUBSCRIBED:
                self._at_subscribed = True
            elif state != NOTIFY_SUBSCRIBING:
                ble.enable_at_notify('', ESP32_AT_UUID)

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
        raw = bytes(bytearray(payload))
        raw_hex = to_hex(raw)
        text = decode_text(payload)
        self.add_record('命令字 0x%02X · %d 字节' % (cmd, len(raw)), text, raw_hex)
        Logger.info('BleAssistant: 收到回传 cmd=0x%02X 载荷=%r 原始=%s', cmd, text, raw_hex)

        # 载荷为空或全是不可见字符时，直接把原始字节显示出来，
        # 避免出现"弹窗有、内容空"这种查不下去的情况
        if text.strip():
            body = text
        else:
            body = '载荷不是可显示文字。\n原始字节：%s' % (raw_hex or '（空）')
        show_info('收到设备回传（0x%02X，%d 字节）' % (cmd, len(raw)), body)

    def add_record(self, label, text, raw_hex=''):
        """往"回传记录"里加一条。

        模块诊断的结论也走这里——因为"回传记录"这条显示路径在你的手机上已验证可用，
        等于给诊断结果留了第二条能被看到的通道。
        """
        self._replies.append((time.strftime('%H:%M:%S'), label, text, raw_hex))
        self.reply_label = '查看回传记录（%d）' % len(self._replies)

    def show_diag_summary(self, summary):
        self.add_record('模块诊断', summary)

    # ------------------------------------------------------------------
    # 回传记录（本次登录期间）
    # ------------------------------------------------------------------
    def replies(self):
        """返回本次登录收到的回传列表 [(时间, 命令字, 文字, 原始hex), ...]。"""
        return list(self._replies)

    def clear_replies(self):
        """清空回传记录。

        登录进入本页、退出登录、以及界面上的「清空记录」都会走这里，
        所以不会出现"还显示上次那条 Hello World"的情况。
        """
        self._replies = []
        self.reply_label = '查看回传记录'

    def open_reply_dialog(self):
        ReplyHistoryPopup(history=self.replies(), on_clear=self.clear_replies).open()

    def run_module_diag(self):
        """模块诊断：走模块自带的 AT 通道读它自己的设置（不经过串口）。

        结果**固定显示在主界面上的 6 行标签**里（一行一项，不轮换、不弹窗），
        用的是和状态卡/服务页绿字完全相同的那套写法；查不到或格式不对的行
        会显示「输出异常」。同时写进「回传记录」作为第二条通道。
        """
        if not self.connected:
            show_info('未连接', '请先连接 BLE 设备，再做模块诊断。')
            return
        if self._diag is not None:
            self._diag.stop()
        self._diag = ModuleDiagRunner(
            ble=App.get_running_app().ble,
            on_lines=self._set_diag_lines,
            on_progress=self._set_diag_progress,
            on_done=self._on_diag_done)
        self._diag.start()

    def _set_diag_lines(self, lines):
        """把 6 行检验结果写进主界面上 6 个固定高度标签。"""
        for index, text in enumerate(lines[:6], start=1):
            try:
                label = self.ids['diag_%d' % index]
            except Exception:                                   # noqa: BLE001
                continue
            label.text = clip_line(text, 40)

    def _set_diag_progress(self, text):
        self.diag_button = clip_line(text, 12)

    def _on_diag_done(self, summary, detail_lines):
        # 先写明细、最后写结论：记录页按"最新的在上面"排列，
        # 这样打开记录页第一眼看到的就是结论本身
        for line in detail_lines:
            self.add_record('模块诊断明细', line)
        self.add_record('模块诊断', summary)

    def open_at_debug(self):
        """AT 调试弹窗：走蓝牙 AT 通道读写模块配置，不经过串口。"""
        if not self.connected:
            show_info('未连接', '请先连接 BLE 设备，再使用 AT 调试。')
            return
        AtDebugPopup(ble=App.get_running_app().ble).open()

    def open_device_dialog(self):
        if self.connected:
            show_info('已连接', '当前已连接设备，如需更换请先点击「断开连接」。')
            return
        ble = App.get_running_app().ble
        DevicePopup(ble=ble, on_pick=self._on_device_picked).open()

    def _on_device_picked(self, device):
        App.get_running_app().ble.connect(device['address'])

    def do_disconnect(self):
        App.get_running_app().ble.disconnect()

    def open_services_dialog(self):
        if not self.connected:
            show_info('未连接', '请先连接 BLE 设备，再查看它的服务与特征。')
            return
        ServicesPopup(ble=App.get_running_app().ble).open()

    def reserved(self, name):
        # 功能一已接入真实命令下发，其余按钮仍是预留
        if name == '功能一':
            self._send_function_one()
            return
        show_info('功能预留', '「%s」为预留功能，后续可在此接入具体医疗设备指令。' % name)

    def _send_function_one(self):
        app = App.get_running_app()
        if not self.connected:
            show_info('未连接', '请先连接 BLE 设备，再下发命令。')
            return

        # 没有服务表就写不进去：先催一次服务发现，别让你对着"发送中…"干等
        service_count, discovery_message = app.ble.discovery_state()
        if service_count <= 0:
            app.ble.ensure_services(force=True)
            show_info('设备的服务尚未就绪',
                      '还没读到设备的服务/特征列表（当前 %d 个），无法确定往哪个特征写命令。\n\n'
                      '已重新发起一次服务发现，请等 1~2 秒后再点「功能一」。\n'
                      '若这里一直是 0：点「服务/特征」→「重新发现服务」，或断开重连、'
                      '把手机蓝牙关一下再打开（清掉安卓的 GATT 缓存）。\n\n'
                      '当前状态：%s' % (service_count, discovery_message or '未知'))
            return

        frame = build_frame(CMD_FUNC_1)
        if len(frame) > MAX_PAYLOAD:
            show_info('命令过长',
                      '当前命令 %d 字节，超过单次写入上限 %d 字节。' % (len(frame), MAX_PAYLOAD))
            return

        hex_data = to_hex(frame)
        accepted, message = app.ble.send_command(ESP32_SERVICE_UUID,
                                                 ESP32_WRITE_UUID,
                                                 hex_data,
                                                 auto_pick=ESP32_AUTO_PICK_WRITE)
        if not accepted:
            # 失败时直接把设备上实际可用的特征列出来，省掉一轮试错
            show_info('命令下发失败', '%s\n\n%s' % (message, self._feature_hint(app.ble)))
            return

        CommandPopup(ble=app.ble,
                     command_name='功能一',
                     frame_hex=hex_data,
                     accepted=accepted,
                     message=message).open()

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

    def logout(self):
        self.clear_replies()
        App.get_running_app().logout()


# ----------------------------------------------------------------------
# App
# ----------------------------------------------------------------------
class BleAssistantApp(App):
    title = '绿联蓝牙助手'

    font_name = StringProperty('Roboto')
    current_user = StringProperty('')

    COLOR_PRIMARY = ListProperty(COLOR_PRIMARY)
    COLOR_PRIMARY_DARK = ListProperty(COLOR_PRIMARY_DARK)
    COLOR_BG = ListProperty(COLOR_BG)
    COLOR_CARD = ListProperty(COLOR_CARD)
    COLOR_LINE = ListProperty(COLOR_LINE)
    COLOR_TEXT = ListProperty(COLOR_TEXT)
    COLOR_TEXT_WEAK = ListProperty(COLOR_TEXT_WEAK)
    COLOR_DANGER = ListProperty(COLOR_DANGER)
    COLOR_DISABLED = ListProperty(COLOR_DISABLED)

    def build(self):
        self.font_name = register_cjk_font()
        self.ble = create_ble_manager()
        self.store = AccountStore(os.path.join(self.user_data_dir, 'accounts.db'))

        Window.bind(on_keyboard=self._on_keyboard)
        Builder.load_file(KV_FILE)
        return RootWidget()

    # ------------------------------------------------------------------
    # 全局
    # ------------------------------------------------------------------
    def logout(self):
        try:
            self.ble.disconnect()
        except Exception:
            Logger.exception('BleAssistant: 退出登录时断开连接失败')
        self.current_user = ''
        self.root.get_screen('login').reset()
        self.root.current = 'login'

    def _on_keyboard(self, window, key, scancode, codepoint, modifiers):
        # Android 返回键（27）与桌面 ESC 一致
        if key == 27:
            current = self.root.current
            if current == 'register':
                self.root.get_screen('register').back_to_login()
                return True
            if current == 'main':
                # 主界面拦截返回键，避免误退出应用
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
