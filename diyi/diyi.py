# -*- coding: utf-8 -*-
"""diyi：第一人称历史人物口播稿 → 配音 一键管线。

用法（cmd）：
    D:\GPT-SoVITS\diyi.cmd --script 口播稿.md --out 配音.wav [--voice dabao-zhugeliang] [--speed 0.82]

流程：
    1. 读取口播稿（.md / .txt，UTF-8）
    2. 清洗 Markdown（标题、分隔线、引号空格、数字空格）
    3. 读音修正：默认使用所选音色 preset.json 的 speak_fixes（古文多音字）
       可再传 --fixes 指定补充修正文件（每行：原文<TAB>替换）
    4. 调用 dabao_tts.py（复用其 cut1 分句、时长校验、压停顿、噪声门、json 输出）
    5. 输出 .wav/.mp3 + 同名 .json（每段原文/实际朗读/起止时间/时长）

可选音色 preset（voices/<id>/preset.json）：
    dabao-zhugeliang  — 诸葛亮垂暮慢速（默认）
    dabao             — 原 dabao 音色（V5turbo 底模）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # D:\GPT-SoVITS
DABAO_TTS = ROOT / "dabao_tts.py"
VOICES = ROOT / "voices"
DEFAULT_VOICE = "dabao-zhugeliang"


def clean_script(text: str) -> str:
    """去掉 markdown 标记并规范化文本，供 TTS 朗读。"""
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):          # 标题（# / ## / ###）
            continue
        if set(s) in ({"*"}, {"-"}, {"_"}) or re.fullmatch(r"[-*_]{3,}", s):
            continue                   # 分隔线
        lines.append(s)
    text = "\n".join(lines)
    # 中文引号/书名号内外空格
    for ch in ["“", "”", "《", "》", "‘", "’", '"', "「", "」"]:
        text = text.replace(" " + ch, ch).replace(ch + " ", ch)
    # 数字与单位之间的空格（公元 181 年 → 公元181年）
    text = re.sub(r"(?<=\d)\s+(?=年|月|日|岁|万|千|百|十)", "", text)
    text = re.sub(r"(?<=公元)\s+(?=\d)", "", text)
    text = text.replace("--", "——")
    return text.strip()


def apply_fixes_file(text: str, fixes_path: Path) -> str:
    """应用补充读音修正文件。格式：每行 '原文\t替换'，长词优先。"""
    pairs = []
    for line in fixes_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "\t" not in line:
            continue
        src, dst = line.split("\t", 1)
        pairs.append((src.strip(), dst.strip()))
    if not pairs:
        return text
    for src, dst in sorted(pairs, key=lambda p: len(p[0]), reverse=True):
        text = text.replace(src, dst)
    print(f"已应用补充读音修正 {len(pairs)} 条: {fixes_path}")
    return text


def resolve_preset(voice: str) -> Path:
    preset = VOICES / voice / "preset.json"
    if not preset.exists():
        raise SystemExit(f"找不到音色预设: {preset}")
    return preset


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="diyi 第一人称口播配音管线")
    parser.add_argument("--script", "-s", type=Path, required=True, help="口播稿 .md 或 .txt")
    parser.add_argument("--out", "-o", type=Path, default=ROOT / "diyi_out.wav", help="输出音频（.wav/.mp3）")
    parser.add_argument("--voice", "-v", default=DEFAULT_VOICE, help=f"音色预设 id（默认 {DEFAULT_VOICE}）")
    parser.add_argument("--fixes", type=Path, help="补充读音修正文件（每行 原文\\t替换）")
    parser.add_argument("--speed", type=float, help="覆盖语速（默认取 preset）")
    parser.add_argument("--temperature", type=float, help="覆盖采样温度")
    parser.add_argument("--top-p", type=float, help="覆盖 top_p")
    parser.add_argument("--top-k", type=int, help="覆盖 top_k")
    parser.add_argument("--seed", type=int, help="固定随机种子")
    parser.add_argument("--act", type=int, help="套用 preset 的按幕读音修正")
    parser.add_argument("--force", action="store_true", help="忽略缓存重配")
    parser.add_argument("--keep-server", action="store_true", help="结束后保留服务进程")
    args = parser.parse_args()

    if not args.script.exists():
        raise SystemExit(f"找不到口播稿: {args.script}")

    # 1. 读原文
    raw = args.script.read_text(encoding="utf-8-sig")
    print(f"读取口播稿: {args.script}（原始 {len(raw)} 字符）")

    # 2. 清洗 markdown
    text = clean_script(raw)
    print(f"清洗后: {len(re.sub(chr(92)+'s', '', text))} 字")

    # 3. 补充读音修正（可选）
    if args.fixes:
        if not args.fixes.exists():
            raise SystemExit(f"找不到修正文件: {args.fixes}")
        text = apply_fixes_file(text, args.fixes)

    # 4. 写临时文本给 dabao_tts.py
    tmp = ROOT / "diyi_tmp_script.txt"
    tmp.write_text(text, encoding="utf-8")

    # 5. 拼 dabao_tts.py 命令
    preset = resolve_preset(args.voice)
    cmd = [
        str(Path(sys.executable).resolve()),
        str(DABAO_TTS.resolve()),
        "--config", str(preset.resolve()),
        "--text-file", str(tmp.resolve()),
        "--out", str(args.out.resolve()),
    ]
    if args.speed is not None:
        cmd += ["--speed", str(args.speed)]
    if args.temperature is not None:
        cmd += ["--temperature", str(args.temperature)]
    if args.top_p is not None:
        cmd += ["--top-p", str(args.top_p)]
    if args.top_k is not None:
        cmd += ["--top-k", str(args.top_k)]
    if args.seed is not None:
        cmd += ["--seed", str(args.seed)]
    if args.act is not None:
        cmd += ["--act", str(args.act)]
    if args.force:
        cmd += ["--force"]
    if args.keep_server:
        cmd += ["--keep-server"]

    print("调用配音引擎...")
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        raise SystemExit(f"配音失败，退出码 {proc.returncode}")
    print(f"\n管线完成: {args.out}")
    if args.out.suffix.lower() in (".wav", ".mp3"):
        print(f"元数据: {args.out.with_suffix('.json')}")


if __name__ == "__main__":
    main()
