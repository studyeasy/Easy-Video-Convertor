# Downloads the FFmpeg shared build bundled with the app (vendor\ffmpeg).
# Uses the BtbN n8.1 stable build — the master builds require newer NVIDIA
# drivers for NVENC than many machines have.
$ErrorActionPreference = "Stop"

$root = Split-Path $PSScriptRoot -Parent
$dest = Join-Path $root "vendor\ffmpeg"

if (Test-Path (Join-Path $dest "ffmpeg.exe")) {
    Write-Host "FFmpeg already present in vendor\ffmpeg — nothing to do."
    exit 0
}

$url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-win64-gpl-shared-8.1.zip"
$zip = Join-Path $env:TEMP "evc-ffmpeg-n8.1.zip"
$tmp = Join-Path $env:TEMP "evc-ffmpeg-extract"

Write-Host "Downloading FFmpeg (about 80 MB)..."
curl.exe -L -o $zip $url

Write-Host "Extracting..."
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force

$bin = (Get-ChildItem $tmp -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1).DirectoryName
New-Item -ItemType Directory -Force $dest | Out-Null
Get-ChildItem $bin | Where-Object { $_.Name -ne "ffplay.exe" } | Copy-Item -Destination $dest -Force

Remove-Item $zip -Force
Remove-Item -Recurse -Force $tmp
Write-Host "FFmpeg installed to vendor\ffmpeg."
