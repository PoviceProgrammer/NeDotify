import os
import winreg

def get_shell_folder(name):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        val, _ = winreg.QueryValueEx(key, name)
        winreg.CloseKey(key)
        return os.path.expandvars(val)
    except Exception as e:
        print(f"Error querying shell folder {name}: {e}")
        return None

print("Real Desktop:", get_shell_folder("Desktop"))
print("Real Programs (Start Menu):", get_shell_folder("Programs"))
