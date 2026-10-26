# -*- coding: utf-8 -*-
"""dabao 音色审核：4 组采样参数生成对比样音（口播风格短文本）。"""
import json
import time
from pathlib import Path
import requests

URL = "http://127.0.0.1:9880/tts"
REF_AUDIO = r"D:\GPT-SoVITS\voices\dabao\ref_dabao3-1.wav"
PROMPT_TEXT = "希特勒在巴伐利亚、阿尔卑斯山的乡间别墅策划了他最大胆的行动，准备迎接最大挑战。罗马尼亚、保加利亚和匈牙利是德国的坚定盟友。"
OUT_DIR = Path(r"D:\@kaifa\lishi\音色审核")
OUT_DIR.mkdir(parents=True, exist_ok=True)

TEXT = "建兴十二年，秋，五丈原。风从渭水那边吹过来，带着对岸魏军大营里的炊烟味。营帐的帘子被掀起一角，又落下，帐里的烛火晃了晃，映着案上那一堆摊开的军报。"

VARIANTS = [
    {
        "name": "v1_基线_预设参数",
        "temperature": 0.7, "top_p": 0.9, "top_k": 15,
        "speed_factor": 0.95, "seed": 20261020, "repetition_penalty": 1.35,
    },
    {
        "name": "v2_稳定干净",
        "temperature": 0.5, "top_p": 0.75, "top_k": 12,
        "speed_factor": 0.95, "seed": -1, "repetition_penalty": 1.4,
    },
    {
        "name": "v3_流畅起伏",
        "temperature": 0.8, "top_p": 0.9, "top_k": 20,
        "speed_factor": 1.0, "seed": -1, "repetition_penalty": 1.3,
    },
    {
        "name": "v4_沉稳克制",
        "temperature": 0.6, "top_p": 0.8, "top_k": 15,
        "speed_factor": 0.9, "seed": -1, "repetition_penalty": 1.45,
    },
]

session = requests.Session()
session.trust_env = False

for v in VARIANTS:
    payload = {
        "text": TEXT,
        "text_lang": "zh",
        "ref_audio_path": REF_AUDIO,
        "prompt_text": PROMPT_TEXT,
        "prompt_lang": "zh",
        "top_k": v["top_k"],
        "top_p": v["top_p"],
        "temperature": v["temperature"],
        "text_split_method": "cut1",
        "batch_size": 1,
        "speed_factor": v["speed_factor"],
        "fragment_interval": 0.3,
        "seed": v["seed"],
        "repetition_penalty": v["repetition_penalty"],
        "media_type": "wav",
        "streaming_mode": False,
        "parallel_infer": False,
        "sample_steps": 32,
    }
    out = OUT_DIR / f"dabao_{v['name']}.wav"
    ok = False
    for attempt in range(3):
        try:
            r = session.post(URL, json=payload, timeout=300)
            if r.status_code == 200 and len(r.content) > 1000 and r.content[:4] == b"RIFF":
                out.write_bytes(r.content)
                print(f"OK  {v['name']}  {len(r.content)/1024:.0f} KB", flush=True)
                ok = True
                break
            else:
                print(f"FAIL {v['name']} status={r.status_code}: {r.text[:150]}", flush=True)
        except Exception as e:
            print(f"ERR {v['name']} {e}", flush=True)
        time.sleep(2)
    if not ok:
        print(f"SKIP {v['name']} 三次尝试均失败", flush=True)

print("done")
