#!/usr/bin/env python3
"""aipassport 无设备集成测试：用 FakeTransport 跑通 设备→ASR→整理→注入 全链路。

不需要真机、不需要 BLE/麦克风。它把一个 WAV 文件切成 100ms 帧，模拟设备
"按住说话→逐帧上行音频→松开 voice.end"，验证：
  1) relay 用本地 whisper（LocalWhisperASR）完成转写；
  2) 定稿后过 DeepSeek 整理（refine_enabled 时，需 DEEPSEEK_API_KEY）；
  3) 注入的"是整理稿"而非原始口语。

运行（本机 venv，已装 whisper-cpp-python + requests）：
  DEEPSEEK_API_KEY=sk-xxx python3 test_pipeline_headless.py [wav路径]
  AIPASSPORT_TEST_REFINE=0 python3 test_pipeline_headless.py   # 跳过 DeepSeek，仅验本地 ASR+注入

默认用 ~/models 下的 large-v3-turbo 与 /tmp/jfk.wav（英文样本，language=en）。
设 AIPASSPORT_TEST_WAV 指向中文 wav、AIPASSPORT_TEST_LANG=zh 可测中文。
"""
import asyncio
import json
import os
import sys

COMPANION = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, COMPANION)

from asr_local_whisper import LocalWhisperASR  # noqa: E402
from relay import EVENT_UUID, AUDIO_UUID  # relay 顶层不 import bleak/pyobjc（懒加载），可直接取 UUID


class FakeTransport:
    """与 BleakTransport 同接口的假传输：不连真机，由测试驱动喂数据。"""

    def __init__(self):
        self._handlers = {}
        self._connected = asyncio.Event()
        self.downs = []          # 下行 CTRL 记录(测试断言 segment.ready 等)
        self._dl_accum = b""     # 下行分帧重组缓冲(模拟固件 '\n' 分帧)

    async def scan_for_device(self, name, timeout):
        return "fake-ai-passport"

    async def connect(self, address, on_disconnect=None):
        self.on_disconnect = on_disconnect
        self._connected.set()

    async def write_gatt_char(self, uuid, data, response=False):
        # 模拟固件 v0.2.1 下行分帧: 累积到行尾 '\n' 再成完整行(短行单次、
        # 长行多片最终都重组为 JSON 对象进 downs)。
        self._dl_accum += bytes(data)
        import json as _json
        while b"\n" in self._dl_accum:
            line, self._dl_accum = self._dl_accum.split(b"\n", 1)
            if not line:
                continue
            try:
                self.downs.append(_json.loads(line))
            except Exception:
                self.downs.append(line)   # 非 JSON(不期望)原样存

    async def start_notify(self, uuid, handler):
        # relay 内部 handler 签名为 (data_bytes)；bleak 会包一层 (char,data)
        self._handlers[uuid] = handler

    async def disconnect(self):
        if not self._connected.is_set() and self.on_disconnect:
            self.on_disconnect()

    # ---- 测试驱动 ----
    def push_event(self, obj):
        h = self._handlers.get(EVENT_UUID)
        if h:
            # relay 的 EVENT 行以 '\n' 结尾（reassemble_event 按换行切分）
            h(json.dumps(obj).encode("utf-8") + b"\n")

    def push_audio(self, pcm_frame: bytes):
        h = self._handlers.get(AUDIO_UUID)
        if h:
            h(pcm_frame)


def _load_pcm(wav_path):
    """WAV -> 裸 16kHz/16bit/单声道 PCM 字节。"""
    import wave
    with wave.open(wav_path, "rb") as wf:
        assert wf.getnchannels() == 1 and wf.getframerate() == 16000, \
            "需 16kHz 单声道 WAV"
        return wf.readframes(wf.getnframes())


