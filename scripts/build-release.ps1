[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipSigning,
    [switch]$SkipInstaller,
    [string]$AppVersion,
    [string]$InnoSetupCompilerPath,
    [string]$CertificateThumbprint = "d7e33e34882d111c4a3eb5cf0175bea39ecf8a29",
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $repoRoot ".venv-build"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
$distDir = Join-Path $repoRoot "dist"
$appDistDir = Join-Path $distDir "WinWhisperPlus"
$appExePath = Join-Path $appDistDir "WinWhisperPlus.exe"
$zipPath = Join-Path $distDir "WinWhisperPlus.zip"
$installerScriptPath = Join-Path $repoRoot "installer\WinWhisperPlus.iss"
$installerBaseExePath = Join-Path $distDir "WinWhisperPlus-Setup.exe"
$versionFilePath = Join-Path $repoRoot "VERSION"
$pythonVersionArgs = @("-3.14", "-3.13", "-3.12", "-3.11", "-3.10")
$whisperCppVersion = "v1.9.1"
$llamaCppVersion = "b9999"
$whisperCppWorkDir = Join-Path $env:TEMP "wwp-wcpp"
$whisperCppSourceDir = Join-Path $whisperCppWorkDir "src"
$whisperCppBuildDir = Join-Path $whisperCppWorkDir "build"
$whisperCppRuntimeDir = Join-Path $repoRoot "build\whispercpp-runtime"
$llamaCppWorkDir = Join-Path $env:TEMP "wwp-llama"
$llamaCppSourceDir = Join-Path $llamaCppWorkDir "src"
$llamaCppBuildDir = Join-Path $llamaCppWorkDir "build"
$textOptimizerRuntimeDir = Join-Path $repoRoot "build\textoptimizer-runtime"
$textModelDir = Join-Path $textOptimizerRuntimeDir "models"
$textModelFileName = "Qwen_Qwen3-4B-Q4_K_M.gguf"
$textModelPath = Join-Path $textModelDir $textModelFileName
$textModelUrl = "https://huggingface.co/bartowski/Qwen_Qwen3-4B-GGUF/resolve/main/$textModelFileName"

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action
    )

    Write-Host ""
    Write-Host "==> $Name"
    & $Action
}

function Remove-BuildPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        return
    }

    try {
        Remove-Item -Recurse -Force $Path
    } catch {
        throw "Konnte '$Path' nicht loeschen. Bitte pruefen, ob WinWhisperPlus.exe oder ein Prozess aus dem dist-Ordner noch laeuft, und den Build danach erneut starten. Originalfehler: $($_.Exception.Message)"
    }
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$ErrorMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage Exitcode: $LASTEXITCODE"
    }
}

function Resolve-InnoSetupCompiler {
    if ($InnoSetupCompilerPath) {
        if (-not (Test-Path $InnoSetupCompilerPath)) {
            throw "Inno Setup Compiler wurde nicht gefunden: $InnoSetupCompilerPath"
        }
        return (Resolve-Path $InnoSetupCompilerPath).Path
    }

    $isccCommand = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($isccCommand) {
        return $isccCommand.Source
    }

    $candidatePaths = @(
        "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 7\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidatePath in $candidatePaths) {
        if ($candidatePath -and (Test-Path $candidatePath)) {
            return $candidatePath
        }
    }

    throw "Inno Setup Compiler 'iscc.exe' wurde nicht gefunden. Bitte Inno Setup 7 oder 6 installieren oder -InnoSetupCompilerPath angeben."
}

