' start-tts-server.vbs — 静默启动本地 GPT-SoVITS TTS 服务（127.0.0.1:9880）
'
' 为什么要有这个文件（2026-10-22）：
'   原先按 CLAUDE.md 用 `python.exe tts_server.py` 起服务。python.exe 是控制台程序，
'   CC（Claude Code）的宿主进程没有控制台，Windows 就会给它新分配一个控制台窗口
'   —— 桌面上那个标题是 pythonw.exe 全路径的黑窗口就是这么来的。
'   wscript.exe 本身是 GUI 子系统，从这里 Run 出去时窗口样式设成 0（隐藏），
'   既不会分配控制台，也不会闪一下；服务照旧监听 9880，
'   CC 调 tools\tts.cmd 与 POST /v1/audio/speech 完全不受影响。
'
' 用法（幂等：服务已在跑就什么都不做，直接退出）：
'   wscript "D:\@kaifa\tushuo\vendor\gpt-sovits\start-tts-server.vbs"
'
Option Explicit

Dim fso, sh, base, pyw, srv, tmpCmd, code

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = base & "\.venv\Scripts\pythonw.exe"
srv = base & "\tts_server.py"

If Not fso.FileExists(pyw) Then
    WScript.Echo "找不到 " & pyw
    WScript.Quit 2
End If

' ---- 幂等探活：用临时 cmd 查 9880 是否 LISTENING（避免在 VBS 里拼一堆引号）
tmpCmd = fso.GetSpecialFolder(2) & "\tts-port-probe.cmd"
On Error Resume Next
fso.DeleteFile tmpCmd, True
On Error GoTo 0
Dim ts
Set ts = fso.CreateTextFile(tmpCmd, True)
ts.WriteLine "@echo off"
ts.WriteLine "netstat -ano -p tcp | findstr "":9880"" | findstr ""LISTENING"" >nul"
ts.Close

code = sh.Run("""" & tmpCmd & """", 0, True)
On Error Resume Next
fso.DeleteFile tmpCmd, True
On Error GoTo 0

If code = 0 Then
    ' 已经在跑
    WScript.Quit 0
End If

' ---- 隐藏启动：窗口样式 0，不占用控制台，父进程立刻返回
sh.CurrentDirectory = base
sh.Run """" & pyw & """ """ & srv & """", 0, False
WScript.Quit 0
