# Full Windows setup: dependencies, model, services. Idempotent, safe to re-run.
#
# Installs via winget: Python 3.12, Git, Ollama, ActivityWatch.
# Then: pulls the Ollama model, starts ActivityWatch, stores API keys,
# registers the nightly auditor + cache-commit tasks, installs the poller.
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -OllamaModel "qwen2.5:7b"
param(
    [string]$OllamaModel = "qwen2.5:7b",
    [string]$MistralApiKey = "",
    [string]$GitToken = "",
    [switch]$SkipApiKeys
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSCommandPath
$Git = "C:\Program Files\Git\cmd\git.exe"

function Ensure-Winget([string]$Id) {
    $found = winget list --id $Id -e 2>$null | Select-String -SimpleMatch $Id
    if (-not $found) {
        Write-Output "Installing $Id ..."
        winget install --id $Id -e --accept-package-agreements `
            --accept-source-agreements --silent
    } else {
        Write-Output "Found $Id"
    }
}

function Find-PythonW {
    $cands = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe",
        (where.exe pythonw 2>$null | Select-Object -First 1)
    ) | Where-Object { $_ -and (Test-Path $_) }
    if (-not $cands) { throw "pythonw.exe not found even after install" }
    return $cands[0]
}

function Ensure-Task([string]$Name, $Action, $Trigger, [string]$Desc) {
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Write-Output "Task present: $Name"
        return
    }
    Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger `
        -Description $Desc -Force | Out-Null
    Write-Output "Registered task: $Name"
}

# -- 1. dependencies (no Python packages: stdlib only) --
Ensure-Winget "Python.Python.3.12"
Ensure-Winget "Git.Git"
Ensure-Winget "Ollama.Ollama"
Ensure-Winget "ActivityWatch.ActivityWatch"
$PythonW = Find-PythonW
$env:PATH += ";C:\Program Files\Git\cmd;$env:LOCALAPPDATA\Programs\Ollama"
python -m compileall -q "$ProjectDir\screentime" "$ProjectDir\poll.py" `
    "$ProjectDir\audit.py"

# -- 2. ollama model (start server first if needed) --
try { ollama list 2>$null | Out-Null } catch {
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Minimized
    Start-Sleep 5
}
ollama pull $OllamaModel

# -- 3. activitywatch running? (port 5600 serves the window bucket) --
$awUp = $false
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:5600/api/0/buckets/" `
        -TimeoutSec 5 -UseBasicParsing
    $awUp = $r.StatusCode -eq 200
} catch { }
if (-not $awUp) {
    $awExe = (where.exe activitywatch 2>$null | Select-Object -First 1),
        "$env:PROGRAMFILES\ActivityWatch\activitywatch.exe",
        "$env:LOCALAPPDATA\Programs\ActivityWatch\activitywatch.exe" |
        Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if ($awExe) {
        Start-Process -FilePath $awExe -WindowStyle Minimized
        Write-Output "Started ActivityWatch"
    } else {
        Write-Warning "ActivityWatch is installed but not running - start it once by hand"
    }
} else {
    Write-Output "ActivityWatch is up"
}

# -- 4. secrets (user env so nightly tasks inherit them) --
if (-not $SkipApiKeys) {
    if (-not $MistralApiKey) {
        $MistralApiKey = Read-Host "MISTRAL_API_KEY (empty to skip)"
    }
    if (-not $GitToken) {
        $sec = Read-Host "GitHub PAT for push (empty to skip)" -AsSecureString
        if ($sec.Length -gt 0) {
            $GitToken = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
        }
    }
}
if ($MistralApiKey) {
    [Environment]::SetEnvironmentVariable("MISTRAL_API_KEY", $MistralApiKey, "User")
    Write-Output "Stored MISTRAL_API_KEY (user env)"
}
if ($GitToken) {
    "url=https://github.com`nusername=x-access-token`npassword=$GitToken`n" |
        & $Git credential approve
    Write-Output "Stored git credential"
}

# -- 5. nightly tasks (auditor 00:00, cache commit 00:15) --
$audAction = New-ScheduledTaskAction -Execute $PythonW `
    -Argument "`"$ProjectDir\audit.py`"" -WorkingDirectory $ProjectDir
Ensure-Task "Screentime Auditor" $audAction `
    (New-ScheduledTaskTrigger -Daily -At "00:00") `
    "Nightly Mistral review of new cache.md decisions"
$commitAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ProjectDir\commit_cache.ps1`"" `
    -WorkingDirectory $ProjectDir
Ensure-Task "Screentime Cache Commit" $commitAction `
    (New-ScheduledTaskTrigger -Daily -At "00:15") `
    "Commit and push cache.md after the nightly auditor run"

# -- 6. poller at startup (existing installer) --
& "$ProjectDir\install.ps1"

Write-Output "Setup complete."
