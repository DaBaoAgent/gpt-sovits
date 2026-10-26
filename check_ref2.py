# -*- coding: utf-8 -*-
import os

p = r"D:\GPT-SoVITS\zhuge_ref.mp3"
print("文件存在:", os.path.exists(p))
print("文件大小:", os.path.getsize(p), "字节")

# 用标准库wave读取WAV，用ffprobe或解析MP3头
# 尝试用GPT-SoVITS自带的PyAV
try:
    import av
    container = av.open(p)
    stream = container.streams.audio[0]
    duration = float(stream.duration * stream.time_base)
    print("PyAV 时长(秒):", round(duration, 2))
    print("PyAV 采样率:", stream.codec_context.sample_rate)
except Exception as e:
    print("PyAV不可用:", e)
