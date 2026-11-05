import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SIGN_SCRIPT = ROOT / "tools" / "packaging" / "sign_release.ps1"
INSTALLER = ROOT / "installer.iss"


def test_signing_is_opt_in_for_inno_and_enables_signed_uninstaller():
    source = INSTALLER.read_text(encoding="utf-8")
    signing_block = source.split("#ifdef NEDOTIFY_RELEASE_SIGNING", 1)[1].split("#endif", 1)[0]
    assert "SignTool=NeDotifyRelease" in signing_block
    assert "SignedUninstaller=yes" in signing_block
    assert "--define=NEDOTIFY_RELEASE_SIGNING=1" in SIGN_SCRIPT.read_text(encoding="utf-8")


def test_release_script_requires_user_certificate_and_checks_signed_outputs():
    source = SIGN_SCRIPT.read_text(encoding="utf-8")
    assert "Cert:\\CurrentUser\\My" in source
    assert "1.3.6.1.5.5.7.3.3" in source
    assert "-not $cert.HasPrivateKey" in source
    assert "SignatureStatus]::Valid" in source
    assert "expected $ExpectedThumbprint" in source
    assert "-TimestampServer" in source
    assert "--signtool=NeDotifyRelease=" in source
    assert "-VerifyUninstallerPath" in source


def test_validate_only_fails_clearly_without_thumbprint_before_touching_artifacts():
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if not powershell:
        pytest.skip("PowerShell unavailable; script invocation is unverified")
    result = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SIGN_SCRIPT), "-ValidateOnly"],
        text=True,
        capture_output=True,
        timeout=15,
        encoding='utf-8', errors='replace',
    )
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "-Thumbprint" in output
    assert "40-character SHA-1 thumbprint" in output
