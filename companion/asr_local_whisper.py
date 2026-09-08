#!/usr/bin/env python3
"""本地 whisper.cpp 流式 ASR（替代火山引擎）。

aipassport 改造版：把 folo-ai-passport-voice 默认的「火山云端 ASR」整段换成
「Mac 本地 whisper.cpp」，零云端 ASR、零费用、音频不出本机。

接口契约与 asr_client.StreamingASR 完全对齐，relay.py 只需把
    from asr_client import StreamingASR
改成
    from asr_local_whisper import LocalWhisperASR as StreamingASR
即可无缝替换，其余链路（注入、预览、状态机）一行不动。

用法（relay 内部）：
    asr = StreamingASR(cfg)            # cfg 缺省自动 load_config()
    await asr.connect()               # 加载本地模型（进程内缓存）
    await asr.send_frame(pcm_3200b)    # 每帧 100ms @16kHz/16bit/mono
    await asr.send_end()              # 末帧后跑最终转写
    async for text, is_final in asr.results():
        ...                           # partial 实时预览 / final 定稿

模型加载是阻塞操作，内部用 asyncio.to_thread + 锁串行化，避免多次并发跑 whisper。
首次连接会加载模型（large-v3-turbo 约 1.5GB，M4 上 ~1s），之后复用。
"""
import asyncio
import json
import os
import tempfile
import threading
import wave

# whisper_cpp_python 0.2.0 的导入名（不是老文档的 whisper_cpp）。
# macOS 上 whisper_cpp.py 写死找 libwhisper.so，实际产出 libwhisper.dylib，
# 首次安装需建软链接（见 install_whisper_local.sh）。这里只负责 import。
try:
    from whisper_cpp_python import Whisper  # noqa: E402
except Exception as exc:  # pragma: no cover - 安装/软链接问题集中在此
    raise RuntimeError(
        "无法导入 whisper_cpp_python。请确认：\n"
        "  1) 已在 venv 装 whisper-cpp-python（bash install_whisper_local.sh）\n"
        "  2) macOS 已建软链接 libwhisper.so -> libwhisper.dylib\n"
        f"原始错误: {exc}"
    )

CHUNK_BYTES_100MS = 3200  # 100ms @ 16kHz/16bit/单声道（与固件音频块一致）

# 进程内模型缓存：同一路径只初始化一次（模型加载很慢很占内存）
_MODEL_CACHE = {}
_MODEL_LOCK = threading.Lock()


def _get_model(model_path, n_threads, engine="cpp"):
    """取（必要时加载）本地 whisper 模型实例。

    engine="cpp": whisper_cpp_python 的 Whisper 对象, 进程内按路径缓存
    （whisper.cpp 底层 context 非线程安全, 需配合 _TRANSCRIBE_LOCK 串行）。
    engine="mlx": 不做本地缓存 —— mlx_whisper.transcribe 内部 ModelHolder
    按路径缓存模型(类级, 同路径只 load 一次), 直接调 transcribe 即可。
    """
    if engine == "mlx":
        if not os.path.isdir(model_path):
            raise RuntimeError(
                f"MLX whisper 模型目录不存在: {model_path}\n"
                f"请先下载: HF_ENDPOINT=https://hf-mirror.com python -c "
                f"\"from huggingface_hub import snapshot_download; "
                f"snapshot_download('mlx-community/whisper-large-v3-turbo', "
                f"local_dir='{model_path}')\"")
        return None  # 模型由 mlx_whisper 内部 ModelHolder 缓存管理
    key = (model_path, n_threads)
    with _MODEL_LOCK:
        m = _MODEL_CACHE.get(key)
        if m is None:
            if not os.path.exists(model_path):
                raise RuntimeError(
                    f"本地 whisper 模型不存在: {model_path}\n"
                    f"请先运行 bash install_whisper_local.sh 下载 "
                    f"ggml-large-v3-turbo.bin")
            m = Whisper(model_path=model_path, n_threads=n_threads)
            _MODEL_CACHE[key] = m
        return m


