# Tiled Palette Quantizer uninstaller for Windows.
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Drak3Dev/tiledpalettequant/main/python/uninstall.ps1 | iex"
# Also available in Settings > Apps. Environment override: TPQ_HOME (install dir).
$ErrorActionPreference = 'Stop'

function Say($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

if ($env:TPQ_HOME) {
    $Dest = $env:TPQ_HOME
} elseif ($PSScriptRoot -and (Test-Path (Join-Path (Split-Path $PSScriptRoot -Parent) 'venv'))) {
    # Started from the installed copy (<install dir>\app\uninstall.ps1).
    $Dest = Split-Path $PSScriptRoot -Parent
} else {
    $Dest = Join-Path $env:LOCALAPPDATA 'tiledpalettequant'
}

$removed = $false
function Remove-Thing($path) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
        Say "Removed $path"
        $script:removed = $true
    }
}

if (Test-Path -LiteralPath $Dest) {
    # Never delete a directory that isn't ours, e.g. a mistyped TPQ_HOME.
    if (-not ((Test-Path (Join-Path $Dest 'app\run.py')) -or (Test-Path (Join-Path $Dest 'venv')))) {
        Write-Host "error: $Dest doesn't look like a Tiled Palette Quantizer install, leaving it alone" -ForegroundColor Red
        exit 1
    }
    # Close running copies, otherwise their files stay locked.
    Get-Process -Name python, pythonw -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -and $_.Path.StartsWith($Dest, [StringComparison]::OrdinalIgnoreCase) } catch { $false }
    } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 300
    Set-Location ([IO.Path]::GetTempPath())
    Remove-Thing $Dest
}

foreach ($folder in 'Programs', 'Desktop') {
    $dir = [Environment]::GetFolderPath($folder)
    if ($dir) { Remove-Thing (Join-Path $dir 'Tiled Palette Quantizer.lnk') }
}
Remove-Thing 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\TiledPaletteQuantizer'

if ($removed) {
    Say 'Tiled Palette Quantizer has been uninstalled.'
} else {
    Say 'Tiled Palette Quantizer is not installed, nothing to remove.'
}