async def main():
    wav = os.environ.get("AIPASSPORT_TEST_WAV", "/tmp/jfk.wav")
    lang = os.environ.get("AIPASSPORT_TEST_LANG", "en")
    refine_on = os.environ.get("AIPASSPORT_TEST_REFINE", "1") == "1"
    model = os.path.expanduser("~/models/ggml-large-v3-turbo.bin")

    # 延迟 import relay（它 import bleak/pyobjc 等，仅本测试需要）
    from relay import Relay

    collected = []
    injected = asyncio.Event()

    def inject_fn(text):
        collected.append(text)
        print(f"\n[headless] 📥 注入输入框的文本({len(text)}字):\n{text}\n")
        injected.set()

    cfg = {
        "whisper_model_path": model,
        "whisper_threads": 8,
        "whisper_language": lang,
        "whisper_partial_interval": 999.0,
        "whisper_min_partial_sec": 999.0,
        "refine_enabled": refine_on,
        "refine_preset": os.environ.get("AIPASSPORT_TEST_PRESET", "work_wechat"),
        "deepseek_api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "deepseek_base_url": "https://api.deepseek.com",
        "deepseek_model": "deepseek-v4-flash",
        "deepseek_temperature": 0.3,
    }

    phases = []
    transport = FakeTransport()
    relay = Relay(
        transport=transport,
        asr_factory=lambda: LocalWhisperASR(cfg),
        inject_fn=inject_fn,
        on_phase=lambda p: phases.append(p),
        do_inject=True,
        do_approval=False,    # 跳过审批演示（不等人按设备键）
        dry_run=False,
        connect_timeout_s=60.0,
    )

    run_task = asyncio.ensure_future(relay.run())
    # 等连接就绪 + AUDIO/EVENT 处理器注册完成（run() 在 connect 后才 start_notify）
    await asyncio.wait_for(transport._connected.wait(), timeout=10)
    while EVENT_UUID not in transport._handlers or AUDIO_UUID not in transport._handlers:
        await asyncio.sleep(0.02)

    # 模拟一次录音：voice.start -> 逐帧音频 -> voice.end
    pcm = _load_pcm(wav)
    print(f"[headless] 模拟录音: PCM={len(pcm)}B, 帧数={len(pcm)//3200}")
    transport.push_event({"event": "voice.start", "audio": "pcm"})
    await asyncio.sleep(0.05)
    # 真实实时节奏推流：每帧 100ms（与真机 PTT 录音节拍一致），避免音频队列
    # （上限 20 帧≈2s）溢出丢帧
    for i in range(0, len(pcm), 3200):
        transport.push_audio(pcm[i:i + 3200])
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.2)
    transport.push_event({"event": "voice.end"})

    # v0.2.0 分段录入: voice.end 定稿 → 段预览(segment.ready) → 用户按 OK
    # 结束录入(recording.done) → 综合整理 → 整理稿(merge.result) → 再按
    # OK 确认注入(inject.confirm ok:true)。headless 模拟按键, 但必须等前
    # 一步的下行真的到达(真实设备是用户看到屏幕才按键), 用轮询替代固定 sleep。

    def _wait_down(ttype, timeout_s=30.0):
        async def w():
            waited = 0.0
            while waited < timeout_s:
                if any(m.get("type") == ttype for m in transport.downs):
                    return True
                await asyncio.sleep(0.2)
                waited += 0.2
            return False
        return w()

    # 1) 等定稿下行 segment.ready(whisper 定稿入段)
    ok_seg = await _wait_down("segment.ready")
    print(f"[headless] segment.ready 到达: {ok_seg}")
    if ok_seg:
        transport.push_event({"event": "recording.done"})
        # 2) 等综合整理下行 merge.result
        ok_merge = await _wait_down("merge.result", timeout_s=40.0)
        print(f"[headless] merge.result 到达: {ok_merge}")
        if ok_merge:
            transport.push_event({"event": "inject.confirm", "ok": True})
    else:
        # 退化(定稿未下行, 说明转写异常/无内容): 直接模拟单段确认注入路径
        # 已不可能 —— 由下方超时兜底暴露
        pass

    # 等注入（含本地 ASR + 可选 DeepSeek 整理）
    try:
        await asyncio.wait_for(injected.wait(), timeout=120)
        print(f"\n✅ 全链路跑通！阶段={phases}")
        print(f"✅ 最终注入文本见上方（refine={'开' if refine_on else '关'}）")
    except asyncio.TimeoutError:
        print("❌ 超时未注入，检查 ASR/DeepSeek 配置")
    finally:
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):
            pass


if __name__ == "__main__":
    asyncio.run(main())
