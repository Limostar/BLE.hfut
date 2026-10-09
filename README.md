# 绿联蓝牙助手（Android BLE App）

一个用 **Python（Kivy）+ 少量 Java 桥接** 写的安卓低功耗蓝牙（BLE）App 源码工程。
按本文档操作，可以在**不需要在自己电脑上安装安卓开发环境**的前提下，
通过 GitHub 的云端服务器自动编译出可以装到手机上的 `.apk` 文件。

---

## 一、功能清单

| 功能 | 说明 |
| --- | --- |
| 用户登录 | 首次进入是登录页；用户名 + 密码校验，密码加盐摘要后保存在手机本地 SQLite |
| 用户注册 | 登录页点「还没有账号？点此注册」进入注册页，包含**两次密码核验**、用户名/密码长度校验、重复用户名拦截 |
| 注册后回登录页 | 注册成功自动返回登录页并带出用户名，提示「注册成功，请返回登录」 |
| BLE 连接 | 蓝牙功能页点「蓝牙连接」→ 弹出附近 BLE 设备列表（实时刷新，按信号强度排序）→ 点选设备即发起真实 GATT 连接 |
| 连接后解锁按钮 | 未连接时界面上 8 个功能按钮为**灰色锁定**状态；连接成功后自动变为**绿色可点** |
| 8 个预留功能 | 点击后弹出「功能预留」提示，后续在这些按钮里接入具体医疗设备指令即可 |

**暂未实现（按需求约定）**：密码找回、邮箱验证、多设备并发管理。

---

## 二、目录结构

```
ble-assistant/
├── main.py                  # 程序入口：三个页面、主题配色、界面逻辑
├── ui.kv                    # 界面布局与样式（Kivy 语言，医疗绿主题）
├── accounts.py              # 账号模块：注册 / 登录 / 密码摘要（本地 SQLite）
├── ble_android.py           # Android 真机的 BLE 实现（调用 Java 桥接类）
├── ble_sim.py               # 电脑上的 BLE 模拟实现（只用于在电脑预览界面）
├── buildozer.spec           # 打包配置（应用名、包名、权限、架构等）
├── javasrc/
│   └── com/med/bleassistant/ble/BleHelper.java   # BLE 原生桥接类（必须保留）
├── assets/fonts/NotoSansSC-Regular.ttf           # 中文字体（不装会显示成方框）
├── .github/workflows/build-apk.yml               # 云端自动构建脚本
└── .gitignore
```

---

## 三、你需要准备什么

1. 一个 **GitHub 账号**（免费注册：<https://github.com/signup>）
2. 一台**安卓手机**（Android 7.0 及以上，建议 Android 8 以上）
3. 一个用来上传项目的工具，推荐 **GitHub Desktop**（图形界面，不用敲命令）：
   <https://desktop.github.com/>

> 说明：云端编译用的是 GitHub Actions 的免费额度。
> **公开（Public）仓库不限时长**；私人（Private）仓库每月有 2000 分钟免费额度，
> 本项目一次完整构建大约 20～40 分钟，通常够用。
> 为了让第一次就顺利，**建议先建成公开仓库**。

---

## 四、第 1 步：把项目上传到 GitHub

### 1.1 安装 GitHub Desktop

1. 打开 <https://desktop.github.com/>，点 **Download for Windows**，下载后双击安装；
2. 安装完成后打开 GitHub Desktop，点 **Sign in to GitHub.com**，用你的账号登录（浏览器会弹出授权页面，点同意即可）；
3. 登录后如果提示配置用户名和邮箱，随便填一个显示名和邮箱即可。

### 1.2 把本工程添加为本地仓库

1. GitHub Desktop 菜单栏 → **File → Add local repository…**
2. 在弹窗里点 **Choose…**，选中本工程文件夹（就是包含 `main.py` 的那个 `ble-assistant` 文件夹），然后点 **Add repository**；
3. 如果弹出 “This directory does not appear to be a Git repository. Would you like to create a repository here instead?”，点 **create a repository**，然后直接点 **Create repository** 即可。

### 1.3 发布到 GitHub（上传）

1. 界面右上角点 **Publish repository**；
2. **Name** 填 `ble-assistant`；
3. **取消勾选** “Keep this code private”（这样就建成公开仓库，免费用时不限量）；
4. 点 **Publish repository**，等进度条走完。

上传完成后，在浏览器打开 `https://github.com/你的用户名/ble-assistant` 应该能看到这些文件。