def _pcm_to_wav_bytes(pcm: bytes) -> str:
    """把 16kHz/16bit/单声道 PCM 字节写成临时 WAV 文件，返回路径。

    whisper_cpp_python.transcribe 走 librosa.load(文件路径)，所以本地流式
    预览/定稿都通过临时 WAV 喂进去。临时文件用完即删（见调用方）。
    """
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="aipassport_asr_")
    os.close(fd)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm)
    return path


# whisper 模型全局互斥: _get_model 按 key 缓存使多个 LocalWhisperASR 实例
# 共享同一 Whisper 对象, 而 whisper.cpp 底层 context 非线程安全 —— 跨实例
# 并发 transcribe(如前一会话 final 未结束 + 下一会话 partial 开始)会段错误
# (实测 2026-09-07: 第二次 voice.start 后 segmentation fault)。所有转写在
# 此全局串行; 实例内 partial/final 由各实例 _lock 保证不重叠。
_TRANSCRIBE_LOCK = threading.Lock()


def _pcm_to_float32(pcm: bytes):
    """16kHz/16bit/单声道 PCM → float32 numpy(MLX 输入, -1.0~1.0)。"""
    import numpy as np
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def _transcribe_pcm(model, pcm: bytes, language: str, engine="cpp",
                    mlx_model_path=None) -> str:
    """对一段 PCM 跑一次 whisper，返回识别文本（空串表示静音/无语音）。

    engine="cpp" 走 whisper_cpp_python(写临时 wav → transcribe);
    engine="mlx" 走 mlx_whisper(Metal GPU, 直接吃 float32 波形, 快 10x+)。
    两引擎都在 _TRANSCRIBE_LOCK 内串行(共享模型非线程安全, 保守一致)。
    """
    if not pcm:
        return ""
    if engine == "mlx":
        import mlx_whisper
        try:
            with _TRANSCRIBE_LOCK:
                res = mlx_whisper.transcribe(
                    _pcm_to_float32(pcm),
                    path_or_hf_repo=mlx_model_path,
                    language=language,
                    temperature=0.0,
                    verbose=None,
                    fp16=True,
                    condition_on_previous_text=False,
                )
            if isinstance(res, dict):
                return (res.get("text") or "").strip()
            return str(res).strip()
        except Exception as e:
            print(f"[asr] MLX 转写异常: {e}", file=__import__("sys").stderr)
            return ""
    path = _pcm_to_wav_bytes(pcm)
    try:
        with _TRANSCRIBE_LOCK:
            try:
                res = model.transcribe(path, language=language, temperature=0.0)
            except UnicodeDecodeError as e:
                # whisper_cpp_python 绑定层按 utf-8 解码 token 流, 遇非 utf-8
                # 字节(如韩文/异常 token)直接抛(实测 2026-09-07 中文会话
                # 收音混入非中文内容时触发)。音频异常内容, 记日志回退空串。
                print(f"[asr] 转写输出非法 utf-8, 丢弃本次结果: {e}",
                      file=__import__("sys").stderr)
                return ""
        if isinstance(res, dict):
            return (res.get("text") or "").strip()
        return str(res).strip()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ---- 配置 ----（与 asr_client.load_config 字段兼容，并新增 aipassport 字段）

