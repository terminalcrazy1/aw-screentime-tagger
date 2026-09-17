# Installs the screentime poller as a startup program (idempotent).
# Creates "Screentime Poller.lnk" in shell:startup running poll.py hidden
# via pythonw.exe. Run once; safe to re-run (overwrites the same shortcut).
$ProjectDir = Split-Path -Parent $PSCommandPath
$PythonW = "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe"
if (-not (Test-Path $PythonW)) { throw "pythonw.exe not found at $PythonW" }

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Screentime Poller.lnk")
$lnk.TargetPath = $PythonW
$lnk.Arguments = '"poll.py"'
$lnk.WorkingDirectory = $ProjectDir
$lnk.WindowStyle = 7  # minimized (pythonw shows no window anyway)
$lnk.Save()
Write-Output "Installed: Screentime Poller.lnk -> $PythonW poll.py"

# Start it now too, unless already running.
$running = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*poll.py*" }).Count -gt 0
if (-not $running) {
    $env:OLLAMA_MODEL = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "qwen2.5:7b" }
    Start-Process -FilePath $PythonW -ArgumentList '"poll.py"' -WorkingDirectory $ProjectDir -WindowStyle Hidden
    Write-Output "Poller started."
} else {
    Write-Output "Poller already running."
}
