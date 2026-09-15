# wake-on-usb-server-on-onecloud-armbian-docker

[English](README.md) | [简体中文](README.zh-CN.md)

在跑 Armbian 的玩客云上跑一个极简 Docker 服务，打开网页点一下按钮，就通过 USB OTG 口模拟键盘，唤醒另一台设备。

```
浏览器 ──HTTP──> 容器(Flask) ──写报文──> /dev/hidg0 ──USB OTG──> 被控设备
```

## 硬件准备

| 项目     | 说明                                                                   |
| -------- | ---------------------------------------------------------------------- |
| 玩客云   | 刷好 Armbian                                                           |
| 连线     | 见下方「线材选择」                                                     |
| 接哪个口 | **靠近 HDMI 的那个 USB 口**是 OTG（device 模式）；靠近网口的是 host 口 |

### 线材选择

选线就一条原则：这条线必须让**被控机那端当主机**（它才是 USB host），让**玩客云这端当设备**（它在模拟键盘）。方向搞反了，键盘不会被枚举。

#### 首选：A 公对 A 公双公线

**刷机时用的那条线可以直接复用**，不用另外买。刷机教程里的插法（一端接电脑，另一端接**靠近 HDMI 的 USB 口**）和本项目需要的拓扑完全一致：电脑/被控机是主机，玩客云是设备。

- 必须是**数据线**，四芯：VBUS / GND / D+ / D-。纯充电线只有两根芯、没有 D+/D-，一定不行。既然用它刷机成功过，就说明 D+/D- 是通的。
- 不要用中间带芯片的"电脑对传线"，那种是主动线，不是直通。
- 插口要和刷机时一致：**靠近 HDMI 的那个**。另一个 USB 口是纯主机口，插上去不会有任何反应。

一个提醒：刷机成功只能证明那个 A 口的 D+/D- 确实连到了 SoC 的 USB 设备控制器上（走的是 Amlogic mask ROM 模式），**并不证明 Linux 下 dwc2 能进 peripheral 模式**。所以「步骤 0」仍然必须做。

#### 被控机是 USB-C 口：要多加一个转接器

**不能直接用 A-to-C 线。** A-to-C 线里焊了一颗 56kΩ 上拉电阻（Rp），它的作用是告诉被控机的 C 口"对面接的是个旧式主机"，于是被控机的 C 口会把自己切成**设备**。可我们需要它当**主机**，结果就是两头都是设备，枚举不起来；如果被控机是纯主机口，则两侧都是 Rp，端口干脆判定"没插东西"。

正确做法是加一个 **C 公转 A 母的 OTG 转接器**（内含 5.1kΩ 下拉电阻 Rd，就是给手机/笔记本插 U 盘鼠标的那种）：

```
玩客云 USB-A ──A 公对 A 公线──> [ C 公转 A 母 OTG 转接器 ] ──> 被控机 USB-C 口
```

选购与排错：

- 挑明确标 **OTG / 支持外设** 的转接器，纯充电转接头里面可能根本没焊电阻。
- 插上没反应就**把 C 头翻个面**再试 —— 便宜转接器可能只在一个 CC 引脚上焊了电阻，而 USB-C 正反插走的是不同引脚。
- 被控机的 C 口得是主机/数据口（台式机、笔记本一般没问题），纯充电口不行。

#### VBUS 反向供电的处理

A 公对 A 公线两端 VBUS 直连，被控机可能通过它反向取电导致异常。两种处理方式：

- 剪断线里的红线（VCC），只保留 D+/D- 和 GND；
- 或者串一个带独立开关的 USB Hub，连接时保持关闭。

判据：**剪掉 VCC 后如果玩客云认不到被控机**（`cat /sys/class/udc/*/state` 一直停在 `not attached`），说明这个口需要靠 VBUS 才能建立连接，那就别剪线，改用带开关的 Hub 方案。

另：玩客云的 OTG 端点总数只有 6 个，本项目的键盘用掉 2 个，够用但不宽裕。

## 步骤 0：先验证 OTG 可行性

这一步不过，后面的 Web 层没有意义，先做完它。

