# aipassport 改造版（本地 whisper + DeepSeek 整理）

把原 `folo-ai-passport-voice`（火山云 ASR）改成 **Mac 本地 whisper.cpp 转写 + DeepSeek 整理**，
实现「零碎口语 → 本地听写 → AI 理顺 → 注入输入框」的零云端 ASR 闭环。

## 改了什么（相对原仓库）

| 文件 | 改动 |
|---|---|
| `asr_local_whisper.py` | **新增**。本地 whisper.cpp 流式 ASR，接口与火山 `StreamingASR` 完全对齐（`connect/send_frame/send_end/results`），relay 零改动替换 |
| `refine_deepseek.py` | **新增**。DeepSeek V4-Flash 整理层，把原始口语理顺成工作稿；含 4 个预设 |
| `relay.py` | **改 3 处**：① 顶部 ASR 导入指向本地 whisper；② `main()` 的 `load_config` 指向本地；③ `_results_loop` 定稿分支插入 `refine()`（失败优雅回退原文） |
| `config.example.json` | 火山字段 → 本地 whisper + DeepSeek 字段 |
| `requirements.txt` | 去掉 `websockets`（火山用），加 `whisper-cpp-python` + `requests` |
| `test_pipeline_headless.py` | **新增**。无设备集成测试，用 FakeTransport 跑通全链路 |

> 原 `asr_client.py`（火山）保留未删，想切回云端改一行导入即可。

## 核心数据流

```
设备(按住说话) → BLE/USB 音频帧(3200B/100ms)
   → relay._drain_audio → session.feed → asr.send_frame
   → voice.end → asr.send_end → 本地 whisper 定稿
   → relay._results_loop: refine(原文) → DeepSeek 整理稿
   → inject_fn(整理稿) 注入当前输入框 / 悬浮窗预览
```

## 运行前准备

1. **本地 whisper 引擎 + 模型**（已完成）：`bash install_whisper_local.sh`
   模型默认 `~/models/ggml-large-v3-turbo.bin`。
2. **Companion 依赖**：在已装好 whisper-cpp-python 的 venv 里补装设备/注入依赖：
   ```bash
   PY=/Users/Zhuanz/.workbuddy/binaries/python/envs/default/bin/python
   $PY -m pip install bleak pyobjc-framework-Quartz pyobjc-framework-ApplicationServices pyserial pystray
   ```
   （whisper-cpp-python 安装见 `install_whisper_local.sh`，沙箱/CMake 4 坑已避开）
3. **配置**：拷贝 `config.example.json` 为 `config.local.json`，填入：
   - `whisper_model_path` / `whisper_threads` / `whisper_language`（默认 zh）
   - `deepseek_api_key`（你的 DeepSeek key；整理层需要）
   - `refine_preset`：`work_wechat`(默认) / `report_boss` / `meeting_notes` / `light_polish`
   - `refine_enabled`：true 开整理 / false 只转写不整理

## 验证（无需硬件）

```bash
cd companion
PY=/Users/Zhuanz/.workbuddy/binaries/python/envs/default/bin/python

# 仅验本地 ASR + 注入（不调 DeepSeek）
AIPASSPORT_TEST_REFINE=0 AIPASSPORT_TEST_LANG=en \
  $PY test_pipeline_headless.py /tmp/jfk.wav

# 验含 DeepSeek 整理（需 DEEPSEEK_API_KEY）
DEEPSEEK_API_KEY=sk-xxx AIPASSPORT_TEST_REFINE=1 AIPASSPORT_TEST_LANG=en \
  $PY test_pipeline_headless.py /tmp/jfk.wav
```
测试会用 FakeTransport 模拟一次录音，把最终「注入输入框的文本」打印出来。
中文样本：`AIPASSPORT_TEST_WAV=某中文.wav AIPASSPORT_TEST_LANG=zh`。

## 真机运行

```bash
PY=/Users/Zhuanz/.workbuddy/binaries/python/envs/default/bin/python
$PY relay.py                # 扫描 "AI Passport" 并全流程
$PY relay.py --no-inject    # 只转写不注入（调试）
```
首次连接会加载 whisper 模型（~1s，之后进程内缓存）；首次发音可能因模型预热丢前几帧，
后续会话正常。

## 已知限制 / 后续增强

- **多段录入 + 逐段预览 + 确认后统一整理**：当前是「单次录音 → 整理 → 注入」。
  用户原始想法是分多次录、每段先看文字、确认后统一整理。这需扩展 `fre_state`
  状态机（新增「段落子态」）与设备审批协议（OK 批准注入 / UP 拒绝），属后续迭代。
- **回传手机（微信/企微）**：当前只做「回传电脑输入框」。回传手机可接官方 MQTT
  或你已连的企业微信 Connector，与电脑注入双轨并行。
- 预览窗口显示的是「原始转写」（实时），定稿注入的是「DeepSeek 整理稿」。
  如需先预览整理稿再确认发送，需把注入改为「审批门控」（借原 approval 协议）。
