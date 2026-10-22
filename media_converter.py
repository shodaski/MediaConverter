"""
Media Converter - convert video and audio files between formats (MP4, MP3, MKV, ...)
Dark theme, settings window, app icon.
Requires FFmpeg (ffmpeg + ffprobe): bundled in the installer, or put next to this file / in PATH.
"""
import os
import sys
import json
import shutil
import subprocess
import threading
import queue
import tempfile
import re
import hashlib
import urllib.request
import tkinter as tk
from tkinter import ttk, filedialog

try:  # drag & drop support (pip install tkinterdnd2)
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_OK = True
    BaseTk = TkinterDnD.Tk
except Exception:
    DND_OK = False
    BaseTk = tk.Tk

APP_NAME = "Media Converter"
AUTHOR = "Zakariae (Shodaski)"

# Where the app looks for updates. Put the public link to your version.json here
# (example: "https://raw.githubusercontent.com/YOURNAME/MediaConverter/main/version.json").
# Leave it empty ("") to turn the update system off.
UPDATE_URL = "https://raw.githubusercontent.com/shodaski/MediaConverter/main/version.json"
APP_ID = "MediaConverter.App"

AUDIO_EXT = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff"}
VIDEO_FORMATS = ["mp4", "mkv", "avi", "mov", "webm", "flv", "wmv", "gif"]
AUDIO_FORMATS = ["mp3", "wav", "flac", "aac", "m4a", "ogg", "opus", "wma"]
ALL_FORMATS = VIDEO_FORMATS + AUDIO_FORMATS
MEDIA_EXT = AUDIO_EXT | {"." + f for f in VIDEO_FORMATS} | {".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".m2ts"}
QUALITY = {"Low": (28, "96k", 38), "Medium": (23, "192k", 32), "High": (18, "320k", 24)}

# ---- dark palette ----
BG = "#1b1c20"
PANEL = "#2a2c33"
HOVER = "#363944"
FIELD = "#15161a"
BORDER = "#3a3d47"
FG = "#e8e9ed"
MUTED = "#9096a3"
ACCENT = "#4f8cff"
ACCENT_H = "#6ba0ff"

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DLL_MISSING = (3221225781, -1073741515)  # 0xC0000135: Windows cannot find a DLL
DEFAULTS = {"format": "mp3", "quality": "Medium", "outdir": "", "ffmpeg_path": "", "open_when_done": True,
            "auto_update": True}


# ---------------------------------------------------------------- helpers
def resource(name):
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


def read_version():
    try:
        with open(resource("version.txt"), "r", encoding="utf-8") as f:
            return f.read().strip() or "1.0"
    except Exception:
        return "1.0"


APP_VERSION = read_version()


def parse_version(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v)))


def settings_path():
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(root, "MediaConverter")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "settings.json")


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            s.update(json.load(f))
    except Exception:
        pass
    if s["format"] not in ALL_FORMATS:
        s["format"] = DEFAULTS["format"]
    if s["quality"] not in QUALITY:
        s["quality"] = DEFAULTS["quality"]
    return s


def save_settings(s):
    try:
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass


def find_tool(name, custom=""):
    exe = name + (".exe" if os.name == "nt" else "")
    if custom:
        folder = custom if os.path.isdir(custom) else os.path.dirname(custom)
        p = os.path.join(folder, exe)
        if os.path.isfile(p):
            return p
    exe_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    for folder in (exe_dir, getattr(sys, "_MEIPASS", exe_dir)):
        p = os.path.join(folder, exe)
        if os.path.isfile(p):
            return p
    return shutil.which(name)


