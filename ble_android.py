# -*- coding: utf-8 -*-
"""Android 端 BLE 实现。

通过 PyJNIus 调用本工程自带的 Java 桥接类 BleHelper
（javasrc/com/med/bleassistant/ble/BleHelper.java），
Python 侧只做"发起动作 + 轮询状态"，不直接接触 Java 回调接口。
"""

from kivy.clock import Clock
from kivy.logger import Logger

HELPER_CLASS = 'com.med.bleassistant.ble.BleHelper'

# 与 BleHelper.java 中的常量保持一致
SCAN_IDLE, SCAN_RUNNING, SCAN_FAILED = 0, 1, 2
CONN_IDLE, CONN_CONNECTING, CONN_CONNECTED, CONN_DISCONNECTED, CONN_FAILED = 0, 1, 2, 3, 4

_SCAN_ERROR_TEXT = {
    -1: '无法获取蓝牙适配器，请确认手机支持蓝牙',
    -2: '蓝牙未开启，请先在系统设置中打开蓝牙',
    -3: '无法获取 BLE 扫描器，请确认手机支持低功耗蓝牙',
    -4: '扫描启动失败，请检查「附近的设备」权限是否允许',
}


class AndroidBleManager(object):
    """Android 真机上的 BLE 管理器。"""

    def __init__(self):
        self._helper = None
        self._activity = None
        self._init_error = ''
        self._note = ''
        self._scanning = False
        self._pending_grant = None
        self._setup()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _setup(self):
        try:
            from jnius import autoclass
            python_activity = autoclass('org.kivy.android.PythonActivity')
            self._activity = python_activity.mActivity
            self._helper = autoclass(HELPER_CLASS)
        except Exception as exc:
            self._init_error = '蓝牙组件加载失败：%s' % exc
            Logger.exception('BleAssistant: BleHelper 初始化失败')

    @property
    def available(self):
        return self._helper is not None

    # ------------------------------------------------------------------
    # 权限
    # ------------------------------------------------------------------
    @staticmethod
    def _sdk_int():
        try:
            from jnius import autoclass
            return int(autoclass('android.os.Build$VERSION').SDK_INT)
        except Exception:
            return 30

    def _permission_list(self):
        if self._sdk_int() >= 31:
            # Android 12 起蓝牙扫描/连接使用独立权限
            return ['android.permission.BLUETOOTH_SCAN',
                    'android.permission.BLUETOOTH_CONNECT']
        return ['android.permission.ACCESS_FINE_LOCATION']

    def _ensure_permissions(self, on_granted):
        try:
            from android.permissions import request_permissions
        except Exception:
            # 没有 android 模块时直接继续，让系统在调用时抛错并给出提示
            if on_granted is not None:
                on_granted()
            return
        self._pending_grant = on_granted
        try:
            request_permissions(self._permission_list(), self._on_permission_result)
        except Exception:
            Logger.exception('BleAssistant: 请求蓝牙权限失败')
            self._pending_grant = None
            if on_granted is not None:
                on_granted()

    def _on_permission_result(self, permissions, grant_results):
        try:
            if isinstance(grant_results, (list, tuple)):
                granted = bool(grant_results) and all(bool(g) for g in grant_results)
            else:
                granted = bool(grant_results)
        except Exception:
            granted = False

        callback = self._pending_grant
        self._pending_grant = None
        if not granted:
            self._note = '蓝牙权限被拒绝，请在系统设置中允许「附近的设备」权限'
            return
        if callback is not None:
            Clock.schedule_once(lambda dt: callback(), 0)

    # ------------------------------------------------------------------
    # 扫描
    # ------------------------------------------------------------------
    def start_scan(self):
        if not self.available:
            return
        self._note = ''
        self._ensure_permissions(self._do_start_scan)
        # 用户此前已授权时，权限回调不一定触发，这里补一次
        Clock.schedule_once(lambda dt: self._do_start_scan(), 1.2)

    def _do_start_scan(self):
        if not self.available or self._scanning:
            return
        try:
            if not self._helper.isBluetoothEnabled(self._activity):
                self._helper.requestEnable(self._activity)
                self._note = '蓝牙未开启，请在系统弹窗中开启蓝牙'
                return
            self._helper.clearDevices()
            self._helper.startScan(self._activity)
            self._scanning = True
        except Exception:
            Logger.exception('BleAssistant: 启动扫描失败')
            self._note = '启动扫描失败，请查看日志'

    def stop_scan(self):
        self._scanning = False
        if not self.available:
            return
        try:
            self._helper.stopScan()
        except Exception:
            Logger.exception('BleAssistant: 停止扫描失败')

    def devices(self):
        """返回 [{'name','address','rssi'}, ...]，按信号强度排序。"""
        if not self.available:
            return []
        try:
            raw = self._helper.getDevices()
        except Exception:
            Logger.exception('BleAssistant: 读取扫描结果失败')
            return []
        result = []
        for item in raw or []:
            parts = str(item).split('|')
            if len(parts) != 3:
                continue
            name, address, rssi = parts
            try:
                rssi_val = int(rssi)
            except ValueError:
                rssi_val = 0
            result.append({
                'name': name.strip() or '未知设备',
                'address': address.strip(),
                'rssi': rssi_val,
            })
        result.sort(key=lambda d: -d['rssi'])
        return result

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------
    def connect(self, address):
        if not self.available:
            return
        self._note = ''
        self.stop_scan()
        try:
            self._helper.connect(self._activity, address)
        except Exception:
            Logger.exception('BleAssistant: 连接失败')

    def disconnect(self):
        if not self.available:
            return
        self._scanning = False
        try:
            self._helper.disconnect()
        except Exception:
            Logger.exception('BleAssistant: 断开连接失败')

    # ------------------------------------------------------------------
    # 状态（供界面轮询）
    # ------------------------------------------------------------------
    def status(self):
        """返回 (标题, 详情, 是否已连接)。"""
        if not self.available:
            return '蓝牙不可用', self._init_error or '未找到蓝牙组件', False
        try:
            conn = int(self._helper.getConnState())
            scan = int(self._helper.getScanState())
            count = int(self._helper.getDeviceCount())
            scan_error = int(self._helper.getScanError())
        except Exception as exc:
            Logger.exception('BleAssistant: 读取蓝牙状态失败')
            return '蓝牙异常', str(exc), False

        if scan != SCAN_RUNNING:
            self._scanning = False

        if conn == CONN_CONNECTED:
            name = self._helper.getConnectedName() or '未命名设备'
            address = self._helper.getConnectedAddress() or '-'
            services = int(self._helper.getServiceCount())
            detail = '%s\n%s · 服务 %d 个' % (name, address, services)
            return '已连接', detail, True

        if conn == CONN_CONNECTING:
            return '正在连接…', '正在与设备建立 GATT 连接，请稍候', False

        if conn == CONN_FAILED:
            return '连接失败', '请确认设备在附近、已开机，且未被其他手机占用', False

        if scan == SCAN_RUNNING:
            return '正在扫描…', '已发现 %d 个 BLE 设备' % count, False

        if scan == SCAN_FAILED:
            return '扫描失败', _SCAN_ERROR_TEXT.get(scan_error,
                                                    '错误码 %d' % scan_error), False

        if self._note:
            return '未连接', self._note, False

        if conn == CONN_DISCONNECTED:
            return '连接已断开', '点击「蓝牙连接」可重新搜索设备', False

        return '未连接', '点击下方「蓝牙连接」搜索附近的 BLE 设备', False
