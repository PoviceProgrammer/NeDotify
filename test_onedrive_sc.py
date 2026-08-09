import os
import winreg
import subprocess

def get_shell_folder(name):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        val, _ = winreg.QueryValueEx(key, name)
        winreg.CloseKey(key)
        return os.path.expandvars(val)
    except Exception as e:
        print(f"Error querying shell folder {name}: {e}")
        return None

desktop = get_shell_folder("Desktop")
sc_path = os.path.join(desktop, "TestNeDotify.lnk")
vbs = f'''Set WshShell = CreateObject("WScript.Shell")
Set Shortcut = WshShell.CreateShortcut("{sc_path}")
Shortcut.TargetPath = "C:\\Windows\\notepad.exe"
Shortcut.Save
'''
vbs_file = os.path.join(os.environ["TEMP"], "test_sc.vbs")
with open(vbs_file, "w", encoding="cp1251") as f:
    f.write(vbs)
res = subprocess.run(["cscript", "//nologo", vbs_file], capture_output=True, text=True)
print("Created on OneDrive Desktop:", os.path.exists(sc_path))
if os.path.exists(sc_path):
    os.remove(sc_path)
