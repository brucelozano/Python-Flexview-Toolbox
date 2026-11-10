param(
    [string]$Name = "FlexviewPlayer",
    [switch]$Clean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$entryScript = Join-Path $repoRoot "flexview_player\main.py"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $entryScript)) {
    throw "Entry script not found: $entryScript"
}

if (Test-Path -LiteralPath $venvPython) {
    $pythonCmd = $venvPython
}
else {
    $pythonCmd = "py"
}

$toolboxDir = Join-Path $repoRoot "M3_MATLAB_Toolbox_1.2"
$helpersDir = Join-Path $repoRoot "matlab_helpers"
if (-not (Test-Path -LiteralPath $toolboxDir)) {
    Write-Warning "MATLAB toolbox folder missing: $toolboxDir"
}
if (-not (Test-Path -LiteralPath $helpersDir)) {
    Write-Warning "MATLAB helpers folder missing: $helpersDir"
}

$pyArgs = @("-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir", "--name", $Name)
if ($Clean) {
    $pyArgs += "--clean"
}
$pyArgs += @(
    "--collect-all", "PySide6",
    "--collect-all", "matlab",
    "--collect-submodules", "matlab.engine",
    "--hidden-import", "matlab.engine",
    "--add-data", "$helpersDir;matlab_helpers",
    "--add-data", "$toolboxDir;M3_MATLAB_Toolbox_1.2",
    $entryScript
)

Write-Host "Building $Name from $entryScript"
if ($pythonCmd -eq "py") {
    & py -3 @pyArgs
}
else {
    & $pythonCmd @pyArgs
}

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE."
}

Write-Host "Build complete. See: $repoRoot\dist\$Name"
