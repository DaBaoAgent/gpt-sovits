# -*- coding: utf-8 -*-
"""为 dabao-zhugeliang 预设追加古文/多音字读音修正"""
import json

p = r"D:\GPT-SoVITS\voices\dabao-zhugeliang\preset.json"
d = json.load(open(p, encoding="utf-8"))

zhuge_fixes = [
    # 古文关键句（长句优先，避免被短词先替换）
    ["竭股肱之力", "节古功之力"],
    ["鞠躬尽瘁", "鞠躬尽脆"],
    ["嗣子可辅", "四子可辅"],
    ["还于旧都", "环于旧都"],
    ["食少事烦", "石少事烦"],
    ["而知之", "而知知"],   # 保护"知"（zhī 无歧义，实际是占位防误判，可省略）
    # 专名/多音字
    ["刘禅", "刘善"],
    ["曹丕", "曹披"],
    ["马谡", "马素"],
    ["司马懿", "司马意"],
    ["费祎", "费一"],
    ["蒋琬", "蒋碗"],
    ["琅琊", "郎牙"],
    ["渭水", "卫水"],
    ["阳都", "阳督"],
    ["刘琮", "刘丛"],
    ["祁山", "奇山"],
    ["陇右", "垄右"],
    ["陆逊", "陆迅"],
    ["夷陵", "宜陵"],
    ["股肱", "古功"],
    ["嗣子", "四子"],
    ["兴复", "星复"],
    ["华夏", "滑夏"],
]

# 追加（去重）
existing = [f[0] for f in d["speak_fixes"]["global"]]
added = 0
for fix in zhuge_fixes:
    if fix[0] not in existing:
        d["speak_fixes"]["global"].append(fix)
        existing.append(fix[0])
        added += 1

json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"新增 {added} 条古文读音修正，总计 {len(d['speak_fixes']['global'])} 条")
# 打印本次新增
for fix in zhuge_fixes:
    if fix[0] in existing:
        pass
for fix in d["speak_fixes"]["global"][-10:]:
    print("  ", fix)
