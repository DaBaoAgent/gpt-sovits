# -*- coding: utf-8 -*-
"""s2Gv3.pth 断点续传下载，走系统代理"""
import requests
import os

url = "https://huggingface.co/lj1995/GPT-SoVITS/resolve/main/s2Gv3.pth"
out_path = r"D:\GPT-SoVITS\GPT_SoVITS\pretrained_models\s2Gv3.pth"
proxies = {"http": "http://127.0.0.1:15715", "https": "http://127.0.0.1:15715"}

existing = os.path.getsize(out_path) if os.path.exists(out_path) else 0
print(f"已有: {existing/1024/1024:.1f} MB, 开始续传...")

headers = {"Range": f"bytes={existing}-"} if existing > 0 else {}
r = requests.get(url, proxies=proxies, headers=headers, stream=True, timeout=60)
print("HTTP:", r.status_code, r.headers.get("Content-Length", "?") )

total = existing
mode = "ab" if existing > 0 else "wb"
with open(out_path, mode) as f:
    for chunk in r.iter_content(chunk_size=1024 * 1024):
        if chunk:
            f.write(chunk)
            total += len(chunk)
            print(f"\r{total/1024/1024:.1f} MB", end="", flush=True)
print("\n下载完成")
