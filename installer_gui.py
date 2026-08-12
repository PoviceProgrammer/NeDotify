import os
import sys
import shutil
import subprocess
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from tkinter import filedialog
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

def get_base_path():
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def create_shortcut(target, shortcut_path, description="NeDotify"):
    try:
        target = os.path.abspath(target).replace('/', '\\')
        shortcut_path = os.path.abspath(shortcut_path).replace('/', '\\')
        work_dir = os.path.dirname(target).replace('/', '\\')
        
        # Ensure parent folder exists
        os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)

        vbs_content = f'''Set WshShell = CreateObject("WScript.Shell")
Set Shortcut = WshShell.CreateShortcut("{shortcut_path}")
Shortcut.TargetPath = "{target}"
Shortcut.WorkingDirectory = "{work_dir}"
Shortcut.Description = "{description}"
Shortcut.IconLocation = "{target},0"
Shortcut.Save
'''
        vbs_file = os.path.join(os.environ["TEMP"], "create_nedotify_sc.vbs")
        with open(vbs_file, "w", encoding="cp1251") as f:
            f.write(vbs_content)
            
        no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        res = subprocess.run(["cscript", "//nologo", vbs_file], creationflags=no_window, capture_output=True, text=True)
        if os.path.exists(vbs_file):
            os.remove(vbs_file)
            
        if not os.path.exists(shortcut_path):
            print(f"Failed to create shortcut at {shortcut_path}: {res.stderr}")
    except Exception as e:
        print(f"Error creating shortcut: {e}")

def register_uninstaller(dest_dir, exe_path, uninstaller_path):
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\NeDotify"
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "NeDotify v1.5.1")
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{uninstaller_path}"')
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, f'"{exe_path}"')
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "The NeDotify Team")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "1.5.1")
        winreg.CloseKey(key)
    except Exception as e:
        print(f"Failed to register uninstaller in registry: {e}")

class InstallerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Установка NeDotify v1.5.1")
        self.root.geometry("540x420")
        self.root.resizable(False, False)

        # Style
        style = ttk.Style()
        try:
            style.theme_use('winnative')
        except Exception:
            pass

        style.configure('TButton', font=('Segoe UI', 10))
        style.configure('TLabel', font=('Segoe UI', 10))

        # Title
        title = tk.Label(root, text="Установка NeDotify v1.5.1", font=("Segoe UI", 16, "bold"))
        title.pack(pady=(15, 10))

        # Path variable
        local_appdata = os.environ.get('LOCALAPPDATA', '')
        default_dir = os.path.join(local_appdata, "Programs", "NeDotify") if local_appdata else os.path.join(os.environ.get("USERPROFILE", "C:\\"), "NeDotify")
        self.path_var = tk.StringVar(value=default_dir)

        # Path Frame
        path_frame = tk.LabelFrame(root, text=" Папка установки ", font=('Segoe UI', 9), padx=10, pady=10)
        path_frame.pack(pady=5, padx=25, fill='x')

        path_entry = ttk.Entry(path_frame, textvariable=self.path_var, font=('Segoe UI', 9))
        path_entry.pack(side=tk.LEFT, fill='x', expand=True, padx=(0, 8))

        btn_browse = ttk.Button(path_frame, text="Обзор...", width=10, command=self.browse_folder)
        btn_browse.pack(side=tk.RIGHT)

        # Options Frame
        opts_frame = tk.LabelFrame(root, text=" Опции установки ", font=('Segoe UI', 9), padx=10, pady=5)
        opts_frame.pack(pady=5, padx=25, fill='x')

        self.desktop_var = tk.BooleanVar(value=True)
        self.start_var = tk.BooleanVar(value=True)
        self.clean_var = tk.BooleanVar(value=True)

        cb1 = tk.Checkbutton(
            opts_frame, 
            text="Создать ярлык на рабочем столе", 
            variable=self.desktop_var,
            onvalue=True,
            offvalue=False,
            font=('Segoe UI', 10),
            anchor='w',
            activebackground=root.cget('bg')
        )
        cb1.pack(anchor='w', pady=2)

        cb2 = tk.Checkbutton(
            opts_frame, 
            text="Создать ярлык в меню «Пуск»", 
            variable=self.start_var,
            onvalue=True,
            offvalue=False,
            font=('Segoe UI', 10),
            anchor='w',
            activebackground=root.cget('bg')
        )
        cb2.pack(anchor='w', pady=2)

        cb3 = tk.Checkbutton(
            opts_frame, 
            text="Очистить кэш и временные данные прошлых версий", 
            variable=self.clean_var,
            onvalue=True,
            offvalue=False,
            font=('Segoe UI', 10),
            fg='#4b5563',
            anchor='w',
            activebackground=root.cget('bg')
        )
        cb3.pack(anchor='w', pady=2)

        # Install Button
        self.btn = ttk.Button(root, text="Установить", command=self.install)
        self.btn.pack(pady=(10, 5))

        self.status = ttk.Label(root, text="")
        self.status.pack()

    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.path_var.get(), title="Выберите папку для установки NeDotify")
        if folder:
            self.path_var.set(os.path.normpath(folder))

    def install(self):
        dest_dir = self.path_var.get().strip()
        if not dest_dir:
            messagebox.showerror("Ошибка", "Укажите путь для установки.")
            return

        self.btn.config(state=tk.DISABLED)
        self.status.config(text="Очистка старых версий и установка файлов...")
        self.root.update()

        try:
            # 1. Kill old running instances silently
            no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
            for old_exe in ["NeDotify.exe", "AURA Music.exe", "Beta_NeDotify.exe"]:
                subprocess.run(["taskkill", "/f", "/im", old_exe], creationflags=no_window, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Option to wipe previous user data/activation
            if self.clean_var.get():
                user_data_dir = os.path.join(os.path.expanduser("~"), ".nedotify")
                if os.path.exists(user_data_dir):
                    try:
                        shutil.rmtree(user_data_dir, ignore_errors=True)
                    except Exception as err:
                        print(f"Could not remove old user data: {err}")

            # 2. Real user folders via registry
            desktop_dir = get_shell_folder("Desktop")
            programs_dir = get_shell_folder("Programs")

            # Cleanup old shortcuts
            for old_sc in ["AURA Music beta5.lnk", "Beta_NeDotify.lnk", "NeDotify Beta 5.lnk", "NeDotify.lnk"]:
                sc_d = os.path.join(desktop_dir, old_sc) if desktop_dir else None
                sc_s = os.path.join(programs_dir, old_sc) if programs_dir else None
                if sc_d and os.path.exists(sc_d): 
                    try: os.remove(sc_d)
                    except Exception: pass
                if sc_s and os.path.exists(sc_s): 
                    try: os.remove(sc_s)
                    except Exception: pass

            # 3. Setup new directory
            os.makedirs(dest_dir, exist_ok=True)
            
            src_exe = os.path.join(get_base_path(), "NeDotify.exe")
            src_uninstaller = os.path.join(get_base_path(), "uninstall.exe")
            
            exe_path = os.path.join(dest_dir, "NeDotify.exe")
            uninstaller_path = os.path.join(dest_dir, "uninstall.exe")
            
            # Copy main exe
            if os.path.exists(src_exe):
                shutil.copy2(src_exe, exe_path)
            else:
                self.status.config(text="Ошибка: Основной файл программы не найден.")
                self.btn.config(state=tk.NORMAL)
                return

            # Copy uninstaller exe
            if os.path.exists(src_uninstaller):
                shutil.copy2(src_uninstaller, uninstaller_path)

            # 4. Create Shortcuts
            self.status.config(text="Создание ярлыков...")
            self.root.update()

            if self.desktop_var.get() and desktop_dir:
                create_shortcut(exe_path, os.path.join(desktop_dir, "NeDotify.lnk"), "NeDotify — Музыкальный плеер")

            if self.start_var.get() and programs_dir:
                create_shortcut(exe_path, os.path.join(programs_dir, "NeDotify.lnk"), "NeDotify — Музыкальный плеер")

            # 5. Register in Windows Uninstall menu
            if os.path.exists(uninstaller_path):
                register_uninstaller(dest_dir, exe_path, uninstaller_path)

            self.status.config(text="Установка успешно завершена!")
            messagebox.showinfo("Успех", f"NeDotify v1.5.1 успешно установлен в:\n{dest_dir}")
            self.root.destroy()
            
        except Exception as e:
            self.status.config(text="Произошла ошибка при установке.")
            messagebox.showerror("Ошибка", f"Ошибка: {e}")
            self.btn.config(state=tk.NORMAL)

if __name__ == '__main__':
    root = tk.Tk()
    app = InstallerApp(root)
    root.mainloop()
