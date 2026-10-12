import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "MXGP3 Transfer Tool"
VERSION = "0.1"
STEAM_APP_ID = "561600"
REQUIRED_TABLES = {"Pilots", "Teams", "PilotsInRosters"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry("820x610")
        self.minsize(760, 560)

        self.conn = None
        self.db_path = None
        self.game_path = None
        self.riders = {}
        self.teams = {}
        self.config = self.load_config()

        self._build_ui()
        self.after(250, self.auto_detect)

    # -------------------- UI --------------------

    def _build_ui(self):
        ttk.Label(self, text="MXGP3 TRANSFER TOOL", font=("Segoe UI", 20, "bold")).pack(pady=(18, 2))
        ttk.Label(self, text="v0.1 TEST BUILD — Cro14 / Jeffrey Helings").pack(pady=(0, 14))

        detect = ttk.LabelFrame(self, text="Automatic detection")
        detect.pack(fill="x", padx=18, pady=8)
        detect.columnconfigure(1, weight=1)

        ttk.Label(detect, text="Game:").grid(row=0, column=0, sticky="w", padx=(10, 6), pady=(10, 5))
        self.game_label = ttk.Label(detect, text="Searching...")
        self.game_label.grid(row=0, column=1, sticky="ew", padx=6, pady=(10, 5))

        ttk.Label(detect, text="Database:").grid(row=1, column=0, sticky="w", padx=(10, 6), pady=(5, 10))
        self.db_label = ttk.Label(detect, text="Searching...")
        self.db_label.grid(row=1, column=1, sticky="ew", padx=6, pady=(5, 10))

        ttk.Button(detect, text="Auto Detect", command=lambda: self.auto_detect(show_result=True)).grid(
            row=0, column=2, rowspan=2, padx=(8, 4), pady=10, ipadx=8, ipady=4
        )
        ttk.Button(detect, text="Browse DB", command=self.open_db).grid(
            row=0, column=3, rowspan=2, padx=(4, 10), pady=10, ipadx=8, ipady=4
        )

        tf = ttk.LabelFrame(self, text="Transfer")
        tf.pack(fill="x", padx=18, pady=8)
        tf.columnconfigure(1, weight=1)

        ttk.Label(tf, text="Class:").grid(row=0, column=0, sticky="w", padx=10, pady=8)
        self.class_box = ttk.Combobox(tf, state="readonly", values=["MX2", "MXGP"])
        self.class_box.grid(row=0, column=1, sticky="ew", padx=10, pady=8)
        self.class_box.bind("<<ComboboxSelected>>", lambda e: self.load_riders())

        ttk.Label(tf, text="Rider:").grid(row=1, column=0, sticky="w", padx=10, pady=8)
        self.rider_box = ttk.Combobox(tf, state="readonly")
        self.rider_box.grid(row=1, column=1, sticky="ew", padx=10, pady=8)
        self.rider_box.bind("<<ComboboxSelected>>", lambda e: self.rider_changed())

        ttk.Label(tf, text="Current team:").grid(row=2, column=0, sticky="w", padx=10, pady=8)
        self.current_team = ttk.Label(tf, text="-")
        self.current_team.grid(row=2, column=1, sticky="w", padx=10, pady=8)

        ttk.Label(tf, text="New team:").grid(row=3, column=0, sticky="w", padx=10, pady=8)
        self.team_box = ttk.Combobox(tf, state="readonly")
        self.team_box.grid(row=3, column=1, sticky="ew", padx=10, pady=8)

        ttk.Button(tf, text="TRANSFER RIDER", command=self.transfer).grid(
            row=4, column=0, columnspan=2, pady=14, ipadx=30, ipady=5
        )

        sf = ttk.LabelFrame(self, text="Safety")
        sf.pack(fill="x", padx=18, pady=8)
        ttk.Button(sf, text="Create Backup", command=self.backup_manual).pack(side="left", padx=10, pady=10)
        ttk.Button(sf, text="Restore Backup", command=self.restore_backup).pack(side="left", padx=10, pady=10)

        lf = ttk.LabelFrame(self, text="Log")
        lf.pack(fill="both", expand=True, padx=18, pady=(8, 18))
        self.logbox = tk.Text(lf, height=9, state="disabled", font=("Consolas", 9))
        self.logbox.pack(fill="both", expand=True, padx=8, pady=8)
        self.log("Ready. Automatic detection will start now.")

    def log(self, text):
        self.logbox.config(state="normal")
        self.logbox.insert("end", text + "\n")
        self.logbox.see("end")
        self.logbox.config(state="disabled")

    # -------------------- CONFIG --------------------

    def config_path(self):
        base = os.getenv("APPDATA") or str(Path.home())
        folder = Path(base) / "MXGP3TransferTool"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "config.json"

    def load_config(self):
        try:
            p = self.config_path()
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def save_config(self):
        try:
            self.config["last_db"] = self.db_path
            self.config["last_game"] = self.game_path
            self.config_path().write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        except Exception as e:
            self.log(f"Warning: couldn't save settings: {e}")

    # -------------------- AUTOMATIC DETECTION --------------------

    def auto_detect(self, show_result=False):
        self.log("Auto detection started...")

        game = self.detect_game_path()
        if game:
            self.game_path = str(game)
            self.game_label.config(text=self.game_path)
            self.log(f"MXGP3 detected: {self.game_path}")
        else:
            self.game_label.config(text="Not detected")
            self.log("MXGP3 Steam installation not detected.")

        db = self.detect_database_path(game)
        if db:
            try:
                self.load_database(str(db), automatic=True)
                self.save_config()
                if show_result:
                    messagebox.showinfo(APP_NAME, f"MXGP3 database detected automatically:\n\n{db}")
                return
            except Exception as e:
                self.log(f"Detected DB rejected: {e}")

        self.db_label.config(text="Not detected — use Browse DB once")
        self.log("Compatible DB.sqlite3 not found automatically.")
        if game:
            pak = self.find_main_pak(Path(game))
            if pak:
                self.log(f"Main PAK detected: {pak}")
                self.log("The stock database is still inside the PAK. v0.1 auto-detects an extracted DB.sqlite3.")
        if show_result:
            messagebox.showinfo(
                APP_NAME,
                "MXGP3 was detected, but an extracted compatible DB.sqlite3 was not found.\n\n"
                "Use Browse DB once; the tool remembers it and loads it automatically next time."
                if game else
                "MXGP3 and its extracted DB.sqlite3 were not detected automatically.\n\nUse Browse DB as fallback."
            )

    def detect_game_path(self):
        # 1) Last known valid game folder.
        last = self.config.get("last_game")
        if last and self.looks_like_game_dir(Path(last)):
            return Path(last)

        # 2) Locate Steam libraries and appmanifest_561600.acf.
        for steam_root in self.get_steam_roots():
            for library in self.get_steam_libraries(steam_root):
                manifest = library / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
                if not manifest.exists():
                    continue
                try:
                    text = manifest.read_text(encoding="utf-8", errors="ignore")
                    m = re.search(r'"installdir"\s+"([^"]+)"', text, re.I)
                    if m:
                        game = library / "steamapps" / "common" / m.group(1)
                        if self.looks_like_game_dir(game):
                            return game
                except Exception:
                    continue
        return None

    def get_steam_roots(self):
        roots = []

        # Windows registry is the most reliable source.
        if os.name == "nt":
            try:
                import winreg
                checks = [
                    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamExe"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
                ]
                for hive, key, value in checks:
                    try:
                        with winreg.OpenKey(hive, key) as k:
                            raw, _ = winreg.QueryValueEx(k, value)
                            p = Path(raw)
                            if p.suffix.lower() == ".exe":
                                p = p.parent
                            roots.append(p)
                    except OSError:
                        pass
            except Exception:
                pass

        defaults = [
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam",
            Path(r"C:\Steam"),
        ]
        roots.extend(defaults)

        out = []
        seen = set()
        for p in roots:
            try:
                p = p.resolve()
            except Exception:
                pass
            key = str(p).lower()
            if key not in seen and p.exists():
                seen.add(key)
                out.append(p)
        return out

    def get_steam_libraries(self, steam_root):
        libraries = [steam_root]
        vdf = steam_root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            try:
                text = vdf.read_text(encoding="utf-8", errors="ignore")
                for raw in re.findall(r'"path"\s+"([^"]+)"', text, re.I):
                    raw = raw.replace("\\\\", "\\")
                    libraries.append(Path(raw))
            except Exception:
                pass

        out = []
        seen = set()
        for p in libraries:
            key = str(p).lower()
            if key not in seen and p.exists():
                seen.add(key)
                out.append(p)
        return out

    def looks_like_game_dir(self, path):
        if not path or not path.exists() or not path.is_dir():
            return False
        possible = [
            path / "mxgp3" / "Content" / "Paks",
            path / "MXGP3" / "Content" / "Paks",
            path / "Content" / "Paks",
        ]
        return any(p.exists() for p in possible)

    def find_main_pak(self, game):
        if not game:
            return None
        candidates = [
            game / "mxgp3" / "Content" / "Paks" / "pakchunk0-WindowsNoEditor.pak",
            game / "MXGP3" / "Content" / "Paks" / "pakchunk0-WindowsNoEditor.pak",
            game / "Content" / "Paks" / "pakchunk0-WindowsNoEditor.pak",
        ]
        return next((p for p in candidates if p.exists()), None)

    def detect_database_path(self, game=None):
        candidates = []

        last = self.config.get("last_db")
        if last:
            candidates.append(Path(last))

        app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        cwd = Path.cwd()

        roots = [app_dir, cwd]
        if game:
            roots.insert(0, Path(game))

        relative_candidates = [
            Path("DB.sqlite3"),
            Path("NoCook") / "DB.sqlite3",
            Path("data") / "db" / "NoCook" / "DB.sqlite3",
            Path("assets") / "data" / "db" / "NoCook" / "DB.sqlite3",
            Path("Content") / "assets" / "data" / "db" / "NoCook" / "DB.sqlite3",
            Path("mxgp3") / "Content" / "assets" / "data" / "db" / "NoCook" / "DB.sqlite3",
            Path("Extracted") / "mxgp3" / "Content" / "assets" / "data" / "db" / "NoCook" / "DB.sqlite3",
            Path("Extracted") / "Content" / "assets" / "data" / "db" / "NoCook" / "DB.sqlite3",
        ]

        for root in roots:
            for rel in relative_candidates:
                candidates.append(root / rel)

        checked = set()
        for p in candidates:
            key = str(p).lower()
            if key in checked:
                continue
            checked.add(key)
            if p.exists() and self.is_compatible_db(p):
                return p

        # Limited recursive scan: exact filename only, with aggressive pruning.
        for root in roots:
            found = self.scan_for_database(root, max_depth=7)
            if found:
                return found
        return None

    def scan_for_database(self, root, max_depth=7):
        try:
            root = Path(root)
            if not root.exists() or not root.is_dir():
                return None
            root_parts = len(root.parts)
            skip = {".git", "Engine", "Binaries", "Saved", "Intermediate", "__pycache__"}
            for current, dirs, files in os.walk(root):
                p = Path(current)
                depth = len(p.parts) - root_parts
                if depth >= max_depth:
                    dirs[:] = []
                else:
                    dirs[:] = [d for d in dirs if d not in skip]
                if "DB.sqlite3" in files:
                    candidate = p / "DB.sqlite3"
                    if self.is_compatible_db(candidate):
                        return candidate
        except Exception:
            pass
        return None

    def is_compatible_db(self, path):
        try:
            c = sqlite3.connect(str(path))
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            c.close()
            return REQUIRED_TABLES.issubset(tables)
        except Exception:
            return False

    # -------------------- DATABASE --------------------

    def open_db(self):
        initial = self.game_path or str(Path.home())
        path = filedialog.askopenfilename(
            title="Select MXGP3 DB.sqlite3",
            initialdir=initial if os.path.isdir(initial) else None,
            filetypes=[("SQLite database", "*.sqlite3"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.load_database(path, automatic=False)
            self.save_config()
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def load_database(self, path, automatic=False):
        c = sqlite3.connect(path)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = REQUIRED_TABLES - tables
        if missing:
            c.close()
            raise RuntimeError("Not a compatible MXGP3 database. Missing: " + ", ".join(sorted(missing)))

        if self.conn:
            self.conn.close()
        self.conn = c
        self.db_path = path
        self.db_label.config(text=path)
        self.class_box.set("MX2")
        self.load_riders()
        self.log(("Auto-loaded" if automatic else "Loaded") + f": {path}")

    def load_riders(self):
        if not self.conn:
            return
        cat = self.class_box.get()
        rows = self.conn.execute(
            """SELECT P.Key, P.Number, P.Teams_Key
               FROM Pilots P JOIN Teams T ON P.Teams_Key=T.Key
               WHERE P.IsStrippedFromDB=0 AND P.Teams_Key IS NOT NULL AND T.Categories_Key=?
               ORDER BY P.Key""",
            (cat,),
        ).fetchall()
        self.riders = {}
        values = []
        for key, number, team in rows:
            label = f"#{number}  {key.split('-', 1)[-1]}"
            self.riders[label] = (key, team)
            values.append(label)
        self.rider_box["values"] = values
        if values:
            preferred = next((v for v in values if "Herlings" in v), values[0])
            self.rider_box.set(preferred)
            self.rider_changed()

    def rider_changed(self):
        item = self.riders.get(self.rider_box.get())
        if not item:
            return
        _, old_team = item
        cat = self.class_box.get()
        rows = self.conn.execute("SELECT Key FROM Teams WHERE Categories_Key=? ORDER BY Ordering", (cat,)).fetchall()
        self.teams = {}
        names = []
        for (team_key,) in rows:
            short = team_key[len(cat) + 1:] if team_key.startswith(cat + "-") else team_key
            self.teams[short] = team_key
            names.append(short)
        self.team_box["values"] = names
        self.current_team.config(text=old_team)
        old_short = old_team[len(cat) + 1:] if old_team.startswith(cat + "-") else old_team
        if old_short in self.teams:
            self.team_box.set(old_short)

    # -------------------- BACKUP / RESTORE --------------------

    def create_backup(self):
        if not self.db_path:
            raise RuntimeError("No database loaded")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = self.db_path + f".MXGP3TransferTool_{stamp}.bak"
        shutil.copy2(self.db_path, out)
        return out

    def backup_manual(self):
        try:
            out = self.create_backup()
            self.log(f"Backup created: {out}")
            messagebox.showinfo(APP_NAME, f"Backup created:\n\n{out}")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def restore_backup(self):
        if not self.db_path:
            messagebox.showwarning(APP_NAME, "Load DB.sqlite3 first.")
            return
        bak = filedialog.askopenfilename(
            title="Select backup",
            initialdir=str(Path(self.db_path).parent),
            filetypes=[("Backup", "*.bak"), ("All files", "*.*")],
        )
        if not bak:
            return
        if not messagebox.askyesno(APP_NAME, "Restore this backup and replace the current database?"):
            return
        try:
            if self.conn:
                self.conn.close()
            shutil.copy2(bak, self.db_path)
            self.conn = sqlite3.connect(self.db_path)
            self.load_riders()
            self.log(f"Restored backup: {bak}")
            messagebox.showinfo(APP_NAME, "Backup restored.")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    # -------------------- TRANSFER --------------------

    def transfer(self):
        if not self.conn:
            messagebox.showwarning(APP_NAME, "MXGP3 database was not loaded.")
            return
        rider = self.riders.get(self.rider_box.get())
        new_team = self.teams.get(self.team_box.get())
        if not rider or not new_team:
            return
        rider_key, old_team = rider
        if old_team == new_team:
            messagebox.showinfo(APP_NAME, "The rider is already in this team.")
            return
        if not messagebox.askyesno(APP_NAME, f"Transfer {rider_key}?\n\n{old_team}\n→\n{new_team}"):
            return
        try:
            backup = self.create_backup()
            self.conn.execute("UPDATE Pilots SET Teams_Key=? WHERE Key=?", (new_team, rider_key))
            self.conn.commit()
            check = self.conn.execute("SELECT Teams_Key FROM Pilots WHERE Key=?", (rider_key,)).fetchone()
            if not check or check[0] != new_team:
                raise RuntimeError("Verification failed after transfer")
            self.log(f"{rider_key}: {old_team} -> {new_team}")
            self.log(f"Backup: {backup}")
            messagebox.showinfo(
                APP_NAME,
                "Transfer saved.\n\nv0.1 changes team assignment only; bike/gear graphics are not synchronized yet.",
            )
            self.load_riders()
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass
            messagebox.showerror(APP_NAME, str(e))


if __name__ == "__main__":
    App().mainloop()
