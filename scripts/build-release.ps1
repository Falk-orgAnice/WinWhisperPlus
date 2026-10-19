[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipSigning,
    [switch]$SkipInstaller,
    [switch]$PrepareOnly,
    [switch]$ReuseRuntimes,
    [switch]$ReuseEnvironment,
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
$whisperCppVersion = "v1.9.4"
$llamaCppVersion = "v0.6.0"
$whisperCppWorkDir = Join-Path $env:TEMP "wwp-wcpp"
$whisperCppSourceDir = Join-Path $whisperCppWorkDir "src"
$whisperCppBuildDir = Join-Path $whisperCppWorkDir "build"
$whisperCppRuntimeDir = Join-Path $repoRoot "build\whispercpp-runtime"
$llamaCppWorkDir = Join-Path $env:TEMP "wwp-llama"
$llamaCppSourceDir = Join-Path $llamaCppWorkDir "src"
$llamaCppBuildDir = Join-Path $llamaCppWorkDir "build"
$textOptimizerRuntimeDir = Join-Path $repoRoot "build\textoptimizer-runtime"
$whisperCpuRuntimeDir = Join-Path $repoRoot "build\whispercpp-runtime-cpu"
$textCpuRuntimeDir = Join-Path $repoRoot "build\textoptimizer-runtime-cpu"
$portableInstallerScriptPath = Join-Path $repoRoot "installer\WinWhisperPlus-Portable.iss"
$vulkanLoaderVersion = "v1.4.350"
$vulkanLoaderRuntimeDir = Join-Path $repoRoot "build\vulkan-loader-runtime"

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

    $resolvedTarget = [System.IO.Path]::GetFullPath($Path)
    $allowedRoots = @((Join-Path $repoRoot "build"), (Join-Path $repoRoot "dist"))
    $insideBuildRoot = $false
    foreach ($allowedRoot in $allowedRoots) {
        $resolvedRoot = [System.IO.Path]::GetFullPath($allowedRoot)
        if ($resolvedTarget -eq $resolvedRoot -or $resolvedTarget.StartsWith($resolvedRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            $insideBuildRoot = $true
        }
    }
    if (-not $insideBuildRoot -or ((Get-Item -LiteralPath $resolvedTarget).Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw "Unsicherer Build-Loeschpfad: $resolvedTarget"
    }

    try {
        Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
    } catch {
        throw "Konnte '$Path' nicht loeschen. Bitte pruefen, ob WinWhisperPlus.exe oder ein Prozess aus dem dist-Ordner noch laeuft, und den Build danach erneut starten. Originalfehler: $($_.Exception.Message)"
    }
}

function Remove-TemporaryBuildPath {
    param([string]$Path, [string]$ExpectedName)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $resolvedTarget = [System.IO.Path]::GetFullPath($Path)
    $expectedTarget = [System.IO.Path]::GetFullPath((Join-Path $env:TEMP $ExpectedName))
    if ($resolvedTarget -ne $expectedTarget -or ((Get-Item -LiteralPath $resolvedTarget).Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw "Unsicherer temporaerer Build-Loeschpfad: $resolvedTarget"
    }
    Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
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
        "${env:LOCALAPPDATA}\Programs\Inno Setup 7\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe",
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
        Remove-TemporaryBuildPath $whisperCppWorkDir "wwp-wcpp"
    }
    New-Item -ItemType Directory -Force -Path $whisperCppWorkDir | Out-Null

    Invoke-NativeCommand {
        & $gitExe.Source clone --depth 1 --branch $whisperCppVersion `
            https://github.com/ggml-org/whisper.cpp.git $whisperCppSourceDir
    } "whisper.cpp konnte nicht abgerufen werden."

    Invoke-NativeCommand {
        & $pythonExe (Join-Path $PSScriptRoot "patch-whisper-timestamps.py") $whisperCppSourceDir
    } "VAD-Zeitmarken konnten nicht korrigiert werden."
    Invoke-NativeCommand {
        & $cmakeExe -S $whisperCppSourceDir -B $whisperCppBuildDir `
            -A x64 -DGGML_VULKAN=1 -DWHISPER_BUILD_TESTS=OFF `
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
        Remove-TemporaryBuildPath $llamaCppWorkDir "wwp-llama"
    }
    New-Item -ItemType Directory -Force -Path $llamaCppWorkDir | Out-Null
    Invoke-NativeCommand {
        & $gitExe.Source clone --depth 1 --branch $llamaCppVersion `
            https://github.com/ggml-org/llama.cpp.git $llamaCppSourceDir
    } "llama.cpp konnte nicht abgerufen werden."
    Invoke-NativeCommand {
        & $cmakeExe -S $llamaCppSourceDir -B $llamaCppBuildDir `
            -A x64 -DGGML_VULKAN=1 -DLLAMA_BUILD_TESTS=OFF `
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

    $env:WINWHISPERPLUS_TEXTOPTIMIZER_DIR = $textOptimizerRuntimeDir
}

function Build-CpuRuntime {
    param([ValidateSet("whispercpp", "textoptimizer")][string]$Kind)
    $isWhisper = $Kind -eq "whispercpp"
    $source = Join-Path $repoRoot "build\cpu-sources\$Kind"
    $version = if ($isWhisper) { $whisperCppVersion } else { $llamaCppVersion }
    $repository = if ($isWhisper) { "whisper.cpp" } else { "llama.cpp" }
    $destination = if ($isWhisper) { $whisperCpuRuntimeDir } else { $textCpuRuntimeDir }
    $filename = if ($isWhisper) { "whisper-cli.exe" } else { "llama-server.exe" }
    $marker = Join-Path $destination "BUILD-CPU.txt"
    $buildIdentity = "$repository $version CPU dispatch-x64 v3"
    if ($ReuseRuntimes -and (Test-Path (Join-Path $destination $filename)) -and
        (Test-Path $marker) -and (Get-Content -Raw $marker).Trim() -eq $buildIdentity) {
        Write-Host "Verwende vorhandene CPU-Laufzeit: $Kind"
        return
    }
    # Reuse only the exact pinned checkout (including the Whisper timestamp fix).
    if (-not (Test-Path (Join-Path $source "CMakeLists.txt"))) {
        # A failed clone may have left an incomplete .git directory.
        Remove-BuildPath $source
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $source) | Out-Null
        Invoke-NativeCommand {
            git clone --depth 1 --branch $version "https://github.com/ggml-org/$repository.git" $source
        } "CPU-Quellcode konnte nicht abgerufen werden."
    }
    $sourceTag = & git -c "safe.directory=$($source.Replace('\', '/'))" -C $source describe --tags --exact-match
    if ($LASTEXITCODE -ne 0 -or $sourceTag -ne $version) {
        throw "Unerwartete CPU-Quellversion in $source. Erwartet: $version"
    }
    if ($isWhisper) {
        Invoke-NativeCommand {
            & $pythonExe (Join-Path $PSScriptRoot "patch-whisper-timestamps.py") $source
        } "CPU-VAD-Zeitmarken konnten nicht korrigiert werden."
    }
    $cmakeExe = Resolve-CMake
    $cpuBuild = Join-Path $repoRoot "build\native-cpu\$Kind"
    # Remove old linked-backend outputs before switching to CPU dispatch DLLs.
    Remove-BuildPath $cpuBuild
    $options = @("-DGGML_VULKAN=OFF", "-DGGML_NATIVE=OFF", "-DGGML_AVX=OFF", "-DGGML_AVX2=OFF",
        "-DGGML_FMA=OFF", "-DGGML_F16C=OFF", "-DGGML_SSE42=OFF", "-DGGML_BMI2=OFF", "-DBUILD_SHARED_LIBS=ON",
        "-DGGML_BACKEND_DL=ON", "-DGGML_CPU_ALL_VARIANTS=ON")
    $options += if ($isWhisper) { "-DWHISPER_BUILD_TESTS=OFF" } else { "-DLLAMA_BUILD_TESTS=OFF" }
    Invoke-NativeCommand {
        & $cmakeExe -S $source -B $cpuBuild -A x64 @options
    } "CPU-Laufzeit konnte nicht konfiguriert werden."
    $targets = @(if ($isWhisper) { "whisper-cli"; "whisper-server" } else { "llama-server" })
    foreach ($target in $targets) {
        Invoke-NativeCommand {
            & $cmakeExe --build $cpuBuild --config Release --parallel 4 --target $target
        } "CPU-Laufzeit konnte nicht gebaut werden."
    }
    $executable = Get-ChildItem -Path $cpuBuild -Recurse -Filter $filename | Select-Object -First 1
    if (-not $executable) { throw "CPU-Build hat keine $filename erzeugt." }
    Remove-BuildPath $destination
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    Copy-Item -Path (Join-Path $executable.DirectoryName "*") -Destination $destination -Force
    Copy-Item -LiteralPath (Join-Path $source "LICENSE") -Destination (Join-Path $destination "LICENSE-$repository") -Force
    Set-Content -LiteralPath $marker -Value $buildIdentity -Encoding ascii
}

function Build-VulkanLoader {
    $marker = Join-Path $vulkanLoaderRuntimeDir "BUILD-Vulkan-Loader.txt"
    $identity = "Khronos Vulkan-Loader $vulkanLoaderVersion x64"
    if ($ReuseRuntimes -and (Test-Path (Join-Path $vulkanLoaderRuntimeDir "vulkan-1.dll")) -and
        (Test-Path $marker) -and (Get-Content -Raw $marker).Trim() -eq $identity) {
        Write-Host "Verwende vorhandenen lokalen Vulkan-Loader."
        return
    }
    foreach ($component in @("Vulkan-Headers", "Vulkan-Loader")) {
        $sourceName = if ($component -eq "Vulkan-Headers") { "vulkan-headers-src" } else { "vulkan-loader-src" }
        $source = Join-Path $repoRoot "build\$sourceName"
        if (-not (Test-Path (Join-Path $source "CMakeLists.txt"))) {
            Remove-BuildPath $source
            Invoke-NativeCommand {
                git clone --depth 1 --branch $vulkanLoaderVersion "https://github.com/KhronosGroup/$component.git" $source
            } "Khronos-Quellen konnten nicht geladen werden."
        }
        $sourceTag = & git -c "safe.directory=$($source.Replace('\', '/'))" -C $source describe --tags --exact-match
        if ($LASTEXITCODE -ne 0 -or $sourceTag -ne $vulkanLoaderVersion) {
            throw "Unerwartete Khronos-Quellversion in $source. Erwartet: $vulkanLoaderVersion"
        }
    }
    $cmakeExe = Resolve-CMake
    $headersSource = Join-Path $repoRoot "build\vulkan-headers-src"
    $headersBuild = Join-Path $repoRoot "build\vulkan-headers-build"
    $headersInstall = Join-Path $repoRoot "build\vulkan-headers-install"
    $loaderSource = Join-Path $repoRoot "build\vulkan-loader-src"
    $loaderBuild = Join-Path $repoRoot "build\vulkan-loader-build"
    Invoke-NativeCommand {
        & $cmakeExe -S $headersSource -B $headersBuild -A x64 "-DCMAKE_INSTALL_PREFIX=$headersInstall" -DVULKAN_HEADERS_ENABLE_TESTS=OFF
    } "Vulkan-Headers konnten nicht konfiguriert werden."
    Invoke-NativeCommand {
        & $cmakeExe --install $headersBuild --config Release
    } "Vulkan-Headers konnten nicht im Build-Ordner bereitgestellt werden."
    Invoke-NativeCommand {
        & $cmakeExe -S $loaderSource -B $loaderBuild -A x64 "-DVULKAN_HEADERS_INSTALL_DIR=$headersInstall" `
            -DBUILD_TESTS=OFF -DUPDATE_DEPS=OFF -DLOADER_CODEGEN=OFF
    } "Vulkan-Loader konnte nicht konfiguriert werden."
    Invoke-NativeCommand {
        & $cmakeExe --build $loaderBuild --config Release --parallel 4 --target vulkan
    } "Vulkan-Loader konnte nicht gebaut werden."
    $loader = Get-ChildItem -LiteralPath $loaderBuild -Recurse -Filter "vulkan-1.dll" | Select-Object -First 1
    if (-not $loader) { throw "Der Khronos-Build hat keine vulkan-1.dll erzeugt." }
    New-Item -ItemType Directory -Force -Path $vulkanLoaderRuntimeDir | Out-Null
    Copy-Item -LiteralPath $loader.FullName -Destination (Join-Path $vulkanLoaderRuntimeDir "vulkan-1.dll") -Force
    Copy-Item -LiteralPath (Join-Path $loaderSource "LICENSE.txt") -Destination (Join-Path $vulkanLoaderRuntimeDir "LICENSE-Vulkan-Loader.txt") -Force
    $cjson = Get-Content -Raw -LiteralPath (Join-Path $loaderSource "loader\cJSON.c")
    $cjsonLicense = $cjson.Substring(0, $cjson.IndexOf('*/') + 2)
    Set-Content -LiteralPath (Join-Path $vulkanLoaderRuntimeDir "LICENSE-cJSON.txt") -Value $cjsonLicense -Encoding UTF8
    Set-Content -LiteralPath $marker -Value $identity -Encoding ascii
}

function Get-ReleaseVersion {
    if ($AppVersion) {
        if ($AppVersion -notmatch '^\d+\.\d+\.\d+$') {
            throw "AppVersion muss im Format Major.Minor.Patch angegeben werden, z. B. 1.0.1."
        }
        Set-Content -LiteralPath $versionFilePath -Value $AppVersion -NoNewline -Encoding ascii
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
$releaseVersion = if ($PrepareOnly) { (Get-Content -LiteralPath $versionFilePath -Raw).Trim() } else { Get-ReleaseVersion }
$installerExePath = Join-Path $distDir "WinWhisperPlus-Setup-$releaseVersion.exe"
$portableZipPath = Join-Path $distDir "WinWhisperPlus-Portable-$releaseVersion-win-x64.zip"
$portableInstallerExePath = Join-Path $distDir "WinWhisperPlus-Portable-Setup-$releaseVersion.exe"
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
        & $pythonExe -c "import struct; raise SystemExit(0 if struct.calcsize('P') == 8 else 1)"
    } "Die Build-Umgebung muss 64-bit Python verwenden. Entferne die 32-bit .venv-build und starte erneut."
    if (-not $ReuseEnvironment) {
        Invoke-NativeCommand {
            & $pythonExe -m pip install --upgrade pip
        } "pip konnte nicht aktualisiert werden."
    }
    Invoke-NativeCommand {
        & $pythonExe -m pip --disable-pip-version-check install -r requirements-dev.txt
    } "Abhaengigkeiten konnten nicht installiert werden."
}

if (-not $SkipTests -and -not $PrepareOnly) {
    Invoke-Step "Fuehre Tests aus" {
        Invoke-NativeCommand {
            & $pythonExe -m pytest tests
        } "Tests sind fehlgeschlagen."
    }
}

if (-not $PrepareOnly) {
Invoke-Step "Bereinige alte Build-Ausgaben" {
    # Keep runtime caches and other configuration outputs; PyInstaller cleans its work.
    Remove-BuildPath (Join-Path $repoRoot "build\WinWhisperPlus")
    Remove-BuildPath $appDistDir
    Remove-BuildPath $zipPath
    Remove-BuildPath $installerBaseExePath
    Remove-BuildPath $installerExePath
    Remove-BuildPath $portableZipPath
    Remove-BuildPath $portableInstallerExePath
}
}

Invoke-Step "Baue whisper.cpp mit Vulkan" {
    if ($ReuseRuntimes -and (Test-Path (Join-Path $whisperCppRuntimeDir "whisper-cli.exe")) -and
        (Test-Path (Join-Path $whisperCppRuntimeDir "whisper-server.exe"))) {
        Write-Host "Verwende vorhandene whisper.cpp-Laufzeit."
    } else {
        Build-WhisperCppVulkanRuntime
    }
}

Invoke-Step "Baue lokalen Textoptimierer mit Vulkan" {
    if ($ReuseRuntimes -and (Test-Path (Join-Path $textOptimizerRuntimeDir "llama-server.exe"))) {
        Write-Host "Verwende vorhandene llama.cpp-Laufzeit."
    } else {
        Build-TextOptimizerRuntime
    }
}

$env:WINWHISPERPLUS_WHISPERCPP_DIR = $whisperCppRuntimeDir
$env:WINWHISPERPLUS_TEXTOPTIMIZER_DIR = $textOptimizerRuntimeDir
Invoke-Step "Baue CPU-Laufzeiten ohne Vulkan" {
    Build-CpuRuntime "whispercpp"
    Build-CpuRuntime "textoptimizer"
}
$env:WINWHISPERPLUS_WHISPERCPP_CPU_DIR = $whisperCpuRuntimeDir
$env:WINWHISPERPLUS_TEXTOPTIMIZER_CPU_DIR = $textCpuRuntimeDir
Invoke-Step "Baue lokalen Khronos Vulkan-Loader" {
    Build-VulkanLoader
}
if ($PrepareOnly) {
    Write-Host "Build-Abhaengigkeiten vorbereitet; VERSION und bestehende Pakete bleiben unveraendert."
    return
}

Invoke-Step "Baue WinWhisperPlus.exe" {
    Invoke-NativeCommand {
        & $pythonExe -m PyInstaller --clean .\WinWhisperPlus.spec
    } "PyInstaller-Build ist fehlgeschlagen."
}

Copy-Item -LiteralPath (Join-Path $repoRoot "assets\model-catalog.json") -Destination (Join-Path $distDir "model-catalog.json") -Force

Invoke-Step "Pruefe eigenstaendiges Programmpaket" {
    Invoke-NativeCommand {
        & $pythonExe (Join-Path $PSScriptRoot "runtime_bundle.py") --package $appDistDir
    } "Portable-Paketpruefung fehlgeschlagen."
    Invoke-NativeCommand {
        & $pythonExe (Join-Path $PSScriptRoot "check-bundle.py") --package $appDistDir
    } "Paket-Smoke-Test fehlgeschlagen."
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
    Copy-Item -LiteralPath $zipPath -Destination $portableZipPath -Force
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

        Invoke-NativeCommand {
            & $isccPath $appVersionDefine $portableInstallerScriptPath
        } "Portable-Benutzer-Setup konnte nicht erstellt werden."
        if (-not (Test-Path -LiteralPath $portableInstallerExePath)) {
            throw "Portable-Installer-Ausgabe wurde nicht gefunden: $portableInstallerExePath"
        }
    }

    if (-not $SkipSigning) {
        Invoke-Step "Signiere Setup-EXE" {
            if (-not (Test-Path $installerExePath)) {
                throw "Installer-Ausgabe wurde nicht gefunden: $installerExePath"
            }
            Set-CodeSignatureWithPowerShell -FilePath $installerExePath
            Set-CodeSignatureWithPowerShell -FilePath $portableInstallerExePath
        }
    }
}

Write-Host ""
Write-Host "Release-Paket erstellt:"
Write-Host "  $appDistDir"
Write-Host "  $zipPath"
Write-Host "  $portableZipPath"
if (-not $SkipInstaller) {
    Write-Host "  $installerExePath"
    Write-Host "  $portableInstallerExePath"
}
