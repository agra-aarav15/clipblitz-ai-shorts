# fetch-tools.ps1 — download the two binaries ClipBlitz needs into .\bin\
#
# Windows PowerShell version. Run it from the project folder:
#     powershell -ExecutionPolicy Bypass -File scripts\fetch-tools.ps1
#
# What it fetches (both are free, no account needed):
#   * ffmpeg  — from gyan.dev (the standard Windows build)  -> bin\ffmpeg-*\bin\ffmpeg.exe
#   * yt-dlp  — the standalone .exe from its GitHub releases -> bin\yt-dlp.exe
#
# ClipBlitz finds them automatically (clipblitz/config.py) — you never touch PATH.
# Re-running is safe: existing files are skipped unless you pass -Force.

param([switch]$Force)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$bin  = Join-Path $root 'bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null

Write-Host ''
Write-Host 'ClipBlitz tool fetch' -ForegroundColor White
Write-Host "  target: $bin"
Write-Host ''

# ---------------------------------------------------------------- yt-dlp
$ytdlp = Join-Path $bin 'yt-dlp.exe'
if ((Test-Path $ytdlp) -and -not $Force) {
    Write-Host '[skip] yt-dlp.exe already present' -ForegroundColor DarkGray
} else {
    Write-Host '[get ] yt-dlp.exe ...' -ForegroundColor Cyan
    $url = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe'
    try {
        Invoke-WebRequest -Uri $url -OutFile $ytdlp -UseBasicParsing
        Write-Host '       ok' -ForegroundColor Green
    } catch {
        Write-Host "       FAILED: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host '       Download it manually from https://github.com/yt-dlp/yt-dlp/releases' -ForegroundColor Yellow
        Write-Host "       and save it as: $ytdlp" -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------- ffmpeg
$have = Get-ChildItem -Path $bin -Directory -Filter 'ffmpeg*' -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName 'bin\ffmpeg.exe') }
if ($have -and -not $Force) {
    Write-Host "[skip] ffmpeg already present ($($have[0].Name))" -ForegroundColor DarkGray
} else {
    Write-Host '[get ] ffmpeg (about 80 MB) ...' -ForegroundColor Cyan
    $zip = Join-Path $env:TEMP 'cb-ffmpeg.zip'
    $url = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
    try {
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        Write-Host '       downloaded, extracting ...' -ForegroundColor DarkGray
        Expand-Archive -Path $zip -DestinationPath $bin -Force
        Remove-Item $zip -ErrorAction SilentlyContinue
        Write-Host '       ok' -ForegroundColor Green
    } catch {
        Write-Host "       FAILED: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host '       Download https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -ForegroundColor Yellow
        Write-Host "       and extract it into: $bin" -ForegroundColor Yellow
        Write-Host '       (the result must be bin\ffmpeg-<version>\bin\ffmpeg.exe)' -ForegroundColor Yellow
    }
}

# ---------------------------------------------------------------- verify
Write-Host ''
Write-Host 'Verifying:' -ForegroundColor White
$ok = 0
if (Test-Path $ytdlp) {
    try { $v = & $ytdlp --version 2>$null; Write-Host "  yt-dlp  $v" -ForegroundColor Green; $ok++ }
    catch { Write-Host '  yt-dlp  present but would not run' -ForegroundColor Yellow }
} else { Write-Host '  yt-dlp  MISSING' -ForegroundColor Red }

$ff = Get-ChildItem -Path $bin -Directory -Filter 'ffmpeg*' -ErrorAction SilentlyContinue |
      ForEach-Object { Join-Path $_.FullName 'bin\ffmpeg.exe' } |
      Where-Object { Test-Path $_ } | Select-Object -First 1
if ($ff) {
    try { $v = (& $ff -version 2>$null | Select-Object -First 1); Write-Host "  ffmpeg  $v" -ForegroundColor Green; $ok++ }
    catch { Write-Host '  ffmpeg  present but would not run' -ForegroundColor Yellow }
} else { Write-Host '  ffmpeg  MISSING' -ForegroundColor Red }

Write-Host ''
if ($ok -eq 2) {
    Write-Host 'Both tools ready. Start the app with:  python run.py' -ForegroundColor Green
} else {
    Write-Host 'Some tools are missing — see the messages above, then run this script again.' -ForegroundColor Yellow
}
Write-Host ''