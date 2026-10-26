# -*- coding: utf-8 -*-
"""s2Gv3.pth 健壮续传下载：断点续传 + 自动重试直到完整"""
import requests
import os
import time

url = "https://huggingface.co/lj1995/GPT-SoVITS/resolve/main/s2Gv3.pth"
out_path = r"D:\GPT-SoVITS\GPT_SoVITS\pretrained_models\s2Gv3.pth"
proxies = {"http": "http://127.0.0.1:15715", "https": "http://127.0.0.1:15715"}
TOTAL = 769035145  # 官方大小

max_attempts = 50
for attempt in range(1, max_attempts + 1):
    existing = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    if existing >= TOTAL:
        print(f"下载完成! 大小 {existing} 字节")
        break
    headers = {"Range": f"bytes={existing}-"} if existing > 0 else {}
    print(f"[尝试 {attempt}/{max_attempts}] 从 {existing/1024/1024:.1f}MB 续传...")
    try:
        r = requests.get(url, proxies=proxies, headers=headers, stream=True, timeout=60)
        if r.status_code not in (200, 206):
            print(f"HTTP {r.status_code}, 5秒后重试")
            time.sleep(5)
            continue
        mode = "ab" if existing > 0 else "wb"
        total = existing
        with open(out_path, mode) as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)
        if total >= TOTAL:
            print(f"下载完成! 大小 {total} 字节")
            break
    except Exception as e:
        print(f"  断连: {str(e)[:80]}, 3秒后重试")
        time.sleep(3)
else:
    print("达到最大尝试次数")