function Resolve-CMake {
    $cmakeCommand = Get-Command cmake.exe -ErrorAction SilentlyContinue
    if ($cmakeCommand) {
        return $cmakeCommand.Source
    }

    $vswherePath = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswherePath) {
        $vsInstallPath = & $vswherePath -latest -products * `
            -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($vsInstallPath) {
            $visualStudioCmake = Join-Path $vsInstallPath "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
            if (Test-Path $visualStudioCmake) {
                return $visualStudioCmake
            }
        }
    }

    throw "CMake wurde nicht gefunden. Installiere CMake oder die Visual-Studio-Komponente fuer CMake-Unterstuetzung."
}

function Resolve-VulkanSdk {
    $sdkPath = $env:VULKAN_SDK
    if (-not $sdkPath) {
        $sdkPath = Get-ChildItem "C:\VulkanSDK" -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            Where-Object { Test-Path (Join-Path $_.FullName "Bin\glslc.exe") } |
            Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $sdkPath -or -not (Test-Path (Join-Path $sdkPath "Bin\glslc.exe"))) {
        throw "Das Vulkan SDK wurde nicht gefunden. Installiere das LunarG Vulkan SDK und setze VULKAN_SDK."
    }
    return $sdkPath
}

function Build-WhisperCppVulkanRuntime {
    $cmakeExe = Resolve-CMake
    $vulkanSdk = Resolve-VulkanSdk
    $env:VULKAN_SDK = $vulkanSdk
    $gitExe = Get-Command git.exe -ErrorAction SilentlyContinue
    if (-not $gitExe) {
        throw "Git wurde nicht gefunden. Es wird benoetigt, um whisper.cpp $whisperCppVersion abzurufen."
    }

    if (Test-Path $whisperCppWorkDir) {
        Remove-Item -Recurse -Force $whisperCppWorkDir
    }
    New-Item -ItemType Directory -Force -Path $whisperCppWorkDir | Out-Null

    Invoke-NativeCommand {
        & $gitExe.Source clone --depth 1 --branch $whisperCppVersion `
            https://github.com/ggml-org/whisper.cpp.git $whisperCppSourceDir
    } "whisper.cpp konnte nicht abgerufen werden."

    Invoke-NativeCommand {
        & $cmakeExe -S $whisperCppSourceDir -B $whisperCppBuildDir `
            -DGGML_VULKAN=1 -DWHISPER_BUILD_TESTS=OFF `
            "-DVulkan_ROOT=$vulkanSdk"
    } "whisper.cpp konnte nicht fuer Vulkan konfiguriert werden."
    Invoke-NativeCommand {
        & $cmakeExe --build $whisperCppBuildDir --config Release --target whisper-cli whisper-server
    } "whisper.cpp konnte nicht gebaut werden."

    $cli = Get-ChildItem -Path $whisperCppBuildDir -Recurse -Filter "whisper-cli.exe" |
        Select-Object -First 1
    if (-not $cli) {
        throw "Der whisper.cpp-Build hat keine whisper-cli.exe erzeugt."
    }
    if (-not (Test-Path (Join-Path $cli.DirectoryName "whisper-server.exe"))) {
        throw "Der whisper.cpp-Build hat keine whisper-server.exe erzeugt."
    }
    New-Item -ItemType Directory -Force -Path $whisperCppRuntimeDir | Out-Null
    Copy-Item -Path (Join-Path $cli.DirectoryName "*") -Destination $whisperCppRuntimeDir -Force
    $env:WINWHISPERPLUS_WHISPERCPP_DIR = $whisperCppRuntimeDir
}