def load_config():
    """读取 companion/config.local.json，补全 aipassport 所需的本地 ASR 配置。

    与 fre_state.config_path 同目录（源码运行即模块目录）。缺失字段给默认值，
    密钥类字段优先取环境变量。
    """
    from fre_state import config_path

    cfg = {}
    p = config_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    # 本地 whisper 必填
    cfg.setdefault("whisper_model_path",
                   os.path.expanduser("~/models/ggml-large-v3-turbo.bin"))
    # 配置里可能写的是 "~/models/..."，setdefault 不会展开已存在的值，
    # 这里统一补一次 expanduser（否则 Whisper 找不到模型直接抛 RuntimeError）。
    cfg["whisper_model_path"] = os.path.expanduser(cfg["whisper_model_path"])
    # aipassport: ASR 引擎双轨 —— "mlx"=Apple MLX(M 系列 Metal GPU, 快 10x+,
    # 默认); "cpp"=whisper_cpp_python(旧引擎, 转写慢, 保留作回退)。
    cfg.setdefault("asr_engine", "mlx")
    cfg.setdefault("mlx_model_path",
                   os.path.expanduser(
                       "~/models/mlx-whisper-large-v3-turbo"))
    cfg["mlx_model_path"] = os.path.expanduser(cfg["mlx_model_path"])
    cfg.setdefault("whisper_threads", 8)
    cfg.setdefault("whisper_language", "zh")
    cfg.setdefault("whisper_partial_interval", 1.0)  # 秒：流式预览重跑间隔
    cfg.setdefault("whisper_min_partial_sec", 1.0)   # 至少攒够多少秒才出预览
    # DeepSeek 整理层（refine_deepseek 用）
    cfg.setdefault("refine_enabled", True)
    # refine 后端: "deepseek"(默认) / "glm"(智谱 glm-4.7-flash 免费)
    cfg.setdefault("refine_provider", "deepseek")
    cfg.setdefault("glm_model", "glm-4.7-flash")
    cfg.setdefault("glm_base_url", "https://open.bigmodel.cn/api/paas/v4")
    cfg.setdefault("glm_temperature", 0.3)
    cfg.setdefault("refine_preset", "work_wechat")  # 见 refine_deepseek.PRESETS
    cfg.setdefault("deepseek_api_key", os.environ.get("DEEPSEEK_API_KEY", ""))
    cfg.setdefault("deepseek_base_url", "https://api.deepseek.com")
    cfg.setdefault("deepseek_model", "deepseek-v4-flash")
    cfg.setdefault("deepseek_temperature", 0.3)
    # 兼容原 relay 的通道/注入字段（保持 macOS 现有行为）
    cfg.setdefault("channel", "ble")
    cfg.setdefault("inject_focus_delay", 2.0)
    cfg.setdefault("inject_mode", "auto")
    return cfg


RESULTS_Q_MAX = 32