```bash
ls /sys/class/udc/
#   期望有 1 个条目（如 c9040000.usb）。为空说明 dwc2 没进 peripheral 模式。

cat /proc/device-tree/soc/usb@c9040000/dr_mode 2>/dev/null   # 期望 otg 或 peripheral

zcat /proc/config.gz 2>/dev/null \
  | grep -E 'CONFIG_USB_CONFIGFS=|CONFIG_USB_CONFIGFS_F_HID|CONFIG_USB_DWC2|CONFIGFS_FS'

modinfo usb_f_hid 2>/dev/null | head -5

# remote wakeup 补丁是否存在（大概率不存在，属正常）
ls /sys/module/usb_f_hid/parameters/ 2>/dev/null
```

如果 `/sys/class/udc/` 为空，需要让 dwc2 以 peripheral 模式加载：改 `/boot/armbianEnv.txt` 的 `overlays=` / `extraargs=`，或直接参考 One-KVM 玩客云整合包里已经配好的设备树。**不要 `apt upgrade` 内核/设备树**，OTG 会失效。

## 部署

### 1. 宿主机侧 gadget

```bash
sudo install -m 0755 host/setup-hid-gadget.sh host/teardown-hid-gadget.sh host/verify-hid.sh /usr/local/sbin/
sudo install -m 0644 host/i18n.sh /usr/local/sbin/
sudo install -m 0644 host/hid-gadget.service /etc/systemd/system/
sudo systemctl enable --now hid-gadget.service
```

`hid-gadget.service` 里写了 `Before=docker.service`，保证容器启动时 `/dev/hidg0` 已经存在。

### 2. 先验证裸硬件链路

```bash
sudo /usr/local/sbin/verify-hid.sh
```

它直接往 `/dev/hidg0` 写一次 Enter，不经过 Docker。目标机有反应，说明线接对了、gadget 活了。

### 3. 启动容器

```bash
cp .env.example .env
# 改 SECRET_KEY（openssl rand -hex 32）和 APP_PASSWORD
docker compose up -d --build
```

浏览器打开 `http://<玩客云IP>:8080`，用 `.env` 里的用户名密码登录。

## 网页上的三种唤醒方式

| 方式            | 行为                         | 适用场景                     |
| --------------- | ---------------------------- | ---------------------------- |
| 仅按键          | 只发按键报文                 | 睡眠 / 锁屏 / 息屏，最可靠   |
| 仅唤醒信号      | 不产生任何按键，只发唤醒信号 | 想唤醒但不想在目标机留下输入 |
| 唤醒信号 + 按键 | 先信号后按键                 | 默认，成功率最高             |

也可以在 `.env` 里设默认值（`WAKE_MODE` / `WAKE_KEY` / `WAKE_REPEAT`），网页上的选择只影响当次请求。

接口约定：

- `POST /api/wake` 的请求体必须是 JSON **对象**。数组、裸字符串、畸形 JSON、带 `Content-Type: application/json` 的空请求体一律 400，且绝不会真的触发唤醒。
- 输入有误（按键或模式无法识别、重复次数不在 1-5、按键超过 32 字符）返回 **400**；只有设备侧问题（`/dev/hidg0` 不存在、gadget 被主机禁用）才是 **503**，两者在监控里可以区分。
- `lang` 和 `repeat` 可以省略，或传 `null` / `""` 表示「用默认值」。`repeat` 传布尔、小数、对象或数组会返回 400，而不是被静默转换。

按键支持组合键写法，例如 `ctrl+enter`、`ctrl+shift+enter`、`alt+enter`。命令行调用：

```bash
# 需要先登录拿到会话 cookie 和 CSRF token
curl -s -c jar.txt http://<IP>:8080/login -o /dev/null
TOKEN=$(grep csrf jar.txt | awk '{print $7}')
curl -s -b jar.txt -c jar.txt -d "username=admin&password=xxx&_csrf=$TOKEN" http://<IP>:8080/login -o /dev/null
curl -s -b jar.txt -H "X-CSRF-Token: $TOKEN" http://<IP>:8080/api/wake -H 'Content-Type: application/json' -d '{"key":"enter"}'
```