def open_folder(path):
    try:
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def dark_titlebar(win):
    """Dark title bar on Windows 10/11."""
    if os.name != "nt":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def codec_args(fmt, quality):
    crf, abr, vp9 = QUALITY[quality]
    x264 = ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p"]
    table = {
        "mp4": x264 + ["-c:a", "aac", "-b:a", abr, "-movflags", "+faststart"],
        "mkv": x264 + ["-c:a", "aac", "-b:a", abr],
        "mov": x264 + ["-c:a", "aac", "-b:a", abr],
        "avi": ["-c:v", "mpeg4", "-q:v", str({"Low": 8, "Medium": 4, "High": 2}[quality]),
                "-c:a", "libmp3lame", "-b:a", abr],
        "webm": ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(vp9), "-row-mt", "1",
                 "-deadline", "good", "-cpu-used", "4", "-c:a", "libopus", "-b:a", abr],
        "flv": ["-c:v", "flv1", "-q:v", "4", "-c:a", "libmp3lame", "-b:a", abr, "-ar", "44100"],
        "wmv": ["-c:v", "wmv2", "-b:v", {"Low": "1M", "Medium": "2500k", "High": "6M"}[quality],
                "-c:a", "wmav2", "-b:a", abr],
        "gif": ["-an", "-vf", "fps=12,scale=480:-1:flags=lanczos"],
        "mp3": ["-vn", "-c:a", "libmp3lame", "-b:a", abr],
        "wav": ["-vn", "-c:a", "pcm_s16le"],
        "flac": ["-vn", "-c:a", "flac"],
        "aac": ["-vn", "-c:a", "aac", "-b:a", abr],
        "m4a": ["-vn", "-c:a", "aac", "-b:a", abr],
        "ogg": ["-vn", "-c:a", "libvorbis", "-b:a", abr],
        "opus": ["-vn", "-c:a", "libopus", "-b:a", abr],
        "wma": ["-vn", "-c:a", "wmav2", "-b:a", abr],
    }
    return table[fmt]


def build_command(ffmpeg, src, dst, fmt, quality):
    cmd = [ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]
    src_is_audio = os.path.splitext(src)[1].lower() in AUDIO_EXT
    if fmt in VIDEO_FORMATS and src_is_audio:
        cmd += ["-f", "lavfi", "-i", "color=c=black:s=1280x720:r=25", "-i", src,
                "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    elif fmt in VIDEO_FORMATS:
        cmd += ["-i", src, "-map", "0:v:0", "-map", "0:a:0?"]
    else:
        cmd += ["-i", src]
    cmd += codec_args(fmt, quality) + [dst]
    return cmd


def get_duration(ffprobe, path):
    if not ffprobe:
        return 0.0
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
            stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace",
            creationflags=NO_WINDOW).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


# ---------------------------------------------------------------- dark dialogs
class DarkMessage(tk.Toplevel):
    def __init__(self, parent, title, text, kind="info", buttons=None):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        set_window_icon(self)
        glyph, color = {"info": ("ⓘ", ACCENT), "error": ("⚠", "#ff6b6b"), "warn": ("⚠", "#ffb454")}[kind]
        body = ttk.Frame(self)
        body.pack(padx=22, pady=(20, 10))
        tk.Label(body, text=glyph, fg=color, bg=BG, font=("Segoe UI", 28)).pack(side="left", padx=(0, 14))
        tk.Label(body, text=text, fg=FG, bg=BG, justify="left", wraplength=380,
                 font=("Segoe UI", 10)).pack(side="left")
        self.result = None
        bar = ttk.Frame(self)
        bar.pack(pady=(4, 16))
        labels = buttons or ["OK"]
        for i, label in enumerate(labels):
            ttk.Button(bar, text=label, style="Accent.TButton" if i == 0 else "TButton",
                       command=lambda l=label: self._pick(l)).pack(side="left", padx=5)
        self.bind("<Return>", lambda e: self._pick(labels[0]))
        self.bind("<Escape>", lambda e: self._pick(labels[-1]))
        dark_titlebar(self)
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        self.focus_set()
        self.wait_window()

    def _pick(self, label):
        self.result = label
        self.destroy()


def set_window_icon(win):
    try:
        if os.name == "nt":
            win.iconbitmap(resource("icon.ico"))
        else:
            img = tk.PhotoImage(file=resource("icon.png"))
            win.iconphoto(True, img)
            win._icon_ref = img
    except Exception:
        pass


