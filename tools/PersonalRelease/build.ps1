param(
    [Parameter(Mandatory = $true)][string]$Workspace,
    [string]$Generator = 'Visual Studio 18 2026',
    [string]$CMake = 'cmake',
    [string]$Dotnet = 'dotnet',
    [switch]$DependenciesReady
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$env:MSBUILDDISABLENODEREUSE = '1'
$workspaceRoot = (Resolve-Path -LiteralPath $Workspace).Path
$sourceRoot = Join-Path $workspaceRoot 'source'
$installRoot = Join-Path $workspaceRoot 'install'
$buildRoot = Join-Path $sourceRoot 'build/personal-ci'
$identity = Get-Content -LiteralPath (Join-Path $workspaceRoot 'personal-build.json') -Raw | ConvertFrom-Json
$job = Get-Content -LiteralPath (Join-Path $workspaceRoot 'job.json') -Raw | ConvertFrom-Json

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

Push-Location $sourceRoot
try {
    if (-not $DependenciesReady) {
        Invoke-Checked 'git' @('submodule', 'update', '--init', '--depth', '1', 'src/MaaUtils', '3rdparty/EmulatorExtras')
        Invoke-Checked 'python' @('tools/maadeps-download.py', 'x64-windows')
    }
    Invoke-Checked 'python' @('tools/CheckStubLocalization.py')
    Invoke-Checked 'python' @('tools/CheckLocalizationReferences.py')
    Invoke-Checked 'python' @('tools/SortLocalizationKeys.py', '--check')
    Invoke-Checked 'python' @('-m', 'unittest', 'discover', '-s', 'tools/PersonalRelease/tests', '-v')
    Invoke-Checked $Dotnet @('run', '--project', 'tools/PersonalUpdateTests', '-c', 'Release')
    Invoke-Checked $Dotnet @('run', '--project', 'tools/PersonalCultivationUiTests', '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true', '-p:Platform=x64')
    Invoke-Checked $CMake @('-S', '.', '-B', $buildRoot, '-G', $Generator, '-A', 'x64',
        '-DMAADEPS_TRIPLET=maa-x64-windows', '-DBUILD_WPF_GUI=ON', '-DBUILD_SMOKE_TEST=OFF',
        '-DBUILD_DEBUG_DEMO=OFF', '-DBUILD_RESOURCE_UPDATER=OFF', '-DINSTALL_RESOURCE=ON',
        "-DCMAKE_INSTALL_PREFIX=$installRoot", "-DMAA_HASH_VERSION=$($identity.upstreamVersion)")
    Invoke-Checked $CMake @('--build', $buildRoot, '--target', 'MaaCore', '--config', 'Debug', '--parallel', '4', '--', '/nr:false')
    Invoke-Checked 'python' @('tools/PersonalRelease/validate_resources.py',
        '--dll-dir', (Join-Path $buildRoot 'bin/Debug'), '--source', $sourceRoot,
        '--user-dir', (Join-Path $workspaceRoot 'validation'))
    Invoke-Checked 'python' @('tools/PersonalCultivationTests/image_regression.py',
        '--dll-dir', (Join-Path $buildRoot 'bin/Debug'), '--source', $sourceRoot,
        '--user-dir', (Join-Path $workspaceRoot 'validation'))
    # The pure budget/planner test harness has no emulator or account access.
    Invoke-Checked 'python' @('tools/PersonalCultivationTests/run_tests.py')
    New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
    if ($job.kind -eq 'app') {
        Invoke-Checked $CMake @('--build', $buildRoot, '--target', 'MaaCore', 'MAA.Updater', 'MaaAppHostStub', '--config', 'RelWithDebInfo', '--parallel', '4', '--', '/nr:false')
        Invoke-Checked $CMake @('--install', $buildRoot, '--config', 'RelWithDebInfo')
        $numericVersion = $identity.upstreamVersion -replace '^v', '' -replace '-.*$', ''
        Invoke-Checked $Dotnet @('publish', 'src/MaaWpfGui/MaaWpfGui.csproj', '-c', 'Release', '-r', 'win-x64',
            '--self-contained', 'true', '-p:Platform=x64', "-p:Version=$numericVersion",
            "-p:InformationalVersion=$($identity.upstreamVersion)", '-o', $installRoot)
        Copy-Item -LiteralPath (Join-Path $buildRoot 'bin/RelWithDebInfo/MaaAppHostStub.exe') -Destination (Join-Path $installRoot 'MAA.exe') -Force
        Copy-Item -LiteralPath 'tools/DependencySetup_依赖库安装.bat' -Destination $installRoot
        $frameworkDir = Join-Path $workspaceRoot 'framework'
        New-Item -ItemType Directory -Force -Path $frameworkDir | Out-Null
        Invoke-Checked 'gh' @('release', 'download', 'v5.13.0', '--repo', 'MaaXYZ/MaaFramework', '--pattern', '*win-x86_64*.zip', '--dir', $frameworkDir)
        $frameworkArchive = Get-ChildItem -LiteralPath $frameworkDir -Filter '*.zip' | Select-Object -First 1
        Expand-Archive -LiteralPath $frameworkArchive.FullName -DestinationPath (Join-Path $frameworkDir 'expanded')
        Get-ChildItem -LiteralPath (Join-Path $frameworkDir 'expanded') -Recurse -File |
            Where-Object { $_.Name -match '(Win32|Adb)ControlUnit.*\.dll$' } |
            ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $installRoot }
        foreach ($component in 'MaaAdbControlUnit.dll', 'MaaWin32ControlUnit.dll') {
            if (-not (Test-Path -LiteralPath (Join-Path $installRoot $component) -PathType Leaf)) {
                throw "Missing required MaaFramework component: $component"
            }
        }
        $debugRuntime = [IO.Path]::GetFullPath((Join-Path $installRoot 'msvc-debug'))
        if (-not $debugRuntime.StartsWith($installRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Debug runtime cleanup escaped the install directory'
        }
        if (Test-Path -LiteralPath $debugRuntime) { Remove-Item -LiteralPath $debugRuntime -Recurse -Force }
        # Exclude development files by enumerating only files within this install.
        Get-ChildItem -LiteralPath $installRoot -File |
            Where-Object { $_.Extension -in '.pdb', '.h', '.bak' -or $_.Name -eq 'smoke_test.exe' } |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName }
    }
    else {
        Copy-Item -LiteralPath (Join-Path $sourceRoot 'resource') -Destination (Join-Path $installRoot 'resource') -Recurse
    }
    & (Join-Path $PSScriptRoot 'CopyPersonalPayload.ps1') -SourceDir $sourceRoot -InstallDir $installRoot -IdentityFile (Join-Path $workspaceRoot 'personal-build.json')
    if ($job.kind -eq 'app') {
        # Exercise the production package planner and native installer in isolated fixtures.
        Invoke-Checked $Dotnet @('run', '--project', 'tools/PersonalUpdateTests/Installer/InstallerTests.csproj', '-c', 'Release',
            '--', (Join-Path $installRoot 'MAA.dll'), (Join-Path $installRoot 'MAA.Updater.exe'),
            (Join-Path $workspaceRoot 'installer-validation'))
    }
}
finally { Pop-Location }
