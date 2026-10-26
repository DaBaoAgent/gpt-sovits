# dabao 配音预设

固定音色与参数在 `voices\dabao\`，在本引擎目录（`GPT-SoVITS\`）下运行一键入口：

```powershell
.\dabao_tts.cmd --text-file .\口播稿.txt --out .\out\narration.mp3
```

从其他项目目录调用时，用引擎所在的绝对路径即可：

```powershell
D:\@kaifa\PeiYin\GPT-SoVITS\dabao_tts.cmd --text-file .\口播稿.txt --out .\out\narration.mp3
```

- 参数与读音规则：`voices\dabao\preset.json`
- 使用方法/HTTP 直调：`voices\dabao\README.md`
- 文言多音字：`voices\dabao\读音规范.md`

音色名：**dabao**（GPT-SoVITS v5turbo + `ref_dabao3-1.wav` 零样本克隆）。
