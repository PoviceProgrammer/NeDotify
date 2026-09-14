import os
import sys
import shutil
import subprocess
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import winreg

def get_shell_folder(name):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        val, _ = winreg.QueryValueEx(key, name)
        winreg.CloseKey(key)
        return os.path.expandvars(val)
    except Exception as e:
        print(f"Error querying shell folder {name}: {e}")
        if name == "Desktop":
            return os.path.join(os.environ["USERPROFILE"], "Desktop")
        elif name == "Programs":
            return os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")
        return None

def remove_shortcut(shortcut_path):
    try:
        if shortcut_path and os.path.exists(shortcut_path):
            os.remove(shortcut_path)
    except Exception as e:
        print(f"Failed to remove {shortcut_path}: {e}")

def remove_registry_key():
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\NeDotify"
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
    except Exception:
        pass

class UninstallerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Удаление NeDotify beta5")
        self.root.geometry("450x200")
        self.root.resizable(False, False)

        style = ttk.Style()
        try:
            style.theme_use('winnative')
        except Exception:
            pass

        style.configure('TButton', font=('Segoe UI', 10))
        style.configure('TLabel', font=('Segoe UI', 10))

        title = tk.Label(root, text="Удаление NeDotify", font=("Segoe UI", 16, "bold"))
        title.pack(pady=20)

        self.status = ttk.Label(root, text="Вы действительно хотите удалить NeDotify?")
        self.status.pack(pady=10)
        
        self.delete_settings_var = tk.BooleanVar(value=True)
        self.delete_settings_cb = ttk.Checkbutton(
            root, text="Удалить все пользовательские настройки (история, логи, кэш)", 
            variable=self.delete_settings_var
        )
        self.delete_settings_cb.pack(pady=5)

        frame = ttk.Frame(root)
        frame.pack(pady=10)

        self.btn_yes = ttk.Button(frame, text="Да, удалить", command=self.uninstall)
        self.btn_yes.pack(side=tk.LEFT, padx=10)
        
        self.btn_no = ttk.Button(frame, text="Отмена", command=self.root.destroy)
        self.btn_no.pack(side=tk.LEFT, padx=10)

    def uninstall(self):
        self.btn_yes.config(state=tk.DISABLED)
        self.btn_no.config(state=tk.DISABLED)
        self.delete_settings_cb.config(state=tk.DISABLED)
        self.status.config(text="Удаление файлов и ярлыков...")
        self.root.update()

        try:
            # Kill process if running
            os.system('taskkill /f /im "NeDotify.exe" >nul 2>&1')
            os.system('taskkill /f /im "AURA Music.exe" >nul 2>&1')
            os.system('taskkill /f /im "Beta_NeDotify.exe" >nul 2>&1')

            # Delete shortcuts using winreg real folders
            desktop_dir = get_shell_folder("Desktop")
            programs_dir = get_shell_folder("Programs")
            
            for name in ["NeDotify.lnk", "NeDotify beta5.lnk", "AURA Music beta5.lnk"]:
                if desktop_dir: remove_shortcut(os.path.join(desktop_dir, name))
                if programs_dir: remove_shortcut(os.path.join(programs_dir, name))

            # Remove registry uninstall entry
            remove_registry_key()

            if self.delete_settings_var.get():
                user_home = os.path.expanduser("~")
                local_appdata = os.environ.get("LOCALAPPDATA", "")
                appdata = os.environ.get("APPDATA", "")
                
                paths_to_clean = [
                    os.path.join(user_home, ".nedotify"),
                    os.path.join(user_home, ".aura_music"),
                    os.path.join(local_appdata, "NeDotify"),
                    os.path.join(local_appdata, "AURA_Music"),
                    os.path.join(appdata, "NeDotify"),
                    os.path.join(appdata, "AURA_Music"),
                    os.path.join(local_appdata, "pywebview"),
                ]
                
                for path in paths_to_clean:
                    if path and os.path.exists(path):
                        shutil.rmtree(path, ignore_errors=True)

            self.status.config(text="Файлы успешно удалены! Программа закроется...")
            self.root.update()
            
            # VBS script to self-delete the folder after we exit.
            local_appdata = os.environ.get('LOCALAPPDATA', '')
            target_dir = os.path.join(local_appdata, "Programs", "NeDotify")
            
            if os.path.exists(target_dir):
                vbs_path = os.path.join(os.environ["TEMP"], "nedotify_clean.vbs")
                with open(vbs_path, "w", encoding="utf-8") as f:
                    f.write(f'''WScript.Sleep 2000
Dim fso
Set fso = CreateObject("Scripting.FileSystemObject")
If fso.FolderExists("{target_dir}") Then
    On Error Resume Next
    fso.DeleteFolder "{target_dir}", True
End If
''')
                os.startfile(vbs_path)

            messagebox.showinfo("Успех", "NeDotify полностью удален с вашего ПК.")
            self.root.destroy()
            
        except Exception as e:
            self.status.config(text="Произошла ошибка при удалении.")
            messagebox.showerror("Ошибка", f"Ошибка: {e}")
            self.btn_yes.config(state=tk.NORMAL)
            self.btn_no.config(state=tk.NORMAL)

if __name__ == '__main__':
    root = tk.Tk()
    app = UninstallerApp(root)
    root.mainloop()