function Build-TextOptimizerRuntime {
    $cmakeExe = Resolve-CMake
    $vulkanSdk = Resolve-VulkanSdk
    $env:VULKAN_SDK = $vulkanSdk
    $gitExe = Get-Command git.exe -ErrorAction SilentlyContinue
    if (-not $gitExe) {
        throw "Git wurde nicht gefunden. Es wird benoetigt, um llama.cpp $llamaCppVersion abzurufen."
    }

    if (Test-Path $llamaCppWorkDir) {
        Remove-Item -Recurse -Force $llamaCppWorkDir
    }
    New-Item -ItemType Directory -Force -Path $llamaCppWorkDir | Out-Null
    Invoke-NativeCommand {
        & $gitExe.Source clone --depth 1 --branch $llamaCppVersion `
            https://github.com/ggml-org/llama.cpp.git $llamaCppSourceDir
    } "llama.cpp konnte nicht abgerufen werden."
    Invoke-NativeCommand {
        & $cmakeExe -S $llamaCppSourceDir -B $llamaCppBuildDir `
            -DGGML_VULKAN=1 -DLLAMA_BUILD_TESTS=OFF `
            "-DVulkan_ROOT=$vulkanSdk"
    } "llama.cpp konnte nicht fuer Vulkan konfiguriert werden."
    Invoke-NativeCommand {
        & $cmakeExe --build $llamaCppBuildDir --config Release --target llama-server
    } "llama.cpp konnte nicht gebaut werden."

    $server = Get-ChildItem -Path $llamaCppBuildDir -Recurse -Filter "llama-server.exe" |
        Select-Object -First 1
    if (-not $server) {
        throw "Der llama.cpp-Build hat keine llama-server.exe erzeugt."
    }
    New-Item -ItemType Directory -Force -Path $textOptimizerRuntimeDir | Out-Null
    Copy-Item -Path (Join-Path $server.DirectoryName "*") -Destination $textOptimizerRuntimeDir -Force
    Copy-Item -Path (Join-Path $llamaCppSourceDir "LICENSE") `
        -Destination (Join-Path $textOptimizerRuntimeDir "LICENSE-llama.cpp") -Force

    New-Item -ItemType Directory -Force -Path $textModelDir | Out-Null
    Write-Host "Lade Qwen3-4B Q4_K_M Textmodell (einmalig fuer das Release)..."
    $curlExe = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curlExe) {
        throw "curl.exe wurde nicht gefunden. Es wird fuer den robusten Modell-Download benoetigt."
    }
    Invoke-NativeCommand {
        & $curlExe.Source --fail --location --retry 3 --retry-delay 2 `
            --output $textModelPath $textModelUrl
    } "Das Qwen3-Modell konnte nicht heruntergeladen werden."
    if ((Get-Item $textModelPath).Length -lt 1GB) {
        throw "Das heruntergeladene Qwen3-Modell ist unerwartet klein und wird nicht paketiert."
    }
    $modelHash = (Get-FileHash -Path $textModelPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -Path (Join-Path $textModelDir "text-model.sha256") `
        -Value "$modelHash  $textModelFileName" -NoNewline -Encoding ascii
    Invoke-WebRequest -Uri "https://www.apache.org/licenses/LICENSE-2.0.txt" `
        -OutFile (Join-Path $textOptimizerRuntimeDir "LICENSE-Qwen3-Apache-2.0.txt")
    $env:WINWHISPERPLUS_TEXTOPTIMIZER_DIR = $textOptimizerRuntimeDir
}

function Get-ReleaseVersion {
    if ($AppVersion) {
        if ($AppVersion -notmatch '^\d+\.\d+\.\d+$') {
            throw "AppVersion muss im Format Major.Minor.Patch angegeben werden, z. B. 1.0.1."
        }
        return $AppVersion
    }

    if (-not (Test-Path $versionFilePath)) {
        Set-Content -Path $versionFilePath -Value "1.0.0" -NoNewline -Encoding ascii
        return "1.0.0"
    }

    $currentVersion = (Get-Content $versionFilePath -Raw).Trim()
    if ($currentVersion -notmatch '^(\d+)\.(\d+)\.(\d+)$') {
        throw "VERSION enthaelt keine gueltige Version im Format Major.Minor.Patch: $currentVersion"
    }

    $nextPatch = [int]$Matches[3] + 1
    $nextVersion = "$($Matches[1]).$($Matches[2]).$nextPatch"
    Set-Content -Path $versionFilePath -Value $nextVersion -NoNewline -Encoding ascii
    return $nextVersion
}

function Set-CodeSignatureWithPowerShell {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath
    )

    $normalizedThumbprint = $CertificateThumbprint.Replace(" ", "").ToUpperInvariant()
    $certificate = Get-Item "Cert:\CurrentUser\My\$normalizedThumbprint" -ErrorAction SilentlyContinue
    if (-not $certificate) {
        $certificate = Get-Item "Cert:\LocalMachine\My\$normalizedThumbprint" -ErrorAction SilentlyContinue
    }
    if (-not $certificate) {
        $certificate = Get-ChildItem "Cert:\CurrentUser\My" -ErrorAction SilentlyContinue |
            Where-Object { $_.Thumbprint -eq $normalizedThumbprint } |
            Select-Object -First 1
    }
    if (-not $certificate) {
        $certificate = Get-ChildItem "Cert:\LocalMachine\My" -ErrorAction SilentlyContinue |
            Where-Object { $_.Thumbprint -eq $normalizedThumbprint } |
            Select-Object -First 1
    }

    if (-not $certificate) {
        throw "Zertifikat mit Thumbprint $CertificateThumbprint wurde im Benutzer- oder Maschinenzertifikatsspeicher nicht gefunden."
    }
    if (-not $certificate.HasPrivateKey) {
        throw "Zertifikat mit Thumbprint $CertificateThumbprint hat keinen verfuegbaren privaten Schluessel."
    }

    $signature = Set-AuthenticodeSignature `
        -FilePath $FilePath `
        -Certificate $certificate `
        -HashAlgorithm SHA256 `
        -TimestampServer $TimestampServer

    if ($signature.Status -ne "Valid") {
        throw "PowerShell-Signierung ist fehlgeschlagen. Status: $($signature.Status). $($signature.StatusMessage)"
    }
}

Set-Location $repoRoot
$releaseVersion = Get-ReleaseVersion
$installerExePath = Join-Path $distDir "WinWhisperPlus-Setup-$releaseVersion.exe"
Write-Host "Release-Version: $releaseVersion"

Invoke-Step "Pruefe Python" {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) {
        throw "Python Launcher 'py' wurde nicht gefunden. Bitte Python 3.10 bis 3.14 64-bit installieren."
    }

    $script:PythonLauncherArg = $null
    foreach ($versionArg in $pythonVersionArgs) {
        py $versionArg -c "import sys; raise SystemExit(0 if sys.maxsize > 2**32 else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $script:PythonLauncherArg = $versionArg
            break
        }
    }

    if (-not $script:PythonLauncherArg) {
        throw "Keine passende 64-bit Python-Version gefunden. Bitte Python 3.10 bis 3.14 installieren."
    }

    Write-Host "Verwende Python $script:PythonLauncherArg"
}

Invoke-Step "Erstelle Build-Umgebung" {
    if (-not (Test-Path $pythonExe)) {
        Invoke-NativeCommand {
            py $script:PythonLauncherArg -m venv $venvPath
        } "Virtuelle Build-Umgebung konnte nicht erstellt werden."
    }
    Invoke-NativeCommand {
        & $pythonExe -m pip install --upgrade pip
    } "pip konnte nicht aktualisiert werden."
    Invoke-NativeCommand {
        & $pythonExe -m pip install -r requirements.txt -r requirements-dev.txt
    } "Abhaengigkeiten konnten nicht installiert werden."
}

if (-not $SkipTests) {
    Invoke-Step "Fuehre Tests aus" {
        Invoke-NativeCommand {
            & $pythonExe -m pytest tests
        } "Tests sind fehlgeschlagen."
    }
}

Invoke-Step "Bereinige alte Build-Ausgaben" {
    Remove-BuildPath (Join-Path $repoRoot "build")
    Remove-BuildPath $appDistDir
    Remove-BuildPath $zipPath
    Remove-BuildPath $installerBaseExePath
    Remove-BuildPath $installerExePath
}

Invoke-Step "Baue whisper.cpp mit Vulkan" {
    Build-WhisperCppVulkanRuntime
}

Invoke-Step "Baue lokalen Textoptimierer mit Vulkan" {
    Build-TextOptimizerRuntime
}

Invoke-Step "Baue WinWhisperPlus.exe" {
    Invoke-NativeCommand {
        & $pythonExe -m PyInstaller --clean .\WinWhisperPlus.spec
    } "PyInstaller-Build ist fehlgeschlagen."
}

if (-not $SkipSigning) {
    Invoke-Step "Signiere WinWhisperPlus.exe" {
        if (-not (Test-Path $appExePath)) {
            throw "Build-Ausgabe wurde nicht gefunden: $appExePath"
        }
        Set-CodeSignatureWithPowerShell -FilePath $appExePath
    }
}

Invoke-Step "Erstelle ZIP-Paket" {
    if (-not (Test-Path $appDistDir)) {
        throw "Build-Ausgabe wurde nicht gefunden: $appDistDir"
    }
    Compress-Archive -Path (Join-Path $appDistDir "*") -DestinationPath $zipPath -Force
}

if (-not $SkipInstaller) {
    Invoke-Step "Baue Inno-Setup-Installer" {
        if (-not (Test-Path $installerScriptPath)) {
            throw "Inno-Setup-Skript wurde nicht gefunden: $installerScriptPath"
        }

        $isccPath = Resolve-InnoSetupCompiler
        $appVersionDefine = "/DAppVersion=`"$releaseVersion`""
        Invoke-NativeCommand {
            & $isccPath $appVersionDefine $installerScriptPath
        } "Inno-Setup-Installer konnte nicht erstellt werden."

        if (-not (Test-Path $installerBaseExePath)) {
            throw "Installer-Ausgabe wurde nicht gefunden: $installerBaseExePath"
        }
        Move-Item -Path $installerBaseExePath -Destination $installerExePath -Force
    }

    if (-not $SkipSigning) {
        Invoke-Step "Signiere Setup-EXE" {
            if (-not (Test-Path $installerExePath)) {
                throw "Installer-Ausgabe wurde nicht gefunden: $installerExePath"
            }
            Set-CodeSignatureWithPowerShell -FilePath $installerExePath
        }
    }
}

Write-Host ""
Write-Host "Release-Paket erstellt:"
Write-Host "  $appDistDir"
Write-Host "  $zipPath"
if (-not $SkipInstaller) {
    Write-Host "  $installerExePath"
}
