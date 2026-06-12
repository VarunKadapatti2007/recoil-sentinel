# Windows-native demo orchestration (PowerShell equivalent of demo.sh):
#   reset -> doctor -> start API + web -> print the on-stage runbook.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "[recoil] restoring pristine demo state..."
& $py -m recoil.cli reset --demo
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "[recoil] running doctor..."
& $py -m recoil.cli doctor
if ($LASTEXITCODE -ne 0) {
    Write-Host "[recoil] doctor is NOT READY - fix the failures above before demoing." -ForegroundColor Red
    exit 1
}

Write-Host "[recoil] starting API on :8787..."
$api = Start-Process -FilePath $py -ArgumentList "-m","uvicorn","server.main:app","--port","8787","--log-level","warning" -PassThru -NoNewWindow

Write-Host "[recoil] starting web on :3000..."
$web = Start-Process -FilePath "cmd.exe" -ArgumentList "/c","cd web && npm run dev" -PassThru -NoNewWindow

Start-Sleep -Seconds 3
@"

============================================================================
 RECOIL DEMO RUNBOOK (rehearse this exact flow)
============================================================================
 0. Pre-stage:  'recoil demo-check' must print PASSED. Doctor must be READY.
 1. Open http://localhost:3000  -> Overview: 250 runs, 12 frozen cases,
    last gate PASS, published v_good. "This is a real agent in production."
 2. Traces -> click any run -> show the span waterfall (tokens/latency/cost).
 3. "I want my agent to be more concise." Top bar: candidate = v_regressed.
    Press RUN GATE. Cases tick green... then the after-hours outage case
    SNAPS RED. Verdict: BLOCK. Publish refused (exit 1 from the CLI too).
 4. Click "Open regression diff": escalate true -> false, on_call_paged
    true -> false, highlighted. Read the judge's grounded rationale.
 5. "Here's the fix." Top bar: candidate = v_fixed. RUN GATE again.
    12/12 green. Verdict: PASS. Press "Publish v_fixed" -> published.
 6. Optional: "Send test alert" -> after-hours outage -> a live run appears
    in Traces, judged in real time.
 7. Close: "Every failure becomes a permanent test. Nothing regresses twice."
============================================================================
 Press Ctrl-C (or close this window) to stop; API/web are child processes.
"@ | Write-Host

try {
    Wait-Process -Id $api.Id
} finally {
    Write-Host "[recoil] shutting down..."
    foreach ($p in @($api, $web)) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
}
