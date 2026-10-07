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
requirements = python3,kivy,pyjnius,android,charset-normalizer==3.3.2

# 必须锁定 p4a 分支，避免 buildozer 默认值变化导致构建行为漂移
p4a.branch = master

orientation = portrait
fullscreen = 0

# ----------------------------------------------------------------------
# Android 配置
# ----------------------------------------------------------------------
# BLUETOOTH_SCAN 必须带 usesPermissionFlags=neverForLocation，否则手机「定位」总开关
# 一旦关闭，系统会直接掐掉 BLE 扫描结果（表现为搜到 0 个设备，且不报任何错）。
# 高级写法里的 name 必须写全限定名（p4a 只对普通写法自动补 android.permission. 前缀）。
# ACCESS_FINE_LOCATION 是 Android 11 及以下扫描 BLE 的必需权限，按官方建议限制在 API 30 及以下。
android.permissions = BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_CONNECT,(name=android.permission.BLUETOOTH_SCAN;usesPermissionFlags=neverForLocation),(name=android.permission.ACCESS_FINE_LOCATION;maxSdkVersion=30)

# BLUETOOTH_SCAN 要求 API >= 31，这里用 33
android.api = 33

# 注意：不要低于 24！工具链编译 CPython 时用到的 preadv / pwritev
# 需要 API >= 24 才会在头文件中声明，设成 23 会直接报
# "implicit declaration of function 'preadv'" 中断构建（buildozer 默认值也是 24）。
android.minapi = 24

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
