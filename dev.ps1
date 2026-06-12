# dev.ps1 - run the whole dev stack in one terminal with one command:
#   .\dev.ps1
# Starts the django-q transcode worker and the Tailwind watcher (if the
# standalone CLI is present in .bin\), applies migrations, then runs the
# Django dev server in the foreground. Ctrl+C stops everything: the
# children share this console, so the interrupt reaches them all.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Error 'No .venv found. Create it first (see README "Setup").'
}

& $py manage.py migrate

$children = @()
$children += Start-Process -NoNewWindow -PassThru -FilePath $py -ArgumentList 'manage.py', 'qcluster'

$tailwind = Join-Path $PSScriptRoot '.bin\tailwindcss.exe'
if (Test-Path $tailwind) {
    $children += Start-Process -NoNewWindow -PassThru -FilePath $tailwind -ArgumentList `
        '-i', 'static_src/input.css', '-o', 'static/css/style.css', '--watch'
} else {
    Write-Host '[dev] .bin\tailwindcss.exe not found - skipping CSS watch (see README "Frontend build").'
}

try {
    & $py manage.py runserver
} finally {
    foreach ($child in $children) {
        if (-not $child.HasExited) {
            try { Stop-Process -Id $child.Id -Force -ErrorAction Stop } catch {}
        }
    }
}
