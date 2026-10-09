# -*- coding: utf-8 -*-
"""Android 端 BLE 实现。

通过 PyJNIus 调用本工程自带的 Java 桥接类 BleHelper
（javasrc/com/med/bleassistant/ble/BleHelper.java），
Python 侧只做"发起动作 + 轮询状态"，不直接接触 Java 回调接口。
"""

import time

from kivy.clock import Clock
from kivy.logger import Logger

HELPER_CLASS = 'com.med.bleassistant.ble.BleHelper'

# 与 BleHelper.java 中的常量保持一致
SCAN_IDLE, SCAN_RUNNING, SCAN_FAILED = 0, 1, 2
CONN_IDLE, CONN_CONNECTING, CONN_CONNECTED, CONN_DISCONNECTED, CONN_FAILED = 0, 1, 2, 3, 4
WRITE_IDLE, WRITE_SENDING, WRITE_SUCCESS, WRITE_FAILED = 0, 1, 2, 3
NOTIFY_OFF, NOTIFY_SUBSCRIBING, NOTIFY_SUBSCRIBED, NOTIFY_FAILED = 0, 1, 2, 3

_SCAN_STATE_TEXT = {SCAN_IDLE: '空闲', SCAN_RUNNING: '扫描中', SCAN_FAILED: '失败'}

_SCAN_ERROR_TEXT = {
    -1: '无法获取蓝牙适配器，请确认手机支持蓝牙',
    -2: '蓝牙未开启，请先在系统设置中打开蓝牙',
    -3: '无法获取 BLE 扫描器，请确认手机支持低功耗蓝牙',
    -4: '扫描被系统拒绝：请确认已允许「附近的设备」权限',
}


