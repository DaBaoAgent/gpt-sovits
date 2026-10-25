# -*- coding: utf-8 -*-
"""本地 OpenAI 形状 TTS 服务：把 GPT-SoVITS v3 包成 POST /v1/audio/speech。

- 音色参数**定死**为一轮轮试听收敛出来的「26E」组合（见下 LOCKED）。
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

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "GPT_SoVITS"))
os.environ.setdefault("G2PW", "0")

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

# ---------------------------------------------------------------- 锁定参数
# 宝哥 2026-10-07 拍板：26E = 参考 ref_dabao3-1.wav / 温 0.8 / top_k 15 /
# seed 666 / 语速 1.0 / 重复惩罚 1.35。改这里 = 改全片音色，勿轻动。
REF = "ref_dabao3-1.wav"
PROMPT = ("希特勒在巴法利亚阿尔卑斯山的乡间别墅策划了他最大胆的行动，准备迎接最大挑战。"
          "罗马尼亚、保加利亚和匈牙利是德国的坚定盟友。")
LOCKED = {
    "speed_factor": 1.00,
    "repetition_penalty": 1.35,
    "top_k": 15,
    "top_p": 0.95,
    "temperature": 0.80,
    "seed": 666,
}
# 切句方式（宝哥 2026-10-07 二次定版）：cut1=凑四句一切（现默认）。
# ⚠ cut0=整段不切曾为默认，但对长文本（>110 字）会把末句合成成**不可识别音频**——
#   实测 46 幕里有 6 幕（7/10/15/20/36/42）末句/中间句被判「听不出」，字幕对时全挂；
#   单独合成同一末句却清晰。故改为 cut1：切段更短，末句正常，听感与 cut0 几乎一样
#   （第32幕停顿 13 vs 11）。cut2=凑50字一切；cut3=按句号切；cut5=按每个标点切（旧旧默认，
#   听感「一段一段」，宝哥嫌碎）。
# 可用环境变量 TTS_SPLIT 或请求体 text_split_method 覆盖。
DEFAULT_SPLIT = os.environ.get("TTS_SPLIT", "cut1")

FFMPEG = os.path.join(ROOT, "runtime", "ffmpeg.exe")
LOG = os.path.join(ROOT, "tts_server.log")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW

PM = "GPT_SoVITS/pretrained_models"
CFG = {"custom": {
    "device": "cpu", "is_half": False, "version": "v3",
    "t2s_weights_path": f"{PM}/s1v3.ckpt",
    "vits_weights_path": f"{PM}/s2Gv3.pth",
    "cnhuhbert_base_path": f"{PM}/chinese-hubert-base",
    "bert_base_path": f"{PM}/chinese-roberta-wwm-ext-large",
}}


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def to_mp3(pcm, sr):
    """int16 numpy -> MP3 bytes（走 ffmpeg 管道，不落临时文件）。"""
    raw = np.ascontiguousarray(pcm.astype(np.int16)).tobytes()
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error",
           "-f", "s16le", "-ar", str(int(sr)), "-ac", "1", "-i", "pipe:0",
           "-codec:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "pipe:1"]
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


def synth(text, speed=None, split=None):
    tts = get_tts()
    req = {
        "text": text, "text_lang": "zh",
        "ref_audio_path": os.path.join(ROOT, REF), "prompt_text": PROMPT, "prompt_lang": "zh",
        "text_split_method": split or DEFAULT_SPLIT, "batch_size": 1,
        "media_type": "wav", "streaming_mode": False,
        "parallel_infer": False, "use_cuda_graph": False, "split_bucket": False,
        **LOCKED,
    }
    if speed:
        req["speed_factor"] = float(speed)
    sr, pcm = None, None
    with _lock:
        for item in tts.run(req):
            if isinstance(item, tuple) and len(item) == 2:
                sr, pcm = item
                break
    if pcm is None:
        raise RuntimeError("TTS 没有返回音频")
    return sr, pcm


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
            self._json(200, {"ok": True, "voice": "gpt-sovits-26E", "locked": LOCKED,
                             "split": DEFAULT_SPLIT})
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

        t0 = time.time()
        try:
            sr, pcm = synth(text, speed, split)
            mp3 = to_mp3(pcm, sr)
        except Exception as e:
            log("合成失败: %s\n%s" % (e, traceback.format_exc()))
            self._json(500, {"error": str(e)})
            return
        log("合成 %d 字 -> %.1fs / %.1fs 用时 %.1fs" % (
            len(text), len(pcm) / float(sr), time.time() - t0, time.time() - t0))
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(mp3)))
        self.end_headers()
        self.wfile.write(mp3)


def warmup():
    """丢弃式预热：GPT-SoVITS 在本进程的**第 1 次**合成与之后的结果不同
    （实测同一个 seed：第 1 次 20.80s，第 2 次起稳定 19.36s）。
    宝哥拍板的 26E 是稳态那一版 → 必须先跑一次丢掉的合成，让真实请求落在稳态。"""
    text = "预热。"
    try:
        sr, pcm = synth(text)
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
