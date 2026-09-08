# AI Passport · 语音整理器

[简体中文](README.md) | [English](README.en.md)

> **基于 [FoloToy AI Passport](https://github.com/zhaohuaxiaoy/folo-ai-passport-voice)（MIT）二次开发的个性化分支。**
> 底层框架（ESP32-C3 固件状态机、LVGL UI、BLE/USB 双通道传输、物理审批机制）继承自该项目，本仓库在此之上做了场景化与本地化的改造。

**AI Passport** 是一台 ESP32-C3 随身语音硬件 + 桌面端（Mac/Windows）组成的小系统。它解决的核心问题**不是"语音转文字"，而是"把零碎口语变成可以直接发送的工作信息"**：

按住设备说话 → **本地 whisper.cpp** 转写（音频不出本机）→ **DeepSeek** 按你选的**工作场景**把口语理顺成通顺 / 结构化的成稿 → 自动注入当前输入框（微信 / 文档 / 任意光标处），或回传手机。

一句话：把脑子里的碎片想法，用最省力的方式变成一段"能直接发出去"的话。

```text
按住说话 ──► 设备录音 ──► 桌面端中转 ──► 本地 whisper.cpp 转写（音频不出本机）
                    │  经 BLE / USB
                    ▼  识别中 partial 实时
            屏幕预览候选字
                    │
                    ▼  定稿 → DeepSeek 按场景整理
            通顺/结构化成稿  ──► 注入当前输入框（仅一次） / 回传手机
```

> 仓库同时包含**固件**（ESP-IDF，设备端）与**桌面端**（companion/，Mac/Windows 中转程序），二者通过 BLE / USB 双通道配合工作。

## 四个工作场景

设备 HOME 态进入 READY 后可先选场景，不同场景对应不同的 DeepSeek 整理预设——同一段口语，整理出来的"成稿形态"完全不同：

| 场景 | 设备显示 | 整理目标（DeepSeek preset） | 典型用途 |
| --- | --- | --- | --- |
| **① 同事** | `同事` | 去口语、补主语、简洁工作消息（`work_wechat`） | 工作群 / 同事消息 |
| **② 领导/客户** | `领导客户` | 结论先行、正式书面语、可量化（`report_boss`） | 向上汇报 / 对客户沟通 |
| **③ 对 AI** | `对AI` | 口语想法 → 可直接执行的 AI 任务指令（`agent_prompt`） | 给 coding / 工作 agent 派活 |
| **④ 语音输入** | `语音输入` | 口语 → 通顺书面文字，保留全部信息点（`voice_input`） | 随手记 / 长段口述 / 写作草稿 |

## 与上游 FoloToy AI Passport 的差异

| 维度 | 上游 FoloToy AI Passport | 本 fork（AI Passport 语音整理器） |
| --- | --- | --- |
| **定位** | 通用语音输入 + AI Agent 控制面 | 场景化「语音 → 可发送工作信息」整理器 |
| **ASR** | 火山引擎云端流式 ASR（需密钥、音频出网） | **本地 whisper.cpp**（零云端费用、音频不出本机） |
| **智能层** | Agent 思考 / 执行 / 审批可视化 | **DeepSeek 按场景**把口语理顺成成稿 |
| **录入方式** | 单段按住说话 | **1–3 段分段录入 + 合并**、连续快录（v0.2.4） |
| **整理形态** | 原样转写文本 | 按场景转写成消息 / 汇报 / 指令 / 文字 |
| **回传** | 注入桌面输入框 | 桌面注入 + 企业微信回传（设计中） |
| **共用底座** | 双通道 / 状态机 / 物理审批 / LVGL | 沿用并扩展 |

## 架构总览

| 层 | 组件 | 职责 |
| --- | --- | --- |
| 设备端 | ESP32-C3 固件（ESP-IDF 5.5 + LVGL 9.5） | 状态机、按键/录音、场景选择、UI 渲染、双通道传输、功耗管理 |
| 桌面端 | companion（macOS / Windows） | 双通道接入、本地 whisper.cpp ASR、DeepSeek 整理层、悬浮窗、剪贴板注入、向导、托盘 |
| 本地模型 | whisper.cpp（ASR）+ DeepSeek V4-Flash（整理） | 音频 → 文本（本机）；口语 → 场景化成稿（云端 LLM，仅文本、不出隐私音频） |

数据流：设备采集 16kHz 音频 → 按 100ms 一帧经 **BLE / USB** 任一通道上行 → 桌面端 relay 送入**本地 whisper.cpp** 转写 → 定稿文本送入 **DeepSeek 整理层**按当前场景预设理顺 → 成稿回显设备屏幕并注入当前输入框（或回传手机）。Agent 状态、审批请求与按键裁决走反向通道。

## 项目亮点

- **本地优先、隐私可控**：ASR 默认跑在本机 whisper.cpp，音频从不出网、零云端费用；只有"整理"这一步走 DeepSeek 文本接口（传的是已转写的中文文本，不含原始声音）。
- **场景化整理**：同一段口语，按「同事 / 领导客户 / 对AI / 语音输入」四种目标整理成不同形态——消息、汇报、AI 指令或通顺文字，而不是千篇一律的转写稿。
- **分段录入 + 合并**：一次想法可以分 1–3 段录完，每段定稿在设备上即时预览，全部录完由 DeepSeek 跨段去重、理顺逻辑、合并成一篇完整成稿，OK 确认后注入。
- **连续快录（v0.2.4）**：在「语音输入」场景松手即回到就绪态，可立刻录下一句，无需等上一段整理完成——适合灵感连续迸发时一口气记。
- **双通道冗余链路**：一套音频/事件协议跑两条物理通道——BLE（Mac 直连，GATT 服务 `0xA2B0`）、USB-Serial-JTAG（有线调试 + 完整控制台命令面）。任意通道断线自动收束回 READY、审批保持等待重连，链路故障不会废掉设备。
- **状态机驱动 + 快照渲染**：核心状态机是纯 C 归约器（`state + event → action`），零 ESP-IDF 依赖，host 测试直接跑在 PC 上；UI 渲染由快照差异驱动，逻辑与硬件彻底解耦、可单测、可移植。
- **低资源流式音频管线**：在只有 **400KB SRAM** 的 ESP32-C3 上以 3200B/100ms 帧流式上行——静态环形缓冲零动态分配、源端丢帧不整段缓存、掉帧对账防静默丢失，长句不断流。
- **物理安全审批**（继承自上游底座）：Agent 的权限请求不是推送通知，而是设备屏幕上的审批页——**OK 批准 / UP 拒绝**，真实按键才算数；审批态屏幕永不熄屏。
- **两级功耗管理**：20s 无操作关背光（渲染跳过、面板冻结最后一帧），60s 面板 SLPIN 断电进入 μA 级睡眠，任意键瞬时唤醒、内容免重绘。

## 功能特性

### 设备端（固件）

- **按住说话**：READY 态按住**音量+**立即开始录音（按下即录，滴声提示），松开自动发送；短于 500ms 的误碰当场收束丢弃
- **场景选择**：HOME → READY 后可在「同事 / 领导客户 / 对AI / 语音输入」间用 UP/DOWN 选择、OK 确认；场景标签显示在就绪页顶栏
- **分段录入（①–③ 场景）**：最多 3 段，每段定稿在 SEG_WAIT 页即时预览（显示「第 N 段」），OK 结束录入 → MERGE_REVIEW 页显示 DeepSeek 合并成稿 → OK 注入 / 放弃
- **连续快录（④ 语音输入）**：松手即回就绪态，可立刻录下一句；各段成稿在桌面端按录音顺序累计
- **返回上级**：在场景选择 / 分段等待等页可一键回退到上一级菜单
- **真锁屏**：锁屏态下任何键都不亮屏、不渲染（省电），仅 OK 长按解锁
- **转写中退出**：TRANSCRIBING 态单击音量+ 立即退出转写场景回 READY，迟到的识别文本不上屏
- **Agent 工作流可视化**：THINKING / RUNNING / DONE 状态、任务回显、离线横幅——AI 在做什么，屏幕上看得到
- **物理审批**：Agent 审批请求进入审批页，OK 批准 / UP 拒绝 / DOWN 看 Diff 详情
- **三键交互**：UP/DOWN/OK —— 按住音量+说话、转写中单击音量+退出、单击音量-回车、长按音量-清空输入框（全局语义）
- **完整状态机**：HOME → READY → LISTENING → TRANSCRIBING → SCENE_SELECT → SEG_WAIT → MERGE_REVIEW → AGENT_RUNNING → APPROVAL → DONE
- **提示音**：开始 / 发送 / 审批提醒 / 完成 / 拒绝 / 错误六种
- **双通道传输**：BLE / USB-Serial-JTAG（含完整控制台命令面）
- **低资源音频管线**：3200B/100ms 帧、静态环形缓冲、源端丢帧不整段缓存、掉帧对账
- **两级息屏**：20s 无操作关背光 / 60s 面板 SLPIN 断电 / 任意键唤醒；审批态常亮
- **控制台命令**：`st`（堆/栈水位、连接、掉帧统计）、`log [offset]`（日志环导出）、`rst`（复位原因）、`time`（校时）、`bt scan/dtx`（射频诊断）、`reboot`、`factory`（清 NVS）

### 桌面端（companion/，macOS + Windows）

- **本地 whisper.cpp ASR**（核心改造）：替代上游火山云端 ASR，转写在本机完成，**零云端费用、音频不出本机**；接口与上游 `asr_client.StreamingASR` 对齐，relay 一行切换即可换回云端后端
- **DeepSeek 整理层**：`refine_deepseek.py` 在转写定稿后、注入前按场景预设理顺文本；网络/密钥失败时回退注入原文，保证"最差也能用"
- **候选字悬浮窗**：ASR 中间结果全量累计文本实时显示在屏幕底部居中的无边框置顶小窗，自动换行、随内容向上生长；松手后整理成稿注入输入框一次、窗口消失
- **不抢焦点**：悬浮窗绝不 focus；Windows 走 `WS_EX_NOACTIVATE` + `SWP_NOACTIVATE`，macOS 热路径不触发 WindowServer 同步（按住说话不卡桌面）
- **高频帧合并**：120ms 合并窗口只刷最新帧，首帧立即渲染，杜绝逐帧重绘卡顿
- **5 步向导**：欢迎 → 自动发现设备（BLE → USB）→ 本地模型/整理配置 → 系统授权引导（macOS）→ 完成状态页
- **托盘驻留**：连接后驻留系统菜单栏/托盘，状态行 + 诊断 + 设置
- **诊断页**：USB 通道完整设备命令面；BLE 通道只读运行状态
- **注入**：macOS 剪贴板 + Cmd+V（需辅助功能授权；中文必须走剪贴板通道）；Windows 独立注入器

## 按键操作

| 按键 | 语境 | 动作 |
| --- | --- | --- |
| **UP（音量+）按住** | READY | 开始录音（PTT，滴声提示），松开自动发送转写 |
| **UP（音量+）单击** | TRANSCRIBING | 退出转写场景，立即回 READY（迟到的识别结果不上屏） |
| **UP / DOWN 单击** | SCENE_SELECT | 在四个场景间移动光标 |
| **OK 单击** | SCENE_SELECT | 确认当前场景，进入就绪 |
| **OK 单击** | SEG_WAIT | 结束分段录入，触发合并整理（进入 MERGE_REVIEW） |
| **OK 单击** | MERGE_REVIEW | 确认并注入整理成稿 / 放弃（按提示） |
| **DOWN（音量-）长按** | 任意 | 清空当前输入框全部文字（长按 0.5s，到点一声确认音） |
| DOWN 单击 | HOME / READY | 输入框回车（提交） |
| OK 单击 | HOME | 进入 READY（工作流就绪） |
| OK 长按 | 任意 | 锁屏 / 解锁（锁定 = 省电息屏，按键照常执行但不亮屏） |
| OK 单击 | APPROVAL | 批准 Agent 请求 |
| UP 单击 | APPROVAL | 拒绝 Agent 请求 |
| DOWN 单击 | APPROVAL | 查看 Diff 详情 |

> 长按阈值：三颗键统一 500ms —— DOWN 长按清空、OK 长按锁屏/解锁。UP 不用阈值开录（**按下即录**），阈值在 UP 上只划定"这一按事后还会不会补报单击"的边界。

## 快速开始

### 桌面端（Mac / Windows）

**系统要求**：

| 平台 | 系统版本 | 架构 | 说明 |
| --- | --- | --- | --- |
| macOS | 11.0（Big Sur）及以上 | **Apple Silicon（arm64）** | Intel Mac 暂不提供官方产物（Pillow 无通用二进制，需 x86 环境自构建） |
| Windows | 10 1803+（建议 21H2）/ 11 | x64 | bleak winrt 后端要求；首次运行需允许防火墙 |

**配置本地模型与整理后端**：

语音转写默认走**本地 whisper.cpp**（需在本机准备好 whisper.cpp 模型，如 `large-v3-turbo`），整理默认走 DeepSeek V4-Flash：

1. 准备本地 whisper 模型（见 `companion/install_whisper_local.sh` 与 `asr_local_whisper.py` 注释）
2. 在 `companion/config.local.json` 填入 DeepSeek Key（`deepseek_api_key`，或导出环境变量 `DEEPSEEK_API_KEY`）与 `refine_preset`（默认 `work_wechat`）
3. 首次运行自动生成 `companion/config.local.json`（**不入 git**）

> **可选云端后端**：上游默认的火山引擎云端 ASR 仍可通过把 `from asr_local_whisper import ...` 换回 `from asr_client import StreamingASR` 启用，适合无本地算力的机器。

> **安全**：API Key 只存于 `companion/config.local.json`（已被 .gitignore 忽略）或向导本地配置，**严禁提交进 git**。Key 泄露可在控制台随时吊销重建。

**从源码运行（开发）**：

```bash
pip install -r companion/requirements.txt
cp companion/config.example.json companion/config.local.json   # 填入 DeepSeek Key 与整理预设
companion/.venv/bin/python companion/fre_app.py                 # 向导 GUI（--dry-run 假链路演练）
companion/.venv/bin/python companion/relay.py                   # CLI 中转（BLE 自动扫描 "AI Passport"）
```

macOS 首次使用需授予**辅助功能**权限（注入剪贴板+Cmd+V 必需）与蓝牙权限。Windows 使用说明见 [`companion/WINDOWS.md`](companion/WINDOWS.md)。

### 固件（ESP32-C3）

需要 ESP-IDF 5.5.x（已知环境 5.5.3）+ Python 3.10+（本机 `.venv` 在 `companion/`）。

**首次构建**（会经 Component Manager 拉取 LVGL、`esp_lvgl_port`、`button`、`esp_codec_dev` 等依赖）：

```bash
git clone <repo-url> && cd ai-passport
python3 -m venv companion/.venv && companion/.venv/bin/pip install -r companion/requirements.txt
source "$HOME/esp/esp-idf-v5.5.3/export.sh"   # 或你的安装路径
idf.py set-target esp32c3
idf.py build
```

**刷机与日志**（设备用 USB 线连电脑，`/dev/cu.usbmodem*` 按实际端口替换）：

```bash
idf.py -p /dev/cu.usbmodem1101 flash         # 烧录 + 自动复位
idf.py -p /dev/cu.usbmodem1101 monitor       # 串口日志（REPL 控制台）
```

烧录后控制台为 USB-Serial-JTAG（GPIO18/19；UART0 默认 TX GPIO21 与本板背光冲突）。

**主机逻辑测试**（固件状态机/协议/音频分片，纯 C，无需硬件）：

```bash
cd tests && cmake -B build && cmake --build build && ctest --test-dir build
```

**USB 控制台命令**（`idf.py monitor` 的 REPL，或桌面端诊断页经 SYS 帧下发）：

| 命令 | 作用 |
| --- | --- |
| `st` | 系统状态：堆/栈水位、BLE/USB 连接、MTU、掉帧、电池 |
| `log [offset]` | 导出日志环（有 USB 主机时日志进 16KB RAM 环）；环超 2048B 时按 `log 2048` / `log 4096` 分段取全量 |
| `rst` | 复位原因（1 上电 / 4 软件 / 11 USB-flash） |
| `time` / `time set <epoch>` | 查看 / 设置 wall-clock（校时源仅电脑客户端） |
| `bt scan` / `bt dtx [ch]` | 射频诊断：主动扫描周边广播 / 固定信道强制发射 |
| `reboot` | 软件重启 |
| `factory` | 清空 NVS 并重启（出厂复位） |

## 仓库结构

```text
main/                    ESP32-C3 固件:状态机、UI、双通道传输、音频流、控制台命令
components/bsp/          板级驱动:显示 / 按键 / 音频 / 电池 / 共享 I2C(bsp_pins.h 为硬件事实唯一来源)
companion/               桌面端:relay 中转(本地 whisper ASR + DeepSeek 整理 + 注入)、悬浮窗、向导、托盘、双通道传输
tests/                   可脱离硬件运行的固件逻辑测试(纯 C,ctest)
docs/                    硬件开发指南与验收文档
sdkconfig.defaults       ESP32-C3、USB console、Flash、LVGL 默认配置
partitions.csv           自定义分区表(factory 4MB)
```

## 工作原理

1. 设备 READY 态按住**音量+** → 滴声 → `voice.start` → 3200B/100ms 音频帧经 BLE（GATT NOTIFY）/ USB 上行
2. 桌面端 relay 把音频帧送入**本地 whisper.cpp** 转写（每包结果携带**全量累计文本**）
3. 中间结果（partial）→ 设备屏幕实时预览；松手 → `voice.end` → ASR 定稿
4. 定稿文本送入 **DeepSeek 整理层**，按当前场景预设（`work_wechat` / `report_boss` / `agent_prompt` / `voice_input`）理顺成成稿
5. ①–③ 场景：分段录制时每段预览，全部录完由 DeepSeek **跨段合并**成完整成稿，MERGE_REVIEW 页 OK 确认后注入；④ 场景：单段定稿即整理，可连续快录
6. 成稿注入当前输入框（剪贴板 + Cmd+V）→ 悬浮窗消失；同时回显设备屏幕

注入目标是用户当前焦点窗口，悬浮窗绝不抢焦点；整理服务不可用时回退注入原文。

## 设计决策

- **为什么本地 ASR**：隐私与成本是硬约束——语音是高度敏感数据，本地 whisper.cpp 让音频从不出网、零按量费用；只有在"整理"这一步才把已转写的中文文本发给 DeepSeek（且整理失败可回退原文）。
- **为什么场景化整理**：用户要的不是"我说了什么"，而是"这段话发出去该长什么样"。同事消息要简洁、对领导要结论先行、给 AI 要可执行指令、随手记要通顺文字——预设把"意图"编码进整理，避免每次手写 prompt。
- **为什么分段录入 + 合并**：灵感常是碎片、跳跃、跨多次口述的；逐段预览 + 跨段去重合并，比单次长录更易控、成稿更连贯。
- **为什么双通道**：BLE 覆盖有蓝牙的 Mac；USB 是调试器兼最后保底——任何单一链路失效都可用另一条继续工作，断线事件统一收束，不残留半开会话。
- **为什么状态机是纯 C 归约器**：`state + event → action` 的归约模式让全部转移逻辑**零硬件依赖**，host 侧测试直接覆盖状态转移、协议编解码、音频分片、UI 像素计算；UI 按快照差异渲染，加页面不加状态耦合。
- **为什么音频管线做静态环形缓冲**：ESP32-C3 只有 400KB SRAM，动态分配 + 整段缓存一次长录音会直接爆内存。3200B/100ms 帧、源端丢帧、掉帧对账，是"入门级 MCU 也能当 AI 输入设备"的关键。
- **为什么物理审批**：AI 自动改文件、执行命令是有风险的——审批不放通知栏，放设备屏幕，按实体键才算数，且审批态永不熄屏。

## 开发

固件逻辑测试（无硬件，cmake + ctest）：

```bash
cd tests && cmake -B build && cmake --build build && ctest --test-dir build
```

桌面端单测（pytest）：

```bash
companion/.venv/bin/python -m pytest companion/tests/ -q -o asyncio_mode=auto
```

- 固件状态机、协议、音频分片、UI 像素计算均有 host 侧测试覆盖；构建通过 ≠ 硬件验证通过
- 添加新页面/功能时保持硬件逻辑在 `components/bsp`、应用逻辑在 `main`；可测试的纯逻辑与 ESP-IDF/LVGL 分离
- LVGL 非线程安全；按键回调只派发轻量事件；慢操作放工作任务

### 真机验收状态

设备到货后的完整验收清单见 [`docs/ON_DEVICE.md`](docs/ON_DEVICE.md)。当前状态：**Build PASS、Host tests PASS、真机连续实测 PASS**。已真机验证：四场景切换、1–3 段分段录入与合并、连续快录、按住说话多次会话、连续快速长按无丢键、转写中单击退出、双通道传输、休眠唤醒、真锁屏。仍待重点验收：Windows 焦点不抢占、长句连续十几秒无丢字、USB 拔线恢复、电池读数、企业微信回传。

## 路线 / 设计中

- **企业微信回传**：把整理成稿经企业微信 push 回手机（规避个人微信封号风险），让"语音录入 → 手机可取"闭环——桌面注入已实现，手机回传为下一步。
- **多段编排状态机**：逐段预览 + 确认后统一整理，支持更长的连续口述。
- **像素风 UI**：在 240×320 屏上用索引色小图（≤128×128）呈现物品/人物形象，资源占用低（~50–200KB Flash、几乎零 RAM）。

## 致谢 / 上游

本项目基于 [zhaohuaxiaoy/folo-ai-passport-voice](https://github.com/zhaohuaxiaoy/folo-ai-passport-voice)（FoloToy AI Passport，MIT）二次开发：固件的状态机、LVGL UI、BLE/USB 双通道传输与物理审批机制继承自该项目；本仓库增加了本地 whisper.cpp ASR、场景化 DeepSeek 整理层、四场景与分段/连续录入等个性化能力。

## 许可

MIT © 2026 AI Passport，见 [LICENSE](LICENSE)。

第三方组件：LVGL、esp_lvgl_port、NimBLE、cJSON、whisper.cpp、OpenAI-compatible SDK 等版权归其各自作者。