class LocalWhisperASR:
    """本地 whisper.cpp 流式 ASR 会话，接口对齐火山 StreamingASR。

    设计：send_frame 只把 PCM 攒进内存缓冲；连接后起一个后台「预览循环」按
    间隔对当前缓冲跑一次 whisper 出 partial；send_end 跑最终 whisper 出 final。
    results() 异步产出 (text, is_final)。
    """

    def __init__(self, cfg=None, chunk_bytes=CHUNK_BYTES_100MS):
        # 外部传入的精简 cfg(如 headless 测试)可能缺新字段, 用 load_config()
        # 的完整默认(含 asr_engine/mlx_model_path)兜底合并, 保证引擎分派健壮。
        base = load_config()
        if cfg is not None:
            base.update(cfg)
        self.cfg = base
        self.chunk_bytes = chunk_bytes
        self._pcm = bytearray()
        self._model = None
        self._results_q = asyncio.Queue(maxsize=RESULTS_Q_MAX)
        self._closed = False
        self._final_sent = False
        self._final_requested = False
        self._lock = asyncio.Lock()
        self._partial_task = None
        self._last_partial_len = 0

    # -- 连接 / 模型加载 --

    async def connect(self):
        # 模型加载较慢且占内存，放线程里跑，避免阻塞事件循环
        def _load():
            engine = self.cfg.get("asr_engine", "mlx")
            if engine == "mlx":
                mp = self.cfg["mlx_model_path"]
                _get_model(mp, 0, engine="mlx")   # 校验目录存在
                # 真正预加载: ModelHolder.get_model 触发 1.6GB safetensors
                # 载入(与 transcribe 内部同 fp16)。relay 预热阶段完成它,
                # 首次 PTT 的 send_end 就不再吞模型加载延迟(实测省 ~10s)。
                try:
                    import mlx.core as mx
                    from mlx_whisper.transcribe import ModelHolder
                    ModelHolder.get_model(mp, mx.float16)
                except Exception as e:
                    print(f"[asr] MLX 模型预加载失败(首次转写时再试): {e}",
                          file=__import__("sys").stderr)
                return None
            return _get_model(self.cfg["whisper_model_path"],
                              int(self.cfg.get("whisper_threads", 8)),
                              engine="cpp")

        self._model = await asyncio.to_thread(_load)
        # 启动流式预览循环（与音频帧喂入并发）
        self._partial_task = asyncio.ensure_future(self._partial_loop())

    async def _partial_loop(self):
        # 预览频率与窗口(2026-09-07 调优): 预览每次全量转写很贵(MLX 4s/次),
        # 与 send_end 的 final 抢同一把锁 → 松手后 final 排队, 感知延迟变大。
        # ① interval 提到 2s(默认) ② 每次只转最近 PARTIAL_WIN_SEC 秒,
        # 计算量封顶; final(send_end)仍转全量。
        interval = float(self.cfg.get("whisper_partial_interval", 2.0))
        min_bytes = int(self.cfg.get("whisper_min_partial_sec", 2.0) * 16000 * 2)
        win_bytes = int(self.cfg.get("whisper_partial_window_sec", 8.0) * 16000 * 2)
        try:
            while not self._closed and not self._final_sent:
                await asyncio.sleep(interval)
                if self._final_sent or self._closed or self._final_requested:
                    break
                buf = bytes(self._pcm)
                if len(buf) < min_bytes:
                    continue
                if len(buf) <= self._last_partial_len:
                    continue  # 没新音频，跳过（避免重复预览）
                if len(buf) > win_bytes:
                    buf = buf[-win_bytes:]   # 只转最近窗口, 封顶计算量
                self._last_partial_len = len(buf)
                text = await self._run_whisper(buf)
                if text and not self._final_sent:
                    try:
                        self._results_q.put_nowait((text, False))
                    except asyncio.QueueFull:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception as e:  # 预览失败不影响主链路
            print(f"[asr] 预览循环异常(已忽略): {e}", file=__import__("sys").stderr)

    async def _run_whisper(self, pcm: bytes) -> str:
        async with self._lock:
            return await asyncio.to_thread(
                _transcribe_pcm, self._model, pcm,
                self.cfg.get("whisper_language", "zh"),
                self.cfg.get("asr_engine", "mlx"),
                self.cfg.get("mlx_model_path"))

    # -- 音频上行 --

    async def send_frame(self, pcm_bytes):
        self._pcm += bytes(pcm_bytes)

    async def send_end(self):
        # 停预览循环，跑最终转写。置 final 请求标志: partial 循环(可能正
        # 在 sleep/准备下一次)据此不再启动新预览, 把 GPU/锁让给 final。
        self._final_requested = True
        if self._partial_task is not None:
            self._partial_task.cancel()
            try:
                await self._partial_task
            except (asyncio.CancelledError, Exception):
                pass
        self._partial_task = None
        if self._final_sent:
            return
        text = await self._run_whisper(bytes(self._pcm))
        self._final_sent = True
        try:
            self._results_q.put_nowait((text, True))
        except asyncio.QueueFull:
            # 队列满（极端积压）也强制入队，定稿不能丢
            await self._results_q.put((text, True))

    # -- 结果下行 --

    async def results(self):
        """产出 (text, is_final)。is_final=True 后流结束。"""
        while True:
            item = await self._results_q.get()
            if item[0] == "error":
                raise RuntimeError(str(item[1]))
            yield item[0], item[1]
            if item[1]:  # is_final
                return

    async def close(self):
        self._closed = True
        if self._partial_task is not None:
            self._partial_task.cancel()
            try:
                await self._partial_task
            except (asyncio.CancelledError, Exception):
                pass
        self._partial_task = None


# 兼容 relay 内 `from asr_client import StreamingASR` 的别名
StreamingASR = LocalWhisperASR