class AndroidBleManager(object):
    """Android 真机上的 BLE 管理器。"""

    def __init__(self):
        self._helper = None
        self._activity = None
        self._init_error = ''
        self._note = ''
        self._pending_grant = None
        self._last_start = 0.0
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
        # 用户此前已授权时权限回调不一定触发，这里补一次
        Clock.schedule_once(lambda dt: self._do_start_scan(), 0.8)

    def _do_start_scan(self):
        """发起扫描。

        注意：不要用一个 Python 侧的标志位去判断"是否已在扫描" ——
        Java 侧 startScan 内部会把异常吞掉，Python 以为成功、其实没启动，
        之后权限回调再进来就会被那个标志位挡住，扫描永远起不来。
        这里改为直接读 Java 侧的真实状态，重复调用是安全的
        （Java 的 startScan 会先停掉上一次）。
        """
        if not self.available:
            return
        now = time.monotonic()
        try:
            if not self._helper.isBluetoothEnabled(self._activity):
                self._helper.requestEnable(self._activity)
                self._note = '蓝牙未开启，请在系统弹窗中开启蓝牙'
                return
            if int(self._helper.getScanState()) == SCAN_RUNNING:
                return
            if now - self._last_start < 0.5:
                return
            self._last_start = now
            self._helper.clearDevices()
            self._helper.startScan(self._activity)
        except Exception:
            Logger.exception('BleAssistant: 启动扫描失败')
            self._note = '启动扫描失败，请查看日志'

    def stop_scan(self):
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
        try:
            self._helper.disconnect()
        except Exception:
            Logger.exception('BleAssistant: 断开连接失败')

    # ------------------------------------------------------------------
    # 诊断（显示在设备弹窗里，出问题时能一眼看出卡在哪一环）
    # ------------------------------------------------------------------
    def diagnostics(self):
        if not self.available:
            return '蓝牙组件缺失：%s' % (self._init_error or '未知原因')
        try:
            return '系统API %d | 蓝牙 %s | 扫描 %s | 错误码 %d | 权限 %s | 定位 %s' % (
                self._sdk_int(),
                '开' if self._helper.isBluetoothEnabled(self._activity) else '关',
                _SCAN_STATE_TEXT.get(int(self._helper.getScanState()), '未知'),
                int(self._helper.getScanError()),
                self._permission_text(),
                '开' if self._helper.isLocationEnabled(self._activity) else '关',
            )
        except Exception as exc:
            Logger.exception('BleAssistant: 读取诊断信息失败')
            return '诊断信息读取失败：%s' % exc

    def _permission_text(self):
        try:
            from android.permissions import check_permission
        except Exception:
            return '未知'
        items = [('扫描', 'android.permission.BLUETOOTH_SCAN'),
                 ('连接', 'android.permission.BLUETOOTH_CONNECT')]
        # Android 12 (API 31) 起不再需要定位权限，只有更低版本才显示它，避免误导
        if self._sdk_int() < 31:
            items.append(('定位', 'android.permission.ACCESS_FINE_LOCATION'))
        result = []
        for label, name in items:
            try:
                granted = bool(check_permission(name))
            except Exception:
                granted = False
            result.append('%s%s' % (label, '有' if granted else '无'))
        return ' '.join(result)

    # ------------------------------------------------------------------
    # 命令下发（界面上的功能按钮使用）
    # ------------------------------------------------------------------
    def send_command(self, service_uuid, char_uuid, hex_data, auto_pick=True):
        """下发一条命令。返回 (是否受理, 提示)。

        参数用十六进制字符串（如 'AA55010001'）而不是 bytes：
        pyjnius 对 Java byte[] 的封送处理容易踩坑，字符串最稳妥。
        受理只代表已入队，真正的写入结果要轮询 write_state()。

        auto_pick=True 时，若按 UUID 找不到特征，会退化为"第一个可写特征"，
        实际写的目标可用 write_target() 查到。
        """
        if not self.available:
            return False, self._init_error or '蓝牙组件不可用'
        try:
            message = self._helper.writeCommand(service_uuid or '', char_uuid or '',
                                                hex_data, bool(auto_pick))
        except Exception as exc:
            Logger.exception('BleAssistant: 下发命令失败')
            return False, '下发命令异常：%s' % exc
        message = str(message or '')
        if message:
            return False, message
        return True, '命令已入队'

    def write_target(self):
        """最近一次命令实际写入的特征 UUID（用于确认到底写到哪去了）。"""
        if not self.available:
            return ''
        try:
            return str(self._helper.getLastWriteTarget() or '')
        except Exception:
            return ''

    def write_state(self):
        """返回 (状态码, 说明)：0 空闲 / 1 发送中 / 2 成功 / 3 失败。"""
        if not self.available:
            return WRITE_IDLE, self._init_error or ''
        try:
            return int(self._helper.getWriteState()), str(self._helper.getWriteMessage() or '')
        except Exception:
            Logger.exception('BleAssistant: 读取写入状态失败')
            return WRITE_IDLE, ''

    def reset_writes(self):
        """清空待发队列（客户端超时时调用，避免队列卡死）。"""
        if not self.available:
            return
        try:
            self._helper.resetWrites()
        except Exception:
            Logger.exception('BleAssistant: 重置写入队列失败')

    def services_info(self):
        """列出已发现的服务与特征，用于在手机上确认 UUID。

        返回 [{'service', 'characteristic', 'properties'}, ...]，
        只列服务时 characteristic 为空字符串。
        """
        if not self.available:
            return []
        try:
            raw = self._helper.getServicesInfo()
        except Exception:
            Logger.exception('BleAssistant: 读取服务列表失败')
            return []
        result = []
        for line in raw or []:
            parts = str(line).split('|')
            while len(parts) < 3:
                parts.append('')
            result.append({'service': parts[0],
                           'characteristic': parts[1],
                           'properties': parts[2]})
        return result

    # ------------------------------------------------------------------
    # 回传（ESP32 → 手机）：订阅通知 + 取回数据
    # ------------------------------------------------------------------
    def enable_notify(self, service_uuid, char_uuid, auto_pick=True):
        """订阅通知特征（幂等，可重复调用）。返回 (是否受理, 提示)。"""
        if not self.available:
            return False, self._init_error or '蓝牙组件不可用'
        try:
            message = self._helper.enableNotify(service_uuid or '', char_uuid or '',
                                                bool(auto_pick))
        except Exception as exc:
            Logger.exception('BleAssistant: 订阅通知失败')
            return False, '订阅通知异常：%s' % exc
        message = str(message or '')
        if message:
            return False, message
        return True, ''

    def notify_state(self):
        """返回 (状态码, 说明)：0 未订阅 / 1 订阅中 / 2 已订阅 / 3 失败。"""
        if not self.available:
            return NOTIFY_OFF, ''
        try:
            return (int(self._helper.getNotifyState()),
                    str(self._helper.getNotifyMessage() or ''))
        except Exception:
            return NOTIFY_OFF, ''

    def pop_received(self):
        """取出并清空已收到的回传数据，每项是一个十六进制字符串（一段字节流）。

        用"取出即清空"而不是索引轮询，避免界面轮询频率变化导致漏读。
        """
        if not self.available:
            return []
        try:
            raw = self._helper.popReceived()
        except Exception:
            Logger.exception('BleAssistant: 读取回传数据失败')
            return []
        return [str(item) for item in (raw or [])]

    # ------------------------------------------------------------------
    # 服务发现（异步，刚连上时经常一次不成功，需要重试）
    # ------------------------------------------------------------------
    def ensure_services(self, force=False):
        """确保 GATT 服务表可用；幂等，界面轮询里反复调用是安全的。

        返回空字符串表示"不用做什么"或"已重新发起"，否则是原因说明。
        """
        if not self.available:
            return self._init_error or '蓝牙组件不可用'
        try:
            return str(self._helper.ensureServices(bool(force)) or '')
        except Exception:
            Logger.exception('BleAssistant: 服务发现失败')
            return '服务发现调用异常'

    def discovery_state(self):
        """返回 (已发现服务数, 状态说明)。"""
        if not self.available:
            return 0, self._init_error or ''
        try:
            return (int(self._helper.getServiceCount()),
                    str(self._helper.getDiscoveryMessage() or ''))
        except Exception:
            return 0, ''

    # ------------------------------------------------------------------
    # 状态（供界面轮询）
    # ------------------------------------------------------------------
    def _notify_text(self):
        """回传订阅状态的短文本，直接显示在连接状态卡上。"""
        try:
            state = int(self._helper.getNotifyState())
        except Exception:
            return '回传状态未知'
        return {NOTIFY_OFF: '回传未订阅',
                NOTIFY_SUBSCRIBING: '回传订阅中',
                NOTIFY_SUBSCRIBED: '回传已订阅',
                NOTIFY_FAILED: '回传订阅失败'}.get(state, '回传状态未知')

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

        if conn == CONN_CONNECTED:
            name = self._helper.getConnectedName() or '未命名设备'
            address = self._helper.getConnectedAddress() or '-'
            services = int(self._helper.getServiceCount())
            detail = '%s\n%s · 服务 %d 个 · %s' % (name, address, services, self._notify_text())
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
