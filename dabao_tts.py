"""dabao 配音：GPT-SoVITS v5turbo 零样本克隆（tts_server.py HTTP 服务版）。

- 服务端由 tts_server.py 提供（POST /tts，OpenAI 兼容形状）
- 参考音频、采样参数、发音修正全部由服务端从 preset.json 读取
- 客户端只传 text / speed_factor / text_split_method / act
- 响应是 MP3，本脚本用 ffmpeg 解码后做后处理（切段校验、静音压缩、噪声门、拼接）

流程：
- 按句切成 <= max_chunk_chars 字的段，cut1 切分，speed 1.0
- 每段时长校验：超过 max_chars_per_second 字/秒视为尾句截断，丢弃重配（最多 retries 次）
- 44.1 kHz 单声道；句间静音 > min_gap_ms 压到 keep_gap_ms；gate_db 静音门限
- gate_db 轻噪声门，门限以下保留 gate_floor 增益；段间补 gap_ms
- 输出 mp3 192 kbps，并写同名 .json 记录分段与时长

所有相对路径都基于本文件所在目录（引擎根目录）解析，克隆到任何位置都能直接运行。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import numpy as np
import requests


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "voices" / "dabao" / "preset.json"


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"找不到配音配置：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(p: str | os.PathLike) -> Path:
    """相对路径基于 ROOT 解析，绝对路径原样返回。"""
    pp = Path(p)
    return pp if pp.is_absolute() else (ROOT / pp)


def resolve_tool(p: str | os.PathLike, name: str) -> str:
    """配置里的相对路径存在就用它，否则回退到 PATH 上的同名命令。"""
    candidate = resolve_path(p)
    if candidate.exists():
        return str(candidate)
    return name


def apply_speak_fixes(text: str, fixes: list[list[str]]) -> str:
    for pair in sorted(fixes, key=lambda p: len(p[0]), reverse=True):
        text = text.replace(pair[0], pair[1])
    return text


def split_script(script: str, maximum: int) -> list[str]:
    sentences = [s for s in re.split(r"(?<=[。！？])", script) if s.strip()]
    groups: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current + sentence) > maximum:
            groups.append(current)
            current = ""
        current += sentence
    if current:
        groups.append(current)
    return groups


def probe_seconds(path: Path, ffprobe: str) -> float:
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def decode(path: Path, ffmpeg: str, sr: int) -> np.ndarray:
    raw = subprocess.check_output([
        ffmpeg, "-v", "error", "-i", str(path),
        "-ar", str(sr), "-ac", "1", "-f", "f32le", "pipe:1"])
    return np.frombuffer(raw, dtype="<f4").copy()


def write_wav(pcm: np.ndarray, path: Path, ffmpeg: str, sr: int) -> None:
    proc = subprocess.run([
        ffmpeg, "-y", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1",
        "-i", "pipe:0", "-c:a", "pcm_s16le", str(path)],
        input=np.asarray(pcm, dtype="<f4").tobytes(), capture_output=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))


def frame_rms(x: np.ndarray, hop: int) -> np.ndarray:
    n = len(x)
    if n < hop:
        return np.zeros(0, np.float64)
    c = np.concatenate(([0.0], np.cumsum(np.asarray(x, dtype=np.float64) ** 2)))
    starts = np.arange(0, n - hop + 1, hop)
    return np.sqrt(np.maximum((c[starts + hop] - c[starts]) / hop, 1e-12))


def tighten(x: np.ndarray, sr: int, post: dict) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if x.size == 0:
        return x
    hop = sr // 100
    rms = frame_rms(x, hop)
    if rms.size == 0:
        return x
    silent = 20 * np.log10(rms + 1e-12) <= post["silence_db"]
    keep = int(sr * post["keep_gap_ms"] / 1000)
    min_gap = int(sr * post["min_gap_ms"] / 1000)
    fade = int(sr * 0.006)
    out: list[np.ndarray] = []
    cut_from = 0
    i = 0
    n = len(silent)
    while i < n:
        if not silent[i]:
            i += 1
            continue
        j = i
        while j < n and silent[j]:
            j += 1
        start = i * hop
        end = min(len(x), j * hop)
        length = end - start
        out.append(x[cut_from:start])
        half = keep // 2
        if length > min_gap:
            if i == 0:
                out.append(x[end - half:end])
            elif j == n:
                out.append(x[start:start + half])
            else:
                out.append(x[start:start + half])
                out.append(x[end - half:end])
        else:
            out.append(x[start:end])
        cut_from = end
        i = j
    out.append(x[cut_from:])
    y = np.concatenate(out).astype(np.float32)
    if fade > 1 and len(y) > 2 * fade:
        y[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
        y[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return y


def soft_gate(x: np.ndarray, sr: int, post: dict) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if x.size == 0:
        return x
    thr = post["gate_db"]
    ramp = 8.0
    hop = sr // 100
    rms = frame_rms(x, hop)
    if rms.size == 0:
        return x
    db = 20 * np.log10(rms + 1e-12)
    gain = np.clip((db - (thr - ramp)) / ramp, 0.0, 1.0)
    gain = post["gate_floor"] + (1.0 - post["gate_floor"]) * gain
    gain = np.convolve(gain, np.ones(7) / 7, mode="same")
    xs = np.arange(len(gain)) * hop + hop / 2
    gi = np.interp(np.arange(len(x)), xs, gain).astype(np.float32)
    return (x * gi).astype(np.float32)


def server_health(session: requests.Session, base_url: str) -> dict | None:
    try:
        response = session.get(base_url + "/health", timeout=2)
        if response.status_code == 200:
            return response.json()
    except (requests.RequestException, ValueError):
        pass
    return None


def ensure_server(cfg: dict, base_url: str, env: dict) -> subprocess.Popen | None:
    session = env["session"]
    health = server_health(session, base_url)
    if health is not None:
        expect = env.get("voice_id")
        got = health.get("voice")
        if expect and got and got != expect:
            raise SystemExit(
                f"{base_url} 上已有 tts_server 在跑音色 {got}，"
                f"与当前配置 {expect} 不一致；请先停掉该服务再试。"
            )
        return None

    server = cfg["server"]
    root = resolve_path(server["root"])
    python = resolve_path(server["python"])
    api = resolve_path(server["api_script"])
    if not python.exists() or not api.exists():
        raise SystemExit(f"GPT-SoVITS 目录不完整：{root}（需要 {python} 与 {api}）")

    log_path = ROOT / "logs" / "dabao_tts_server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    port = cfg["server"]["port"]
    cmd = [str(python), str(api), str(port)]
    popen_env = os.environ.copy()
    popen_env["PYTHONUTF8"] = "1"
    if env.get("preset"):
        popen_env["TTS_PRESET"] = env["preset"]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log = open(log_path, "ab")
    process = subprocess.Popen(
        cmd, cwd=str(root), env=popen_env,
        creationflags=creationflags,
        stdout=log, stderr=log,
    )
    env["log"] = log
    print(f"启动 GPT-SoVITS tts_server（首次加载约 1 分钟，日志 {log_path}）", flush=True)
    deadline = time.time() + int(server.get("start_timeout_seconds", 180))
    while time.time() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"GPT-SoVITS 服务提前退出，状态码 {process.returncode}；见 {log_path}")
        if server_health(session, base_url) is not None:
            return process
        time.sleep(2)
    process.terminate()
    raise SystemExit(f"GPT-SoVITS 在 {server.get('start_timeout_seconds', 180)} 秒内未就绪；见 {log_path}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="dabao 配音（GPT-SoVITS v5turbo 零样本，参数已定稿）")
    parser.add_argument("--text", "-t", help="直接给口播文本")
    parser.add_argument("--text-file", "-f", type=Path, help="口播稿文件（UTF-8）")
    parser.add_argument("--out", "-o", type=Path, default=ROOT / "narration.mp3",
                        help="输出音频，按扩展名出 mp3 或 wav")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--port", type=int, help="覆盖配置里的服务端口")
    parser.add_argument("--force", action="store_true", help="忽略缓存重新合成")
    parser.add_argument("--act", type=int, help="按幕号套用配置里的 acts 读音修正")
    parser.add_argument("--speed", type=float, help="覆盖语速")
    parser.add_argument("--seed", type=int, help="固定随机种子（服务端默认随机）")
    parser.add_argument("--keep-gap-ms", type=int, help="覆盖保留的句间静音毫秒")
    parser.add_argument("--min-gap-ms", type=int, help="覆盖判定为可压缩静音的毫秒")
    parser.add_argument("--keep-server", action="store_true", help="结束后保留服务进程")
    args = parser.parse_args()

    if not args.text and not args.text_file:
        raise SystemExit("需要 --text 或 --text-file")
    if args.text_file:
        script = re.sub(r"\s*\n\s*", "", args.text_file.read_text(encoding="utf-8-sig")).strip()
        source = str(args.text_file)
    else:
        script = args.text
        source = "<text>"
    if not script:
        raise SystemExit("口播稿为空")

    cfg = load_config(args.config)
    if args.port:
        cfg["server"]["port"] = args.port
    if args.speed is not None:
        cfg["synthesis"]["speed_factor"] = args.speed
    if args.keep_gap_ms is not None:
        cfg["postprocess"]["keep_gap_ms"] = args.keep_gap_ms
    if args.min_gap_ms is not None:
        cfg["postprocess"]["min_gap_ms"] = args.min_gap_ms

    synth = cfg["synthesis"]
    post = cfg["postprocess"]
    if not 0 < post["keep_gap_ms"] < post["min_gap_ms"]:
        raise SystemExit("keep_gap_ms 必须大于 0 且小于 min_gap_ms")
    sr = int(post["sample_rate"])

    ffmpeg = resolve_tool(cfg.get("ffmpeg", "ffmpeg"), "ffmpeg")
    ffprobe = resolve_tool(cfg.get("ffprobe", "ffprobe"), "ffprobe")
    speak_fixes = cfg.get("speak_fixes") or {}
    fixes = list(speak_fixes.get("global", []))
    if args.act is not None:
        fixes.extend(speak_fixes.get("acts", {}).get(str(args.act), []))

    voice_fp = {
        "sampling": synth, "post": post, "fixes": fixes,
    }
    config_hash = hashlib.sha256(
        json.dumps(voice_fp, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:10]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = args.out.with_suffix(".json")
    original_groups = split_script(script, int(synth["max_chunk_chars"]))
    spoken_groups = [apply_speak_fixes(group, fixes) for group in original_groups]
    chunks_dir = args.out.parent / "narration-chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    # 缓存键加一次性盐：--force 时不删旧段，而是本次全部重新合成
    cache_salt = str(time.time_ns()) if args.force else ""
    parts = []
    for index, (original, spoken) in enumerate(zip(original_groups, spoken_groups), 1):
        key = spoken + "|" + config_hash + "|" + cache_salt
        hash8 = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
        parts.append((index, original, spoken, chunks_dir / f"{index:03d}-{hash8}.wav"))

    session = requests.Session()
    session.trust_env = False
    base_url = f"http://{cfg['server']['host']}:{cfg['server']['port']}"
    env = {
        "session": session,
        "preset": str(args.config.resolve()),
        "voice_id": (cfg.get("voice") or {}).get("id"),
    }
    process = None
    missing = [part for _, _, _, part in parts if not part.exists()]
    if missing:
        try:
            process = ensure_server(cfg, base_url, env)
            for index, original, spoken, part in parts:
                if part.exists():
                    continue
                clean_chars = len(re.sub(r"[^\w\u3400-\u9fff]", "", spoken))
                for attempt in range(int(synth["retries"])):
                    payload = {
                        "text": spoken,
                        "speed_factor": synth["speed_factor"],
                        "text_split_method": synth["text_split_method"],
                    }
                    if args.act is not None:
                        payload["act"] = args.act
                    if args.seed is not None:
                        payload["seed"] = args.seed
                    response = session.post(base_url + "/tts", json=payload, timeout=(10, 1800))
                    response.raise_for_status()
                    # tts_server.py 返回 MP3（audio/mpeg），写入临时文件后用 ffmpeg 校验时长
                    if len(response.content) < 1000:
                        raise RuntimeError(f"第 {index} 段返回内容过短：{len(response.content)} bytes")
                    tmp = part.with_suffix(".tmp.mp3")
                    tmp.write_bytes(response.content)
                    seconds = probe_seconds(tmp, ffprobe)
                    if seconds > 0 and clean_chars / seconds <= synth["max_chars_per_second"]:
                        tmp.replace(part.with_suffix(".mp3"))
                        part.write_bytes(b"")
                        break
                    tmp.unlink(missing_ok=True)
                    print(f"第 {index} 段疑似截断（{clean_chars} 字 / {seconds:.2f}s），"
                          f"第 {attempt + 1} 次重配", flush=True)
                    time.sleep(0.8)
                else:
                    raise SystemExit(f"第 {index} 段连续 {synth['retries']} 次截断")
                print(f"合成第 {index} 段 {len(spoken)} 字", flush=True)
        finally:
            if process is not None and not args.keep_server:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            if env.get("log"):
                env["log"].close()
            session.close()

    pieces: list[np.ndarray] = []
    chunks_meta = []
    timeline = 0.0
    gap = np.zeros(int(sr * post["gap_ms"] / 1000), np.float32)
    for index, original, spoken, part in parts:
        # tts_server.py 返回 MP3，实际文件是 .mp3
        mp3_file = part.with_suffix(".mp3")
        raw = decode(mp3_file, ffmpeg, sr)
        tight = tighten(raw, sr, post)
        tight_path = part.with_suffix(".tight.wav")
        write_wav(tight, tight_path, ffmpeg, sr)
        tight_duration = len(tight) / sr
        chunks_meta.append({
            "index": index, "text": original, "spoken": spoken, "file": str(tight_path),
            "start": round(timeline, 4), "duration": round(tight_duration, 4),
            "raw_duration": round(len(raw) / sr, 4), "raw_file": str(mp3_file),
        })
        pieces.append(tight)
        timeline += tight_duration
        if index < len(parts):
            pieces.append(gap)
            timeline += len(gap) / sr
        print(f"第 {index} 段 {len(original)} 字 / 原 {len(raw) / sr:.2f}s → 紧 {tight_duration:.2f}s",
              flush=True)

    pcm_all = soft_gate(np.concatenate(pieces).astype(np.float32), sr, post)
    tmp_out = args.out.with_name(f"{args.out.stem}.tmp{args.out.suffix}")
    codec = ["-c:a", "libmp3lame", "-b:a", post.get("mp3_bitrate", "192k")] \
        if args.out.suffix.lower() == ".mp3" else ["-c:a", "pcm_s16le"]
    encoder = subprocess.run([
        ffmpeg, "-y", "-v", "error",
        "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
        *codec, str(tmp_out)],
        input=pcm_all.astype("<f4").tobytes(), capture_output=True)
    if encoder.returncode:
        raise SystemExit(encoder.stderr.decode("utf-8", errors="replace"))
    tmp_out.replace(args.out)
    duration = probe_seconds(args.out, ffprobe)

    metadata_path.write_text(json.dumps({
        "fingerprint": config_hash,
        "preset": cfg.get("preset", ""),
        "voice_id": cfg.get("voice", {}).get("id", ""),
        "voice": cfg.get("voice", {}).get("label", cfg.get("voice", {}).get("id", "")),
        "model": synth.get("model", "gpt-sovits-v5turbo"),
        "split": synth["text_split_method"],
        "speed": synth["speed_factor"],
        "sampling": {
            "temperature": synth.get("temperature"),
            "top_p": synth.get("top_p"),
            "top_k": synth.get("top_k"),
            "seed": synth.get("seed"),
            "repetition_penalty": synth.get("repetition_penalty", 1.3),
        },
        "duration": duration,
        "speakFixes": fixes,
        "tighten": {k: post[k] for k in (
            "min_gap_ms", "keep_gap_ms", "silence_db", "gate_db", "gate_floor")},
        "script": source,
        "chunks": chunks_meta,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"生成 {args.out}，{duration:.2f} 秒，{len(script)} 字，{len(parts)} 段", flush=True)


if __name__ == "__main__":
    main()