> **看不到 `.github` 文件夹？** 这是正常的，它以点开头属于隐藏文件，GitHub Desktop 已经把它一并上传了。
> 在网页上点进 `.github/workflows/` 目录，能看到 `build-apk.yml` 就说明上传成功。

---

## 五、第 2 步：等待云端自动编译

1. 打开网页版仓库 → 顶部点 **Actions** 标签；
2. 会看到一条名为「构建 APK」的运行记录（可能显示为正在转圈）；
3. 点进去，能看到 10 个步骤依次执行。**第一次构建需要下载 Android SDK / NDK（约 2～4 GB），耗时最长，约 20～40 分钟属正常**；
4. 全部步骤变成绿色对勾，标题旁出现绿色 ✅，就表示编译成功；
5. 如果某一步出现红色 ❌，点开那一步，把红色报错文字复制下来发我，我来改配置（常见原因见第十节）。

---

## 六、第 3 步：下载 APK

1. 在刚才那次成功的构建页面，**拉到最底部**，找到 **Artifacts** 区域；
2. 点 **lvlian-ble-assistant-apk** 下载（**需要登录 GitHub 才能下载**）；
3. 下载得到的是一个 **zip 压缩包**，解压后里面才是真正的 `.apk` 文件；
4. 注意：GitHub 的 Artifacts 默认只保留 **30 天**，过期后重新跑一次构建即可。

---

## 七、第 4 步：装到手机上

1. 把解压出来的 `.apk` 传到手机：微信/QQ 发给自己、数据线拷贝、网盘都可以；
2. 手机上点开这个 apk 文件安装；
3. 如果提示「禁止安装未知来源应用」，按提示进入设置，允许该来源安装应用后再试；
4. 如果提示「应用未安装」，多半是手机是 32 位老机型，见第十节 FAQ。

> 这个 APK 是 **debug 版**（开发调试签名），自己安装使用完全没问题；
> 如果要上架应用商店，需要另外做正式签名，那是后话。

---

## 八、第 5 步：在手机上使用

1. **打开手机蓝牙**（控制中心或设置里打开）；
2. 打开 App，进入**登录页**；
3. 先点「还没有账号？点此注册」→ 填用户名（3-20 个字符）、密码（至少 6 位）、**再输一次密码** → 点「注 册」；
4. 注册成功会自动回到登录页，用户名已填好，输入密码点「登 录」；
5. 进入蓝牙功能页，此时 8 个按钮都是**灰色锁定**的；
6. 点「蓝牙连接」，这时会弹出系统权限申请：
   - Android 12 及以上：要允许 **「附近的设备」** 权限；
   - Android 11 及以下：要允许 **「位置信息」** 权限（系统限制，无法绕过）；
   - **一定要点允许**，否则会提示扫描失败；
7. 允许后稍等几秒，弹窗里会列出附近搜到的 BLE 设备（显示名称、MAC 地址、信号强度）；
   弹窗里还有一行灰色的**诊断信息**，会显示「系统API / 蓝牙 / 扫描状态 / 错误码 / 三项权限 / 定位开关」，
   搜不到设备时先看这一行，基本能直接判断卡在哪一环；
8. 点你要连接的那个设备 → 连接成功后弹窗自动关闭，页面顶部状态变为绿色的 **「已连接」**，并显示设备名与已发现的服务数量；
9. 此时 **8 个功能按钮全部解锁变绿**，点击任意一个会弹出「功能预留」提示；
10. 需要更换设备时，先点「断开连接」，再点「蓝牙连接」重新搜索。

---

## 九、想改代码怎么办

改完代码后重新构建，只需两步：

1. 打开 GitHub Desktop，它会自动列出你改动的文件；
2. 左下角 **Summary** 随便写一句说明（例如「调整按钮文案」）→ 点 **Commit to main** → 再点右上角的 **Push origin**；

推送成功后，GitHub Actions 会**自动重新开始编译**，流程和第五节完全一样。

### 常见改动位置

