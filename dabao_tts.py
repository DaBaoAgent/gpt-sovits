"""dabao 配音：本机 GPT-SoVITS v5turbo 零样本克隆（tushuo 26E 参考音色）。

参数来源：DaBaoAgent/tushuo 的 tools/narrate.py 与 tools/production-defaults.json；音色与参数定稿为 dabao 预设（2026-10-20）。
原项目走 OpenAI 兼容的本地 tts_server；这里改用 D:\\GPT-SoVITS 原生 api_v2 的
POST /tts（ref_audio_path + prompt_text），其余流程保持一致：

- 按句切成 <= 78 字的段，cut1 切分，speed 1.0
- 每段时长校验：超过 6.2 字/秒视为尾句截断，丢弃重配（最多 3 次）
- 44.1 kHz 单声道；句间静音 > 150 ms 压到 100 ms；-40 dB 静音门限
- -33 dB 轻噪声门，门限以下保留 0.3 增益；段间补 20 ms
- 输出 mp3 192 kbps，并写同名 .json 记录分段与时长
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


def server_ready(session: requests.Session, base_url: str) -> bool:
    for path in ("/docs", "/tts"):
        try:
            response = session.get(base_url + path, timeout=2)
        except requests.RequestException:
            continue
        if response.status_code in (200, 405, 422):
            return True
    return False


def ensure_server(cfg: dict, base_url: str, env: dict) -> subprocess.Popen | None:
    session = env["session"]
    if server_ready(session, base_url):
        return None

    server = cfg["server"]
    root = Path(server["root"])
    python = Path(server["python"])
    api = Path(server["api_script"])
    if not python.exists() or not api.exists():
        raise SystemExit(f"GPT-SoVITS 目录不完整：{root}（需要 {python} 与 {api}）")

    log_path = ROOT / "logs" / "dabao_tts_server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(python), str(api), "-a", server["host"], "-p", str(server["port"])]
    infer_cfg = server.get("infer_config")
    if infer_cfg:
        cmd += ["-c", str(infer_cfg)]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log = open(log_path, "ab")
    process = subprocess.Popen(
        cmd, cwd=str(root), creationflags=creationflags,
        stdout=log, stderr=log,
    )
    env["log"] = log
    print(f"启动 GPT-SoVITS 服务（首次加载约 1 分钟，日志 {log_path}）", flush=True)
    deadline = time.time() + int(server.get("start_timeout_seconds", 180))
    while time.time() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"GPT-SoVITS 服务提前退出，状态码 {process.returncode}；见 {log_path}")
        if server_ready(session, base_url):
            return process
        time.sleep(2)
    process.terminate()
    raise SystemExit(f"GPT-SoVITS 在 {server.get('start_timeout_seconds', 180)} 秒内未就绪；见 {log_path}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="dabao 配音（本机 GPT-SoVITS v5turbo 零样本，参数已定稿）")
    parser.add_argument("--text", "-t", help="直接给口播文本")
    parser.add_argument("--text-file", "-f", type=Path, help="口播稿文件（UTF-8）")
    parser.add_argument("--out", "-o", type=Path, default=ROOT / "narration.mp3",
                        help="输出音频，按扩展名出 mp3 或 wav")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--port", type=int, help="覆盖配置里的服务端口")
    parser.add_argument("--force", action="store_true", help="忽略缓存重新合成")
    parser.add_argument("--act", type=int, help="按幕号套用配置里的 acts 读音修正")
    parser.add_argument("--temperature", type=float, help="覆盖采样温度")
    parser.add_argument("--top-p", type=float, help="覆盖 top_p")
    parser.add_argument("--top-k", type=int, help="覆盖 top_k")
    parser.add_argument("--speed", type=float, help="覆盖语速")
    parser.add_argument("--seed", type=int, help="固定随机种子")
    parser.add_argument("--ref-audio", type=Path, help="临时换参考音频（逐字稿仍用配置/sidecar）")
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
    if args.ref_audio:
        cfg["voice"]["ref_audio_path"] = str(args.ref_audio.resolve())
    if args.temperature is not None:
        cfg["synthesis"]["temperature"] = args.temperature
    if args.top_p is not None:
        cfg["synthesis"]["top_p"] = args.top_p
    if args.top_k is not None:
        cfg["synthesis"]["top_k"] = args.top_k
    if args.speed is not None:
        cfg["synthesis"]["speed_factor"] = args.speed
    if args.seed is not None:
        cfg["synthesis"]["seed"] = args.seed
    if args.keep_gap_ms is not None:
        cfg["postprocess"]["keep_gap_ms"] = args.keep_gap_ms
    if args.min_gap_ms is not None:
        cfg["postprocess"]["min_gap_ms"] = args.min_gap_ms

    voice = cfg["voice"]
    synth = cfg["synthesis"]
    post = cfg["postprocess"]
    if not 0 < post["keep_gap_ms"] < post["min_gap_ms"]:
        raise SystemExit("keep_gap_ms 必须大于 0 且小于 min_gap_ms")
    sr = int(post["sample_rate"])
    text_lang = voice["text_lang"]
    prompt_lang = voice["prompt_lang"]
    ref_path = Path(voice["ref_audio_path"])
    prompt_text = (voice.get("prompt_text") or "").strip()
    if args.ref_audio:
        sidecar = ref_path.with_suffix(".txt")
        if sidecar.exists():
            prompt_text = sidecar.read_text(encoding="utf-8-sig").strip()
        else:
            print("警告：--ref-audio 没有同名 .txt，仍使用 preset.prompt_text；请确认逐字一致。")
    if not prompt_text:
        sidecar = ref_path.with_suffix(".txt")
        if sidecar.exists():
            prompt_text = sidecar.read_text(encoding="utf-8-sig").strip()
    if not ref_path.exists():
        raise SystemExit(
            f"缺少 dabao 参考音频：{ref_path}\n"
            "检查 D:/GPT-SoVITS/voices/dabao/preset.json 的 voice.ref_audio_path。"
        )
    if not prompt_text:
        raise SystemExit(
            f"缺少参考音频逐字文本：在配置里填 voice.prompt_text，"
            f"或在 {ref_path.with_suffix('.txt')} 写一份与参考音频逐字一致的中文文本。"
        )

    ffmpeg = cfg.get("ffmpeg", "ffmpeg")
    ffprobe = cfg.get("ffprobe", "ffprobe")
    speak_fixes = cfg.get("speak_fixes") or {}
    fixes = list(speak_fixes.get("global", []))
    if args.act is not None:
        fixes.extend(speak_fixes.get("acts", {}).get(str(args.act), []))

    voice_fp = {
        "ref": str(ref_path), "ref_mtime": ref_path.stat().st_mtime,
        "prompt": prompt_text, "sampling": synth, "voice": voice, "post": post,
        "fixes": fixes,
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
    env = {"session": session}
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
                        "text_lang": text_lang,
                        "ref_audio_path": str(ref_path.resolve()),
                        "prompt_text": prompt_text,
                        "prompt_lang": prompt_lang,
                        "top_k": synth["top_k"],
                        "top_p": synth["top_p"],
                        "temperature": synth["temperature"],
                        "text_split_method": synth["text_split_method"],
                        "batch_size": synth["batch_size"],
                        "speed_factor": synth["speed_factor"],
                        "fragment_interval": synth["fragment_interval"],
                        "seed": synth["seed"],
                        "repetition_penalty": synth.get("repetition_penalty", 1.35),
                        "media_type": "wav",
                        "streaming_mode": False,
                    }
                    response = session.post(base_url + "/tts", json=payload, timeout=(10, 1800))
                    response.raise_for_status()
                    if len(response.content) < 1000 or response.content[:4] != b"RIFF":
                        raise RuntimeError(f"第 {index} 段未返回有效 WAV：{response.headers.get('Content-Type')}")
                    tmp = part.with_suffix(".tmp.wav")
                    tmp.write_bytes(response.content)
                    seconds = probe_seconds(tmp, ffprobe)
                    if seconds > 0 and clean_chars / seconds <= synth["max_chars_per_second"]:
                        tmp.replace(part)
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
        raw = decode(part, ffmpeg, sr)
        tight = tighten(raw, sr, post)
        tight_path = part.with_suffix(".tight.wav")
        write_wav(tight, tight_path, ffmpeg, sr)
        tight_duration = len(tight) / sr
        chunks_meta.append({
            "index": index, "text": original, "spoken": spoken, "file": str(tight_path),
            "start": round(timeline, 4), "duration": round(tight_duration, 4),
            "raw_duration": round(len(raw) / sr, 4), "raw_file": str(part),
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
        "voice_id": voice.get("id", ""),
        "voice": voice.get("label", voice.get("id", "")),
        "model": synth.get("model", "gpt-sovits-v5turbo"),
        "split": synth["text_split_method"],
        "speed": synth["speed_factor"],
        "sampling": {
            "temperature": synth["temperature"],
            "top_p": synth["top_p"],
            "top_k": synth["top_k"],
            "seed": synth["seed"],
            "repetition_penalty": synth.get("repetition_penalty", 1.35),
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
