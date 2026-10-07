# -*- coding: utf-8 -*-
"""绿联蓝牙助手 —— 医疗设备 BLE 连接演示 App。

界面结构：
    登录页  ->  注册页（注册成功回到登录页）
            ->  蓝牙功能页（登录成功后进入）

蓝牙功能页：点击「蓝牙连接」搜索附近 BLE 设备并选择连接，
连接成功后解锁 8 个预留功能按钮。
"""

import os

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
ESP32_WRITE_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'   # 默认示例：Nordic UART 的 RX 特征
ESP32_SERVICE_UUID = ''

# 调试开关：按上面的 UUID 找不到特征时，自动改用"设备上第一个可写特征"，
# 这样第一次构建就能先跑通链路；弹窗里会显示它实际写到了哪个特征。
# 正式使用时建议把这个改成 False，只允许写约定的那一个特征。
ESP32_AUTO_PICK_WRITE = True

# 各功能按钮对应的命令字（与 ESP32 固件约定）
CMD_FUNC_1 = 0x01

# 命令帧格式：[0xAA][0x55][命令字][数据长度][数据...][异或校验]
# 如果你们固件用的是别的格式，只需要改 build_frame() 这一个函数。
FRAME_HEADER = (0xAA, 0x55)

# 单次写入的载荷上限：默认 MTU=23，减去 3 字节 ATT 头，即 20 字节。
# 超过这个长度需要先协商 MTU 并分片，当前版本会明确提示而不是静默失败。
MAX_PAYLOAD = 20

# 写入结果等待超时（秒）
WRITE_TIMEOUT = 3.0

WRITE_IDLE, WRITE_SENDING, WRITE_SUCCESS, WRITE_FAILED = 0, 1, 2, 3


def build_frame(cmd, data=b''):
    """按默认帧格式拼一条命令。要换格式就改这个函数。"""
    payload = bytes(bytearray(data))
    body = bytes(bytearray([cmd, len(payload)])) + payload
    checksum = 0
    for value in bytearray(body):
        checksum ^= value
    return bytes(bytearray(FRAME_HEADER)) + body + bytes(bytearray([checksum]))


def to_hex(data):
    return ''.join('%02X' % value for value in bytearray(data))


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


class RootWidget(ScreenManager):
    """承载三个页面。"""


def show_info(title, message):
    popup = InfoPopup(title=title, message=message)
    popup.open()
    return popup


class InfoPopup(Popup):
    message = StringProperty('')


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
        elif state == WRITE_SENDING and self._elapsed > WRITE_TIMEOUT:
            # 客户端超时：清掉队列，否则后续命令会一直卡在"发送中"
            self._ble.reset_writes()
            self._finish('超时：设备 %.0f 秒内没有返回写入结果' % WRITE_TIMEOUT)
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
        box = self.ids.service_list
        box.clear_widgets()
        items = self._ble.services_info()
        if not items:
            box.add_widget(ServiceRow(
                text='还没读到服务列表。\n'
                     '请确认设备已连接，并稍等一两秒（服务发现是异步完成的）后再打开本页。'))
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

    def __init__(self, **kwargs):
        super(MainScreen, self).__init__(**kwargs)
        self._poll = None

    def on_enter(self, *args):
        app = App.get_running_app()
        self.user_text = '当前用户：%s' % (app.current_user or '-')
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
        CommandPopup(ble=app.ble,
                     command_name='功能一',
                     frame_hex=hex_data,
                     accepted=accepted,
                     message=message).open()

    def logout(self):
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