| 想改什么 | 改哪里 |
| --- | --- |
| 应用名字（手机桌面显示） | `buildozer.spec` 里的 `title` |
| 包名 | `buildozer.spec` 里的 `package.domain` + `package.name`（改完记得同步改 `javasrc` 下的目录名和 `BleHelper.java` 第一行的 `package`） |
| 8 个按钮的文案 | `ui.kv` 里搜索 `功能一`…`功能八` |
| 8 个按钮的实际功能 | `main.py` 里 `MainScreen.reserved()` |
| **功能按钮要下发的 ESP32 命令** | `main.py` 顶部 `CMD_FUNC_1` 等常量 + `build_frame()` |
| **要写哪个 BLE 特征** | `main.py` 顶部 `ESP32_WRITE_UUID` / `ESP32_SERVICE_UUID` |
| 主题配色 | `main.py` 顶部的 `COLOR_PRIMARY` 等常量（现在主色是 `#00C853` 活力绿） |
| 登录/注册规则（长度等） | `accounts.py` 顶部的 `MIN_USERNAME_LEN`、`MIN_PASSWORD_LEN` |

### 给功能按钮接上 ESP32 命令（「功能一」已接好，其余照抄即可）

**第 1 步：先确认该写哪个特征 UUID**

连上 ESP32 后，点界面上的「**服务/特征**」按钮，手机上会列出该设备暴露的全部服务与特征及其属性。
找到属性里带 `WRITE` 的那一条，把它的 UUID 填到 `main.py` 顶部的配置区：

```python
ESP32_WRITE_UUID = '你的写入特征 UUID'
ESP32_SERVICE_UUID = ''      # 留空＝在所有服务里按上面的 UUID 查找，最省事
```

> 还有个调试开关 `ESP32_AUTO_PICK_WRITE`（默认 `True`）：按上面的 UUID 找不到特征时，
> 自动改用设备上**第一个可写特征**，这样第一次构建就能先把链路跑通，
> 弹窗里会显示它实际写到了哪个特征。正式使用时建议改成 `False`，只允许写约定的那一个。

**第 2 步：确认命令帧格式**

默认格式是 `[0xAA][0x55][命令字][数据长度][数据...][异或校验]`，
由 `main.py` 里的 `build_frame()` 生成。要换成你们固件自己的格式，**只改这一个函数**即可。
各按钮对应的命令字在 `CMD_FUNC_1` 这类常量里定义。

**第 3 步：按下按钮之后发生了什么**

```
功能一按钮 → MainScreen._send_function_one()
          → ble.send_command(uuid, uuid, 'AA55010001')
          → Java(BleHelper) 入队 → 串行写入特征值 → onCharacteristicWrite 回调更新状态
          → 弹窗每 0.3 秒轮询一次，显示 "发送中 / 发送成功 / 发送失败 / 超时" + 实际发出的 HEX
```

**第 4 步：一个已知限制**

单次写入上限是 **20 字节**（蓝牙默认 MTU=23，减去 3 字节 ATT 协议头）。
超过时 App 会明确弹「命令过长」，不会静默失败。要发更长的包需要先协商 MTU 再分片，
这块目前没做——需要的话告诉我，我再加。

**第 5 步：回传（设备 → 手机）**

App 在**连接成功后会自动订阅**通知特征，不需要手动操作。回传帧和下发用同一套格式：

```
AA 55 | 0x81 | 长度 | "Hello World" | 异或校验
= AA 55 81 0B 48 65 6C 6C 6F 20 57 6F 72 6C 64 AA
```

收到后 App 会做两件事：

1. 弹出一个提示框，显示载荷解码出来的文本（也就是 `Hello World`）；
2. 在连接状态卡下面留一行 `设备回传（0x81）：Hello World`，方便事后核对。

载荷是按 UTF-8 解码显示文本的，所以设备端回传任意字符串都能直接看到，不用改 App。

要换回传用的特征 UUID，改 `main.py` 顶部的 `ESP32_NOTIFY_UUID` —— 填错或留空也会自动
退化为"设备上第一个支持 NOTIFY 的特征"。

> 注意：**上行链路要求设备侧提供一个支持 NOTIFY 的特征**。本项目附带的 ESP32 代码
> 已经建好了（`6E400003-...`）。如果你用的是 Arduino 自带的 `BLE_server` 示例，
> 它那个特征只有 READ|WRITE，没有 NOTIFY，手机收不到回传——要么换成本项目附带的代码，
> 要么给那个特征加上 `BLECharacteristic::PROPERTY_NOTIFY` 并配一个 `BLE2902` 描述符。

### ESP32 端怎么配合（示例代码已附）

`esp32/esp32_ble_receive/esp32_ble_receive.ino` 是一份可直接烧录的 Arduino 示例：