## 语言

网页、API 和宿主机上的 shell 脚本都是双语的（English / 简体中文）。

**网页与 API。** 每次请求按以下顺序确定语言：

1. 显式的 `lang` 参数 —— 查询串（`?lang=zh-CN`）、表单字段、JSON 字段，或 `X-Lang` 请求头。这是手动选择，会**写进 `lang` cookie**，后续请求沿用它；
2. 之前手动选择留下的 `lang` cookie；
3. 系统语言，探测自浏览器的 `Accept-Language`；
4. 容器变量 `APP_LANG`，供完全没有系统语言的调用方（curl、cron）使用；
5. 英文，始终作为最后的保底。

仅由浏览器探测得到的语言不会写进 cookie，因此它会继续跟随浏览器变化。退出登录清空会话不影响语言 cookie。

**Shell 脚本。** `setup-hid-gadget.sh`、`teardown-hid-gadget.sh`、`verify-hid.sh` 都支持 `--lang en|zh-CN`；不传则跟随系统语言环境（`LC_ALL` / `LC_MESSAGES` / `LANG`），最后回退英文：

```bash
sudo /usr/local/sbin/verify-hid.sh --lang zh-CN
```

三处的取值都是 `en` 和 `zh-CN`；其它中文变体（`zh`、`zh-Hans`、`zh_CN`）都会归一化成 `zh-CN`。

```bash
curl -s -b jar.txt -H "X-CSRF-Token: $TOKEN" -H "X-Lang: zh-CN" \
  http://<IP>:8080/api/wake -H 'Content-Type: application/json' -d '{"key":"enter"}'
```

响应里会用 `lang` 回显最终采用的语言，`steps` 和 `warnings` 都已经是翻译后的文本。

## 验证清单

| 层级   | 命令                                        | 期望                                             |
| ------ | ------------------------------------------- | ------------------------------------------------ |
| 内核   | `ls /sys/class/udc/`                        | 有 1 个条目                                      |
| gadget | `cat /sys/class/udc/*/state`                | 被控机开机时为 `configured`                      |
| gadget | `ls -l /dev/hidg0`                          | 字符设备存在                                     |
| 硬件   | `sudo /usr/local/sbin/verify-hid.sh`        | 被控机收到一次回车                               |
| 容器   | `docker compose ps` / `docker compose logs` | running，无 Traceback                            |
| 鉴权   | 错误密码登录                                | 提示错误，不泄露信息                             |
| 功能   | 网页点「唤醒目标设备」                      | 被控机被唤醒                                     |
| 降级   | 拔掉 USB 双公线后点击                       | 页面给出明确原因（失败或“总线挂起”），服务不崩溃 |

## 已知限制

1. **S4/S5（休眠/关机）唤醒不保证成功。** 主线内核的 `f_hid` 既不调用 `usb_gadget_wakeup()`，也没有 `wakeup_on_write` 参数（那是 JetKVM 的下游补丁），所以"仅唤醒信号"这条路径在无补丁内核上会降级成"发一个空报文"，并在页面明确提示。此时能否唤醒取决于目标机 BIOS 是否支持"USB 键盘唤醒"。S3 睡眠 / 锁屏 / 息屏用「仅按键」基本没问题。
2. 想彻底解决第 1 点，两条路：给内核打 `wakeup_on_write` 补丁；或者把 `.env` 里 `ENABLE_UDC_REBIND=1` 并取消 `docker-compose.yml` 中 `/sys/kernel/config` 那行注释 —— 此时 signal 模式改为解绑/重绑 UDC，等效于拔插一次键盘，对"已通电的 USB 口"最有效。
3. **`f_hid` 的 IN 端点只有一个请求缓冲位**，总线挂起时只可能排进一条报文。所以对着睡眠中的目标机，「唤醒信号 + 按键」里的空报文会占住这个位置，按键反而排不进去；追求唤醒率时优先用「仅按键」。程序不会因此报错，而是把实际情况作为警告显示在页面上。
4. **一个 UDC 同时只能绑一个 gadget**。如果之后装了 One-KVM，会和本项目抢 UDC。
5. 玩客云是 armv7（32 位）。若 `python:3.12-slim` 拉不到 arm/v7 变体，把 `Dockerfile` 首行换成 `python:3.11-slim`。
6. 容器内以 root 运行：`/dev/hidg0` 是 root 权限的字符设备，本地家电场景下这样最简单，未使用 `privileged`。
7. **没有 TLS。** 默认是明文 HTTP，密码和会话 cookie 在局域网上明文传输。如果要暴露到自己网络之外，请在前面加一个做 TLS 终结的反向代理，并设 `COOKIE_SECURE=1` 让两个 cookie 都带上 `Secure`。注意：经过代理后所有请求看起来都来自代理地址，按来源的登录限流会因此失效 —— 只有在信任代理设置 `X-Forwarded-For` 时才启用 `ProxyFix`。
8. `/api/wake` 刻意不加频率限制：第一次按键没生效时连点第二次，正是文档给出的恢复手段。请用密码和网络来保护它，而不是靠限流器。

