import requests
import json

url = "http://127.0.0.1:9880/tts"

text = """建兴十二年，秋，五丈原。风从渭水那边吹过来，带着对岸魏军大营里的炊烟味。营帐的帘子被掀起一角，又落下，帐里的烛火晃了晃，映着案上那一堆摊开的军报。我咳了一声，用帕子捂住嘴，帕子上多了一点红。我知道，这一天终于还是来了。外面姜维他们还在叫着要再战，魏延那张大嗓门隔着帐布都能听见。但我听得见的，不是他们的声音。我听得见秋风刮过渭水南岸的枯草，一片一片，像是什么东西在一点点碎掉。对面的营垒里，司马懿还在缩着。他缩了三年了。而我，已经站不动了。如果你想知道，那个被叫做卧龙的人，是怎样一步步走到这片五丈原的秋风里的，那我们就得从头讲起。"""

payload = {
    "text": text,
    "text_lang": "zh",
    "ref_audio_path": "zhuge_ref.mp3",
    "prompt_text": "东汉末年朝纲混乱，内有董卓巨奸权倾朝野专横跋扈，外有黄巾军起义撼动社稷。",
    "prompt_lang": "zh",
    "text_split_method": "cut5",
    "batch_size": 1,
    "media_type": "wav",
    "streaming_mode": False,
    "speed_factor": 1.0
}

print("开始生成配音...")
response = requests.post(url, json=payload, stream=True)

if response.status_code == 200:
    with open(r"D:\@kaifa\lishi\诸葛亮开头钩子配音.wav", "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    print("配音完成，文件已保存到 D:\\@kaifa\\lishi\\诸葛亮开头钩子配音.wav")
else:
    print(f"失败: {response.status_code}")
    print(response.text)
