# -*- coding: utf-8 -*-
"""桌面端 BLE 模拟实现（仅用于在电脑上预览界面，Android 上不会加载）。

接口与 ble_android.AndroidBleManager 完全一致，方便在没有手机的情况下
检查界面、登录注册流程与按钮解锁逻辑。
"""

import time

from protocol import CMD_FUNC_1, EXAMPLE_BY_CMD, REPLY_FUNC_1, build_frame, to_hex

SCAN_IDLE, SCAN_RUNNING, SCAN_FAILED = 0, 1, 2
CONN_IDLE, CONN_CONNECTING, CONN_CONNECTED, CONN_DISCONNECTED, CONN_FAILED = 0, 1, 2, 3, 4
WRITE_IDLE, WRITE_SENDING, WRITE_SUCCESS, WRITE_FAILED = 0, 1, 2, 3
NOTIFY_OFF, NOTIFY_SUBSCRIBING, NOTIFY_SUBSCRIBED, NOTIFY_FAILED = 0, 1, 2, 3

# 模拟设备收到「功能一」后回传的内容（与桥接脚本保持一致）
SIM_REPLY_TEXT = 'Hello World'

# 模块 AT 指令通道（与真机一致）。波特率/名称按"锁定后的配置"显示。
AT_UUID = '6e400004-b5a3-f393-e0a9-e50e24dcca9e'
SIM_AT_REPLIES = {
    'AT+VERSION': 'AT+VERSION=2024.12.31\r\nOK\r\n',
    'AT+ROLE?': 'AT+ROLE=0 OK\r\n',
    'AT+UART?': 'AT+UART=115200 OK\r\n',
    'AT+STATUS?': 'AT+STATUS=1 OK\r\n',
    'AT+AUTH?': 'AT+AUTH=0,0000,15 OK\r\n',
    'AT+NAME?': 'AT+NAME=0,HFUT.BLE OK\r\n',
}

_FAKE_DEVICES = [
    ('MedPro 心率监测仪', 'C8:1F:66:0A:11:01', -46),
    ('MedPro 血氧指夹', 'C8:1F:66:0A:11:02', -58),
    ('智能输液泵 BLE-200', 'D4:36:39:77:20:11', -71),
    ('电子血压计 BP-5', 'E0:5A:1B:33:41:07', -83),
]

# 桌面预览用的假 GATT 表，结构照 Nordic UART 来，方便对着界面调 UUID
_FAKE_SERVICES = [
    {'service': '6e400001-b5a3-f393-e0a9-e50e24dcca9e',
     'characteristic': '', 'properties': 'service'},
    {'service': '6e400001-b5a3-f393-e0a9-e50e24dcca9e',
     'characteristic': '6e400002-b5a3-f393-e0a9-e50e24dcca9e',
     'properties': 'WRITE WRITE_NO_RESPONSE'},
    {'service': '6e400001-b5a3-f393-e0a9-e50e24dcca9e',
     'characteristic': '6e400003-b5a3-f393-e0a9-e50e24dcca9e',
     'properties': 'NOTIFY'},
]

SCAN_VISIBLE_AFTER = 1.0      # 扫描开始多久后逐个出现设备
CONNECT_DELAY = 1.5           # 模拟连接耗时
WRITE_DELAY = 0.4             # 模拟写入耗时


