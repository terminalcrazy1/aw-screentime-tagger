# Commits auditor output (cache.md, audit.md) and pushes. No-op when unchanged.
# Runs nightly after the "Screentime Auditor" task. Safe to re-run by hand.
$ProjectDir = Split-Path -Parent $PSCommandPath
Set-Location -LiteralPath $ProjectDir
$Git = "C:\Program Files\Git\cmd\git.exe"
$Log = Join-Path $ProjectDir "commit_cache.log"

function Log($msg) {
    Add-Content -LiteralPath $Log -Value ("{0:u} {1}" -f (Get-Date), $msg)
}

& $Git add -- cache.md audit.md 2>&1 | ForEach-Object { Log $_ }
$staged = & $Git diff --cached --name-only
if (-not $staged) {
    Log "no changes, nothing to commit"
    exit 0
}
& $Git commit -m "update cache decisions after nightly audit" 2>&1 | ForEach-Object { Log $_ }
if ($LASTEXITCODE -eq 0) {
    Log "committed: $($staged -join ', ')"
    & $Git push origin main 2>&1 | ForEach-Object { Log $_ }
    if ($LASTEXITCODE -eq 0) { Log "pushed" } else { Log "push failed" }
} else {
    Log "commit failed"
    exit 1
}
