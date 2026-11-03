[CmdletBinding()]
param(
    [string]$Thumbprint,
    [string]$TimestampServer,
    [string]$InnoCompilerPath,
    [string]$VerifyUninstallerPath,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))

function Stop-ReleaseSigning([string]$Message) {
    Write-Error "NeDotify release signing: $Message"
    exit 1
}

function Get-CodeSigningCertificate([string]$RequestedThumbprint) {
    $normalized = ($RequestedThumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
    if ($normalized.Length -ne 40) {
        Stop-ReleaseSigning 'pass -Thumbprint with the 40-character SHA-1 thumbprint of your code-signing certificate in Cert:\CurrentUser\My.'
    }

    $cert = Get-ChildItem -Path Cert:\CurrentUser\My | Where-Object {
        (($_.Thumbprint -replace '\s', '').ToUpperInvariant()) -eq $normalized
    } | Select-Object -First 1
    if (-not $cert) {
        Stop-ReleaseSigning "certificate $normalized was not found in Cert:\CurrentUser\My. Install the user's code-signing certificate first."
    }
    if (-not $cert.HasPrivateKey) {
        Stop-ReleaseSigning "certificate $normalized has no accessible private key."
    }
    $now = Get-Date
    if ($cert.NotBefore -gt $now -or $cert.NotAfter -le $now) {
        Stop-ReleaseSigning "certificate $normalized is not currently valid (validity: $($cert.NotBefore) to $($cert.NotAfter))."
    }

    $hasCodeSigningEku = $false
    foreach ($extension in $cert.Extensions) {
        if ($extension -is [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]) {
            foreach ($oid in $extension.EnhancedKeyUsages) {
                if ($oid.Value -eq '1.3.6.1.5.5.7.3.3') { $hasCodeSigningEku = $true }
            }
        }
    }
    if (-not $hasCodeSigningEku) {
        Stop-ReleaseSigning "certificate $normalized does not contain the Code Signing EKU."
    }
    return $cert
}

function Assert-Authenticode([string]$Path, [string]$ExpectedThumbprint) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Stop-ReleaseSigning "expected signed file does not exist: $Path"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        Stop-ReleaseSigning "Authenticode verification failed for '$Path': $($signature.Status) $($signature.StatusMessage)"
    }
    $actual = ($signature.SignerCertificate.Thumbprint -replace '\s', '').ToUpperInvariant()
    if ($actual -ne $ExpectedThumbprint) {
        Stop-ReleaseSigning "'$Path' is signed by unexpected certificate $actual (expected $ExpectedThumbprint)."
    }
}

function Invoke-SignTool([string]$Path, [string]$CertificateThumbprint, [string]$TimestampUrl) {
    $arguments = @('sign', '/sha1', $CertificateThumbprint, '/s', 'My', '/fd', 'SHA256', '/tr', $TimestampUrl, '/td', 'SHA256', $Path)
    & $script:SignToolPath @arguments
    if ($LASTEXITCODE -ne 0) {
        Stop-ReleaseSigning "signtool.exe failed for '$Path' with exit code $LASTEXITCODE."
    }
    Assert-Authenticode -Path $Path -ExpectedThumbprint $CertificateThumbprint
}

if ($VerifyUninstallerPath) {
    $expected = ($Thumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
    if ($expected.Length -ne 40) {
        Stop-ReleaseSigning 'pass -Thumbprint with the expected 40-character certificate thumbprint when verifying an installed uninstaller.'
    }
    Assert-Authenticode -Path $VerifyUninstallerPath -ExpectedThumbprint $expected
    Write-Host "Authenticode signature verified: $VerifyUninstallerPath"
    exit 0
}

$script:ReleaseCertificate = Get-CodeSigningCertificate -RequestedThumbprint $Thumbprint
$normalizedThumbprint = ($Thumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()

if ([string]::IsNullOrWhiteSpace($TimestampServer)) {
    Stop-ReleaseSigning 'pass -TimestampServer with the release timestamp service URL; release artifacts must be timestamped.'
}
$timestampUri = $null
if (-not [Uri]::TryCreate($TimestampServer, [UriKind]::Absolute, [ref]$timestampUri) -or $timestampUri.Scheme -notin @('http', 'https')) {
    Stop-ReleaseSigning '-TimestampServer must be an absolute http or https URL.'
}

$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
    Stop-ReleaseSigning 'signtool.exe was not found on PATH. Install the Windows SDK signing tools.'
}
$script:SignToolPath = $signtool.Source
if (-not $InnoCompilerPath) {
    $compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($compiler) { $InnoCompilerPath = $compiler.Source }
}
if (-not $InnoCompilerPath -or -not (Test-Path -LiteralPath $InnoCompilerPath -PathType Leaf)) {
    Stop-ReleaseSigning 'ISCC.exe was not found. Install Inno Setup or pass -InnoCompilerPath.'
}

if ($ValidateOnly) {
    Write-Host "Signing prerequisites valid for certificate $normalizedThumbprint ($($script:ReleaseCertificate.Subject))."
    exit 0
}

$distPath = Join-Path $repoRoot 'dist'
$appExe = Join-Path $distPath 'NeDotify.exe'
$setupExe = Join-Path $distPath 'NeDotify_Setup.exe'
$installerScript = Join-Path $repoRoot 'installer.iss'
if (-not (Test-Path -LiteralPath $appExe -PathType Leaf)) {
    Stop-ReleaseSigning "PyInstaller output is missing: $appExe. Build it before signing."
}
if (-not (Test-Path -LiteralPath $installerScript -PathType Leaf)) {
    Stop-ReleaseSigning "Inno script is missing: $installerScript"
}

Write-Host "Signing $appExe"
Invoke-SignTool -Path $appExe -CertificateThumbprint $normalizedThumbprint -TimestampUrl $TimestampServer

# Inno invokes the same Windows SDK signer for both Setup and its signed
# uninstaller. The file placeholder ($f) is substituted by ISCC at compile time.
$signToolCommand = '$q' + $signtool.Source + '$q sign /sha1 ' + $normalizedThumbprint +
    ' /s My /fd SHA256 /tr $q' + $TimestampServer + '$q /td SHA256 $f'
$compilerArgs = @(
    '--define=NEDOTIFY_RELEASE_SIGNING=1',
    "--signtool=NeDotifyRelease=$signToolCommand",
    $installerScript
)
Write-Host 'Compiling installer with signed-uninstaller support enabled.'
Push-Location $repoRoot
try {
    & $InnoCompilerPath @compilerArgs
    $compileExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($compileExitCode -ne 0) {
    Stop-ReleaseSigning "ISCC failed with exit code $compileExitCode. The release installer was not verified."
}
Assert-Authenticode -Path $setupExe -ExpectedThumbprint $normalizedThumbprint
Write-Host "Release signing verified: $appExe and $setupExe"
Write-Host 'Inno Setup signed its uninstaller template through the same SignTool command. Verify an installed unins*.exe with -VerifyUninstallerPath before publishing.'
