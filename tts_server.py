# -*- coding: utf-8 -*-
"""本地 OpenAI 形状 TTS 服务：把 GPT-SoVITS 的 dabao 音色包成 POST /v1/audio/speech。

- 音色、采样参数与发音纠错统一从 voices/dabao/preset.json 读取。
- 底模版本与权重路径从 preset 指定的 tts_infer.yaml 的 custom 块读取。
- 只加载一次模型，进程内循环服务（CPU 稳态约 1x 实时）。
- 用 pythonw.exe 启动 → 不弹命令行窗口。
- 输出 MP3（编解码交给自带 runtime/ffmpeg.exe，CREATE_NO_WINDOW 不闪窗）。
"""
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "GPT_SoVITS"))
os.environ.setdefault("G2PW", "0")

_preset = os.environ.get("TTS_PRESET") or os.path.join("voices", "dabao", "preset.json")
PRESET_PATH = _preset if os.path.isabs(_preset) else os.path.join(ROOT, _preset)
with open(PRESET_PATH, encoding="utf-8") as f:
    PRESET = json.load(f)

VOICE = PRESET["voice"]
SYNTH = PRESET["synthesis"]
POST = PRESET.get("postprocess", {})
SPEAK_FIXES = PRESET.get("speak_fixes", {})
GLOBAL_FIXES = list(SPEAK_FIXES.get("global", []))
ACT_FIXES = SPEAK_FIXES.get("acts", {})

_ref = VOICE["ref_audio_path"]
REF = _ref if os.path.isabs(_ref) else os.path.join(ROOT, _ref)
PROMPT = (VOICE.get("prompt_text") or "").strip()
VOICE_NAME = VOICE.get("id", "dabao")
MODEL = SYNTH.get("model", "gpt-sovits-v5turbo")

if not os.path.isfile(REF):
    raise SystemExit("缺少参考音频：" + REF)
if os.path.getsize(REF) < 100000:
    raise SystemExit("参考音频不是有效文件（可能未拉取 Git LFS）：" + REF)
if not PROMPT:
    raise SystemExit("preset.json 缺少 voice.prompt_text")

# 这些参数锁死在 preset.json，改这里无效；改音色请改 preset。
LOCK_KEYS = (
    "speed_factor", "repetition_penalty", "top_k", "top_p",
    "temperature", "seed", "fragment_interval", "batch_size",
)
LOCKED = {k: SYNTH[k] for k in LOCK_KEYS if k in SYNTH}
DEFAULT_SPLIT = os.environ.get("TTS_SPLIT") or SYNTH.get("text_split_method", "cut1")

_ff = PRESET.get("ffmpeg", "runtime/ffmpeg.exe")
FFMPEG = _ff if os.path.isabs(_ff) else os.path.join(ROOT, _ff)
if not os.path.isfile(FFMPEG) or os.path.getsize(FFMPEG) < 100000:
    FFMPEG = "ffmpeg"
MP3_BITRATE = POST.get("mp3_bitrate", "192k")
LOG = os.path.join(ROOT, "tts_server.log")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
import torchaudio  # noqa: E402

if not hasattr(torchaudio, "_sf_load_patched"):
    def _sf_load(path, *args, **kwargs):
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(np.ascontiguousarray(data.T)), sr
    torchaudio.load = _sf_load
    torchaudio._sf_load_patched = True

from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config  # noqa: E402

# GPT-SoVITS 载入权重时会把内置的全版本默认配置回写 tts_infer.yaml。
# 底模版本与权重统一由该文件的 custom 块决定，这里禁用回写，避免运行期改写配置。
TTS_Config.save_configs = lambda self, configs_path=None: None

_infer = PRESET.get("server", {}).get("infer_config", "GPT_SoVITS/configs/tts_infer.yaml")
CONFIG_PATH = _infer if os.path.isabs(_infer) else os.path.join(ROOT, _infer)
with open(CONFIG_PATH, encoding="utf-8") as f:
    CUSTOM_CFG = (yaml.safe_load(f) or {}).get("custom") or {}
if not CUSTOM_CFG.get("version") or not CUSTOM_CFG.get("vits_weights_path"):
    raise SystemExit("tts_infer.yaml 的 custom 块缺少 version / vits_weights_path：" + CONFIG_PATH)
CFG = {"custom": CUSTOM_CFG}
VERSION = CUSTOM_CFG["version"]

for _key in ("t2s_weights_path", "vits_weights_path"):
    _p = CUSTOM_CFG.get(_key, "")
    _p = _p if os.path.isabs(_p) else os.path.join(ROOT, _p)
    if not os.path.isfile(_p) or os.path.getsize(_p) < 100000:
        raise SystemExit("权重缺失或不完整（可能未拉取 Git LFS）：" + _p)
