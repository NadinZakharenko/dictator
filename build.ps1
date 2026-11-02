$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$Dist = "C:\AI\VoiceAgent\dist"

# PyInstaller logs INFO to stderr; under "Stop" a redirected stderr line aborts the script.
$ErrorActionPreference = "Continue"
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name Dictator `
    --collect-all faster_whisper `
    --collect-all ctranslate2 `
    --collect-all onnxruntime `
    --collect-all tokenizers `
    --collect-all av `
    --collect-all huggingface_hub `
    --collect-all sounddevice `
    --hidden-import numpy `
    --distpath $Dist `
    (Join-Path $Root "dictator.py")

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
$ErrorActionPreference = "Stop"

# Keep this file ASCII: Windows PowerShell 5 reads BOM-less scripts as ANSI.
# PyInstaller bundles VC++ 14.31; CTranslate2 crashes with it (0xc0000005 before main()),
# so the exe must load the newer runtime from System32.
$Internal = Join-Path $Dist "Dictator\_internal"
foreach ($name in @("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll")) {
    Remove-Item -Force (Join-Path $Internal $name) -ErrorAction SilentlyContinue
}

Remove-Item -Recurse -Force (Join-Path $Root "build") -ErrorAction SilentlyContinue
Write-Output "Built: $(Join-Path $Dist 'Dictator\Dictator.exe')"
