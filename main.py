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

    def refresh_list(self):
        self.ids.reply_state.text = '本次登录共收到 %d 条回传' % len(self._history)
        box = self.ids.reply_list
        box.clear_widgets()
        if not self._history:
            box.add_widget(ReplyRow(
                text='本次还没有收到设备回传。\n'
                     '连接设备后点「功能一」，设备回传的内容会记录在这里。'))
            return
        # 最新的排在最上面。每条两行：行高固定时多行会被裁掉。
        for stamp, label, text, raw_hex in reversed(self._history):
            if text.strip():
                shown = text
            else:
                shown = '（空或不可见，原始：%s）' % (raw_hex or '空')
            box.add_widget(ReplyRow(text='%s    %s\n%s'
                                         % (stamp, clip_line(label, 40), shown)))


# ----------------------------------------------------------------------
# 模块诊断（AT 指令通道，只走蓝牙）
# ----------------------------------------------------------------------
AT_QUERIES = ['AT+VERSION?', 'AT+ROLE?', 'AT+UART?', 'AT+STATUS?', 'AT+AUTH?', 'AT+NAME?']

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


class ModuleDiagPopup(Popup):
    """通过模块自带的 AT 指令通道（6E400004）读取模块设置。

    这条通道只走蓝牙、不经过串口，所以即使"模块 → 电脑"那根线没通，
    也能确认模块本身是否正常、以及关键设置（尤其 AT+AUTH 是否开启）。
    """

    result_text = StringProperty('')

    def __init__(self, ble, on_result=None, **kwargs):
        super(ModuleDiagPopup, self).__init__(**kwargs)
        self._ble = ble
        self._on_result = on_result
        self._replies_text = []
        self._timer = None
        self._sent = 0
        self._elapsed = 0.0
        self._at_bytes = 0
        self._done = False

    def on_open(self, *args):
        super(ModuleDiagPopup, self).on_open(*args)
        self._refresh()

    def start(self):
        """由界面在弹出后立刻调用（Kivy 的 on_open 会延迟 0.5~1 秒才派发）。"""
        state, _message = self._ble.at_notify_state()
        if state != NOTIFY_SUBSCRIBED:
            self._stop()
            self._refresh()
            return
        self._timer = Clock.schedule_interval(self._step, 0.35)

    def on_dismiss(self, *args):
        super(ModuleDiagPopup, self).on_dismiss(*args)
        self._stop()

    def _stop(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _step(self, dt):
        self._elapsed += dt
        self._collect_replies()
        if self._sent < len(AT_QUERIES):
            query = AT_QUERIES[self._sent]
            self._sent += 1
            self._refresh()
            # 写操作由 GATT 队列串行化，不用自己再加间隔
            self._ble.send_command('', ESP32_AT_UUID,
                                   to_hex((query + '\r\n').encode('utf-8')))
            return
        if self._elapsed > len(AT_QUERIES) * 0.35 + 2.5:
            self._finish()

    def _finish(self):
        if self._done:
            return
        self._done = True
        self._stop()
        self._refresh()
        if self._on_result is not None:
            self._on_result(self.verdict())

    def _collect_replies(self):
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
        self._refresh()

    def rows(self):
        """把结果整理成若干"短行"，每行都用固定高度标签渲染。"""
        state, _message = self._ble.at_notify_state()
        lines = ['AT 订阅：%s    已收到 %d 字节'
                 % (_NOTIFY_STATE_TEXT.get(state, '未知'), self._at_bytes)]
        if self._at_bytes == 0:
            lines.append('0 字节 = 模块没有通过 6E400004 回复')
        for key, label in AT_QUERY_LABELS:
            value = '（无回复）'
            for text in self._replies_text:
                if text.startswith(key):
                    value = text
                    break
            lines.append('%s：%s' % (label, value))
        lines.append(self.verdict() if self._done else '查询中…')
        return [clip_line(line) for line in lines]

    def verdict(self):
        """一句话结论（同时会写进"回传记录"，那条显示路径已在你手机上验证可用）。"""
        auth = ''
        status = ''
        for text in self._replies_text:
            if text.startswith('AT+AUTH'):
                auth = text
            elif text.startswith('AT+STATUS'):
                status = text
        if not auth and not status:
            return '结论：模块未回复 AT（已收 %d 字节）' % self._at_bytes
        short_auth = auth.replace('AT+AUTH=', '').replace(' OK', '').strip() or '无回复'
        short_status = status.replace('AT+STATUS=', '').replace(' OK', '').strip() or '无回复'
        return '结论：鉴权=%s  状态显示=%s' % (short_auth, short_status)

    def _refresh(self):
        lines = self.rows()
        self.result_text = '\n'.join(lines)
        try:
            box = self.ids.diag_list
        except Exception:                                       # noqa: BLE001
            return
        box.clear_widgets()
        for line in lines:
            box.add_widget(PopupRow(text=line))


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

    def __init__(self, **kwargs):
        super(MainScreen, self).__init__(**kwargs)
        self._poll = None
        self._parser = RxFrameParser()
        self._notify_subscribed = False
        self._at_subscribed = False
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
    # 回传（ESP32 → 手机）
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

    def open_diag_dialog(self):
        """模块诊断：走模块自带的 AT 通道读它自己的设置（不经过串口）。"""
        if not self.connected:
            show_info('未连接', '请先连接 BLE 设备，再做模块诊断。')
            return
        popup = ModuleDiagPopup(ble=App.get_running_app().ble,
                                on_result=self.show_diag_summary)
        popup.open()
        # 不依赖 on_open（Kivy 会延迟 0.5~1 秒才派发），弹出后立刻启动查询
        Clock.schedule_once(lambda dt: popup.start(), 0.05)

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
