# -*- coding: utf-8 -*-
"""桌面端 BLE 模拟实现（仅用于在电脑上预览界面，Android 上不会加载）。

接口与 ble_android.AndroidBleManager 完全一致，方便在没有手机的情况下
检查界面、登录注册流程与按钮解锁逻辑。
"""

import time

SCAN_IDLE, SCAN_RUNNING, SCAN_FAILED = 0, 1, 2
CONN_IDLE, CONN_CONNECTING, CONN_CONNECTED, CONN_DISCONNECTED, CONN_FAILED = 0, 1, 2, 3, 4

_FAKE_DEVICES = [
    ('MedPro 心率监测仪', 'C8:1F:66:0A:11:01', -46),
    ('MedPro 血氧指夹', 'C8:1F:66:0A:11:02', -58),
    ('智能输液泵 BLE-200', 'D4:36:39:77:20:11', -71),
    ('电子血压计 BP-5', 'E0:5A:1B:33:41:07', -83),
]

SCAN_VISIBLE_AFTER = 1.0      # 扫描开始多久后逐个出现设备
CONNECT_DELAY = 1.5           # 模拟连接耗时


class SimulatedBleManager(object):
    """电脑端模拟：扫描 3 秒后停止，连接 1.5 秒后成功。"""

    def __init__(self):
        self._scan_started = None
        self._connected_address = None
        self._connect_started = None
        self._connect_target = None

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

    @staticmethod
    def _name_of(address):
        for name, addr, _rssi in _FAKE_DEVICES:
            if addr == address:
                return name
        return '未知设备'
