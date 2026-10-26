# diyi 第一人称配音管线

把**第一人称历史人物口播稿 → 配音**整条链路封装成一键工具。
命名"diyi"取"第一人称"之意。2026-10-23 定稿。

## 一键调用

在引擎目录（`GPT-SoVITS\`）下：

```powershell
.\diyi.cmd --script D:\@kaifa\lishi\口播稿.md --out D:\@kaifa\lishi\配音.wav
```

从其他项目目录调用时，用引擎的绝对路径，例如 PeiYin 项目：

```powershell
D:\@kaifa\PeiYin\GPT-SoVITS\diyi.cmd --script .\口播稿.md --out .\配音.wav
```

参数：

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| `--script / -s` | 口播稿 .md 或 .txt（必填） | — |
| `--out / -o` | 输出 .wav/.mp3 | 引擎目录下 `diyi_out.wav` |
| `--voice / -v` | 音色预设 id | `dabao-zhugeliang` |
| `--fixes` | 补充读音修正文件（每行 `原文<TAB>替换`） | 无 |
| `--speed` | 覆盖语速（0.82 = 垂暮慢速） | 取 preset |
| `--seed` | 覆盖随机种子 | 取 preset |
| `--act` | 套用 preset 的按幕读音修正 | 无 |
| `--force` | 忽略缓存重配 | 关 |
| `--keep-server` | 结束后保留服务进程 | 关 |

采样参数（temperature / top_p / top_k / repetition_penalty）锁在
`preset.json`，命令行不提供覆盖。

## 管线流程

```
口播稿(.md/.txt)
  → 清洗 Markdown（标题/分隔线/引号空格/数字空格）
  → 补充读音修正（--fixes，可选）
  → dabao_tts.py（cut1 分句 → 时长校验 6.2字/秒 → 压停顿 → 噪声门）
  → tts_server.py（V5turbo 推理）
  → 输出 .wav/.mp3 + 同名 .json（每段原文/实际朗读/起止/时长）
```

## 音色预设

`--voice` 对应 `voices/<id>/preset.json`：

- **dabao-zhugeliang**（默认）— dabao 音色 + 诸葛亮垂暮调参
  （speed 0.82、temperature 0.7、top_k 15、top_p 0.9、rep_pen 1.2、seed 20261023）
- **dabao** — 原 dabao 预设（V5turbo 底模，speed 1.0、temperature 0.9）

## 古文发音

诸葛亮预设内置 **113 条古文/多音字读音修正**（speak_fixes），覆盖：
曹丕→曹披、刘禅→刘善、马谡→马素、司马懿→司马意、费祎→费一、蒋琬→蒋碗、
琅琊→郎牙、渭水→卫水、股肱→古功、嗣子→四子、鞠躬尽瘁→鞠躬尽脆、
还于旧都→环于旧都、兴复→星复、食少事烦→石少事烦、降→祥（全套）等。

新人物如有专属专名，用 `--fixes 人名修正.txt` 补充，格式每行：

```
琅琊<TAB>郎牙
刘禅<TAB>刘善
```

合成后请核对同名 `.json` 的 `spoken` 字段，确认实际朗读符合预期。

## 依赖

- GPT-SoVITS V5turbo 权重：`GPT_SoVITS/pretrained_models/s1v3.ckpt`（T2S）+
  `gsv-v5-pretrained/s2Gv5turbo.pth` + `vocoder.pth`
- 引擎目录下的 `.venv`（由 PeiYin 的 `scripts\setup.ps1` 创建）
- 服务未运行时自动拉起（V5turbo 加载约 1 分钟），结束时自动停；已在运行则复用