class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Settings")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(app)
        set_window_icon(self)

        s = app.settings
        self.v_format = tk.StringVar(value=s["format"])
        self.v_quality = tk.StringVar(value=s["quality"])
        self.v_outdir = tk.StringVar(value=s["outdir"])
        self.v_ffmpeg = tk.StringVar(value=s["ffmpeg_path"])
        self.v_open = tk.BooleanVar(value=s["open_when_done"])
        self.v_auto = tk.BooleanVar(value=s.get("auto_update", True))

        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Default format").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Combobox(f, textvariable=self.v_format, values=ALL_FORMATS, state="readonly",
                     width=10).grid(row=0, column=1, sticky="w", padx=8)

        ttk.Label(f, text="Default quality").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Combobox(f, textvariable=self.v_quality, values=list(QUALITY), state="readonly",
                     width=10).grid(row=1, column=1, sticky="w", padx=8)

        ttk.Label(f, text="Save converted files in").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=self.v_outdir, width=38).grid(row=2, column=1, sticky="we", padx=8)
        ttk.Button(f, text="📂", width=3, command=self.pick_out).grid(row=2, column=2)
        ttk.Label(f, text="Empty = next to the original file", style="Muted.TLabel").grid(
            row=3, column=1, sticky="w", padx=8)

        ttk.Label(f, text="FFmpeg location").grid(row=4, column=0, sticky="w", pady=(12, 6))
        ttk.Entry(f, textvariable=self.v_ffmpeg, width=38).grid(row=4, column=1, sticky="we", padx=8)
        ttk.Button(f, text="📂", width=3, command=self.pick_ffmpeg).grid(row=4, column=2)
        ttk.Label(f, text="Empty = automatic (bundled or PATH)", style="Muted.TLabel").grid(
            row=5, column=1, sticky="w", padx=8)

        ttk.Checkbutton(f, text="Open the output folder when finished",
                        variable=self.v_open).grid(row=6, column=0, columnspan=3, sticky="w", pady=(14, 4))
        ttk.Checkbutton(f, text="Check for updates when the app starts",
                        variable=self.v_auto).grid(row=7, column=0, columnspan=3, sticky="w", pady=4)
        upd = ttk.Frame(f)
        upd.grid(row=8, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(upd, text=f"Version {APP_VERSION}", style="Muted.TLabel").pack(side="left")
        ttk.Button(upd, text="Check for updates now",
                   command=lambda: (self.save(), self.app.check_updates(True))).pack(side="left", padx=12)

        btns = ttk.Frame(f)
        btns.grid(row=9, column=0, columnspan=3, sticky="e", pady=(16, 0))
        ttk.Button(btns, text="Reset", command=self.reset).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(btns, text="Save", style="Accent.TButton", command=self.save).pack(side="left")

        dark_titlebar(self)
        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + 60
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()

    def pick_out(self):
        d = filedialog.askdirectory(parent=self)
        if d:
            self.v_outdir.set(d)

    def pick_ffmpeg(self):
        d = filedialog.askdirectory(parent=self, title="Folder that contains ffmpeg and ffprobe")
        if d:
            self.v_ffmpeg.set(d)

    def reset(self):
        self.v_format.set(DEFAULTS["format"])
        self.v_quality.set(DEFAULTS["quality"])
        self.v_outdir.set("")
        self.v_ffmpeg.set("")
        self.v_open.set(True)
        self.v_auto.set(True)

    def save(self):
        self.app.settings.update({
            "format": self.v_format.get(), "quality": self.v_quality.get(),
            "outdir": self.v_outdir.get().strip(), "ffmpeg_path": self.v_ffmpeg.get().strip(),
            "open_when_done": self.v_open.get(), "auto_update": self.v_auto.get()})
        save_settings(self.app.settings)
        self.app.apply_settings()
        self.destroy()


# ---------------------------------------------------------------- main app
class App(BaseTk):
    def __init__(self):
        super().__init__()
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
            except Exception:
                pass
        self.title(APP_NAME)
        self.geometry("760x690")
        self.minsize(680, 600)
        self.configure(bg=BG)
        set_window_icon(self)
        self.apply_theme()

        self.settings = load_settings()
        self.files = []
        self.msgs = queue.Queue()
        self.proc = None
        self.cancel = threading.Event()
        self.working = False
        self.last_folder = ""
        self._manual_check = False

        self.fmt = tk.StringVar(value=self.settings["format"])
        self.quality = tk.StringVar(value=self.settings["quality"])
        self.outdir = tk.StringVar(value=self.settings["outdir"])
        self.status = tk.StringVar(value="Ready")

        self._build_ui()
        self.apply_settings(initial=True)
        self._setup_drop()
        dark_titlebar(self)
        self.after(100, self._poll)
        if self.settings.get("auto_update", True) and UPDATE_URL:
            self.after(2500, lambda: self.check_updates(False))
        if not self.ffmpeg:
            self.after(300, lambda: DarkMessage(
                self, "FFmpeg not found",
                "FFmpeg was not found, so files cannot be converted yet.\n\n"
                "Open Settings and choose the folder that contains ffmpeg and ffprobe, "
                "or install FFmpeg and add it to PATH.", "warn"))

    # ---- theme ----
    def apply_theme(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=FIELD, bordercolor=BORDER,
                    lightcolor=BG, darkcolor=BG, troughcolor=FIELD, focuscolor=BG,
                    font=("Segoe UI", 10))
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Muted.TLabel", foreground=MUTED, font=("Segoe UI", 9))
        s.configure("Title.TLabel", font=("Segoe UI Semibold", 16))
        s.configure("TLabelframe", background=BG, bordercolor=BORDER)
        s.configure("TLabelframe.Label", background=BG, foreground=MUTED)
        s.configure("TButton", background=PANEL, foreground=FG, borderwidth=0, padding=(12, 7))
        s.map("TButton", background=[("disabled", "#22242a"), ("active", HOVER)],
              foreground=[("disabled", "#5d616c")])
        s.configure("Accent.TButton", background=ACCENT, foreground="white",
                    font=("Segoe UI Semibold", 10), padding=(18, 8))
        s.map("Accent.TButton", background=[("disabled", "#2b3c5c"), ("active", ACCENT_H)],
              foreground=[("disabled", "#7d8aa3")])
        s.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG, padding=5)
        s.configure("TCombobox", fieldbackground=FIELD, background=PANEL, foreground=FG,
                    arrowcolor=FG, bordercolor=BORDER, padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
              selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)],
              background=[("active", HOVER)])
        s.configure("TCheckbutton", background=BG, foreground=FG)
        s.map("TCheckbutton", background=[("active", BG)], indicatorbackground=[("selected", ACCENT)])
        s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=FIELD,
                    bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT, thickness=10)
        s.configure("Total.Horizontal.TProgressbar", background="#7a5cff", troughcolor=FIELD,
                    bordercolor=BG, lightcolor="#7a5cff", darkcolor="#7a5cff", thickness=6)
        s.configure("Vertical.TScrollbar", background=PANEL, troughcolor=BG, arrowcolor=FG,
                    bordercolor=BG, lightcolor=PANEL, darkcolor=PANEL)
        s.map("Vertical.TScrollbar", background=[("active", HOVER)])
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

    # ---- UI ----
    def _build_ui(self):
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 12))
        try:
            self._logo = tk.PhotoImage(file=resource("icon.png")).subsample(5, 5)
            tk.Label(header, image=self._logo, bg=BG).pack(side="left", padx=(0, 10))
        except Exception:
            pass
        titles = ttk.Frame(header)
        titles.pack(side="left")
        ttk.Label(titles, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text="Convert video and audio to any format", style="Muted.TLabel").pack(anchor="w")
        ttk.Button(header, text="⚙  Settings", command=self.open_settings).pack(side="right")

        ttk.Label(root, text="Files to convert", style="Muted.TLabel").pack(anchor="w")
        self.box = tk.Frame(root, bg=BORDER, padx=1, pady=1)
        self.box.pack(fill="both", expand=True, pady=(4, 6))
        inner = tk.Frame(self.box, bg=FIELD)
        inner.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(inner, selectmode="extended", bg=FIELD, fg=FG, bd=0, relief="flat",
                                  highlightthickness=0, selectbackground=ACCENT, selectforeground="white",
                                  activestyle="none", font=("Segoe UI", 10))
        sb = ttk.Scrollbar(inner, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        sb.pack(side="right", fill="y")
        hint = ("⬇\nDrag & drop your music or videos here\n(files or whole folders)" if DND_OK
                else "Click  ＋ Add files  to choose your music or videos")
        self.hint = tk.Label(inner, text=hint, bg=FIELD, fg=MUTED, font=("Segoe UI", 12), justify="center")
        self.hint.place(relx=0.5, rely=0.5, anchor="center")

        row = ttk.Frame(root)
        row.pack(fill="x", pady=(0, 10))
        ttk.Button(row, text="＋  Add files", command=self.add_files).pack(side="left")
        ttk.Button(row, text="✕  Remove selected", command=self.remove_selected).pack(side="left", padx=6)
        ttk.Button(row, text="🗑  Clear", command=self.clear).pack(side="left")

        opts = ttk.LabelFrame(root, text=" Options ", padding=10)
        opts.pack(fill="x", pady=(0, 10))
        opts.columnconfigure(1, weight=1)
        line1 = ttk.Frame(opts)
        line1.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(line1, text="🎞  Convert to").pack(side="left")
        ttk.Combobox(line1, textvariable=self.fmt, values=ALL_FORMATS, state="readonly",
                     width=8).pack(side="left", padx=(8, 24))
        ttk.Label(line1, text="✨  Quality").pack(side="left")
        ttk.Combobox(line1, textvariable=self.quality, values=list(QUALITY), state="readonly",
                     width=8).pack(side="left", padx=8)
        ttk.Label(opts, text="📁  Save in").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(opts, textvariable=self.outdir).grid(row=1, column=1, sticky="we", padx=8, pady=(10, 0))
        ttk.Button(opts, text="Browse", command=self.pick_outdir).grid(row=1, column=2, pady=(10, 0))
        ttk.Label(opts, text="Leave empty to save next to the original file", style="Muted.TLabel").grid(
            row=2, column=1, sticky="w", padx=8)

        ttk.Label(root, textvariable=self.status, style="Muted.TLabel").pack(anchor="w")
        self.bar = ttk.Progressbar(root, maximum=100)
        self.bar.pack(fill="x", pady=(4, 4))
        self.total_bar = ttk.Progressbar(root, maximum=100, style="Total.Horizontal.TProgressbar")
        self.total_bar.pack(fill="x", pady=(0, 12))

        act = ttk.Frame(root)
        act.pack(fill="x")
        self.go_btn = ttk.Button(act, text="▶  Convert", style="Accent.TButton", command=self.start)
        self.go_btn.pack(side="left")
        self.cancel_btn = ttk.Button(act, text="■  Cancel", command=self.cancel_job, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)
        ttk.Button(act, text="📂  Open output folder", command=self.open_output).pack(side="right")

        ttk.Label(root, text=f"Built by {AUTHOR}   •   Version {APP_VERSION}", style="Muted.TLabel").pack(pady=(14, 0))

    # ---- settings ----
    def open_settings(self):
        SettingsDialog(self)

    def apply_settings(self, initial=False):
        s = self.settings
        self.ffmpeg = find_tool("ffmpeg", s["ffmpeg_path"])
        self.ffprobe = find_tool("ffprobe", s["ffmpeg_path"])
        if not initial:
            self.fmt.set(s["format"])
            self.quality.set(s["quality"])
            self.outdir.set(s["outdir"])

    def open_output(self):
        folder = self.last_folder or self.outdir.get().strip()
        if not folder and self.files:
            folder = os.path.dirname(self.files[0])
        if folder and os.path.isdir(folder):
            open_folder(folder)

    # ---- file list ----
    def add_files(self):
        exts = " ".join("*." + e for e in sorted({x.strip(".") for x in AUDIO_EXT} | set(VIDEO_FORMATS) |
                                                  {"m4v", "mpg", "mpeg", "3gp", "ts", "m2ts"}))
        paths = filedialog.askopenfilenames(title="Choose audio/video files",
                                            filetypes=[("Media files", exts), ("All files", "*.*")])
        self.add_paths(paths, strict=False)

    def add_paths(self, paths, strict=True):
        """Add files (or every media file inside dropped folders) to the list."""
        todo = []
        for p in paths:
            p = os.path.normpath(p)
            if os.path.isdir(p):
                for folder, _, names in os.walk(p):
                    todo += [os.path.join(folder, n) for n in sorted(names)]
            elif os.path.isfile(p):
                todo.append(p)
        added = skipped = 0
        for p in todo:
            if strict and os.path.splitext(p)[1].lower() not in MEDIA_EXT:
                skipped += 1
                continue
            if p not in self.files:
                self.files.append(p)
                self.listbox.insert("end", p)
                added += 1
        self._update_hint()
        if added and not self.working:
            self.status.set(f"{len(self.files)} file(s) ready")
        elif skipped and not added:
            self.status.set("That file type is not a supported audio/video file")

    def _update_hint(self):
        if self.files:
            self.hint.place_forget()
        else:
            self.hint.place(relx=0.5, rely=0.5, anchor="center")

    def remove_selected(self):
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)
            del self.files[i]
        self._update_hint()

    def clear(self):
        self.listbox.delete(0, "end")
        self.files.clear()
        self._update_hint()

    # ---- drag & drop ----
    def _setup_drop(self):
        if not DND_OK:
            return

        def register(w):
            try:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)
                w.dnd_bind("<<DropEnter>>", self.on_drop_enter)
                w.dnd_bind("<<DropLeave>>", self.on_drop_leave)
            except Exception:
                pass
            for child in w.winfo_children():
                register(child)

        register(self)

    def on_drop_enter(self, event):
        self.box.config(bg=ACCENT)
        return event.action

    def on_drop_leave(self, event):
        self.box.config(bg=BORDER)
        return event.action

    def on_drop(self, event):
        self.box.config(bg=BORDER)
        self.add_paths(self.tk.splitlist(event.data))
        return event.action

    def pick_outdir(self):
        d = filedialog.askdirectory()
        if d:
            self.outdir.set(d)

    # ---- conversion ----
    def start(self):
        if self.working:
            return
        if not self.ffmpeg:
            DarkMessage(self, "FFmpeg missing", "FFmpeg was not found, so nothing can be converted. "
                        "Set its location in Settings.", "error")
            return
        if not self.files:
            DarkMessage(self, "No files", "Add at least one file first.", "info")
            return
        self.cancel.clear()
        self.working = True
        self.go_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.bar["value"] = 0
        self.total_bar["value"] = 0
        job = (list(self.files), self.fmt.get(), self.quality.get(), self.outdir.get().strip())
        threading.Thread(target=self._worker, args=job, daemon=True).start()

    def cancel_job(self):
        self.cancel.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    # ---- updates ----
    def check_updates(self, manual=False):
        if not UPDATE_URL:
            if manual:
                DarkMessage(self, "Updates", "Automatic updates are not set up in this version.", "info")
            return
        self._manual_check = manual
        threading.Thread(target=self._update_check_worker, daemon=True).start()

    def _update_check_worker(self):
        manual = self._manual_check
        try:
            req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": "MediaConverter"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            if parse_version(data["version"]) > parse_version(APP_VERSION):
                self.msgs.put(("update_found", data))
            elif manual:
                self.msgs.put(("update_none", None))
        except Exception as e:
            if manual:
                self.msgs.put(("update_error", f"Could not check for updates.\n{e}"))

    def _offer_update(self, data):
        if self.working:
            if self._manual_check:
                DarkMessage(self, "Update available", "A new version is available. "
                            "Please wait until the current conversion finishes, then check again.", "info")
            return
        text = f"A new version ({data['version']}) is available. You have version {APP_VERSION}."
        if data.get("notes"):
            text += "\n\n" + str(data["notes"])
        dlg = DarkMessage(self, "Update available", text, "info", buttons=["Update now", "Later"])
        if dlg.result == "Update now":
            self.status.set("Downloading update...")
            self.bar["value"] = 0
            self.go_btn.config(state="disabled")
            threading.Thread(target=self._download_worker, args=(data,), daemon=True).start()

    def _download_worker(self, data):
        try:
            url = data["url"]
            if not url.lower().startswith("https://"):
                raise ValueError("The update link must start with https://")
            path = os.path.join(tempfile.gettempdir(), f"MediaConverter_Setup_{data['version']}.exe")
            digest = hashlib.sha256()
            req = urllib.request.Request(url, headers={"User-Agent": "MediaConverter"})
            with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as out:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if total:
                        self.msgs.put(("file", done / total * 100))
            expected = str(data.get("sha256") or "").strip().lower()
            if expected and digest.hexdigest() != expected:
                os.remove(path)
                raise ValueError("The downloaded file is damaged or was changed (checksum mismatch).")
            self.msgs.put(("update_ready", path))
        except Exception as e:
            self.msgs.put(("update_error", f"The update could not be downloaded.\n{e}"))

    def _run_installer(self, path):
        """Start the downloaded installer (asks Windows for permission), then close this app."""
        try:
            import ctypes
            r = ctypes.windll.shell32.ShellExecuteW(None, "runas", path, "/SILENT /CLOSEAPPLICATIONS",
                                                    None, 1)
            return r > 32
        except Exception:
            return False

    @staticmethod
    def _rm(path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def _log_error(self, cmd, code, err):
        try:
            log = os.path.join(os.path.dirname(settings_path()), "last_error.log")
            with open(log, "w", encoding="utf-8") as f:
                f.write("Command:\n" + " ".join(f'"{c}"' for c in cmd) + f"\n\nExit code: {code}\n\n{err}\n")
        except Exception:
            pass

    def _convert(self, src, out, fmt, quality, duration, idx, n):
        """Run one ffmpeg job. Returns (exit code, stderr text, command)."""
        cmd = build_command(self.ffmpeg, src, out, fmt, quality)
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, creationflags=NO_WINDOW)
            self.proc = p
            chunks = []
            t = threading.Thread(target=lambda: chunks.append(p.stderr.read()), daemon=True)
            t.start()
            for raw in p.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith(("out_time_us=", "out_time_ms=")) and duration > 0:
                    try:
                        pct = min(100, int(line.split("=")[1]) / 1_000_000 / duration * 100)
                        self.msgs.put(("file", pct))
                        self.msgs.put(("total", (idx + pct / 100) / n * 100))
                    except ValueError:
                        pass
            p.wait()
            t.join(timeout=5)
            return p.returncode, b"".join(chunks).decode("utf-8", "replace"), cmd
        except Exception as e:
            return 1, str(e), cmd

    def _worker(self, files, fmt, quality, outdir):
        ok, failed, last_folder = 0, [], ""
        n = len(files)
        for idx, src in enumerate(files):
            if self.cancel.is_set():
                break
            folder = os.path.normpath(outdir or os.path.dirname(src))
            os.makedirs(folder, exist_ok=True)
            last_folder = folder
            base = os.path.splitext(os.path.basename(src))[0]
            dst = os.path.join(folder, f"{base}.{fmt}")
            k = 1
            while os.path.exists(dst):
                suffix = "_converted" if k == 1 else f"_converted{k}"
                dst = os.path.join(folder, f"{base}{suffix}.{fmt}")
                k += 1
            self.msgs.put(("status", f"Converting {idx + 1}/{n}: {os.path.basename(src)}"))
            self.msgs.put(("file", 0))
            duration = get_duration(self.ffprobe, src)
            tmp_out = os.path.join(folder, f"~mc_{os.getpid()}_{idx}.{fmt}")
            code, err, cmd = self._convert(src, tmp_out, fmt, quality, duration, idx, n)
            if (code != 0 and code not in DLL_MISSING and not self.cancel.is_set()
                    and not (src.isascii() and folder.isascii())):
                # retry through plain-ASCII temporary names (Arabic/emoji/special characters in paths)
                self._rm(tmp_out)
                work = tempfile.mkdtemp(prefix="mc_")
                try:
                    alias = os.path.join(work, "input" + os.path.splitext(src)[1])
                    try:
                        os.link(src, alias)
                    except Exception:
                        shutil.copy2(src, alias)
                    tmp2 = os.path.join(work, f"output.{fmt}")
                    code, err, cmd = self._convert(alias, tmp2, fmt, quality, duration, idx, n)
                    if code == 0 and os.path.isfile(tmp2):
                        shutil.move(tmp2, tmp_out)
                except Exception as e:
                    err = (err + "\n" + str(e)).strip()
                    code = code or 1
                finally:
                    shutil.rmtree(work, ignore_errors=True)
            if self.cancel.is_set():
                self._rm(tmp_out)
                break
            good = code == 0 and os.path.isfile(tmp_out) and os.path.getsize(tmp_out) > 0
            if good:
                try:
                    os.replace(tmp_out, dst)
                except Exception as e:
                    good, err = False, str(e)
            if good:
                ok += 1
            else:
                self._rm(tmp_out)
                lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
                if code in DLL_MISSING:
                    msg = ("FFmpeg cannot start because some of its .dll files are missing. "
                           "Copy ALL the .dll files from the FFmpeg 'bin' folder into the same folder "
                           "as ffmpeg.exe (or use the 'essentials' FFmpeg build, which has no DLLs).")
                else:
                    msg = " / ".join(lines[-2:]) if lines else f"ffmpeg stopped with code {code}"
                failed.append((os.path.basename(src), msg))
                self._log_error(cmd, code, err)
            self.msgs.put(("file", 100))
            self.msgs.put(("total", (idx + 1) / n * 100))
        self.msgs.put(("done", (ok, failed, self.cancel.is_set(), last_folder)))

    def _poll(self):
        try:
            while True:
                kind, val = self.msgs.get_nowait()
                if kind == "status":
                    self.status.set(val)
                elif kind == "file":
                    self.bar["value"] = val
                elif kind == "total":
                    self.total_bar["value"] = val
                elif kind == "update_found":
                    self._offer_update(val)
                elif kind == "update_none":
                    DarkMessage(self, "Updates", f"You have the latest version ({APP_VERSION}).", "info")
                elif kind == "update_error":
                    self.go_btn.config(state="normal")
                    self.status.set("Ready")
                    DarkMessage(self, "Update", val, "warn")
                elif kind == "update_ready":
                    self.status.set("Installing update...")
                    if self._run_installer(val):
                        self.destroy()
                        return
                    self.go_btn.config(state="normal")
                    self.status.set("Update cancelled")
                elif kind == "done":
                    ok, failed, cancelled, folder = val
                    self.working = False
                    self.go_btn.config(state="normal")
                    self.cancel_btn.config(state="disabled")
                    if folder:
                        self.last_folder = folder
                    self.status.set("Cancelled" if cancelled else f"Done: {ok} converted, {len(failed)} failed")
                    if failed:
                        DarkMessage(self, "Some files failed",
                                    "\n\n".join(f"{n}\n→ {e}" for n, e in failed[:5]) +
                                    "\n\nFull details were saved to:\n" +
                                    os.path.join(os.path.dirname(settings_path()), "last_error.log"), "error")
                    elif not cancelled and ok:
                        if self.settings["open_when_done"] and folder:
                            open_folder(folder)
                        else:
                            DarkMessage(self, "Finished", f"{ok} file(s) converted successfully.", "info")
        except queue.Empty:
            pass
        self.after(100, self._poll)


if __name__ == "__main__":
    App().mainloop()
