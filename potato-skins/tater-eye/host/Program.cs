// HudWallpaper - parents a native GDI+ surface behind the desktop icons (the
// "WorkerW" trick) and paints the HUD as the live desktop background. It also
// launches and supervises the Python backend, so the whole thing starts from
// one executable.
//
//   1. start  pythonw server.py   (hidden, no console)
//   2. wait until http://127.0.0.1:8765/data answers
//   3. spawn the WorkerW layer and SetParent our borderless form into it
//   4. a timer fetches /data and repaints with GDI+ (~0 VRAM, GPU idle)
//   5. pause repaint while a maximized/fullscreen window covers the screen
//   6. watchdog: if python dies, restart it

using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

static class Native
{
    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr FindWindow(string cls, string win);
    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string cls, string win);
    [DllImport("user32.dll")]
    public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, IntPtr wParam,
        IntPtr lParam, uint flags, uint timeout, out IntPtr result);
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr SetParent(IntPtr child, IntPtr newParent);
    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int index);
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool MoveWindow(IntPtr hWnd, int x, int y, int w, int h, bool repaint);
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int w, int h, uint flags);
    [DllImport("user32.dll", SetLastError = true)]
    public static extern int GetWindowLong(IntPtr hWnd, int index);
    [DllImport("user32.dll", SetLastError = true)]
    public static extern int SetWindowLong(IntPtr hWnd, int index, int newLong);
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetClassName(IntPtr hWnd, StringBuilder s, int max);

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int left, top, right, bottom; }

    public const uint WM_SPAWN_WORKERW = 0x052C;
    public const int SM_XVIRTUALSCREEN = 76, SM_YVIRTUALSCREEN = 77;
    public const int SM_CXVIRTUALSCREEN = 78, SM_CYVIRTUALSCREEN = 79;
    public const int GWL_STYLE = -16;
    public const int WS_CHILD = 0x40000000;
    public const int WS_EX_NOACTIVATE = 0x08000000, WS_EX_TOOLWINDOW = 0x00000080;

    public static readonly IntPtr HWND_BOTTOM = new IntPtr(1);
    public const uint SWP_NOSIZE = 0x0001, SWP_NOMOVE = 0x0002, SWP_NOACTIVATE = 0x0010;

    public static IntPtr GetProgman() => FindWindow("Progman", null);

    // Locate the dedicated "wallpaper" WorkerW that lives BEHIND the desktop
    // icons. On a normal console session, sending WM_SPAWN_WORKERW to Progman
    // splits off a WorkerW whose sibling hosts SHELLDLL_DefView (the icons); we
    // parent into that WorkerW and sit cleanly behind them. But on some sessions
    // (notably RDP, and certain shell configs) Progman never spawns it -- the
    // icons stay as a direct child of Progman and there is no WorkerW behind it.
    // We retry briefly to give the shell a chance, then fall back to Progman; the
    // caller detects the fallback (worker == Progman) and drops us to the bottom
    // of the z-order so the icons still paint in front.
    public static IntPtr FindWorkerW()
    {
        IntPtr progman = GetProgman();
        SendMessageTimeout(progman, WM_SPAWN_WORKERW, IntPtr.Zero, IntPtr.Zero, 0, 1000, out _);
        for (int attempt = 0; attempt < 10; attempt++)
        {
            IntPtr worker = IntPtr.Zero;
            EnumWindows((top, _) =>
            {
                if (FindWindowEx(top, IntPtr.Zero, "SHELLDLL_DefView", null) != IntPtr.Zero)
                    worker = FindWindowEx(IntPtr.Zero, top, "WorkerW", null);
                return true;
            }, IntPtr.Zero);
            if (worker != IntPtr.Zero) return worker;
            Thread.Sleep(100);
        }
        return progman;
    }
}

