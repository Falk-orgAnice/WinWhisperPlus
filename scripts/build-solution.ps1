[CmdletBinding()]
param(
    [ValidateSet("Debug", "Release")][string]$Configuration = "Debug",
    [ValidateSet("x64")][string]$Platform = "x64",
    [ValidateSet("Build", "Rebuild", "Clean")][string]$Action = "Build"
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$outputRoot = Join-Path $repoRoot "Bin"
$outputDirectory = Join-Path $outputRoot $Configuration
$workDirectory = Join-Path $repoRoot "build\vs\$Configuration\pyinstaller"
$pythonExe = Join-Path $repoRoot ".venv-build\Scripts\python.exe"

function Assert-WorkspaceDirectory([string]$Path) {
    $resolved = [System.IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith($repoRoot + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Build-Pfad liegt ausserhalb der Solution: $resolved"
    }
    # Reject junctions/symlinks at every level before deleting or writing.
    $ancestor = $resolved
    while ($ancestor -ne $repoRoot) {
        if ((Test-Path -LiteralPath $ancestor) -and
            ((Get-Item -Force -LiteralPath $ancestor).Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            throw "Build-Pfad darf keine Verknuepfung enthalten: $ancestor"
        }
        $ancestor = Split-Path -Parent $ancestor
    }
}

function Remove-ConfigurationDirectory([string]$Path) {
    Assert-WorkspaceDirectory $Path
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

Assert-WorkspaceDirectory $outputDirectory
Assert-WorkspaceDirectory $workDirectory
if ($Action -in @("Clean", "Rebuild")) {
    Remove-ConfigurationDirectory $outputDirectory
    Remove-ConfigurationDirectory $workDirectory
}
if ($Action -eq "Clean") {
    Write-Host "$Configuration|$Platform bereinigt. Andere Konfigurationen und Laufzeit-Caches bleiben erhalten."
    return
}

$previousConfiguration = $env:WINWHISPERPLUS_BUILD_CONFIGURATION
$previousPackage = $env:WINWHISPERPLUS_PACKAGE_NAME
$previousWhisper = $env:WINWHISPERPLUS_WHISPERCPP_DIR
$previousTextOptimizer = $env:WINWHISPERPLUS_TEXTOPTIMIZER_DIR
$previousWhisperCpu = $env:WINWHISPERPLUS_WHISPERCPP_CPU_DIR
$previousTextCpu = $env:WINWHISPERPLUS_TEXTOPTIMIZER_CPU_DIR
Push-Location $repoRoot
try {
    # Preparation never increments VERSION, signs files, builds an installer,
    # or removes build/runtime caches. A clean checkout bootstraps them once.
    & (Join-Path $PSScriptRoot "build-release.ps1") -PrepareOnly -ReuseRuntimes -ReuseEnvironment
    if (-not $?) { throw "Build-Vorbereitung fehlgeschlagen." }

    $validateArchitecture = @'
import pathlib, struct, sys
if struct.calcsize('P') != 8:
    raise SystemExit('Only 64-bit Python is supported')
for filename in sys.argv[1:]:
    with pathlib.Path(filename).open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise SystemExit(f'Invalid Windows executable: {filename}')
        stream.seek(0x3c)
        offset = struct.unpack('<I', stream.read(4))[0]
        stream.seek(offset)
        if stream.read(4) != b'PE\0\0' or struct.unpack('<H', stream.read(2))[0] != 0x8664:
            raise SystemExit(f'Expected x64 executable: {filename}')
'@
    & $pythonExe -c $validateArchitecture `
        (Join-Path $env:WINWHISPERPLUS_WHISPERCPP_DIR "whisper-cli.exe") `
        (Join-Path $env:WINWHISPERPLUS_WHISPERCPP_DIR "whisper-server.exe") `
        (Join-Path $env:WINWHISPERPLUS_TEXTOPTIMIZER_DIR "llama-server.exe")
    if ($LASTEXITCODE -ne 0) { throw "Laufzeiten muessen fuer x64 gebaut sein." }
    & $pythonExe -c $validateArchitecture `
        (Join-Path $env:WINWHISPERPLUS_WHISPERCPP_CPU_DIR "whisper-cli.exe") `
        (Join-Path $env:WINWHISPERPLUS_WHISPERCPP_CPU_DIR "whisper-server.exe") `
        (Join-Path $env:WINWHISPERPLUS_TEXTOPTIMIZER_CPU_DIR "llama-server.exe")
    if ($LASTEXITCODE -ne 0) { throw "Laufzeiten muessen fuer x64 gebaut sein." }

    $env:WINWHISPERPLUS_BUILD_CONFIGURATION = $Configuration
    $env:WINWHISPERPLUS_PACKAGE_NAME = $Configuration
    Write-Host "Baue $Configuration|$Platform nach $outputDirectory"
    & $pythonExe -m PyInstaller --noconfirm --distpath $outputRoot --workpath $workDirectory `
        (Join-Path $repoRoot "WinWhisperPlus.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller-Build fehlgeschlagen (Exitcode $LASTEXITCODE)." }
    $executable = Join-Path $outputDirectory "WinWhisperPlus.exe"
    if (-not (Test-Path -LiteralPath $executable)) { throw "Build-Ausgabe fehlt: $executable" }
    & $pythonExe -c $validateArchitecture $executable
    if ($LASTEXITCODE -ne 0) { throw "Build-Ausgabe ist keine x64-Anwendung." }
    & $pythonExe (Join-Path $PSScriptRoot "runtime_bundle.py") --package $outputDirectory
    if ($LASTEXITCODE -ne 0) { throw "Paketabhaengigkeiten sind unvollstaendig." }
    Write-Host "Build erfolgreich: $executable"
} finally {
    $env:WINWHISPERPLUS_BUILD_CONFIGURATION = $previousConfiguration
    $env:WINWHISPERPLUS_PACKAGE_NAME = $previousPackage
    $env:WINWHISPERPLUS_WHISPERCPP_DIR = $previousWhisper
    $env:WINWHISPERPLUS_TEXTOPTIMIZER_DIR = $previousTextOptimizer
    $env:WINWHISPERPLUS_WHISPERCPP_CPU_DIR = $previousWhisperCpu
    $env:WINWHISPERPLUS_TEXTOPTIMIZER_CPU_DIR = $previousTextCpu
    Pop-Location
}
