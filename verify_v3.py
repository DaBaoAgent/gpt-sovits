# -*- coding: utf-8 -*-
"""验证所有v3权重文件完整性"""
import torch

files = [
    r"D:\GPT-SoVITS\GPT_SoVITS\pretrained_models\s1v3.ckpt",
    r"D:\GPT-SoVITS\GPT_SoVITS\pretrained_models\s2Gv3.pth",
]
out = []
for f in files:
    try:
        sd = torch.load(f, map_location="cpu", weights_only=False)
        if isinstance(sd, dict):
            keys = list(sd.keys())[:6]
            out.append(f"OK {f.split(chr(92))[-1]}: dict, {len(sd)} keys, 示例 {keys}")
        else:
            out.append(f"OK {f.split(chr(92))[-1]}: {type(sd)}")
    except Exception as e:
        out.append(f"FAIL {f.split(chr(92))[-1]}: {str(e)[:150]}")

# 验证bigvgan
import os, json
bv_dir = r"D:\GPT-SoVITS\GPT_SoVITS\pretrained_models\models--nvidia--bigvgan_v2_24khz_100band_256x"
for fn in ["bigvgan_generator.pt", "config.json"]:
    p = os.path.join(bv_dir, fn)
    if os.path.exists(p):
        out.append(f"存在 {fn}: {os.path.getsize(p)} 字节")
    else:
        out.append(f"缺失 {fn}")

try:
    g = torch.load(os.path.join(bv_dir, "bigvgan_generator.pt"), map_location="cpu", weights_only=False)
    out.append(f"bigvgan 可加载: {type(g)}")
    if isinstance(g, dict):
        out.append(f"  keys: {list(g.keys())[:6]}")
except Exception as e:
    out.append(f"bigvgan 加载失败: {str(e)[:150]}")

with open(r"D:\GPT-SoVITS\verify_all.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("\n".join(out))