- UUID 用的就是 App 的默认值（Nordic UART 那套），**不用改任何东西就能互通**；
- 收到「功能一」会让 GPIO2（多数开发板的板载 LED）翻转，串口会打印收到的每一帧；
- 帧解析是**流式状态机**：一帧被拆成多个 BLE 包也能拼回来，校验不过的帧直接丢弃并计数；
- 换成 ESP-IDF / NimBLE 时，把 `feed_byte()` 这套状态机原样搬过去即可，它不依赖具体蓝牙框架。

上手步骤：

1. Arduino IDE 装好 esp32 开发板包，打开 `esp32_ble_receive.ino`；
2. 选对开发板型号和串口，点「上传」；
3. 打开串口监视器（波特率 **115200**），应看到「已开始广播，设备名 "ESP32-BLE-CMD"」；
4. 手机 App 里连接它 → 点「功能一」，预期看到：
   - 电脑串口打印 `Received`，接着 `[CMD] 功能一已执行：翻转 GPIO2 -> 1`、`[BLE] 已回传 16 字节: "Hello World"`
   - 开发板板载 LED 翻转
   - 手机弹出提示框「收到 ESP32 回传：Hello World」，App 弹窗显示「发送成功」

> 安全提醒：这份示例**没有做鉴权**，任何手机都能连上并下发命令。
> 用于真实的医疗设备前，建议至少加上配对/加密，或在帧里加一个身份/令牌字节。

---

## 十、常见问题

**Q1：Actions 里构建失败（红叉）怎么办？**
点开失败的那一步，复制红色报错内容发我。常见的三类原因：
- 网络波动导致下载 SDK/NDK 失败 → 重新点一次 **Re-run all jobs** 通常就好；
- `buildozer.spec` 有语法错误 → 我帮你改；
- 我使用的某个组件版本更新了 → 我调整版本号即可。

**Q2：手机上装不上，提示「应用未安装」/「不兼容」**
你的手机是 32 位架构。打开 `buildozer.spec`，把
`android.archs = arm64-v8a`
改成
`android.archs = arm64-v8a,armeabi-v7a`
再推送一次重新构建（构建时间会变长）。

**Q3：点「蓝牙连接」一直搜不到设备**
- 确认手机蓝牙已打开；
- 确认权限已允许（设置 → 应用 → 绿联蓝牙助手 → 权限 →「附近的设备」/「位置信息」）；
- 部分手机需要**同时开启定位开关**才能扫描 BLE（这是安卓系统限制）；
- 确认被搜的设备确实在广播（有些设备只有被唤醒后才广播）。

**Q4：连接失败**
- 该设备可能已被另一台手机占用，很多 BLE 设备只允许一个中心设备连接；
- 设备的 GATT 连接可能超时，先「断开连接」再重试；
- 靠近设备再试一次。

**Q5：中文显示成方框**
说明字体没打进包里。确认 `ble-assistant/assets/fonts/NotoSansSC-Regular.ttf` 这个文件存在，
并且 `buildozer.spec` 里有 `source.include_exts = py,kv,ttf,...`。

**Q6：APK 有点大（约 50MB）？**
主要是中文字体占了 ~18MB。想变小可以换成体积更小的中文字体（保持文件名不变即可），
或者用 `fonttools` 做子集化，只保留用到的汉字。

**Q7：构建报 `implicit declaration of function 'preadv'` / `'pwritev'`？**
`buildozer.spec` 里的 `android.minapi` 被设得太低了。编译 CPython 时用到的
`preadv` / `pwritev` 需要 **API >= 24** 才会在头文件里声明，低于 24 就会因为
`-Werror=implicit-function-declaration` 直接中断。确认这一行是
`android.minapi = 24`（或更高）即可。

**Q8：构建报 `xxx-android_24_arm64_v8a.whl is not a supported wheel on this platform`？**
这是当前 python-for-android（master 分支）的一个上游 bug：解析依赖时它用
`--platform=android_24_arm64_v8a` 选中了「Android 专用 wheel」，并把该 wheel 的下载直链
写进依赖清单；但真正执行 `pip install` 时又**漏了 `--platform` 参数**，
于是 pip 拒绝这个「外来平台」的 wheel，构建中断。

> 注意：只在 `buildozer.spec` 的 `requirements` 里写 `xxx==旧版本` **管不住它** ——
> p4a 会先把版本号剥掉，再用一个独立的解析步骤去问「最新版对应哪个 wheel」。

本项目的修法是用 pip 官方的**约束文件**管住那一步解析：

- 工程根目录的 `constraints.txt` 里写着 `charset-normalizer==3.3.2`
  （该包从 3.5.0 起才开始发布 Android wheel，钉到 3.3.2 后只剩通用轮子，不会再被选中）
