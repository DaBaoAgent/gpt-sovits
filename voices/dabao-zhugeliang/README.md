# dabao-zhugeliang 音色预设

**诸葛亮垂暮感配音预设**（2026-10-23 定稿；2026-10-26 底模换为 V5turbo）。

基于 dabao 音色（`ref_dabao3-1.wav` 零样本克隆）＋ 诸葛亮口播调参：
垂暮慢速、咬字准、语气沉稳自然。用于历史人物第一人称口播（诸葛亮及同类老年人物）。

## 文件

- `ref_dabao3-1.wav` — 参考音频（9.15 秒，44.1 kHz 立体声；来源 dabao 音色）
- `ref_dabao3-1.txt` — 参考音频逐字文本
- `preset.json` — 全部参数与读音修正

## 定稿参数（与 dabao 预设的区别）

| 项 | dabao | dabao-zhugeliang |
| --- | --- | --- |
| 底模 | V5turbo | **V5turbo** |
| 语速 | 1.0 | **0.82**（垂暮慢速） |
| temperature | 0.9 | **0.7**（咬字更准） |
| top_p | 0.9 | **0.9** |
| top_k | 20 | **15** |
| repetition_penalty | 1.3 | **1.2**（语气更自然） |
| seed | -1 | **20261023** |
| 每段字数 | 150 | **78** |
| fragment_interval | 0.2 | **0.3** |

## 一键调用

在引擎目录（`GPT-SoVITS\`）下：

```powershell
.\dabao_tts.cmd --config voices\dabao-zhugeliang\preset.json --text-file .\口播稿.txt --out .\out\zhugeliang.wav
```

或用 Python 直接调（已启动服务时更快）：

```powershell
.\.venv\Scripts\python.exe dabao_tts.py --config voices\dabao-zhugeliang\preset.json --text-file .\口播稿.txt --out .\out\zhugeliang.wav
```

- 输出按扩展名出 `.mp3`（192 kbps）或 `.wav`（44.1 kHz PCM16）。
- 同时写同名 `.json`：每段 `text`（原文）、`spoken`（实际朗读）、起止时间、时长。
- 服务未运行时自动拉起（V5turbo 权重加载约 1 分钟），结束时自动停；已在运行则复用。
- 缓存分段在输出目录的 `*-chunks/`；`--force` 强制重配。
- 可临时覆盖 `--speed --seed --keep-gap-ms --min-gap-ms`；采样参数锁在
  `preset.json`，命令行不能改。
- `diyi.cmd` 默认使用本预设；在别的项目里调用时传引擎绝对路径，例如
  `D:\@kaifa\PeiYin\GPT-SoVITS\dabao_tts.cmd`。

## 说明

- 依赖 V5turbo 权重：`GPT_SoVITS/pretrained_models/s1v3.ckpt`（T2S）+
  `gsv-v5-pretrained/s2Gv5turbo.pth` + `vocoder.pth`；不再使用 `s2Gv3.pth` 与 BigVGAN。
- 参考音频是私人声音素材，仅在获授权的工作室项目内使用。
