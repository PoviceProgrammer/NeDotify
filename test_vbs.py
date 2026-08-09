import os
import subprocess

def test():
    desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')
    sc_path = os.path.join(desktop, 'TestNeDotify.lnk')
    vbs = f'''Set WshShell = CreateObject("WScript.Shell")
Set Shortcut = WshShell.CreateShortcut("{sc_path}")
Shortcut.TargetPath = "C:\\Windows\\notepad.exe"
Shortcut.Save
'''
    vbs_file = os.path.join(os.environ["TEMP"], "test_sc.vbs")
    with open(vbs_file, "w", encoding="cp1251") as f:
        f.write(vbs)
    res = subprocess.run(["cscript", "//nologo", vbs_file], capture_output=True, text=True)
    print("STDOUT:", res.stdout)
    print("STDERR:", res.stderr)
    print("Created on Desktop:", os.path.exists(sc_path))

if __name__ == "__main__":
    test()
