#!/usr/bin/env python3
"""麦克风版 aipassport：不依赖硬件，用 Mac 自带麦克风跑通「说话→整理→注入」。

用途
────
当前设备刷的是 TRAE 默认固件（广播名 = SN，无 GATT 0xA2B0 音频服务），
relay.py 连不上。本脚本绕开硬件，复用同一套本地 whisper + DeepSeek 整理 +
输入框注入逻辑，让整条链路今天就能用、能验证。

用法
────
    python mic_relay.py                  # 回车开始录音，再回车结束（默认中文）
    python mic_relay.py --seconds 8      # 固定录 8 秒
    python mic_relay.py --lang en        # 英文转写
    python mic_relay.py --wav /tmp/a.wav # 喂现成 wav（16k 单声道），不录音
    python mic_relay.py --no-inject      # 只打印结果，不注入（安全试跑）

参数
────
    --seconds N      固定录音时长；不给则进入「回车开始/结束」模式
    --lang LANG      转写语言，默认 zh（英文用 en）
    --wav PATH       用现成 wav 替代录音
    --no-inject      不注入，仅打印
    --device N       指定输入设备序号；不给则用系统默认设备

注：注入走 companion/inject.py（macOS Quartz + 剪贴板回退），
    首次使用需给终端「辅助功能」授权。
"""
import argparse
import asyncio
import sys
import threading
import time
import wave

import numpy as np

RATE = 16000
CHUNK = 3200  # 100ms @16k/16bit


# ---------------------------------------------------------------- 录音

def record_until_enter(seconds=None, device=None):
    """录音：回车开始 → 再回车结束；或固定 seconds 秒。返回 int16 numpy 数组。"""
    import sounddevice as sd

    if seconds:
        print(f"[mic] 录 {seconds:g} 秒 … 现在说话")
        frames = int(seconds * RATE)
        data = sd.rec(frames, samplerate=RATE, channels=1, dtype="int16",
                      device=device)
        sd.wait()
        return data.flatten()

    print("[mic] 按 回车 开始录音 …")
    input()
    chunks = []
    stop = threading.Event()

    def waiter():
        input()  # 主线程阻塞在 stream 上，这里等第二次回车
        stop.set()

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    print("[mic] 🔴 录音中 … 说完再按 回车 结束")

    def cb(indata, _n, _t, _s):
        chunks.append(indata.copy())

    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16",
                        blocksize=CHUNK // 2, device=device, callback=cb):
        while not stop.is_set():
            time.sleep(0.05)

    if not chunks:
        return np.zeros(0, dtype="int16")
    return np.concatenate(chunks).flatten()


def load_wav(path):
    with wave.open(path, "rb") as w:
        if w.getframerate() != RATE:
            raise SystemExit(f"[mic] {path} 采样率 {w.getframerate()} ≠ 16000，"
                             f"请先转成 16k 单声道")
        raw = w.readframes(w.getnframes())
    arr = np.frombuffer(raw, dtype=np.int16)
    if w.getnchannels() == 2:
        arr = arr.reshape(-1, 2).mean(axis=1).astype(np.int16)
    return arr


# ---------------------------------------------------------------- 链路

async def run_pipeline(pcm: np.ndarray, lang: str, do_inject: bool):
    from asr_local_whisper import LocalWhisperASR
    from refine_deepseek import refine

    cfg = LocalWhisperASR().cfg  # 走同一份 config.local.json
    cfg["whisper_language"] = lang
    asr = LocalWhisperASR(cfg)

    print("[asr]  加载本地 whisper 模型（首次约 10-20 秒）…")
    t0 = time.time()
    await asr.connect()
    print(f"[asr]  模型就绪 ({time.time() - t0:.1f}s)，转写 {len(pcm) / RATE:.1f}s 音频 …")

    # 按 100ms 帧喂入（与设备路径同样的节奏）
    buf = pcm.tobytes()
    for i in range(0, len(buf), CHUNK):
        await asr.send_frame(buf[i:i + CHUNK])
    await asr.send_end()

    final = ""
    async for text, is_final in asr.results():
        if is_final:
            final = text
            break
    await asr.close()

    print(f"\n[asr]  原文：{final}")

    if not cfg.get("refine_enabled", True):
        print("[refine] 已关闭（refine_enabled=false），直接用原文")
        return final

    print("[refine] DeepSeek 整理中 …")
    refined = await asyncio.to_thread(refine, final, cfg)
    if not refined:
        print("[refine] 返回空，回退原文")
        refined = final
    print(f"[refine] 成稿：{refined}")

    if do_inject:
        from inject import paste_text
        delay = float(cfg.get("inject_focus_delay", 2.0))
        print(f"[inject] {delay:g}s 后注入到当前光标处 —— 请立刻点中目标输入框！")
        time.sleep(delay)
        paste_text(refined)
        print("[inject] 完成")
    else:
        print("[inject] --no-inject，未注入")
    return refined


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="麦克风版 aipassport（无硬件也能跑）")
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--wav", default=None)
    ap.add_argument("--no-inject", action="store_true")
    ap.add_argument("--device", type=int, default=None)
    a = ap.parse_args()

    if a.wav:
        print(f"[mic] 使用现成文件：{a.wav}")
        pcm = load_wav(a.wav)
    else:
        pcm = record_until_enter(a.seconds, a.device)

    if len(pcm) < RATE * 0.3:
        raise SystemExit("[mic] 音频太短（<0.3s），没什么可转写的")

    asyncio.run(run_pipeline(pcm, a.lang, not a.no_inject))


if __name__ == "__main__":
    main()
