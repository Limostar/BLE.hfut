[app]

# 应用名称（手机桌面显示的名字）
title = 绿联蓝牙助手

# 包名：com.med.bleassistant
package.name = bleassistant
package.domain = com.med

# 源码目录
source.dir = .
source.include_exts = py,kv,ttf,otf,png,jpg,json
source.exclude_dirs = build, dist, bin, .git, .github, .buildozer, __pycache__

version = 1.0.0

# Android BLE 扫描/连接需要 pyjnius 调用原生 API，android 模块用于申请运行时权限
requirements = python3,kivy,pyjnius,android

orientation = portrait
fullscreen = 0

# ----------------------------------------------------------------------
# Android 配置
# ----------------------------------------------------------------------
# BLUETOOTH / BLUETOOTH_ADMIN 供 Android 11 及以下使用
# BLUETOOTH_SCAN / BLUETOOTH_CONNECT 供 Android 12 及以上使用
# ACCESS_FINE_LOCATION 是 Android 11 及以下扫描 BLE 的必需权限
android.permissions = BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_SCAN,BLUETOOTH_CONNECT,ACCESS_FINE_LOCATION

# BLUETOOTH_SCAN 要求 API >= 31，这里用 33
android.api = 33
android.minapi = 23
android.ndk = 25b

# 只编译 64 位架构，构建更快、APK 更小；
# 如果你的手机很旧（2017 年前的低端机）装不上，改成 arm64-v8a,armeabi-v7a
android.archs = arm64-v8a

# 把本工程自带的 Java 桥接类编进 APK（BLE 扫描与 GATT 连接的回调实现）
android.add_src = javasrc

android.enable_androidx = True
android.accept_sdk_license = True
android.allow_backup = False

[buildozer]
log_level = 2
warn_on_root = 1
