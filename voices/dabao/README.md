# dabao 音色预设

`D:\GPT-SoVITS` 里的固定配音音色与参数，供任何项目直接调用。2026-10-26 起底模
切换为 **V5turbo**；`locked-sample.mp3` 是 V2 时代的历史样音，不再对应当前参数。

## 文件

- `ref_dabao3-1.wav` — 参考音频（9.15 秒，44.1 kHz 立体声；
  来源 `D:\BaiduSyncdisk\18 艾伦全自动解说\克隆音色\dabao3-1.wav`）
- `ref_dabao3-1.txt` — 参考音频逐字文本（Whisper medium 转写 + 专名校正）
- `preset.json` — 全部参数与读音修正
- `locked-sample.mp3` / `locked-sample.json` — 定稿试听样音与生成元数据
- `读音规范.md` — 文言/历史多音字规则

音色名：**dabao**。当前是 GPT-SoVITS **V5turbo** 底模（`s2Gv5turbo.pth` +
`vocoder.pth`，T2S 仍用 `s1v3.ckpt`）加参考音频的**零样本克隆**；原生输出 48 kHz。
本机没有 26E 微调权重，音色接近 tushuo 原项目的 26E，但不等同。

## 一键调用（推荐）

任意目录、任意项目：

```powershell
D:\GPT-SoVITS\dabao_tts.cmd --text "建安十三年，刘琮不战而降。" --out .\out\dabao-test.mp3
D:\GPT-SoVITS\dabao_tts.cmd --text-file .\口播稿.txt --out .\out\narration.mp3
```

- 输出按扩展名出 `.mp3`（192 kbps）或 `.wav`（44.1 kHz PCM16）。
- 同时写同名 `.json`：每段的 `text`（原文）、`spoken`（实际朗读，含多音字替换）、
  起止时间、时长。
- 首次运行自动拉起 `D:\GPT-SoVITS\api_v2.py`（CPU 加载约 1 分钟），结束时自动停。
- 缓存分段在输出目录的 `narration-chunks/`；`--force` 强制重配。
- 可临时覆盖 `--temperature --top-p --top-k --speed --seed --ref-audio
  --keep-gap-ms --min-gap-ms`；不改 `preset.json`。
- 用 `--ref-audio` 换参考音频时，把与音频同名的 `.txt`（逐字稿）放在旁边；
  有 sidecar 就优先用它，没有则退回 `preset.json` 的 `prompt_text`（可能不匹配）。
- `--act 3/4/5` 套用 tushuo 按幕的读音修正。

## 定稿参数

| 项 | 值 |
| --- | --- |
| 切分 | `cut1`，每段最多 78 字 |
| 语速 | `speed_factor = 1.0` |
| 采样 | `temperature = 0.8`，`top_p = 0.9`，`top_k = 20`，`repetition_penalty = 1.3` |
| 种子 | `-1`（每次随机） |
| 批/片段 | `batch_size = 1`，`fragment_interval = 0.3` |
| 截断守卫 | 6.2 字/秒，最多重配 3 次 |
| 压停顿 | 句间静音 > 150 ms 压到 100 ms；-40 dB 静音门限 |
| 噪声门 | -33 dB，门限以下保留 0.3 增益 |
| 段间 | 20 ms |
| 输出 | 44.1 kHz 单声道；mp3 192 kbps |

## 直接调 HTTP API（可选）

不用一键脚本时，先启动服务：

```powershell
D:\GPT-SoVITS\.venv\Scripts\python.exe D:\GPT-SoVITS\api_v2.py -a 127.0.0.1 -p 9880
```

再 POST `/tts`，参数取 `preset.json` 的 `voice` 与 `synthesis`：

```json
{
  "text": "建安十三年，刘琮不战而降。",
  "text_lang": "zh",
  "ref_audio_path": "D:\\GPT-SoVITS\\voices\\dabao\\ref_dabao3-1.wav",
  "prompt_text": "希特勒在巴伐利亚、阿尔卑斯山的乡间别墅策划了他最大胆的行动，准备迎接最大挑战。罗马尼亚、保加利亚和匈牙利是德国的坚定盟友。",
  "prompt_lang": "zh",
  "text_split_method": "cut1",
  "speed_factor": 1.0,
  "top_k": 20,
  "top_p": 0.9,
  "temperature": 0.8,
  "repetition_penalty": 1.3,
  "fragment_interval": 0.3,
  "batch_size": 1,
  "seed": -1,
  "media_type": "wav",
  "streaming_mode": false
}
```

返回 WAV。注意 HTTP 直调不会做本预设的 6.2 字/秒校验、压停顿、噪声门和段拼接；
需要成片级旁白时用 `dabao_tts.cmd`。

## 换底模或 26E 微调权重

把对应权重放进 `D:\GPT-SoVITS\GPT_SoVITS\pretrained_models\`，改
`GPT_SoVITS\configs\tts_infer.yaml` 的 `custom` 块（`version` 与
`vits_weights_path`），再把 `preset.json` 的 `voice.model`/`synthesis.model`
标签同步改掉。参考音频、逐字稿、采样参数和读音规则保持不变；换底模后必须重新
做 A/B 试听与回读，不要直接沿用旧底模的调参结论。

参考音频是私人声音素材，不要随项目仓库分发。
