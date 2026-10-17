# Tiled Palette Quantizer installer for Windows.
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Drak3Dev/tiledpalettequant/main/python/install.ps1 | iex"
# Environment overrides: TPQ_HOME (install dir), TPQ_BRANCH (git branch), TPQ_SRC_DIR (local source).
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Repo = 'Drak3Dev/tiledpalettequant'
$Branch = if ($env:TPQ_BRANCH) { $env:TPQ_BRANCH } else { 'main' }
$Dest = if ($env:TPQ_HOME) { $env:TPQ_HOME } else { Join-Path $env:LOCALAPPDATA 'tiledpalettequant' }

function Say($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "warning: $msg" -ForegroundColor Yellow }

function Test-Python($exe, [string[]]$pre) {
    try {
        $out = & $exe @pre -c "import sys, tkinter, venv; print(sys.version_info >= (3, 9))" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True')
    } catch { return $false }
}

function Find-Python {
    # The py launcher first: "python" may be the Microsoft Store stub.
    $candidates = @(
        @{ Exe = 'py'; Pre = @('-3') },
        @{ Exe = 'python'; Pre = @() },
        @{ Exe = 'python3'; Pre = @() }
    )
    foreach ($c in $candidates) {
        if ((Get-Command $c.Exe -ErrorAction SilentlyContinue) -and (Test-Python $c.Exe $c.Pre)) {
            $path = & $c.Exe @($c.Pre) -c "import sys; print(sys.executable)"
            return "$path".Trim()
        }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Say 'Python not found, installing Python 3.12 with winget'
        winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $py = Find-Python
        if (-not $py) {
            $guess = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
            if ((Test-Path $guess) -and (Test-Python $guess @())) { $py = $guess }
        }
    }
}
if (-not $py) {
    Write-Host 'Python 3.9+ with tkinter was not found.' -ForegroundColor Red
    Write-Host 'Install it from https://www.python.org/downloads/ (keep "tcl/tk and IDLE" checked) and run this again.'
    exit 1
}
Say "Using $(& $py --version) at $py"

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("tpq-" + [Guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    if ($env:TPQ_SRC_DIR) {
        $src = $env:TPQ_SRC_DIR
    } else {
        Say "Downloading $Repo ($Branch)"
        $zip = Join-Path $tmp 'src.zip'
        Invoke-WebRequest -UseBasicParsing "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" -OutFile $zip
        Expand-Archive -Path $zip -DestinationPath $tmp
        $top = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
        $src = Join-Path $top.FullName 'python'
    }
    if (-not (Test-Path (Join-Path $src 'run.py'))) { throw "sources not found in $src" }

    Say "Installing to $Dest"
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $app = Join-Path $Dest 'app'
    if (Test-Path $app) { Remove-Item -Recurse -Force $app }
    Copy-Item -Recurse -Path $src -Destination $app
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

$venv = Join-Path $Dest 'venv'
$vpy = Join-Path $venv 'Scripts\python.exe'
$vpyw = Join-Path $venv 'Scripts\pythonw.exe'
if (-not (Test-Path $vpy)) {
    & $py -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'could not create a virtual environment' }
}

$ErrorActionPreference = 'Continue'
Say 'Installing dependencies (numpy, Pillow, numba)'
& $vpy -m pip install --quiet --disable-pip-version-check --upgrade pip
& $vpy -m pip install --quiet --disable-pip-version-check numpy Pillow
if ($LASTEXITCODE -ne 0) { Write-Host 'error: could not install numpy/Pillow' -ForegroundColor Red; exit 1 }
& $vpy -m pip install --quiet --disable-pip-version-check numba
if ($LASTEXITCODE -ne 0) { Warn 'numba could not be installed: everything works, but quantizing will be much slower' }
& $vpy -m pip install --quiet --disable-pip-version-check tkinterdnd2 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Warn 'tkinterdnd2 not installed: drag & drop is disabled' }

Say 'Precompiling (takes a few seconds)'
Push-Location $app
& $vpy -c "from tiledpalettequant.core import warmup; warmup()"
if ($LASTEXITCODE -ne 0) { Warn 'precompiling failed, it will happen on first start instead' }
Pop-Location

$runPy = Join-Path $app 'run.py'
$shell = New-Object -ComObject WScript.Shell
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Tiled Palette Quantizer.lnk'
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Tiled Palette Quantizer.lnk'
foreach ($lnkPath in @($startMenu, $desktop)) {
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $vpyw
    $lnk.Arguments = "`"$runPy`""
    $lnk.WorkingDirectory = $app
    $lnk.Description = 'Tiled Palette Quantizer'
    $lnk.Save()
}

$cli = Join-Path $Dest 'tiledpalettequant-cli.cmd'
Set-Content -Path $cli -Encoding ASCII -Value "@echo off`r`nsetlocal`r`nset `"PYTHONPATH=$app`"`r`n`"$vpy`" -m tiledpalettequant cli %*"

Say 'Done! Shortcuts were added to the Start menu and the desktop.'
Say "Command line version: $cli"
