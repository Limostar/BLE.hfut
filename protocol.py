# -*- coding: utf-8 -*-
"""双端共用的帧协议（App 侧唯一实现；ESP32 端 C++ 按同一规则实现）。

帧格式：[0xAA][0x55][命令字][数据长度][数据...][异或校验]
校验 = 命令字 ^ 长度 ^ 数据每个字节（不含两个帧头字节）

把协议集中在这里，是为了避免"App 发一种、模拟器/设备收另一种"的漂移：
App、桌面模拟器、以及验证脚本都从这里取同一套实现。
"""

from kivy.logger import Logger

FRAME_HEADER = (0xAA, 0x55)

# 命令字：两端约定，App 下发用 CMD_*，设备回传用 REPLY_*
CMD_FUNC_1 = 0x01      # App → 设备：功能一
REPLY_FUNC_1 = 0x81    # 设备 → App：功能一的回传

# 单次写入的载荷上限：蓝牙默认 MTU=23，减去 3 字节 ATT 协议头，即 20 字节。
# 超过这个长度需要先协商 MTU 再分片，当前版本会明确提示而不是静默失败。
MAX_PAYLOAD = 20


def build_frame(cmd, data=b''):
    """按帧格式拼一条命令 / 回传。"""
    payload = bytes(bytearray(data))
    body = bytes(bytearray([cmd, len(payload)])) + payload
    checksum = 0
    for value in bytearray(body):
        checksum ^= value
    return bytes(bytearray(FRAME_HEADER)) + body + bytes(bytearray([checksum]))


def to_hex(data):
    return ''.join('%02X' % value for value in bytearray(data))


def decode_text(payload):
    """把帧载荷按 UTF-8 解成文本；解不出来就回退成十六进制展示。"""
    try:
        return bytes(bytearray(payload)).decode('utf-8')
    except Exception:
        return to_hex(payload)


class RxFrameParser(object):
    """接收方向的流式组帧器：字节流 → 完整帧列表。

    规则与 ESP32 端的状态机完全一致，所以两端天然对得上；
    在 Python 侧解析也避免在 Java 里再写一遍协议。
    """

    MAX_BUFFER = 512

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, data):
        """喂入新到的字节，返回本次拼出的 [(命令字, 载荷bytes), ...]。"""
        self._buffer.extend(bytearray(data))
        frames = []
        while True:
            start = self._buffer.find(b'\xAA\x55')
            if start < 0:
                # 没有帧头：只留最后一个字节（它可能是 AA 的一半）
                if len(self._buffer) > 1:
                    del self._buffer[:-1]
                break
            if start > 0:
                del self._buffer[:start]
            if len(self._buffer) < 4:
                break
            length = self._buffer[3]
            total = 5 + length
            if len(self._buffer) < total:
                break
            frame = bytes(self._buffer[:total])
            del self._buffer[:total]

            checksum = 0
            for value in bytearray(frame[2:4 + length]):
                checksum ^= value
            if checksum == frame[-1]:
                frames.append((frame[2], frame[4:4 + length]))
            else:
                Logger.warning('BleAssistant: 收到校验错误的帧，已丢弃')

            if len(self._buffer) > self.MAX_BUFFER:
                Logger.warning('BleAssistant: 接收缓冲过大，已清空')
                self._buffer = bytearray()
                break
        return frames
