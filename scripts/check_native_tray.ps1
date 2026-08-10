[CmdletBinding()]
param(
    [Parameter()]
    [string]$OutputDirectory = ".agent/native-tray"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)) {
    throw "Native tray verification requires Windows because it builds and inspects a Windows executable."
}

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$trayRoot = Join-Path $repositoryRoot "cmd/scribe-tray"
$outputPath = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    [System.IO.Path]::GetFullPath($OutputDirectory)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot $OutputDirectory))
}

New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$artifactA = Join-Path $outputPath "scribe-tray-windows-amd64-a.exe"
$artifactB = Join-Path $outputPath "scribe-tray-windows-amd64-b.exe"
$manifestPath = Join-Path $outputPath "manifest.json"
$manifestTemp = Join-Path $outputPath "manifest.json.tmp"

Remove-Item -LiteralPath @($artifactA, $artifactB, $manifestPath, $manifestTemp) `
    -Force -ErrorAction SilentlyContinue

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [string]$Label,
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )

    $output = & $Command 2>&1
    if ($LASTEXITCODE -ne 0) {
        $details = ($output | Out-String).Trim()
        throw "$Label failed with exit code $LASTEXITCODE.`n$details"
    }
    if ($output) {
        $output | Write-Output
    }
}

$previousEnvironment = @{
    CGO_ENABLED = $env:CGO_ENABLED
    GOOS = $env:GOOS
    GOARCH = $env:GOARCH
    GOAMD64 = $env:GOAMD64
    GOFLAGS = $env:GOFLAGS
    GOWORK = $env:GOWORK
}

$env:GOFLAGS = "-mod=readonly"
$env:GOWORK = "off"
Push-Location $trayRoot
try {
    $trackedExecutables = @(
        @(& git -C $repositoryRoot ls-files "cmd/scribe-tray/*.exe") |
            Where-Object { $_ -and (Test-Path (Join-Path $repositoryRoot $_)) }
    )
    if ($trackedExecutables.Count -ne 0) {
        throw "Native executables must be generated, not tracked: $($trackedExecutables -join ', ')"
    }

    Invoke-Checked "go mod tidy -diff" { go mod tidy -diff }
    Invoke-Checked "go mod verify" { go mod verify }
    $resolvedModules = @(
        Invoke-Checked "go list modules" {
            go list -m -mod=readonly -f `
                '{{.Path}} {{.Version}}{{if .Replace}} => {{.Replace.Path}} {{.Replace.Version}}{{end}}' `
                all
        } | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    )
    Invoke-Checked "go test" { go test ./... }
    Invoke-Checked "go vet" { go vet ./... }
    Invoke-Checked "govulncheck" {
        go run golang.org/x/vuln/cmd/govulncheck@v1.6.0 ./...
    }

    $env:CGO_ENABLED = "0"
    $env:GOOS = "windows"
    $env:GOARCH = "amd64"
    $env:GOAMD64 = "v1"
    $buildArguments = @(
        "build",
        "-trimpath",
        "-buildvcs=true",
        "-ldflags=-s -w"
    )
    Invoke-Checked "first native tray build" {
        go @buildArguments -o $artifactA .
    }
    Invoke-Checked "second native tray build" {
        go @buildArguments -o $artifactB .
    }

    $hashA = (Get-FileHash -LiteralPath $artifactA -Algorithm SHA256).Hash
    $hashB = (Get-FileHash -LiteralPath $artifactB -Algorithm SHA256).Hash
    if ($hashA -ne $hashB) {
        throw "Native tray builds are not reproducible: $hashA != $hashB"
    }

    $head = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $head) {
        throw "Could not resolve the source commit for native build metadata."
    }
    $trackedChanges = @(& git status --porcelain --untracked-files=no)
    $sourceDirty = $trackedChanges.Count -ne 0
    $buildInfo = (& go version -m $artifactA 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read embedded native build metadata.`n$buildInfo"
    }
    if ($buildInfo -notmatch "vcs\.revision=$([regex]::Escape($head))") {
        throw "Native build metadata does not name the current source commit $head."
    }
    if (-not $sourceDirty -and $buildInfo -notmatch "vcs\.modified=false") {
        throw "A clean checkout produced native metadata marked as modified."
    }

    $digestInput = [System.Text.Encoding]::UTF8.GetBytes(($resolvedModules -join "`n"))
    $digestAlgorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        # BitConverter works on Windows PowerShell 5.1 and PowerShell 7+;
        # Convert.ToHexString is not available on older runtimes.
        $resolvedModuleGraphDigest = (
            [System.BitConverter]::ToString($digestAlgorithm.ComputeHash($digestInput))
        ).Replace("-", "")
    }
    finally {
        $digestAlgorithm.Dispose()
    }

    $projectText = Get-Content -LiteralPath (Join-Path $repositoryRoot "pyproject.toml") -Raw
    $versionMatch = [regex]::Match(
        $projectText,
        '(?ms)^\[project\]\s.*?^version\s*=\s*"([^"]+)"'
    )
    if (-not $versionMatch.Success) {
        throw "Could not resolve the project version from pyproject.toml."
    }

    $artifact = Get-Item -LiteralPath $artifactA
    $signature = Get-AuthenticodeSignature -LiteralPath $artifactA
    $manifest = [ordered]@{
        schema_version = 2
        generated_at = [DateTimeOffset]::UtcNow.ToString("o")
        product_version = $versionMatch.Groups[1].Value
        source_commit = $head
        source_dirty = $sourceDirty
        go_version = (& go version).Trim()
        govulncheck_version = "v1.6.0"
        resolved_module_graph_sha256 = $resolvedModuleGraphDigest
        resolved_modules = $resolvedModules
        build_command = "go build -trimpath -buildvcs=true -ldflags=`"-s -w`""
        platform = "windows/amd64/v1"
        cgo_enabled = $false
        artifact = [ordered]@{
            path = $artifact.Name
            size_bytes = $artifact.Length
            sha256 = $hashA
            reproducible_second_sha256 = $hashB
            authenticode_status = $signature.Status.ToString()
            official_release_ready = $false
        }
        embedded_build_info = $buildInfo -split "`n"
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestTemp -Encoding utf8
    Move-Item -LiteralPath $manifestTemp -Destination $manifestPath -Force

    Write-Output "Native tray source contract passed."
    Write-Output "Artifact SHA-256: $hashA"
    Write-Output "Source commit: $head"
    Write-Output "Source dirty: $sourceDirty"
    Write-Output "Go toolchain: $($manifest.go_version)"
    Write-Output "Resolved module graph SHA-256: $resolvedModuleGraphDigest"
    Write-Output "Authenticode status: $($signature.Status)"
    Write-Output "Manifest: $manifestPath"
    Write-Output "Official release ready: false (unsigned developer verification artifact)"
}
catch {
    Remove-Item -LiteralPath @($artifactA, $artifactB, $manifestPath, $manifestTemp) `
        -Force -ErrorAction SilentlyContinue
    throw
}
finally {
    Pop-Location
    $env:CGO_ENABLED = $previousEnvironment.CGO_ENABLED
    $env:GOOS = $previousEnvironment.GOOS
    $env:GOARCH = $previousEnvironment.GOARCH
    $env:GOAMD64 = $previousEnvironment.GOAMD64
    $env:GOFLAGS = $previousEnvironment.GOFLAGS
    $env:GOWORK = $previousEnvironment.GOWORK
}