- 工作流第 8 步通过环境变量 `PIP_CONSTRAINT` 把它交给整个构建过程：

```yaml
      - name: 8. 编译 debug 版 APK
        env:
          PIP_CONSTRAINT: ${{ github.workspace }}/constraints.txt
        run: buildozer -v android debug
```

如果将来**换成别的包名**报同样的错，把那个包补进 `constraints.txt` 并钉到
它发布 Android wheel 之前的最后版本即可。

> 上游的正式修复在 p4a 的 `develop` 分支。走那条路需要把宿主 Python 换成 3.14、
> NDK 换成 29、API 换成 36，改动较大，本项目选择了更小的绕法。

**Q9：点「蓝牙连接」后一直显示「已发现 0 个 BLE 设备」，一个都搜不到？**
先看弹窗里那行灰色的**诊断信息**（它会显示扫描状态／错误码／三项权限／定位开关），
它能直接指出问题在哪一环。

**最常见的原因是手机的「定位 / 位置信息」总开关被关掉了。** Android 官方的规定是：
> 定位服务关闭时，蓝牙扫描结果会被系统直接掐掉（而且不报任何错）；
> 只有声明了 `usesPermissionFlags="neverForLocation"` 的应用才能在关闭定位时照常拿到扫描结果。

本工程已经在 `buildozer.spec` 里给 `BLUETOOTH_SCAN` 声明了这个属性，
所以用**修复后的 APK**，关着定位也能搜到设备；如果装的是修复前的旧版本，
把手机定位开关打开就能搜到。

其它可能原因：
- 被测设备当前没有在广播（有些设备需要按键唤醒后才开始广播）；
- 该设备已被另一台手机连接（不少 BLE 设备只允许一个中心设备连接）；
- 权限被拒绝过：设置 → 应用 → 绿联蓝牙助手 → 权限 → 允许「附近的设备」。

---

## 十一、技术说明（了解即可，不影响使用）

### 1. 为什么工程里有一个 `.java` 文件？

Python 调用安卓原生接口靠的是 PyJNIus，而 PyJNIus 官方有这样一条硬性限制：

> **只能实现 Java 接口，不能继承 Java 抽象类。**

而 BLE 扫描回调 `ScanCallback` 和连接回调 `BluetoothGattCallback` 恰好都是**抽象类**，
所以它们没法直接用 Python 实现。解决方式是：把这两个回调写在
`javasrc/com/med/bleassistant/ble/BleHelper.java` 里，Python 侧只负责「发起动作 + 轮询状态」，
两边不直接互相回调，稳定且没有线程问题。

`buildozer.spec` 里的 `android.add_src = javasrc` 就是告诉打包工具把这个 Java 文件一起编进 APK。

### 2. 权限说明

| 权限 | 用途 |
| --- | --- |
| `BLUETOOTH` / `BLUETOOTH_ADMIN` | Android 11 及以下的蓝牙开关与连接 |
| `BLUETOOTH_SCAN` | Android 12 及以上扫描 BLE 设备（运行时申请） |
| `BLUETOOTH_CONNECT` | Android 12 及以上连接设备、读取设备名（运行时申请） |
| `ACCESS_FINE_LOCATION` | Android 11 及以下扫描 BLE 的强制要求 |

### 3. 账号安全

密码不会明文保存：每个账号有独立随机盐值，用 PBKDF2-SHA256 迭代 10 万次后存摘要。
账号数据放在应用私有目录的 `accounts.db`，卸载 App 即删除，其他应用无法读取。

### 4. 在电脑上预览界面（可选）

没有手机也能看界面，电脑上的蓝牙部分走的是模拟数据：

```powershell
pip install kivy
cd ble-assistant
python main.py
```

---

## 十二、附录：不想装 GitHub Desktop，用命令行也可以

已安装 Git 的前提下（未安装可在 PowerShell 里执行 `winget install --id Git.Git -e`）：

```powershell
cd ble-assistant
git init
git add .
git commit -m "首次提交：绿联蓝牙助手"
git branch -M main
git remote add origin https://github.com/你的用户名/ble-assistant.git
git push -u origin main
```

> 推送时会要求输入账号密码，注意 GitHub **不接受登录密码**，需要先到
> `GitHub → 头像 → Settings → Developer settings → Personal access tokens → Tokens(classic)`
> 生成一个勾选 `repo` 权限的 Token，用它当密码使用。