## 项目结构

```
app.py                     Flask 应用：登录、CSRF、页面与 API
hid.py                     HID 报文写入、按键码表、三种唤醒模式
i18n.py                    语言解析与消息查表
locales/                   en.json / zh-CN.json 消息目录
templates/ static/         页面与样式
Dockerfile docker-compose.yml
requirements-dev.txt       跑测试用的 pytest
tests/                     pytest 用例与两个 bash 套件
host/setup-hid-gadget.sh   configfs gadget 创建（幂等）
host/teardown-hid-gadget.sh
host/verify-hid.sh         脱离 Docker 的硬件链路验证
host/i18n.sh               宿主脚本共用的消息目录
host/hid-gadget.service    systemd unit，Before=docker.service
README.md / README.zh-CN.md
LICENSE                    MIT
```

## 排错

| 现象                                                 | 原因 / 处理                                                                                                                |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| 容器起不来，提示找不到 `/dev/hidg0`                  | gadget 没绑上。`systemctl status hid-gadget` 看日志，或手动跑一次 setup 脚本                                               |
| setup 脚本报 `/sys/class/udc/ 为空`                  | dwc2 不在 peripheral 模式，见「步骤 0」                                                                                    |
| `cat /sys/class/udc/*/state` 一直停在 `not attached` | 线插到了纯主机口（要插**靠近 HDMI** 那个）；或线是纯充电线、没有 D+/D-；或剪了 VCC 而这个口需要靠 VBUS 建立连接            |
| 被控机是 USB-C 口，插上 A-to-C 线毫无反应            | 角色判定反了：A-to-C 线会让被控机的 C 口变成设备。改用 **C 公转 A 母 OTG 转接器**，见「线材选择」                          |
| 转接器接上了但仍认不到键盘                           | 转接器可能没有 Rd、或只在一个 CC 引脚上焊了电阻。先把 C 头翻个面再试                                                       |
| 网页返回 503「HID 设备不可用（…）」                  | 被控机没上电、USB 双公线没插好，或刚经历总线复位，稍后重试                                                                 |
| 提示「目标机很可能正在睡眠」                         | 正常现象而非失败：总线挂起后主机会停止轮询端点，报文取不走。按下报文仍在队列里，唤醒后按键会保持按下，**再点一次即可复位** |
| 页面 USB 链路状态显示「未知」                        | 没挂载 `/sys/class/udc`，不影响唤醒功能                                                                                    |
| 端点不足，绑定失败                                   | 在 setup 脚本里加 `echo 1 > functions/hid.usb0/no_out_endpoint` 省掉 OUT 端点                                              |

## 测试

测试都在 `tests/` 下，不需要真实硬件：HID 设备用一个普通文件代替，shell 套件则在拿不到 configfs 的前提下尽可能验证宿主脚本。

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

`pytest` 会跑全部内容，包括两个 bash 套件（`tests/host_scripts.sh` 与 `tests/host_i18n.sh`）—— 它们由一个很小的包装器调用，环境里没有 bash 时会自动跳过。

## License

本项目采用 [MIT License](LICENSE)。
