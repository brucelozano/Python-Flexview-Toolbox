param(
    [string]$Name = "FlexviewPlayer",
    [string]$DistRoot = "dist",
    [string]$OutDir = "releases",
    [string]$Label = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$distPath = Join-Path $repoRoot $DistRoot
$appDir = Join-Path $distPath $Name
if (-not (Test-Path -LiteralPath $appDir)) {
    throw "Built app folder not found: $appDir. Run build_windows_exe.ps1 first."
}

$releaseDir = Join-Path $repoRoot $OutDir
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$gitSha = ""
try {
    $gitSha = (git -C $repoRoot rev-parse --short HEAD 2>$null).Trim()
}
catch {
    $gitSha = ""
}

$nameParts = @($Name, "win64")
if ($Label.Trim().Length -gt 0) {
    $nameParts += $Label.Trim()
}
if ($gitSha.Length -gt 0) {
    $nameParts += $gitSha
}
$nameParts += $timestamp
$zipName = ($nameParts -join "-") + ".zip"
$zipPath = Join-Path $releaseDir $zipName

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

Write-Host "Packaging release from: $appDir"
Write-Host "Writing archive to: $zipPath"

$stagingRoot = Join-Path $releaseDir "_staging"
if (Test-Path -LiteralPath $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null

$stagingAppDir = Join-Path $stagingRoot $Name
Copy-Item -LiteralPath $appDir -Destination $stagingAppDir -Recurse -Force

Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal
Remove-Item -LiteralPath $stagingRoot -Recurse -Force

Write-Host "Release package created: $zipPath"
