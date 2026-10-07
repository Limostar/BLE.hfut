# -*- coding: utf-8 -*-
"""本地账号模块。

只做最基础的用户名 + 密码注册/登录，密码以加盐摘要保存，
不包含密码找回、邮箱验证等（按需求暂不实现）。
"""

import hashlib
import os
import sqlite3
from datetime import datetime

MIN_USERNAME_LEN = 3
MAX_USERNAME_LEN = 20
MIN_PASSWORD_LEN = 6
PBKDF2_ROUNDS = 100000


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _digest(password, salt):
    """返回加盐摘要。优先用 PBKDF2，环境不支持时退化为 SHA256。"""
    raw = (salt + password).encode('utf-8')
    try:
        dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                                 salt.encode('utf-8'), PBKDF2_ROUNDS)
    except Exception:
        dk = hashlib.sha256(raw).digest()
    return dk.hex()


class AccountStore(object):
    """基于 SQLite 的账号存储。"""

    def __init__(self, db_path):
        self.db_path = db_path
        directory = os.path.dirname(db_path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        self._init_table()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_table(self):
        with self._connect() as conn:
            conn.execute(
                'CREATE TABLE IF NOT EXISTS users ('
                ' username TEXT PRIMARY KEY,'
                ' salt TEXT NOT NULL,'
                ' pw_hash TEXT NOT NULL,'
                ' created_at TEXT NOT NULL)')

    @staticmethod
    def _check_username(username):
        if not username:
            return False, '请输入用户名'
        if len(username) < MIN_USERNAME_LEN:
            return False, '用户名至少 %d 个字符' % MIN_USERNAME_LEN
        if len(username) > MAX_USERNAME_LEN:
            return False, '用户名最多 %d 个字符' % MAX_USERNAME_LEN
        if ' ' in username:
            return False, '用户名不能包含空格'
        return True, ''

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def exists(self, username):
        with self._connect() as conn:
            row = conn.execute('SELECT 1 FROM users WHERE username = ?',
                               ((username or '').strip(),)).fetchone()
        return row is not None

    def count(self):
        with self._connect() as conn:
            return conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]

    def register(self, username, password, confirm):
        """注册。返回 (是否成功, 提示语)。"""
        username = (username or '').strip()
        password = password or ''
        confirm = confirm or ''

        ok, msg = self._check_username(username)
        if not ok:
            return False, msg
        if len(password) < MIN_PASSWORD_LEN:
            return False, '密码至少 %d 位' % MIN_PASSWORD_LEN
        if password != confirm:
            return False, '两次输入的密码不一致'
        if self.exists(username):
            return False, '该用户名已被注册'

        salt = os.urandom(16).hex()
        with self._connect() as conn:
            conn.execute(
                'INSERT INTO users (username, salt, pw_hash, created_at)'
                ' VALUES (?, ?, ?, ?)',
                (username, salt, _digest(password, salt), _now()))
        return True, '注册成功，请返回登录'

    def verify(self, username, password):
        """登录校验。返回 (是否成功, 提示语)。"""
        username = (username or '').strip()
        password = password or ''
        if not username or not password:
            return False, '请输入用户名和密码'

        with self._connect() as conn:
            row = conn.execute(
                'SELECT salt, pw_hash FROM users WHERE username = ?',
                (username,)).fetchone()
        if row is None:
            return False, '用户名不存在，请先注册'
        if _digest(password, row[0]) != row[1]:
            return False, '密码错误，请重新输入'
        return True, '登录成功'
