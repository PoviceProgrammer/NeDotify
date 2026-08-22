# Make the NeDotify host window visible + foreground so GPU samples are taken in a
# deterministic state. The pywebview host window is a WindowsForms window owned by
# python.exe and is *hidden* (not minimized) while the app sits in the tray, so it
# is not exposed as Process.MainWindowHandle -> enumerate top-level windows instead.
param([switch]$Hide)
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices;
public class W {
    public delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    public static IntPtr Found = IntPtr.Zero;
    public static void Find(uint[] pids) {
        EnumWindows(delegate(IntPtr h, IntPtr l) {
            uint p; GetWindowThreadProcessId(h, out p);
            foreach (uint want in pids) if (p == want) {
                var c = new StringBuilder(256); GetClassName(h, c, 256);
                var t = new StringBuilder(512); GetWindowText(h, t, 512);
                if (c.ToString().StartsWith("WindowsForms") && t.ToString().Length > 0) { Found = h; return false; }
            }
            return true;
        }, IntPtr.Zero);
    }
}
"@
$pids = @(Get-Process -Name python -ErrorAction SilentlyContinue | ForEach-Object { [uint32]$_.Id })
if ($pids.Count -eq 0) { Write-Output "no python process"; exit 1 }
[W]::Find($pids)
if ([W]::Found -eq [IntPtr]::Zero) { Write-Output "host window not found"; exit 1 }
$h = [W]::Found
if ($Hide) { [void][W]::ShowWindow($h, 0); Write-Output ("hidden    : visible={0}" -f [W]::IsWindowVisible($h)); exit 0 }
[void][W]::ShowWindow($h, 5)   # SW_SHOW
[void][W]::ShowWindow($h, 9)   # SW_RESTORE
[void][W]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 900
Write-Output ("hwnd      : {0}" -f $h.ToInt64())
Write-Output ("visible   : {0}" -f [W]::IsWindowVisible($h))
Write-Output ("iconic    : {0}" -f [W]::IsIconic($h))
Write-Output ("foreground: {0}" -f ([W]::GetForegroundWindow() -eq $h))
