"""Create or remove the "GTNH Field Guide" desktop and Start-menu shortcuts (Windows).

Run through ``install_shortcuts.bat`` (or ``python -m gtnh_assistant.shortcuts [--remove]``). The shortcut
starts ``pythonw -m gtnh_assistant.launcher`` in the project folder, so no console window appears.
"""

import argparse
import base64
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "GTNH Field Guide"


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def script(remove=False, root=ROOT):
    """PowerShell that writes or deletes the .lnk files. Desktop lookup follows OneDrive redirection."""
    folders = "@([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))"
    if remove:
        return (
            f"foreach ($dir in {folders}) {{ $lnk = Join-Path $dir {ps_quote(NAME + '.lnk')}; "
            'if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk; "Removed $lnk" } }'
        )
    target = root / ".venv" / "Scripts" / "pythonw.exe"
    icon = root / "assets" / "gtnh.ico"
    return (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"foreach ($dir in {folders}) {{ $lnk = Join-Path $dir {ps_quote(NAME + '.lnk')}; "
        "$s = $shell.CreateShortcut($lnk); "
        f"$s.TargetPath = {ps_quote(target)}; "
        "$s.Arguments = '-m gtnh_assistant.launcher'; "
        f"$s.WorkingDirectory = {ps_quote(root)}; "
        f"$s.IconLocation = {ps_quote(str(icon) + ',0')}; "
        "$s.Description = 'Local GT New Horizons wiki assistant'; "
        '$s.Save(); "Created $lnk" }'
    )


def run_powershell(code):
    # -EncodedCommand avoids every cmd/PowerShell quoting problem; inline commands are not blocked by
    # the script execution policy (only .ps1 files are).
    encoded = base64.b64encode(code.encode("utf-16-le")).decode()
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
    ).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remove", action="store_true", help="delete the shortcuts instead")
    args = parser.parse_args()
    if sys.platform != "win32":
        sys.exit("Shortcuts can only be created on Windows.")
    if not args.remove and not (ROOT / ".venv" / "Scripts" / "pythonw.exe").exists():
        sys.exit("The .venv was not found. Install the app first (see README, step 2).")
    sys.exit(run_powershell(script(args.remove)))


if __name__ == "__main__":
    main()
