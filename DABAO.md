# dabao 音色（GPT-SoVITS V3）

本仓库只使用 **V3** 权重与配置（`s1v3.ckpt` / `s2Gv3.pth`）。V1、V2、V2Pro、
V4、V5 的配置项已从 `GPT_SoVITS/configs/tts_infer.yaml` 移除，避免误选到不存在的权重。

## 文件

- `GPT_SoVITS/pretrained_models/s1v3.ckpt`、`s2Gv3.pth` — V3 权重（Git LFS）
- `voices/dabao/ref_dabao3-1.wav` — 参考音频，9.15 秒，44.1 kHz 立体声
- `voices/dabao/ref_dabao3-1.txt` — 参考音频逐字稿
- `voices/dabao/preset.json` — **唯一权威**：合成参数 + 89 条全局发音修正 + 第 3/4/5 幕专项修正
- `voices/dabao/读音规范.md` — 文言多音字与古地名读音说明
- `tts_server.py` — OpenAI 形状的 HTTP 服务，读取上面的 `preset.json`
- `start-tts-server.vbs` — 静默启动 `127.0.0.1:9880`

## 当前参数

| 项 | 值 |
| --- | --- |
| 模型 | GPT-SoVITS V3 |
| 切分 | `cut1` |
| 语速 | `speed_factor = 1.0` |
| 采样 | `temperature = 0.8`，`top_p = 0.9`，`top_k = 20`，`repetition_penalty = 1.3` |
| 种子 | `-1`（每次随机） |
| 片段 | `fragment_interval = 0.3`，`batch_size = 1` |
| 输出 | MP3 192 kbps，44.1 kHz 单声道（服务端编码） |

这些值来自 2026-10-24 的本机 V3 音色审核；改音色请改 `preset.json`，不要改
`tts_server.py`。

`preset.json` 里的 `postprocess`（句间停顿、噪声门等）保留给成片流水线；
当前的 `tts_server.py` 只应用采样参数、发音修正和 MP3 编码，不做这些后期处理。

## 安装（另一台 Windows 电脑）

1. 安装 Python 3.11（64 位）。
2. 拉取 LFS 权重：
   ```powershell
   git lfs install
   git lfs pull
   ```
3. 建虚拟环境并安装 CPU 版 PyTorch：
   ```powershell
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
   .venv\Scripts\python.exe -m pip install -r requirements-win-cpu.txt
   ```
4. 启动服务（二选一）：
   ```powershell
   wscript start-tts-server.vbs
   .venv\Scripts\python.exe tts_server.py
   ```
5. 健康检查：
   ```powershell
   curl http://127.0.0.1:9880/health
   ```

## 合成

```powershell
curl -X POST http://127.0.0.1:9880/v1/audio/speech `
  -H "Content-Type: application/json" `
  -d '{"input":"建安十三年，刘琮不战而降。","act":3}' `
  --output out.mp3
```

- `input` / `text`：要朗读的原文。
- `speed` / `speed_factor`：可选，覆盖 `speed_factor`。
- `text_split_method`：可选，覆盖 `cut1`。
- `act`：可选，`3` / `4` / `5`，追加该幕的读音修正。
- 默认总会应用 `speak_fixes.global`；原文与朗读文本的替换关系会写入
  `tts_server.log`，字幕请使用原文。

## 私密性

参考音频是私人声音素材。本仓库如果是公开仓库，任何访问者都能下载该音频；
仅用于自己的另一台电脑时，建议把仓库设为 Private。
