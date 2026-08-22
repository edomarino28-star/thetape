"""Create the Desktop shortcut, with the generated icon."""
import os
import subprocess

from . import makeicon

NAME = "The Tape"


def desktop_dir():
    """The real Desktop, which Windows often redirects into OneDrive."""
    for cand in (os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"),
                 os.path.join(os.path.expanduser("~"), "Desktop")):
        if os.path.isdir(cand):
            return cand
    return None


def create(target, name=NAME, icon=None, desc="The Tape - public trading disclosures, ranked"):
    """Point a Desktop .lnk at `target`. Returns the shortcut path, or None."""
    desk = desktop_dir()
    if not desk:
        return None
    icon = icon or makeicon.build()
    link = os.path.join(desk, name + ".lnk")

    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut({_q(link)})
$s.TargetPath = {_q(target)}
$s.IconLocation = {_q(icon + ",0")}
$s.Description = {_q(desc)}
$s.WorkingDirectory = {_q(os.path.dirname(target))}
$s.Save()
"""
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   check=True, capture_output=True)
    return link


def _q(s):
    return "'" + str(s).replace("'", "''") + "'"


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(create(os.path.join(here, "out", "dashboard.html")))
