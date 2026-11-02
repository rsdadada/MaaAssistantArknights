param(
    [Parameter(Mandatory = $true)][string]$SourceDir,
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [string]$IdentityFile
)
$ErrorActionPreference = 'Stop'
$personalSource = Join-Path $SourceDir 'personal/resource'
if (Test-Path -LiteralPath $personalSource) {
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir 'personal') | Out-Null
    Copy-Item -LiteralPath $personalSource -Destination (Join-Path $InstallDir 'personal/resource') -Recurse -Force
}
if ($IdentityFile) {
    Copy-Item -LiteralPath $IdentityFile -Destination (Join-Path $InstallDir 'personal-build.json') -Force
}