class SimulatedBleManager(object):
    """电脑端模拟：扫描 3 秒后停止，连接 1.5 秒后成功。"""

    def __init__(self):
        self._scan_started = None
        self._connected_address = None
        self._connect_started = None
        self._connect_target = None
        self._write_started = None
        self._write_result = None
        self._write_message = ''
        self._write_length = 0
        self._write_target = ''
        self._write_frame = b''
        self._notify_state = NOTIFY_OFF
        self._pending_received = []
        self._at_state = NOTIFY_OFF
        self._pending_at = []
        self.at_commands = []

    # ------------------------------------------------------------------
    # 扫描
    # ------------------------------------------------------------------
    def start_scan(self):
        self._scan_started = time.monotonic()

    def stop_scan(self):
        self._scan_started = None

    def devices(self):
        if self._scan_started is None:
            return []
        elapsed = time.monotonic() - self._scan_started
        visible = int(max(0.0, elapsed - SCAN_VISIBLE_AFTER) * 1.5)
        result = []
        for name, address, rssi in _FAKE_DEVICES[:max(1, visible)]:
            result.append({'name': name, 'address': address, 'rssi': rssi})
        result.sort(key=lambda d: -d['rssi'])
        return result

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------
    def connect(self, address):
        self._scan_started = None
        self._connect_target = address
        self._connect_started = time.monotonic()
        self._connected_address = None

    def disconnect(self):
        self._connect_target = None
        self._connect_started = None
        self._connected_address = None
        # 与 Java 侧保持一致：断开时清掉订阅状态与残留回传
        self._notify_state = NOTIFY_OFF
        self._pending_received = []
        self._at_state = NOTIFY_OFF
        self._pending_at = []
        self.reset_writes()

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def status(self):
        if self._connected_address:
            name = self._name_of(self._connected_address)
            detail = '%s\n%s · 服务 4 个' % (name, self._connected_address)
            return '已连接', detail, True

        if self._connect_target is not None:
            if time.monotonic() - self._connect_started < CONNECT_DELAY:
                return '正在连接…', '正在与设备建立 GATT 连接，请稍候', False
            self._connected_address = self._connect_target
            name = self._name_of(self._connected_address)
            detail = '%s\n%s · 服务 4 个' % (name, self._connected_address)
            return '已连接', detail, True

        if self._scan_started is not None:
            elapsed = time.monotonic() - self._scan_started
            if elapsed > 3.0:
                self._scan_started = None
                return '未连接', '未发现更多设备，可再次点击搜索', False
            count = len(self.devices())
            return '正在扫描…', '已发现 %d 个 BLE 设备' % count, False

        return '未连接', '点击下方「蓝牙连接」搜索附近的 BLE 设备', False

    # ------------------------------------------------------------------
    # 服务发现（桌面模拟：立即就绪）
    # ------------------------------------------------------------------
    def ensure_services(self, force=False):
        return ''

    def discovery_state(self):
        # 与 status() 保持一致的连接判定（含"延迟到点后完成连接"的转换）
        if not self._connected_address and self._connect_target is not None:
            if time.monotonic() - self._connect_started >= CONNECT_DELAY:
                self._connected_address = self._connect_target
        if not self._connected_address:
            return 0, ''
        return 4, 'ok, 4 service(s) (desktop mock)'

    def cache_refresh_result(self):
        return 'cleared (desktop mock)'

    # ------------------------------------------------------------------
    # 模块 AT 指令通道（桌面模拟：订阅即成功，按指令回一份合理的回复）
    # ------------------------------------------------------------------
    def enable_at_notify(self, service_uuid, char_uuid):
        if not self._connected_address:
            return False, 'device is not connected'
        self._at_state = NOTIFY_SUBSCRIBED
        return True, ''

    def at_notify_state(self):
        return self._at_state, ''

    def pop_received_at(self):
        chunks = self._pending_at
        self._pending_at = []
        return chunks

    # ------------------------------------------------------------------
    # 命令下发（桌面模拟：延迟一点后返回成功）
    # ------------------------------------------------------------------
    def send_command(self, service_uuid, char_uuid, hex_data, auto_pick=True):
        if not self._connected_address:
            return False, 'device is not connected'
        text = (hex_data or '').strip()
        if not text or (len(text) % 2) != 0:
            return False, 'command payload is empty or not valid hex'

        # 写到 AT 通道：模拟模块回一条合理的 AT 回复
        if AT_UUID in (char_uuid or '').lower():
            try:
                query = bytes(bytearray.fromhex(text)).decode('utf-8', 'replace').strip()
            except ValueError:
                query = ''
            self.at_commands.append(query)          # 供测试/预览查看发过哪些 AT 指令
            reply = SIM_AT_REPLIES.get(query, 'OK\r\n')
            self._pending_at.append(to_hex(reply.encode('utf-8')))
            return True, ''

        if len(text) // 2 > 20:
            return False, 'command payload is longer than a single write'
        self._write_frame = bytes(bytearray.fromhex(text))
        self._write_length = len(text) // 2
        self._write_target = (char_uuid or '6e400002-b5a3-f393-e0a9-e50e24dcca9e '
                                            '(auto-picked, desktop mock)').strip()
        self._write_started = time.monotonic()
        self._write_result = None
        self._write_message = ''
        return True, '命令已入队（桌面模拟）'

    def write_target(self):
        return self._write_target

    def write_state(self):
        if self._write_started is None:
            return WRITE_IDLE, ''
        if self._write_result is not None:
            return self._write_result, self._write_message
        if time.monotonic() - self._write_started >= WRITE_DELAY:
            self._write_result = WRITE_SUCCESS
            self._write_message = 'wrote %d byte(s) successfully' % self._write_length
            # 按命令字回传（与 bridge.py 的行为一致）
            if self._notify_state == NOTIFY_SUBSCRIBED:
                for reply_cmd, reply_text in self._replies_for(self._write_frame):
                    self._pending_received.append(
                        to_hex(build_frame(reply_cmd, reply_text.encode('utf-8'))))
            return self._write_result, self._write_message
        return WRITE_SENDING, ''

    @staticmethod
    def _replies_for(frame):
        """命令帧 → 设备应该回传的 [(命令字, 文字), ...]。"""
        if len(frame) < 3 or frame[0] != 0xAA or frame[1] != 0x55:
            return []
        cmd = frame[2]
        if cmd == CMD_FUNC_1:
            return [(REPLY_FUNC_1, SIM_REPLY_TEXT)]
        example = EXAMPLE_BY_CMD.get(cmd)
        if example is not None:
            reply_cmd, reply_text = example
            return [(reply_cmd, reply_text)]
        return []

    # ------------------------------------------------------------------
    # 回传（桌面模拟：订阅即成功，写入成功后自动回一帧）
    # ------------------------------------------------------------------
    def enable_notify(self, service_uuid, char_uuid, auto_pick=True):
        if not self._connected_address:
            return False, 'device is not connected'
        self._notify_state = NOTIFY_SUBSCRIBED
        return True, ''

    def notify_state(self):
        return self._notify_state, ''

    def pop_received(self):
        chunks = self._pending_received
        self._pending_received = []
        return chunks

    def reset_writes(self):
        self._write_started = None
        self._write_result = None
        self._write_message = ''
        self._write_frame = b''

    def services_info(self):
        return [dict(item) for item in _FAKE_SERVICES]

    # ------------------------------------------------------------------
    # 诊断（桌面模拟）
    # ------------------------------------------------------------------
    def diagnostics(self):
        state = '扫描中' if self._scan_started is not None else '空闲'
        return '桌面模拟环境 | 扫描 %s | 设备 %d' % (state, len(self.devices()))

    @staticmethod
    def _name_of(address):
        for name, addr, _rssi in _FAKE_DEVICES:
            if addr == address:
                return name
        return '未知设备'
