"""Reject operating systems which cannot execute the shipped interpreter."""
from pathlib import Path


def test_installer_requires_windows_10_and_native_x64():
    script = (Path(__file__).resolve().parents[1] / 'installer.iss').read_text(encoding='utf-8')
    setup = script.split('[Setup]', 1)[1].split('[Languages]', 1)[0]
    directives = dict(line.split('=', 1) for line in setup.splitlines()
                      if '=' in line and not line.lstrip().startswith(';'))
    assert directives['MinVersion'] == '10.0'
    assert directives['ArchitecturesAllowed'] == 'x64os'
