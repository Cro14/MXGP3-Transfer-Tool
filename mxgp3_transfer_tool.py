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
VERSION = "0.2"
STEAM_APP_ID = "561600"
REQUIRED_TABLES = {"Pilots", "Teams", "PilotsInRosters"}
MOD_PAK_NAME = "pakchunk0-WindowsNoEditor_MXGP3TransferTool_P.pak"
INTERNAL_DB_PATH = "../../../mxgp3/Content/assets/data/db/NoCook/DB.sqlite3"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry("900x690")
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
        ttk.Label(self, text="v0.2 PAK TEST BUILD — Cro14 / Jeffrey Helings").pack(pady=(0, 12))

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
        ttk.Button(detect, text="Browse UnrealPak", command=self.browse_unrealpak).grid(row=0, column=4, rowspan=3, padx=(6,10), pady=8)

        tf = ttk.LabelFrame(self, text="Rider transfer")
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
        ttk.Button(tf, text="TRANSFER + APPLY TO GAME", command=self.transfer_and_apply).grid(row=4, column=0, columnspan=2, pady=14, ipadx=32, ipady=6)

        af = ttk.LabelFrame(self, text="Game patch")
        af.pack(fill="x", padx=18, pady=7)
        ttk.Button(af, text="Apply Current DB to Game", command=self.apply_current_db).pack(side="left", padx=10, pady=9)
        ttk.Button(af, text="Remove Transfer PAK", command=self.remove_mod_pak).pack(side="left", padx=10, pady=9)
        ttk.Label(af, text=f"Creates {MOD_PAK_NAME}").pack(side="left", padx=8)

        sf = ttk.LabelFrame(self, text="Safety")
        sf.pack(fill="x", padx=18, pady=7)
        ttk.Button(sf, text="Create DB Backup", command=self.backup_manual).pack(side="left", padx=10, pady=9)
        ttk.Button(sf, text="Restore DB Backup", command=self.restore_backup).pack(side="left", padx=10, pady=9)

        lf = ttk.LabelFrame(self, text="Log")
        lf.pack(fill="both", expand=True, padx=18, pady=(7,18))
        self.logbox = tk.Text(lf, height=11, state="disabled", font=("Consolas", 9))
        self.logbox.pack(fill="both", expand=True, padx=8, pady=8)
        self.log("v0.2: transfers are now packed back into the game as an override PAK.")

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
        roots += [Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam", Path(r"C:\Steam")]
        out, seen = [], set()
        for p in roots:
            k = str(p).lower()
            if k not in seen and p.exists():
                seen.add(k); out.append(p)
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
                seen.add(k); out.append(p)
        return out

    def looks_like_game_dir(self, p):
        return bool(p and p.exists() and self.find_paks_dir(p))

    def find_paks_dir(self, game=None):
        game = Path(game or self.game_path or "")
        candidates = [game / "mxgp3" / "Content" / "Paks", game / "MXGP3" / "Content" / "Paks", game / "Content" / "Paks"]
        return next((p for p in candidates if p.exists()), None)

    def detect_database_path(self, game=None):
        candidates = []
        last = self.config.get("last_db")
        if last: candidates.append(Path(last))
        app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        roots = [app_dir, Path.cwd()]
        if game: roots.insert(0, Path(game))
        rels = [
            Path("DB.sqlite3"), Path("NoCook/DB.sqlite3"), Path("Content/assets/data/db/NoCook/DB.sqlite3"),
            Path("mxgp3/Content/assets/data/db/NoCook/DB.sqlite3"), Path("Extracted/Content/assets/data/db/NoCook/DB.sqlite3"),
            Path("Extracted/mxgp3/Content/assets/data/db/NoCook/DB.sqlite3")]
        for root in roots:
            for rel in rels: candidates.append(root / rel)
        for p in candidates:
            if p.exists() and self.is_compatible_db(p): return p
        for root in roots:
            found = self.scan_for_database(root, 7)
            if found: return found
        return None

    def scan_for_database(self, root, max_depth=7):
        try:
            root = Path(root)
            if not root.exists(): return None
            base_depth = len(root.parts)
            skip = {".git", "Engine", "Binaries", "Saved", "Intermediate", "__pycache__"}
            for current, dirs, files in os.walk(root):
                p = Path(current)
                if len(p.parts) - base_depth >= max_depth: dirs[:] = []
                else: dirs[:] = [d for d in dirs if d not in skip]
                if "DB.sqlite3" in files:
                    candidate = p / "DB.sqlite3"
                    if self.is_compatible_db(candidate): return candidate
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
        if last and Path(last).is_file(): return Path(last)
        app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        home = Path.home()
        direct = [app_dir / "UnrealPak.exe", Path.cwd() / "UnrealPak.exe"]
        for p in direct:
            if p.exists(): return p
        roots = [home / "Downloads", home / "Desktop", home / "Documents"]
        for root in roots:
            if not root.exists(): continue
            try:
                for current, dirs, files in os.walk(root):
                    depth = len(Path(current).parts) - len(root.parts)
                    if depth >= 5: dirs[:] = []
                    if "UnrealPak.exe" in files: return Path(current) / "UnrealPak.exe"
            except Exception:
                pass
        return None

    def browse_unrealpak(self):
        p = filedialog.askopenfilename(title="Select UnrealPak.exe", filetypes=[("UnrealPak", "UnrealPak.exe"), ("Executable", "*.exe")])
        if p:
            self.unrealpak_path = p
            self.unrealpak_label.config(text=p)
            self.save_config()

    def open_db(self):
        p = filedialog.askopenfilename(title="Select MXGP3 DB.sqlite3", filetypes=[("SQLite database", "*.sqlite3"), ("All files", "*.*")])
        if p:
            try: self.load_database(p)
            except Exception as e: messagebox.showerror(APP_NAME, str(e))

    def load_database(self, path, automatic=False):
        c = sqlite3.connect(path)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = REQUIRED_TABLES - tables
        if missing:
            c.close(); raise RuntimeError("Not a compatible MXGP3 DB. Missing: " + ", ".join(sorted(missing)))
        if self.conn: self.conn.close()
        self.conn = c
        self.db_path = path
        self.db_label.config(text=path)
        self.class_box.set("MX2")
        self.load_riders()
        self.save_config()
        self.log(("Auto-loaded" if automatic else "Loaded") + f" DB: {path}")

    def load_riders(self):
        if not self.conn: return
        cat = self.class_box.get()
        rows = self.conn.execute("""SELECT P.Key,P.Number,P.Teams_Key FROM Pilots P JOIN Teams T ON P.Teams_Key=T.Key WHERE P.IsStrippedFromDB=0 AND P.Teams_Key IS NOT NULL AND T.Categories_Key=? ORDER BY P.Key""", (cat,)).fetchall()
        self.riders, values = {}, []
        for key, number, team in rows:
            label = f"#{number}  {key.split('-',1)[-1]}"
            self.riders[label] = (key, team); values.append(label)
        self.rider_box["values"] = values
        if values:
            preferred = next((v for v in values if "Herlings" in v), values[0])
            self.rider_box.set(preferred); self.rider_changed()

    def rider_changed(self):
        item = self.riders.get(self.rider_box.get())
        if not item: return
        _, old_team = item
        cat = self.class_box.get()
        rows = self.conn.execute("SELECT Key FROM Teams WHERE Categories_Key=? ORDER BY Ordering", (cat,)).fetchall()
        self.teams, names = {}, []
        for (team_key,) in rows:
            short = team_key[len(cat)+1:] if team_key.startswith(cat + "-") else team_key
            self.teams[short] = team_key; names.append(short)
        self.team_box["values"] = names
        self.current_team.config(text=old_team)
        old_short = old_team[len(cat)+1:] if old_team.startswith(cat + "-") else old_team
        if old_short in self.teams: self.team_box.set(old_short)

    def create_backup(self):
        if not self.db_path: raise RuntimeError("No DB loaded")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = self.db_path + f".MXGP3TransferTool_{stamp}.bak"
        shutil.copy2(self.db_path, out)
        return out

    def backup_manual(self):
        try:
            out = self.create_backup(); self.log(f"DB backup: {out}"); messagebox.showinfo(APP_NAME, f"Backup created:\n\n{out}")
        except Exception as e: messagebox.showerror(APP_NAME, str(e))

    def restore_backup(self):
        if not self.db_path: return messagebox.showwarning(APP_NAME, "Load DB first.")
        bak = filedialog.askopenfilename(title="Select backup", filetypes=[("Backup", "*.bak"), ("All files", "*.*")])
        if not bak: return
        if not messagebox.askyesno(APP_NAME, "Restore this DB backup?"): return
        try:
            if self.conn: self.conn.close()
            shutil.copy2(bak, self.db_path)
            self.conn = sqlite3.connect(self.db_path)
            self.load_riders(); self.log(f"Restored DB backup: {bak}")
        except Exception as e: messagebox.showerror(APP_NAME, str(e))

    def transfer_and_apply(self):
        if not self.conn: return messagebox.showwarning(APP_NAME, "Load DB.sqlite3 first.")
        rider = self.riders.get(self.rider_box.get()); new_team = self.teams.get(self.team_box.get())
        if not rider or not new_team: return
        rider_key, old_team = rider
        if old_team == new_team: return messagebox.showinfo(APP_NAME, "Rider is already in that team.")
        if not messagebox.askyesno(APP_NAME, f"Transfer and install into MXGP3?\n\n{rider_key}\n{old_team}\n→\n{new_team}"): return
        try:
            backup = self.create_backup()
            self.conn.execute("UPDATE Pilots SET Teams_Key=? WHERE Key=?", (new_team, rider_key)); self.conn.commit()
            check = self.conn.execute("SELECT Teams_Key FROM Pilots WHERE Key=?", (rider_key,)).fetchone()
            if not check or check[0] != new_team: raise RuntimeError("DB verification failed")
            self.log(f"DB changed: {rider_key}: {old_team} -> {new_team}")
            self.log(f"Backup: {backup}")
            installed = self.build_and_install_pak()
            self.load_riders()
            messagebox.showinfo(APP_NAME, f"Transfer applied.\n\nInstalled override PAK:\n{installed}\n\nClose/restart MXGP3 and test in Quick Race first.")
        except Exception as e:
            try: self.conn.rollback()
            except Exception: pass
            messagebox.showerror(APP_NAME, str(e))

    def apply_current_db(self):
        try:
            out = self.build_and_install_pak()
            messagebox.showinfo(APP_NAME, f"Current DB installed into game:\n\n{out}\n\nRestart MXGP3 before testing.")
        except Exception as e: messagebox.showerror(APP_NAME, str(e))

    def build_and_install_pak(self):
        if not self.db_path or not Path(self.db_path).exists(): raise RuntimeError("Compatible DB.sqlite3 is not loaded.")
        if not self.game_path: raise RuntimeError("MXGP3 installation was not detected.")
        paks_dir = self.find_paks_dir()
        if not paks_dir: raise RuntimeError("MXGP3 Content\\Paks folder not found.")
        if not self.unrealpak_path or not Path(self.unrealpak_path).exists():
            raise RuntimeError("UnrealPak.exe not found. Click Browse UnrealPak once and select the UnrealPak.exe from your UnrealPakGUI/tools folder.")

        final_pak = paks_dir / MOD_PAK_NAME
        if final_pak.exists():
            backup = final_pak.with_suffix(final_pak.suffix + ".previous")
            shutil.copy2(final_pak, backup)
            self.log(f"Previous transfer PAK backed up: {backup}")

        with tempfile.TemporaryDirectory(prefix="MXGP3TransferTool_") as td:
            td = Path(td)
            staged = td / "DB.sqlite3"
            shutil.copy2(self.db_path, staged)
            response = td / "paklist.txt"
            response.write_text(f'"{staged}" "{INTERNAL_DB_PATH}"\n', encoding="utf-8")
            output = td / MOD_PAK_NAME
            cmd = [self.unrealpak_path, str(output), f"-Create={response}"]
            self.log("Building override PAK...")
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="ignore", creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
            if proc.returncode != 0 or not output.exists() or output.stat().st_size < 1024:
                raise RuntimeError("UnrealPak failed.\n\n" + proc.stdout[-4000:])

            verify = subprocess.run([self.unrealpak_path, str(output), "-List"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="ignore", creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
            listing = verify.stdout.lower().replace("\\", "/")
            if "db.sqlite3" not in listing or "content/assets/data/db/nocook" not in listing:
                raise RuntimeError("PAK was created, but its internal DB path is wrong. Nothing was installed.")

            shutil.copy2(output, final_pak)

        # Some UE4 games ship a .sig next to the original PAK. If MXGP3 has one, mirror it for the override filename.
        sig_candidates = [paks_dir / "pakchunk0-WindowsNoEditor.sig", paks_dir / "MXGP3-WindowsNoEditor.sig"]
        original_sig = next((p for p in sig_candidates if p.exists()), None)
        if original_sig:
            mod_sig = final_pak.with_suffix(".sig")
            try:
                shutil.copy2(original_sig, mod_sig)
                self.log(f"SIG copied: {mod_sig}")
            except Exception as e:
                self.log(f"SIG copy warning: {e}")

        self.log(f"Installed: {final_pak}")
        self.log(f"Internal override: {INTERNAL_DB_PATH}")
        return final_pak

    def remove_mod_pak(self):
        paks_dir = self.find_paks_dir()
        if not paks_dir: return messagebox.showwarning(APP_NAME, "Game Paks folder not detected.")
        target = paks_dir / MOD_PAK_NAME
        sig = target.with_suffix(".sig")
        removed = []
        for p in (target, sig):
            if p.exists():
                try: p.unlink(); removed.append(str(p))
                except Exception as e: return messagebox.showerror(APP_NAME, str(e))
        if removed:
            self.log("Removed transfer override PAK.")
            messagebox.showinfo(APP_NAME, "Transfer PAK removed. Restart MXGP3.")
        else:
            messagebox.showinfo(APP_NAME, "No Transfer Tool PAK is installed.")


if __name__ == "__main__":
    App().mainloop()