if VERSION in ("v5dev", "v5turbo"):
    _voc = os.path.join(ROOT, "GPT_SoVITS", "pretrained_models",
                        "gsv-v5-pretrained", "vocoder.pth")
    if not os.path.isfile(_voc) or os.path.getsize(_voc) < 100000:
        raise SystemExit("V5 声码器缺失或不完整（可能未拉取 Git LFS）：" + _voc)


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def apply_speak_fixes(text, fixes):
    for old, new in sorted(fixes, key=lambda p: len(p[0]), reverse=True):
        text = text.replace(old, new)
    return text


def to_mp3(pcm, sr):
    """int16 numpy -> MP3 bytes（走 ffmpeg 管道，不落临时文件）。"""
    raw = np.ascontiguousarray(pcm.astype(np.int16)).tobytes()
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error",
           "-f", "s16le", "-ar", str(int(sr)), "-ac", "1", "-i", "pipe:0",
           "-codec:a", "libmp3lame", "-b:a", MP3_BITRATE, "-f", "mp3", "pipe:1"]
    p = subprocess.run(cmd, input=raw, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg 失败: " + p.stderr.decode("utf-8", "replace"))
    return p.stdout


_tts = None
_lock = threading.Lock()  # 模型非线程安全，串行推理


def get_tts():
    global _tts
    if _tts is None:
        t0 = time.time()
        _tts = TTS(TTS_Config(CFG))
        log("模型载入完成 %.1fs" % (time.time() - t0))
    return _tts


def synth(text, speed=None, split=None, act=None, seed=None):
    fixes = list(GLOBAL_FIXES)
    if act is not None:
        fixes.extend(ACT_FIXES.get(str(act), []))
    spoken = apply_speak_fixes(text, fixes) if fixes else text

    tts = get_tts()
    req = {
        "text": spoken,
        "text_lang": VOICE.get("text_lang", "zh"),
        "ref_audio_path": REF,
        "prompt_text": PROMPT,
        "prompt_lang": VOICE.get("prompt_lang", "zh"),
        "text_split_method": split or DEFAULT_SPLIT,
        "media_type": "wav", "streaming_mode": False,
        "parallel_infer": False, "use_cuda_graph": False, "split_bucket": False,
        **LOCKED,
    }
    if speed:
        req["speed_factor"] = float(speed)
    if seed is not None:
        req["seed"] = int(seed)
    sr, pcm = None, None
    with _lock:
        for item in tts.run(req):
            if isinstance(item, tuple) and len(item) == 2:
                sr, pcm = item
                break
    if pcm is None:
        raise RuntimeError("TTS 没有返回音频")
    return sr, pcm, spoken


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log("HTTP " + (fmt % args))

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/health", "/healthz"):
            self._json(200, {
                "ok": True,
                "voice": VOICE_NAME,
                "model": MODEL,
                "version": VERSION,
                "weights": CUSTOM_CFG["vits_weights_path"],
                "ref": os.path.relpath(REF, ROOT),
                "params": LOCKED,
                "split": DEFAULT_SPLIT,
                "fixes_global": len(GLOBAL_FIXES),
                "fixes_acts": sorted(ACT_FIXES),
                "mp3_bitrate": MP3_BITRATE,
            })
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path not in ("/v1/audio/speech", "/tts"):
            self._json(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception as e:
            self._json(400, {"error": "bad json: %s" % e})
            return

        text = (body.get("input") or body.get("text") or "").strip()
        if not text:
            self._json(400, {"error": "empty input"})
            return
        speed = body.get("speed") or body.get("speed_factor")
        split = body.get("text_split_method")
        act = body.get("act")
        seed = body.get("seed")

        t0 = time.time()
        try:
            sr, pcm, spoken = synth(text, speed, split, act, seed)
            mp3 = to_mp3(pcm, sr)
        except Exception as e:
            log("合成失败: %s\n%s" % (e, traceback.format_exc()))
            self._json(500, {"error": str(e)})
            return
        log("合成 %d 字 -> %.1fs / %.1fs 用时 %.1fs | act=%s" % (
            len(text), len(pcm) / float(sr), time.time() - t0, time.time() - t0, act))
        if spoken != text:
            log("朗读文本: " + spoken)
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(mp3)))
        self.end_headers()
        self.wfile.write(mp3)


def warmup():
    """丢弃式预热：GPT-SoVITS 在本进程的第 1 次合成与之后的结果不同，
    先跑一次丢掉的合成，让真实请求落在稳态。"""
    text = "预热。"
    try:
        sr, pcm, _ = synth(text)
        log("预热完成 %.2fs（丢弃）" % (len(pcm) / float(sr)))
    except Exception as e:
        log("预热失败: %s" % e)


def main():
    port = 9880
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    log("=== 启动 tts_server 端口 %d (PID %d) ===" % (port, os.getpid()))
    get_tts()  # 载入模型，避免首个请求等冷启动
    warmup()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    log("就绪 http://127.0.0.1:%d/v1/audio/speech" % port)
    srv.serve_forever()


if __name__ == "__main__":
    main()