class WallpaperForm : Form
{
    readonly HudRenderer _renderer = new();
    readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(2) };
    readonly JsonSerializerOptions _json = new() { PropertyNameCaseInsensitive = true };
    readonly string _serverDir, _url = "http://127.0.0.1:8765", _log, _pidFile;
    Process _py;
    System.Windows.Forms.Timer _timer, _watchdog;
    Bitmap _frame;
    Snapshot _data;
    bool _attached, _fallback;
    int _vx, _vy, _vw, _vh;

    public WallpaperForm(string serverDir, string log)
    {
        _serverDir = serverDir; _log = log;
        _pidFile = Path.Combine(Path.GetTempPath(), "hudwallpaper.server.pid");
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.Manual;
        BackColor = Color.Black;
        Text = "HudWallpaper";
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint
               | ControlStyles.OptimizedDoubleBuffer, true);

        _vx = Native.GetSystemMetrics(Native.SM_XVIRTUALSCREEN);
        _vy = Native.GetSystemMetrics(Native.SM_YVIRTUALSCREEN);
        _vw = Native.GetSystemMetrics(Native.SM_CXVIRTUALSCREEN);
        _vh = Native.GetSystemMetrics(Native.SM_CYVIRTUALSCREEN);
        Bounds = new Rectangle(_vx, _vy, _vw, _vh);
    }

    protected override CreateParams CreateParams
    {
        get { var cp = base.CreateParams; cp.ExStyle |= Native.WS_EX_NOACTIVATE | Native.WS_EX_TOOLWINDOW; return cp; }
    }

    protected override async void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        if (_attached) return;
        _attached = true;

        if (!await ServerAlive()) StartPython();   // reuse an already-running backend
        await WaitForServerAsync();
        AttachToWorkerW();

        await FetchAndRenderAsync();
        _timer = new System.Windows.Forms.Timer { Interval = 2000 };
        _timer.Tick += async (_, __) => await FetchAndRenderAsync();
        _timer.Start();
        StartWatchdog();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        if (_frame != null) e.Graphics.DrawImageUnscaled(_frame, 0, 0);
        else { e.Graphics.Clear(Color.Black); }
    }

    protected override void OnPaintBackground(PaintEventArgs e) { /* fully custom */ }

    void Log(string m)
    { try { File.AppendAllText(_log, $"{DateTime.Now:HH:mm:ss} {m}{Environment.NewLine}"); } catch { } }

    async Task FetchAndRenderAsync()
    {
        if (_fallback) PinToBottom();          // keep the icons in front across desktop refreshes
        if (ShouldPause()) return;             // covered by a fullscreen app
        try
        {
            string body = await _http.GetStringAsync(_url + "/data");
            _data = JsonSerializer.Deserialize<Snapshot>(body, _json);
        }
        catch { return; }                       // keep last frame on a hiccup
        RenderFrame();
    }

    void RenderFrame()
    {
        int w = Math.Max(1, ClientSize.Width), h = Math.Max(1, ClientSize.Height);
        if (_frame == null || _frame.Width != w || _frame.Height != h)
        { _frame?.Dispose(); _frame = new Bitmap(w, h); }
        using (var g = Graphics.FromImage(_frame))
            _renderer.Render(g, w, h, _data);
        Invalidate();
    }

    bool ShouldPause()
    {
        try
        {
            IntPtr fg = Native.GetForegroundWindow();
            if (fg == IntPtr.Zero || fg == Handle) return false;
            var sb = new StringBuilder(64);
            Native.GetClassName(fg, sb, sb.Capacity);
            string cls = sb.ToString();
            if (cls is "Progman" or "WorkerW" or "Shell_TrayWnd") return false;
            if (!Native.GetWindowRect(fg, out var r)) return false;
            // pause if the focused window (nearly) covers our whole screen
            return r.left <= _vx + 2 && r.top <= _vy + 2
                && r.right >= _vx + _vw - 2 && r.bottom >= _vy + _vh - 2;
        }
        catch { return false; }
    }

    void StartPython()
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "pythonw.exe",
                Arguments = "server.py",
                WorkingDirectory = _serverDir,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            // Hand the server the exact PID-file path so the two runtimes can't
            // disagree on where it lives (their temp dirs can differ).
            psi.Environment["HUD_PID_FILE"] = _pidFile;
            _py = Process.Start(psi);
            Log($"python started pid={_py?.Id} dir={_serverDir}");
        }
        catch (Exception ex) { Log("python start FAILED: " + ex.Message); }
    }

    async Task WaitForServerAsync()
    {
        for (int i = 0; i < 40; i++)
        {
            if (await ServerAlive()) { Log("server up"); return; }
            await Task.Delay(500);
        }
        Log("server did not come up in time");
    }

    async Task<bool> ServerAlive()
    {
        try { return (await _http.GetAsync(_url + "/data")).IsSuccessStatusCode; }
        catch { return false; }
    }

    // The server records its real PID (the launched pythonw.exe is the Microsoft
    // Store app-execution alias, which trampolines to pythonw3.12.exe and exits,
    // so the Process handle we hold is useless for killing it). Read that PID.
    void KillServer()
    {
        try
        {
            if (File.Exists(_pidFile) && int.TryParse(File.ReadAllText(_pidFile).Trim(), out int pid))
            {
                try { Process.GetProcessById(pid).Kill(true); Log($"killed server pid={pid}"); }
                catch { }
            }
        }
        catch { }
    }

    void AttachToWorkerW()
    {
        try
        {
            IntPtr progman = Native.GetProgman();
            IntPtr worker = Native.FindWorkerW();
            _fallback = worker == progman;
            int style = Native.GetWindowLong(Handle, Native.GWL_STYLE);
            Native.SetWindowLong(Handle, Native.GWL_STYLE, style | Native.WS_CHILD);
            Native.SetParent(Handle, worker);
            Native.MoveWindow(Handle, 0, 0, _vw, _vh, true);
            if (_fallback) PinToBottom();   // no WorkerW behind the icons -> sit under SHELLDLL_DefView
            Log($"attached to {(_fallback ? "Progman(fallback, pinned bottom)" : "WorkerW")}=0x{worker.ToInt64():X} size={_vw}x{_vh}");
        }
        catch (Exception ex) { Log("attach FAILED: " + ex.Message); }
    }

    // When parented straight into Progman (no dedicated wallpaper WorkerW), the
    // desktop icons (SHELLDLL_DefView) are our z-order siblings. Drop to the
    // bottom so they paint in front of us. A desktop refresh (F5, resolution
    // change, icon add/remove) can re-stack the siblings, so we re-assert this
    // on every repaint tick while in fallback mode -- a no-op once we're already
    // at the bottom, so it doesn't flicker.
    void PinToBottom()
    {
        Native.SetWindowPos(Handle, Native.HWND_BOTTOM, 0, 0, 0, 0,
            Native.SWP_NOMOVE | Native.SWP_NOSIZE | Native.SWP_NOACTIVATE);
    }

    void StartWatchdog()
    {
        _watchdog = new System.Windows.Forms.Timer { Interval = 4000 };
        _watchdog.Tick += async (_, __) =>
        {
            // Probe the server, not _py.HasExited: the Store pythonw.exe alias
            // trampolines and the launched process exits at once, so HasExited is
            // always true and would respawn forever. Only restart if /data is dead.
            if (await ServerAlive()) return;
            Log("server unreachable - restarting python");
            StartPython();
            await WaitForServerAsync();
        };
        _watchdog.Start();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        try { _timer?.Stop(); } catch { }
        try { _watchdog?.Stop(); } catch { }
        KillServer();
        base.OnFormClosing(e);
    }
}

