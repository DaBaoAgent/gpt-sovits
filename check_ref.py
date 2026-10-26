import os
try:
    from mutagen import File
    p = r"D:\GPT-SoVITS\zhuge_ref.mp3"
    f = File(p)
    print("时长(秒):", round(f.info.length, 2))
    print("码率:", f.info.bitrate)
except Exception as e:
    print("mutagen不可用:", e)
    # 用wave或直接读文件头
    try:
        from pydub import AudioSegment
        a = AudioSegment.from_file(p)
        print("时长(秒):", round(len(a)/1000, 2))
    except Exception as e2:
        print("pydub也不可用:", e2)
        # 尝试用ffprobe
        import subprocess
        r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", p], capture_output=True, text=True)
        print("ffprobe:", r.stdout, r.stderr)
