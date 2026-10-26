# -*- coding: utf-8 -*-
"""
诸葛亮开头钩子配音 - 流畅自然版
策略：
1. 文本按语义断句（句号/问号/叹号断开，逗号保持句内连读）
2. 逐句顺序合成（不开并行，保证语气连贯）
3. 采样参数调优（temperature=0.8 增加语气起伏，top_p=0.9）
4. PyAV 拼接，句间加自然停顿
"""
import requests
import re
import os
import json
import time
import numpy as np

URL = "http://127.0.0.1:9880/tts"
REF_AUDIO = "zhuge_ref.mp3"
PROMPT_TEXT = "东汉末年朝纲混乱，内有董卓巨奸权倾朝野专横跋扈，外有黄巾军起义撼动社稷。"
OUT_DIR = r"D:\GPT-SoVITS\segments_zhuge"
FINAL_OUT = r"D:\@kaifa\lishi\诸葛亮开头钩子配音_自然版.wav"

TEXT = """建兴十二年，秋，五丈原。风从渭水那边吹过来，带着对岸魏军大营里的炊烟味。营帐的帘子被掀起一角，又落下，帐里的烛火晃了晃，映着案上那一堆摊开的军报。我咳了一声，用帕子捂住嘴，帕子上多了一点红。我知道，这一天终于还是来了。外面姜维他们还在叫着要再战，魏延那张大嗓门隔着帐布都能听见。但我听得见的，不是他们的声音。我听得见秋风刮过渭水南岸的枯草，一片一片，像是什么东西在一点点碎掉。对面的营垒里，司马懿还在缩着。他缩了三年了。而我，已经站不动了。如果你想知道，那个被叫做卧龙的人，是怎样一步步走到这片五丈原的秋风里的，那我们就得从头讲起。"""

def split_sentences(text):
    """按句号/问号/叹号/省略号切句，保留标点；逗号不断句（保持自然连读）"""
    # 先按终句标点切分
    parts = re.split(r'(?<=[。！？…])', text)
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences

def synthesize(text, idx, out_path):
    payload = {
        "text": text,
        "text_lang": "zh",
        "ref_audio_path": REF_AUDIO,
        "prompt_text": PROMPT_TEXT,
        "prompt_lang": "zh",
        "text_split_method": "cut1",     # 单句无需再切
        "batch_size": 1,
        "media_type": "wav",
        "streaming_mode": False,
        "speed_factor": 1.0,
        "top_k": 20,
        "top_p": 0.9,
        "temperature": 0.8,
        "repetition_penalty": 1.25,
        "parallel_infer": False,          # 顺序推理
        "sample_steps": 32,
        "seed": -1,
    }
    for attempt in range(3):
        try:
            r = requests.post(URL, json=payload, timeout=300)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(out_path, "wb") as f:
                    f.write(r.content)
                return True
            else:
                print(f"  句{idx} 失败 status={r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"  句{idx} 异常: {e}")
        time.sleep(2)
    return False

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    sentences = split_sentences(TEXT)
    print(f"共 {len(sentences)} 句，开始逐句合成...")

    # 合并过短片段（<8字的碎句并入前一句，避免音调断裂）
    merged = []
    for s in sentences:
        if len(s) < 8 and merged:
            merged[-1] = merged[-1] + s
        else:
            merged.append(s)
    print("合并后:", len(merged), "句")
    for i, s in enumerate(merged):
        print(f"  句{i+1}: {s[:30]}...")

    wav_files = []
    for i, s in enumerate(merged):
        out_path = os.path.join(OUT_DIR, f"seg_{i:03d}.wav")
        if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
            print(f"句{i+1} 已存在，跳过: {s[:25]}...")
            wav_files.append(out_path)
            continue
        print(f"合成 {i+1}/{len(merged)}: {s[:25]}...")
        ok = synthesize(s, i + 1, out_path)
        if ok:
            wav_files.append(out_path)
            print(f"  -> OK")
        else:
            print(f"  -> FAILED")
            # 失败时用单字重试（更短文本更容易成功）
            sub = s[:20]
            retry_path = os.path.join(OUT_DIR, f"seg_{i:03d}_r.wav")
            if synthesize(sub, i + 1, retry_path):
                wav_files.append(retry_path)

    if not wav_files:
        print("全部失败")
        return

    # 用 PyAV 读帧 + numpy 拼接 + wave 写文件（绕开 PyAV 编码器重采样问题）
    import av
    import wave
    print("拼接中...")
    all_pcm = b""
    target_rate = None
    for wf in wav_files:
        container = av.open(wf)
        stream = container.streams.audio[0]
        if stream.codec_context.sample_rate:
            target_rate = stream.codec_context.sample_rate
        resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)
        frames = []
        for frame in container.decode(stream):
            for out_f in resampler.resample(frame):
                frames.append(out_f.to_ndarray())
        for out_f in resampler.resample(None):
            frames.append(out_f.to_ndarray())
        container.close()
        if frames:
            # 按帧顺序拼接为字节
            for arr in frames:
                if arr.shape[0] != 1:
                    arr = arr.mean(axis=0, keepdims=True).astype(np.int16)
                all_pcm += arr.astype(np.int16).tobytes()

    if not all_pcm:
        print("无有效音频段")
        return
    if target_rate is None:
        target_rate = 24000
    print(f"目标采样率: {target_rate}, 总时长约 {len(all_pcm)/2/target_rate:.1f} 秒")

    # 句间静音（在每段之间插入 0.45s）
    silence_seconds = 0.45
    silence_bytes = int(target_rate * silence_seconds) * 2  # s16 = 2字节
    silence = b"\x00" * silence_bytes

    # 重新按段拼接（带静音间隔）
    segments_bytes = []
    for wf in wav_files:
        container = av.open(wf)
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)
        seg = b""
        for frame in container.decode(stream):
            for out_f in resampler.resample(frame):
                arr = out_f.to_ndarray()
                if arr.shape[0] != 1:
                    arr = arr.mean(axis=0, keepdims=True).astype(np.int16)
                seg += arr.astype(np.int16).tobytes()
        for out_f in resampler.resample(None):
            arr = out_f.to_ndarray()
            if arr.shape[0] != 1:
                arr = arr.mean(axis=0, keepdims=True).astype(np.int16)
            seg += arr.astype(np.int16).tobytes()
        container.close()
        if seg:
            segments_bytes.append(seg)

    final_pcm = silence.join(segments_bytes)

    with wave.open(FINAL_OUT, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(target_rate)
        w.writeframes(final_pcm)

    size = os.path.getsize(FINAL_OUT)
    print(f"\n完成! 输出: {FINAL_OUT}")
    print(f"大小: {round(size/1024/1024, 2)} MB, 共 {len(segments_bytes)} 段拼接")

if __name__ == "__main__":
    main()
