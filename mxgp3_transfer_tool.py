import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "MXGP3 Transfer Tool"
VERSION = "0.3"
STEAM_APP_ID = "561600"
REQUIRED_TABLES = {"Pilots", "Teams", "PilotsInRosters"}
MOD_PAK_NAME = "pakchunk99-MXGP3TransferTool_P.pak"
OLD_MOD_PAK_NAMES = [
    "pakchunk0-WindowsNoEditor_MXGP3TransferTool_P.pak",
    "pakchunk99-MXGP3TransferTool_P.pak",
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry("900x700")
        self.minsize(820, 620)
        self.conn = None
        self.db_path = None
        self.game_path = None
        self.unrealpak_path = None
        self.riders = {}
        self.teams = {}
        self.config = self.load_config()
        self._build_ui()
        self.after(250, self.auto_detect)

    def _build_ui(self):
        ttk.Label(self, text="MXGP3 TRANSFER TOOL", font=("Segoe UI", 20, "bold")).pack(pady=(16, 2))
        ttk.Label(self, text="v0.3 AUTO REPLACE TEST BUILD — Cro14 / Jeffrey Herlings").pack(pady=(0, 12))

        detect = ttk.LabelFrame(self, text="Automatic detection")
        detect.pack(fill="x", padx=18, pady=7)
        detect.columnconfigure(1, weight=1)
        ttk.Label(detect, text="Game:").grid(row=0, column=0, sticky="w", padx=10, pady=5)
        self.game_label = ttk.Label(detect, text="Searching...")
        self.game_label.grid(row=0, column=1, sticky="ew", padx=6, pady=5)
        ttk.Label(detect, text="Database:").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        self.db_label = ttk.Label(detect, text="Searching...")
        self.db_label.grid(row=1, column=1, sticky="ew", padx=6, pady=5)
        ttk.Label(detect, text="UnrealPak:").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        self.unrealpak_label = ttk.Label(detect, text="Searching...")
        self.unrealpak_label.grid(row=2, column=1, sticky="ew", padx=6, pady=5)
        ttk.Button(detect, text="Auto Detect", command=lambda: self.auto_detect(True)).grid(row=0, column=2, rowspan=3, padx=6, pady=8)
        ttk.Button(detect, text="Browse DB", command=self.open_db).grid(row=0, column=3, rowspan=3, padx=6, pady=8)
        ttk.Button(detect, text="Browse UnrealPak", command=self.browse_unrealpak).grid(row=0, column=4, rowspan=3, padx=(6, 10), pady=8)

        tf = ttk.LabelFrame(self, text="Rider transfer — automatic game install")
        tf.pack(fill="x", padx=18, pady=7)
        tf.columnconfigure(1, weight=1)
        ttk.Label(tf, text="Class:").grid(row=0, column=0, sticky="w", padx=10, pady=7)
        self.class_box = ttk.Combobox(tf, state="readonly", values=["MX2", "MXGP"])
        self.class_box.grid(row=0, column=1, sticky="ew", padx=10, pady=7)
        self.class_box.bind("<<ComboboxSelected>>", lambda e: self.load_riders())
        ttk.Label(tf, text="Rider:").grid(row=1, column=0, sticky="w", padx=10, pady=7)
        self.rider_box = ttk.Combobox(tf, state="readonly")
        self.rider_box.grid(row=1, column=1, sticky="ew", padx=10, pady=7)
        self.rider_box.bind("<<ComboboxSelected>>", lambda e: self.rider_changed())
        ttk.Label(tf, text="Current team:").grid(row=2, column=0, sticky="w", padx=10, pady=7)
        self.current_team = ttk.Label(tf, text="-")
        self.current_team.grid(row=2, column=1, sticky="w", padx=10, pady=7)
        ttk.Label(tf, text="New team:").grid(row=3, column=0, sticky="w", padx=10, pady=7)
        self.team_box = ttk.Combobox(tf, state="readonly")
        self.team_box.grid(row=3, column=1, sticky="ew", padx=10, pady=7)
        ttk.Button(tf, text="TRANSFER RIDER — AUTO INSTALL", command=self.transfer_and_apply).grid(
            row=4, column=0, columnspan=2, pady=14, ipadx=34, ipady=7
        )

        af = ttk.LabelFrame(self, text="Automatic replacement")
        af.pack(fill="x", padx=18, pady=7)
        ttk.Label(
            af,
            text="Each transfer rebuilds the DB override, replaces the previous tool PAK atomically, then verifies it."
        ).pack(side="left", padx=10, pady=9)
        ttk.Button(af, text="Remove Tool PAK", command=self.remove_mod_pak).pack(side="right", padx=10, pady=9)

        sf = ttk.LabelFrame(self, text="Safety")
        sf.pack(fill="x", padx=18, pady=7)
        ttk.Button(sf, text="Create DB Backup", command=self.backup_manual).pack(side="left", padx=10, pady=9)
        ttk.Button(sf, text="Restore DB Backup", command=self.restore_backup).pack(side="left", padx=10, pady=9)

        lf = ttk.LabelFrame(self, text="Log")
        lf.pack(fill="both", expand=True, padx=18, pady=(7, 18))
        self.logbox = tk.Text(lf, height=12, state="disabled", font=("Consolas", 9))
        self.logbox.pack(fill="both", expand=True, padx=8, pady=8)
        self.log("v0.3: one click now edits the DB and automatically replaces the installed override PAK.")

    def log(self, text):
        self.logbox.config(state="normal")
        self.logbox.insert("end", text + "\n")
        self.logbox.see("end")
        self.logbox.config(state="disabled")

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
        self.config["last_db"] = self.db_path
        self.config["last_game"] = self.game_path
        self.config["unrealpak"] = self.unrealpak_path
        try:
            self.config_path().write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        except Exception as e:
            self.log(f"Warning saving config: {e}")

    def auto_detect(self, show_result=False):
        self.log("Auto detection started...")
        game = self.detect_game_path()
        if game:
            self.game_path = str(game)
            self.game_label.config(text=self.game_path)
            self.log(f"Game detected: {self.game_path}")
        else:
            self.game_label.config(text="Not detected")
            self.log("MXGP3 installation not detected.")

        db = self.detect_database_path(game)
        if db:
            try:
                self.load_database(str(db), automatic=True)
            except Exception as e:
                self.log(f"DB rejected: {e}")
        else:
            self.db_label.config(text="Not detected — Browse DB once")

        up = self.detect_unrealpak()
        if up:
            self.unrealpak_path = str(up)
            self.unrealpak_label.config(text=self.unrealpak_path)
            self.log(f"UnrealPak detected: {self.unrealpak_path}")
        else:
            self.unrealpak_label.config(text="Not detected — Browse UnrealPak once")
            self.log("UnrealPak.exe not detected.")

        self.save_config()
        if show_result:
            messagebox.showinfo(APP_NAME, "Detection complete. Check the three paths shown in the tool.")

    def detect_game_path(self):
        last = self.config.get("last_game")
        if last and self.looks_like_game_dir(Path(last)):
            return Path(last)
        for root in self.get_steam_roots():
            for library in self.get_steam_libraries(root):
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
                    pass
        return None

    def get_steam_roots(self):
        roots = []
        if os.name == "nt":
            try:
                import winreg
                checks = [
                    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamExe"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
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
        roots += [
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam",
            Path(r"C:\Steam"),
        ]
        out, seen = [], set()
        for p in roots:
            k = str(p).lower()
            if k not in seen and p.exists():
                seen.add(k)
                out.append(p)
        return out

    def get_steam_libraries(self, steam_root):
        libs = [steam_root]
        vdf = steam_root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            try:
                text = vdf.read_text(encoding="utf-8", errors="ignore")
                for raw in re.findall(r'"path"\s+"([^"]+)"', text, re.I):
                    libs.append(Path(raw.replace("\\\\", "\\")))
            except Exception:
                pass
        out, seen = [], set()
        for p in libs:
            k = str(p).lower()
            if k not in seen and p.exists():
                seen.add(k)
                out.append(p)
        return out

    def looks_like_game_dir(self, p):
        return bool(p and p.exists() and self.find_paks_dir(p))

    def find_paks_dir(self, game=None):
        game = Path(game or self.game_path or "")
        candidates = [
            game / "mxgp3" / "Content" / "Paks",
            game / "MXGP3" / "Content" / "Paks",
            game / "Content" / "Paks",
        ]
        return next((p for p in candidates if p.exists()), None)

    def internal_db_path(self, paks_dir):
        try:
            project_name = paks_dir.parent.parent.name
            if not project_name or project_name.lower() == Path(self.game_path or "").name.lower():
                if paks_dir.parent.name.lower() == "content":
                    project_name = paks_dir.parent.parent.name or "mxgp3"
            if project_name.lower() == "content":
                project_name = "mxgp3"
        except Exception:
            project_name = "mxgp3"
        if not project_name:
            project_name = "mxgp3"
        return f"../../../{project_name}/Content/assets/data/db/NoCook/DB.sqlite3"

    def detect_database_path(self, game=None):
        candidates = []
        last = self.config.get("last_db")
        if last:
            candidates.append(Path(last))
        app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        roots = [app_dir, Path.cwd()]
        if game:
            roots.insert(0, Path(game))
        rels = [
            Path("DB.sqlite3"),
            Path("NoCook/DB.sqlite3"),
            Path("Content/assets/data/db/NoCook/DB.sqlite3"),
            Path("mxgp3/Content/assets/data/db/NoCook/DB.sqlite3"),
            Path("Extracted/Content/assets/data/db/NoCook/DB.sqlite3"),
            Path("Extracted/mxgp3/Content/assets/data/db/NoCook/DB.sqlite3"),
        ]
        for root in roots:
            for rel in rels:
                candidates.append(root / rel)
        for p in candidates:
            if p.exists() and self.is_compatible_db(p):
                return p
        for root in roots:
            found = self.scan_for_database(root, 7)
            if found:
                return found
        return None

    def scan_for_database(self, root, max_depth=7):
        try:
            root = Path(root)
            if not root.exists():
                return None
            base_depth = len(root.parts)
            skip = {".git", "Engine", "Binaries", "Saved", "Intermediate", "__pycache__"}
            for current, dirs, files in os.walk(root):
                p = Path(current)
                if len(p.parts) - base_depth >= max_depth:
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

    def is_compatible_db(self, p):
        try:
            c = sqlite3.connect(str(p))
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            c.close()
            return REQUIRED_TABLES.issubset(tables)
        except Exception:
            return False

    def detect_unrealpak(self):
        last = self.config.get("unrealpak")
        if last and Path(last).is_file():
            return Path(last)
        app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        direct = [
            app_dir / "UnrealPak.exe",
            app_dir / "UnrealPak" / "UnrealPak.exe",
            Path.cwd() / "UnrealPak.exe",
        ]
        for p in direct:
            if p.exists():
                return p
        roots = [Path.home() / "Downloads", Path.home() / "Desktop", Path.home() / "Documents"]
        for root in roots:
            if not root.exists():
                continue
            try:
                for current, dirs, files in os.walk(root):
                    depth = len(Path(current).parts) - len(root.parts)
                    if depth >= 6:
                        dirs[:] = []
                    if "UnrealPak.exe" in files:
                        return Path(current) / "UnrealPak.exe"
            except Exception:
                pass
        return None

    def browse_unrealpak(self):
        p = filedialog.askopenfilename(
            title="Select UnrealPak.exe",
            filetypes=[("UnrealPak", "UnrealPak.exe"), ("Executable", "*.exe")],
        )
        if p:
            self.unrealpak_path = p
            self.unrealpak_label.config(text=p)
            self.save_config()

    def open_db(self):
        p = filedialog.askopenfilename(
            title="Select MXGP3 DB.sqlite3",
            filetypes=[("SQLite database", "*.sqlite3"), ("All files", "*.*")],
        )
        if p:
            try:
                self.load_database(p)
            except Exception as e:
                messagebox.showerror(APP_NAME, str(e))

    def load_database(self, path, automatic=False):
        c = sqlite3.connect(path)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = REQUIRED_TABLES - tables
        if missing:
            c.close()
            raise RuntimeError("Not a compatible MXGP3 DB. Missing: " + ", ".join(sorted(missing)))
        if self.conn:
            self.conn.close()
        self.conn = c
        self.db_path = path
        self.db_label.config(text=path)
        self.class_box.set("MX2")
        self.load_riders()
        self.save_config()
        self.log(("Auto-loaded" if automatic else "Loaded") + f" DB: {path}")

    def load_riders(self):
        if not self.conn:
            return
        cat = self.class_box.get()
        rows = self.conn.execute(
            """SELECT P.Key,P.Number,P.Teams_Key
               FROM Pilots P JOIN Teams T ON P.Teams_Key=T.Key
               WHERE P.IsStrippedFromDB=0 AND P.Teams_Key IS NOT NULL AND T.Categories_Key=?
               ORDER BY P.Key""",
            (cat,),
        ).fetchall()
        self.riders, values = {}, []
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
        self.teams, names = {}, []
        for (team_key,) in rows:
            short = team_key[len(cat) + 1:] if team_key.startswith(cat + "-") else team_key
            self.teams[short] = team_key
            names.append(short)
        self.team_box["values"] = names
        self.current_team.config(text=old_team)
        old_short = old_team[len(cat) + 1:] if old_team.startswith(cat + "-") else old_team
        if old_short in self.teams:
            self.team_box.set(old_short)

    def create_backup(self):
        if not self.db_path:
            raise RuntimeError("No DB loaded")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = self.db_path + f".MXGP3TransferTool_{stamp}.bak"
        shutil.copy2(self.db_path, out)
        return out

    def backup_manual(self):
        try:
            out = self.create_backup()
            self.log(f"DB backup: {out}")
            messagebox.showinfo(APP_NAME, f"Backup created:\n\n{out}")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def restore_backup(self):
        if not self.db_path:
            return messagebox.showwarning(APP_NAME, "Load DB first.")
        bak = filedialog.askopenfilename(title="Select backup", filetypes=[("Backup", "*.bak"), ("All files", "*.*")])
        if not bak:
            return
        if not messagebox.askyesno(APP_NAME, "Restore this DB backup?"):
            return
        try:
            if self.conn:
                self.conn.close()
            shutil.copy2(bak, self.db_path)
            self.conn = sqlite3.connect(self.db_path)
            self.load_riders()
            self.log(f"Restored DB backup: {bak}")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def game_is_running(self):
        if os.name != "nt":
            return False
        try:
            proc = subprocess.run(
                ["tasklist"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                errors="ignore",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            text = proc.stdout.lower()
            return any(name in text for name in ["mxgp3.exe", "mxgp3-win64-shipping.exe"])
        except Exception:
            return False

    def transfer_and_apply(self):
        if not self.conn:
            return messagebox.showwarning(APP_NAME, "Load DB.sqlite3 first.")
        if self.game_is_running():
            return messagebox.showwarning(APP_NAME, "Close MXGP3 before applying a transfer, then try again.")
        rider = self.riders.get(self.rider_box.get())
        new_team = self.teams.get(self.team_box.get())
        if not rider or not new_team:
            return
        rider_key, old_team = rider
        if old_team == new_team:
            return messagebox.showinfo(APP_NAME, "Rider is already in that team.")
        if not messagebox.askyesno(
            APP_NAME,
            f"Transfer and automatically replace the game override?\n\n{rider_key}\n{old_team}\n→\n{new_team}",
        ):
            return

        backup = None
        try:
            backup = self.create_backup()
            self.conn.execute("UPDATE Pilots SET Teams_Key=? WHERE Key=?", (new_team, rider_key))
            self.conn.commit()
            check = self.conn.execute("SELECT Teams_Key FROM Pilots WHERE Key=?", (rider_key,)).fetchone()
            if not check or check[0] != new_team:
                raise RuntimeError("DB verification failed")

            self.log(f"DB changed: {rider_key}: {old_team} -> {new_team}")
            self.log(f"Backup: {backup}")
            installed = self.build_and_install_pak()
            self.load_riders()
            messagebox.showinfo(
                APP_NAME,
                f"Transfer applied automatically.\n\nInstalled/replaced:\n{installed}\n\nStart MXGP3 and test Quick Race.",
            )
        except Exception as e:
            if backup and Path(backup).exists() and self.db_path:
                try:
                    if self.conn:
                        self.conn.close()
                    shutil.copy2(backup, self.db_path)
                    self.conn = sqlite3.connect(self.db_path)
                    self.load_riders()
                    self.log("Apply failed: DB rolled back automatically.")
                except Exception as rollback_error:
                    self.log(f"Rollback warning: {rollback_error}")
            messagebox.showerror(APP_NAME, str(e))

    def build_and_install_pak(self):
        if not self.db_path or not Path(self.db_path).exists():
            raise RuntimeError("Compatible DB.sqlite3 is not loaded.")
        if not self.game_path:
            raise RuntimeError("MXGP3 installation was not detected.")
        paks_dir = self.find_paks_dir()
        if not paks_dir:
            raise RuntimeError("MXGP3 Content\\Paks folder not found.")
        if not self.unrealpak_path or not Path(self.unrealpak_path).exists():
            raise RuntimeError("UnrealPak.exe not found. Select it once with Browse UnrealPak; after that it is remembered.")

        internal_db = self.internal_db_path(paks_dir)
        final_pak = paks_dir / MOD_PAK_NAME
        backup_pak = paks_dir / (MOD_PAK_NAME + ".backup")
        staged_install = paks_dir / (MOD_PAK_NAME + ".new")

        with tempfile.TemporaryDirectory(prefix="MXGP3TransferTool_") as td_raw:
            td = Path(td_raw)
            staged_db = td / "DB.sqlite3"
            shutil.copy2(self.db_path, staged_db)
            response = td / "paklist.txt"
            response.write_text(f'"{staged_db}" "{internal_db}"\n', encoding="utf-8")
            output = td / MOD_PAK_NAME

            self.log(f"Building high-priority override: {MOD_PAK_NAME}")
            self.log(f"Internal DB path: {internal_db}")
            proc = subprocess.run(
                [self.unrealpak_path, str(output), f"-Create={response}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="ignore",
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            if proc.returncode != 0 or not output.exists() or output.stat().st_size < 1024:
                raise RuntimeError("UnrealPak failed.\n\n" + proc.stdout[-4000:])

            verify = subprocess.run(
                [self.unrealpak_path, str(output), "-List"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="ignore",
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            listing = verify.stdout.lower().replace("\\", "/")
            expected_tail = "/content/assets/data/db/nocook/db.sqlite3"
            if "db.sqlite3" not in listing or expected_tail not in listing:
                raise RuntimeError("PAK was built, but the internal DB path failed verification. Nothing was replaced.")

            if staged_install.exists():
                staged_install.unlink()
            shutil.copy2(output, staged_install)

        # Clean obsolete tool PAK names so only the newest override can win.
        for old_name in OLD_MOD_PAK_NAMES:
            old = paks_dir / old_name
            if old.name == MOD_PAK_NAME:
                continue
            if old.exists():
                old_backup = old.with_suffix(old.suffix + ".obsolete")
                try:
                    if old_backup.exists():
                        old_backup.unlink()
                    os.replace(old, old_backup)
                    self.log(f"Disabled obsolete tool PAK: {old_backup.name}")
                except Exception as e:
                    self.log(f"Could not disable old PAK {old.name}: {e}")

        # Back up the previously installed tool PAK, then atomically replace it.
        if final_pak.exists():
            if backup_pak.exists():
                backup_pak.unlink()
            shutil.copy2(final_pak, backup_pak)
            self.log(f"Previous override backed up: {backup_pak.name}")

        try:
            os.replace(staged_install, final_pak)
        except PermissionError:
            raise RuntimeError("Windows blocked the PAK replacement. Make sure MXGP3 is fully closed and run the tool as administrator if needed.")

        # Remove an old fake/copied signature from earlier builds; a copied signature is not valid for a modified PAK.
        stale_sig = final_pak.with_suffix(".sig")
        if stale_sig.exists():
            try:
                stale_sig.unlink()
                self.log("Removed stale tool .sig from an older build.")
            except Exception:
                pass

        if not final_pak.exists() or final_pak.stat().st_size < 1024:
            raise RuntimeError("Automatic replacement failed: final PAK is missing or invalid.")

        final_verify = subprocess.run(
            [self.unrealpak_path, str(final_pak), "-List"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="ignore",
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
        final_listing = final_verify.stdout.lower().replace("\\", "/")
        if "db.sqlite3" not in final_listing or "/content/assets/data/db/nocook/db.sqlite3" not in final_listing:
            if backup_pak.exists():
                os.replace(backup_pak, final_pak)
            raise RuntimeError("Installed PAK failed final verification. Previous tool PAK was restored.")

        self.log(f"AUTO REPLACE OK: {final_pak}")
        self.log("The previous Transfer Tool override was replaced automatically.")
        return final_pak

    def remove_mod_pak(self):
        paks_dir = self.find_paks_dir()
        if not paks_dir:
            return messagebox.showwarning(APP_NAME, "Game Paks folder not detected.")
        removed = []
        candidates = [paks_dir / n for n in OLD_MOD_PAK_NAMES]
        candidates += [paks_dir / (MOD_PAK_NAME + ".new"), paks_dir / (MOD_PAK_NAME + ".backup")]
        for p in candidates:
            if p.exists():
                try:
                    p.unlink()
                    removed.append(str(p))
                except Exception as e:
                    return messagebox.showerror(APP_NAME, str(e))
        if removed:
            self.log("Removed Transfer Tool PAK files.")
            messagebox.showinfo(APP_NAME, "Transfer Tool PAK removed. Restart MXGP3.")
        else:
            messagebox.showinfo(APP_NAME, "No Transfer Tool PAK is installed.")


if __name__ == "__main__":
    App().mainloop()
