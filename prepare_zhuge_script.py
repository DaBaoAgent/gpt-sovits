# -*- coding: utf-8 -*-
"""把诸葛亮口播稿 md 转成 TTS 用纯文本"""
import re

src = r"D:\@kaifa\lishi\诸葛亮口播稿_20分钟精简版.md"
dst = r"D:\GPT-SoVITS\口播稿_诸葛亮全文.txt"

lines = src_text = open(src, encoding="utf-8").read().splitlines()
out = []
for line in lines:
    s = line.strip()
    if not s:
        continue
    if s.startswith("#"):
        continue
    if set(s) == {"*"} or s.startswith("***"):
        continue
    out.append(s)

text = "\n".join(out)
# 规范化：去掉中文引号/书名号内外多余空格（用字符串替换避免正则引号问题）
for ch in ["“", "”", "《", "》", "‘", "’", '"']:
    text = text.replace(" " + ch, ch).replace(ch + " ", ch)
# 去掉数字前后空格（公元 181 年 → 公元181年）
text = re.sub(r"(?<=\d)\s+(?=年|月|日)", "", text)
text = re.sub(r"(?<=公元)\s+(?=\d)", "", text)
# 破折号统一为 ——
text = text.replace("--", "——")

with open(dst, "w", encoding="utf-8-sig") as f:
    f.write(text)

chars = len(re.sub(r"\s", "", text))
print(f"输出: {dst}")
print(f"字数(去空白): {chars}")
print("预览前300字:")
print(text[:300])