static class Program
{
    static string ResolveServerDir()
    {
        // Override with the HUD_SERVER_DIR env var; otherwise walk up from the
        // executable looking for server\server.py (handles the repo layout and
        // a published bin\... layout); finally fall back to a sibling folder.
        string env = Environment.GetEnvironmentVariable("HUD_SERVER_DIR");
        if (!string.IsNullOrEmpty(env) && File.Exists(Path.Combine(env, "server.py")))
            return env;
        try
        {
            var dir = new DirectoryInfo(AppContext.BaseDirectory);
            for (int i = 0; i < 8 && dir != null; i++, dir = dir.Parent)
            {
                string cand = Path.Combine(dir.FullName, "server", "server.py");
                if (File.Exists(cand)) return Path.GetDirectoryName(cand);
            }
        }
        catch { }
        return Path.Combine(AppContext.BaseDirectory, "server");
    }

    [STAThread]
    static void Main(string[] args)
    {
        using var mutex = new Mutex(true, "HudWallpaper_singleton", out bool isNew);
        if (!isNew) return;

        string serverDir = args.Length > 0 ? args[0] : ResolveServerDir();
        string log = Path.Combine(Path.GetTempPath(), "hudwallpaper.log");

        Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new WallpaperForm(serverDir, log));
    }
}
