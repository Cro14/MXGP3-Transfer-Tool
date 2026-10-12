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
from tkinter import ttk, messagebox

APP_NAME = "MXGP3 Transfer Tool"
VERSION = "0.6"
STEAM_APP_ID = "561600"
REQUIRED_TABLES = {"Pilots", "Teams", "PilotsInRosters", "Vehicles", "CustomizationFilters", "CustomizationItems"}
DB_SUFFIX = "content/assets/data/db/nocook/db.sqlite3"
STOCK_SUFFIX = ".MXGP3TransferTool.stock"
OLD_PATCH_NAMES = [
    "pakchunk0-WindowsNoEditor_MXGP3TransferTool_P.pak",
    "pakchunk99-MXGP3TransferTool_P.pak",
    "pakchunk0-WindowsNoEditor_999_P.pak",
]


def hidden_flags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def resource_path(name):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def fmt_gb(n):
    return f"{n / (1024 ** 3):.1f} GB"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry("980x760")
        self.minsize(900, 680)

        self.repak = resource_path("repak.exe")
        self.game = None
        self.paks_dir = None
        self.active_pak = None
        self.stock_pak = None
        self.pak_mount = None
        self.pak_version = None
        self.db_entry = None
        self.stock_file_count = None
        self.conn = None
        self.db_path = None
        self.riders = {}
        self.teams = {}
        self.config = self.load_config()

        self.build_ui()
        self.after(250, self.auto_setup)

    # ---------- UI ----------

    def build_ui(self):
        ttk.Label(self, text="MXGP3 TRANSFER TOOL", font=("Segoe UI", 20, "bold")).pack(pady=(14, 2))
        ttk.Label(self, text="v0.6 LOOSE FILES MODE — direct game DB editing").pack(pady=(0, 10))

        sf = ttk.LabelFrame(self, text="Game / Loose Files Mode")
        sf.pack(fill="x", padx=18, pady=7)
        sf.columnconfigure(1, weight=1)

        ttk.Label(sf, text="Game:").grid(row=0, column=0, sticky="w", padx=10, pady=4)
        self.game_label = ttk.Label(sf, text="Searching...")
        self.game_label.grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(sf, text="Stock PAK:").grid(row=1, column=0, sticky="w", padx=10, pady=4)
        self.pak_label = ttk.Label(sf, text="Searching...")
        self.pak_label.grid(row=1, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(sf, text="Mode:").grid(row=2, column=0, sticky="w", padx=10, pady=4)
        self.mode_label = ttk.Label(sf, text="Checking...")
        self.mode_label.grid(row=2, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(sf, text="Database:").grid(row=3, column=0, sticky="w", padx=10, pady=4)
        self.db_label = ttk.Label(sf, text="Preparing...")
        self.db_label.grid(row=3, column=1, sticky="ew", padx=6, pady=4)

        ttk.Button(sf, text="AUTO SETUP", command=lambda: self.auto_setup(True)).grid(row=0, column=2, padx=8, pady=5)
        ttk.Button(sf, text="ENABLE LOOSE FILES MODE", command=self.enable_loose_mode).grid(row=1, column=2, padx=8, pady=5)
        ttk.Button(sf, text="RESTORE STOCK MODE", command=self.restore_stock_mode).grid(row=2, column=2, rowspan=2, padx=8, pady=5)

        tf = ttk.LabelFrame(self, text="Rider transfer")
        tf.pack(fill="x", padx=18, pady=7)
        tf.columnconfigure(1, weight=1)

        ttk.Label(tf, text="Class:").grid(row=0, column=0, sticky="w", padx=10, pady=7)
        self.class_box = ttk.Combobox(tf, state="readonly", values=["MX2", "MXGP"])
        self.class_box.grid(row=0, column=1, sticky="ew", padx=10, pady=7)
        self.class_box.bind("<<ComboboxSelected>>", lambda _e: self.load_riders())

        ttk.Label(tf, text="Rider:").grid(row=1, column=0, sticky="w", padx=10, pady=7)
        self.rider_box = ttk.Combobox(tf, state="readonly")
        self.rider_box.grid(row=1, column=1, sticky="ew", padx=10, pady=7)
        self.rider_box.bind("<<ComboboxSelected>>", lambda _e: self.rider_changed())

        ttk.Label(tf, text="Current team:").grid(row=2, column=0, sticky="w", padx=10, pady=7)
        self.current_team = ttk.Label(tf, text="-")
        self.current_team.grid(row=2, column=1, sticky="w", padx=10, pady=7)

        ttk.Label(tf, text="New team:").grid(row=3, column=0, sticky="w", padx=10, pady=7)
        self.team_box = ttk.Combobox(tf, state="readonly")
        self.team_box.grid(row=3, column=1, sticky="ew", padx=10, pady=7)

        ttk.Button(tf, text="TRANSFER DIRECTLY IN GAME", command=self.transfer).grid(
            row=4, column=0, columnspan=2, pady=14, ipadx=44, ipady=7
        )

        lf = ttk.LabelFrame(self, text="Log / diagnostics")
        lf.pack(fill="both", expand=True, padx=18, pady=(7, 18))
        self.logbox = tk.Text(lf, height=16, state="disabled", font=("Consolas", 9))
        self.logbox.pack(fill="both", expand=True, padx=8, pady=8)
        self.log("v0.6 does NOT use an override PAK for transfers.")
        self.log("Loose Files Mode unpacks the stock PAK once, disables it safely, then edits the real loose DB directly.")

    def log(self, text):
        self.logbox.config(state="normal")
        self.logbox.insert("end", str(text) + "\n")
        self.logbox.see("end")
        self.logbox.config(state="disabled")
        self.update_idletasks()

    # ---------- App data ----------

    def app_dir(self):
        p = Path(os.getenv("APPDATA") or Path.home()) / "MXGP3TransferTool"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def config_path(self):
        return self.app_dir() / "config.json"

    def preview_db(self):
        p = self.app_dir() / "preview"
        p.mkdir(parents=True, exist_ok=True)
        return p / "DB.sqlite3"

    def backup_dir(self):
        p = self.app_dir() / "backups"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def manifest_path(self):
        return self.app_dir() / "loose_mode_manifest.json"

    def load_config(self):
        try:
            p = self.config_path()
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def save_config(self):
        if self.game:
            self.config["last_game"] = str(self.game)
        try:
            self.config_path().write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ---------- Process helpers ----------

    def run(self, args, timeout=300, binary=False):
        return subprocess.run(
            [str(x) for x in args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if binary else subprocess.STDOUT,
            text=not binary,
            errors=None if binary else "replace",
            timeout=timeout,
            creationflags=hidden_flags(),
        )

    def game_running(self):
        if os.name != "nt":
            return False
        try:
            p = self.run(["tasklist"], timeout=15)
            low = p.stdout.lower() if p.stdout else ""
            return "mxgp3.exe" in low or "mxgp3-win64-shipping.exe" in low
        except Exception:
            return False

    # ---------- Detection ----------

    def auto_setup(self, show=False):
        try:
            self.log("--- AUTO SETUP ---")
            if not self.repak.exists():
                raise RuntimeError("Bundled repak.exe is missing from this build.")

            self.game = self.detect_game()
            if not self.game:
                raise RuntimeError("MXGP3 Steam installation not detected.")
            self.game_label.config(text=str(self.game))
            self.paks_dir = self.find_paks(self.game)
            if not self.paks_dir:
                raise RuntimeError("MXGP3 Content\\Paks folder not found.")

            self.active_pak, self.stock_pak = self.find_stock_paks()
            inspect_target = self.active_pak or self.stock_pak
            if not inspect_target:
                raise RuntimeError("Stock pakchunk0 was not found, active or backed up.")
            self.pak_label.config(text=str(inspect_target))
            self.inspect_pak(inspect_target)

            loose_db = self.loose_db_path()
            if self.loose_mode_active():
                self.mode_label.config(text="LOOSE FILES MODE ACTIVE")
                self.load_db(loose_db)
                self.log("Loose Files Mode detected: stock PAK disabled and loose DB active.")
            else:
                self.mode_label.config(text="STOCK PAK MODE — enable Loose Files Mode first")
                preview = self.preview_db()
                self.extract_single_db(inspect_target, preview)
                self.load_db(preview)
                self.log("Loaded stock DB preview. Transfers are blocked until Loose Files Mode is enabled.")

            self.cleanup_old_patch_paks()
            self.save_config()
            if show:
                messagebox.showinfo(APP_NAME, "Setup complete. Check the Mode line.")
        except Exception as e:
            self.log(f"SETUP ERROR: {e}")
            if show:
                messagebox.showerror(APP_NAME, str(e))

    def detect_game(self):
        last = self.config.get("last_game")
        if last and self.find_paks(Path(last)):
            return Path(last)

        roots = []
        if os.name == "nt":
            try:
                import winreg
                checks = [
                    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
                ]
                for hive, key, val in checks:
                    try:
                        with winreg.OpenKey(hive, key) as k:
                            raw = winreg.QueryValueEx(k, val)[0]
                            roots.append(Path(raw))
                    except OSError:
                        pass
            except Exception:
                pass
        roots += [
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam",
            Path(r"C:\Steam"),
        ]

        seen = set()
        for root in roots:
            key = str(root).lower()
            if key in seen or not root.exists():
                continue
            seen.add(key)
            libs = [root]
            vdf = root / "steamapps" / "libraryfolders.vdf"
            if vdf.exists():
                txt = vdf.read_text(encoding="utf-8", errors="ignore")
                for raw in re.findall(r'"path"\s+"([^"]+)"', txt, re.I):
                    libs.append(Path(raw.replace("\\\\", "\\")))
            for lib in libs:
                mf = lib / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
                if not mf.exists():
                    continue
                txt = mf.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r'"installdir"\s+"([^"]+)"', txt, re.I)
                if m:
                    g = lib / "steamapps" / "common" / m.group(1)
                    if self.find_paks(g):
                        return g
        return None

    def find_paks(self, game):
        if not game:
            return None
        game = Path(game)
        for p in [
            game / "mxgp3" / "Content" / "Paks",
            game / "MXGP3" / "Content" / "Paks",
            game / "Content" / "Paks",
        ]:
            if p.exists():
                return p
        return None

    def find_stock_paks(self):
        active_candidates = [
            self.paks_dir / "pakchunk0-WindowsNoEditor.pak",
            self.paks_dir / "MXGP3-WindowsNoEditor.pak",
        ]
        active = next((p for p in active_candidates if p.exists()), None)
        stock = None
        if active:
            candidate = Path(str(active) + STOCK_SUFFIX)
            if candidate.exists():
                stock = candidate
        if not stock:
            backups = list(self.paks_dir.glob("*.pak" + STOCK_SUFFIX))
            stock = backups[0] if backups else None
        return active, stock

    def inspect_pak(self, pak):
        p = self.run([self.repak, "info", pak], timeout=60)
        if p.returncode:
            raise RuntimeError("Could not inspect stock PAK.\n" + (p.stdout or "")[-2000:])
        mount = re.search(r"^mount point:\s*(.+)$", p.stdout, re.M | re.I)
        ver = re.search(r"^version:\s*(V[0-9]+[AB]?)$", p.stdout, re.M | re.I)
        count = re.search(r"^(\d+) file entries$", p.stdout, re.M | re.I)
        if not mount or not ver:
            raise RuntimeError("Could not read stock PAK mount/version.")
        self.pak_mount = mount.group(1).strip()
        self.pak_version = ver.group(1).strip().upper()
        self.stock_file_count = int(count.group(1)) if count else None

        p = self.run([self.repak, "list", "-s", self.pak_mount, pak], timeout=180)
        if p.returncode:
            raise RuntimeError("Could not list stock PAK.\n" + (p.stdout or "")[-2000:])
        entries = [x.strip().replace("\\", "/") for x in p.stdout.splitlines() if x.strip()]
        found = [x for x in entries if x.lower().endswith(DB_SUFFIX)]
        if not found:
            raise RuntimeError("DB.sqlite3 was not found inside the stock PAK.")
        self.db_entry = next((x for x in found if x.lower().startswith("mxgp3/")), found[0])
        self.log(f"PAK: version={self.pak_version}, mount={self.pak_mount}, files={self.stock_file_count or '?'}")
        self.log(f"DB entry: {self.db_entry}")

    def loose_db_path(self):
        if not self.game or not self.db_entry:
            return None
        return self.game.joinpath(*Path(self.db_entry).parts)

    def loose_mode_active(self):
        db = self.loose_db_path()
        return bool(
            db and db.exists() and self.compatible(db)
            and self.stock_pak and self.stock_pak.exists()
            and (not self.active_pak or not self.active_pak.exists())
        )

    # ---------- Stock DB preview ----------

    def extract_single_db(self, pak, dest):
        p = self.run([self.repak, "get", "-s", self.pak_mount, pak, self.db_entry], timeout=120, binary=True)
        if p.returncode:
            err = p.stderr.decode("utf-8", errors="replace") if p.stderr else ""
            raise RuntimeError("Could not extract DB.sqlite3.\n" + err[-2000:])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(p.stdout)
        if not self.compatible(dest):
            raise RuntimeError("Extracted DB is not compatible with MXGP3.")

    # ---------- Loose Files Mode ----------

    def enable_loose_mode(self):
        if self.game_running():
            return messagebox.showwarning(APP_NAME, "Close MXGP3 before enabling Loose Files Mode.")
        try:
            if not self.game or not self.paks_dir:
                self.auto_setup(False)
            self.active_pak, self.stock_pak = self.find_stock_paks()
            if self.loose_mode_active():
                return messagebox.showinfo(APP_NAME, "Loose Files Mode is already active.")
            if not self.active_pak:
                raise RuntimeError("Active stock PAK not found. Use RESTORE STOCK MODE first if it was moved manually.")

            self.inspect_pak(self.active_pak)
            pak_size = self.active_pak.stat().st_size
            free = shutil.disk_usage(self.game).free
            suggested = max(int(pak_size * 2.5), 12 * 1024 ** 3)
            warning = (
                "This is the one-time setup for the direct method.\n\n"
                "The tool will unpack the ENTIRE stock MXGP3 PAK into the game folder, verify the extraction, "
                "then rename the original PAK so the game reads the loose files.\n\n"
                f"Stock PAK: {fmt_gb(pak_size)}\nFree space: {fmt_gb(free)}\n"
                f"Recommended free space: about {fmt_gb(suggested)}\n\n"
                "A restore manifest and backups of any pre-existing loose files will be created. Continue?"
            )
            if not messagebox.askyesno(APP_NAME, warning):
                return
            if free < suggested:
                if not messagebox.askyesno(APP_NAME, "Free space is below the recommendation. Continue anyway?"):
                    return

            self.cleanup_old_patch_paks()
            self.log("Building stock file manifest...")
            p = self.run([self.repak, "list", "-s", self.pak_mount, self.active_pak], timeout=180)
            if p.returncode:
                raise RuntimeError("Could not list stock PAK before extraction.")
            entries = [x.strip().replace("\\", "/") for x in p.stdout.splitlines() if x.strip()]
            if self.stock_file_count and len(entries) != self.stock_file_count:
                raise RuntimeError(f"Stock list count mismatch: expected {self.stock_file_count}, got {len(entries)}")

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            restore_root = self.app_dir() / "loose_restore" / stamp
            pre_root = restore_root / "preexisting"
            preexisting = []
            pre_bytes = 0
            for rel in entries:
                target = self.game.joinpath(*Path(rel).parts)
                if target.is_file():
                    preexisting.append(rel)
                    try:
                        pre_bytes += target.stat().st_size
                    except Exception:
                        pass

            if preexisting:
                msg = f"Found {len(preexisting)} pre-existing loose files ({fmt_gb(pre_bytes)}). They will be backed up before extraction."
                self.log(msg)
                if pre_bytes > 2 * 1024 ** 3:
                    if not messagebox.askyesno(APP_NAME, msg + "\n\nThis backup is large. Continue?"):
                        return
                for i, rel in enumerate(preexisting, 1):
                    src = self.game.joinpath(*Path(rel).parts)
                    dst = pre_root.joinpath(*Path(rel).parts)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    if i % 500 == 0:
                        self.log(f"Backed up {i}/{len(preexisting)} pre-existing loose files...")

            manifest = {
                "version": 1,
                "created": stamp,
                "game": str(self.game),
                "active_pak": str(self.active_pak),
                "stock_backup_pak": str(Path(str(self.active_pak) + STOCK_SUFFIX)),
                "entries": entries,
                "preexisting": preexisting,
                "preexisting_backup_root": str(pre_root),
            }
            restore_root.mkdir(parents=True, exist_ok=True)
            self.manifest_path().write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            self.log(f"Unpacking {len(entries)} stock files directly into MXGP3...")
            self.log("This can take several minutes. Do not close the tool.")
            p = self.run([
                self.repak, "unpack", self.active_pak,
                "-s", self.pak_mount,
                "-o", self.game,
            ], timeout=3600)
            if p.returncode:
                raise RuntimeError("Full PAK extraction failed. The stock PAK was NOT disabled.\n\n" + (p.stdout or "")[-3000:])

            m = re.search(r"Unpacked\s+(\d+)\s+files", p.stdout or "", re.I)
            unpacked = int(m.group(1)) if m else None
            if self.stock_file_count and unpacked is not None and unpacked != self.stock_file_count:
                raise RuntimeError(f"Extraction count mismatch: expected {self.stock_file_count}, got {unpacked}. Stock PAK left enabled.")

            loose_db = self.loose_db_path()
            if not loose_db or not loose_db.exists() or not self.compatible(loose_db):
                raise RuntimeError("Extraction finished but the loose DB.sqlite3 is missing/invalid. Stock PAK left enabled.")

            backup_pak = Path(str(self.active_pak) + STOCK_SUFFIX)
            if backup_pak.exists():
                raise RuntimeError(f"Stock backup already exists: {backup_pak}")
            os.replace(self.active_pak, backup_pak)

            sig = self.active_pak.with_suffix(".sig")
            if sig.exists():
                sig_backup = Path(str(sig) + STOCK_SUFFIX)
                if not sig_backup.exists():
                    os.replace(sig, sig_backup)

            self.stock_pak = backup_pak
            self.active_pak = None
            self.load_db(loose_db)
            self.mode_label.config(text="LOOSE FILES MODE ACTIVE")
            self.pak_label.config(text=str(self.stock_pak))
            self.log("LOOSE FILES MODE ENABLED SUCCESSFULLY.")
            self.log(f"Direct DB: {loose_db}")
            messagebox.showinfo(APP_NAME, "Loose Files Mode enabled.\n\nNow transfers edit the database the game reads directly. No transfer PAK is used.")
        except Exception as e:
            self.log(f"LOOSE MODE ERROR: {e}")
            messagebox.showerror(APP_NAME, str(e))

    def restore_stock_mode(self):
        if self.game_running():
            return messagebox.showwarning(APP_NAME, "Close MXGP3 before restoring stock mode.")
        try:
            if not self.game:
                self.auto_setup(False)
            mp = self.manifest_path()
            if not mp.exists():
                self.active_pak, self.stock_pak = self.find_stock_paks()
                if self.stock_pak and not self.active_pak:
                    if not messagebox.askyesno(APP_NAME, "No restore manifest was found, but a stock backup PAK exists. Restore only the PAK filename? Loose files will be left in place."):
                        return
                    original = Path(str(self.stock_pak)[:-len(STOCK_SUFFIX)])
                    os.replace(self.stock_pak, original)
                    self.log("Stock PAK filename restored. Loose files were not deleted because no manifest was available.")
                    self.auto_setup(False)
                    return messagebox.showinfo(APP_NAME, "Stock PAK restored. Loose files were left in place.")
                return messagebox.showinfo(APP_NAME, "No Loose Files Mode restore manifest exists.")

            manifest = json.loads(mp.read_text(encoding="utf-8"))
            if Path(manifest.get("game", "")).resolve() != self.game.resolve():
                raise RuntimeError("Restore manifest belongs to a different MXGP3 folder.")
            if not messagebox.askyesno(APP_NAME, "Restore stock mode?\n\nThe tool will remove files it extracted, restore any pre-existing loose files it backed up, and put the original PAK back."):
                return

            if self.conn:
                self.conn.close()
                self.conn = None

            entries = manifest.get("entries", [])
            preexisting = set(manifest.get("preexisting", []))
            pre_root = Path(manifest.get("preexisting_backup_root", ""))
            self.log(f"Restoring {len(entries)} loose-file paths...")
            for i, rel in enumerate(entries, 1):
                target = self.game.joinpath(*Path(rel).parts)
                if rel in preexisting:
                    backup = pre_root.joinpath(*Path(rel).parts)
                    if backup.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup, target)
                else:
                    if target.is_file():
                        try:
                            target.unlink()
                        except Exception:
                            pass
                if i % 2000 == 0:
                    self.log(f"Restored {i}/{len(entries)} paths...")

            backup_pak = Path(manifest["stock_backup_pak"])
            original_pak = Path(manifest["active_pak"])
            if not backup_pak.exists():
                raise RuntimeError("Stock backup PAK is missing; cannot complete restore safely.")
            if original_pak.exists():
                raise RuntimeError("Original PAK path is already occupied; refusing to overwrite it.")
            os.replace(backup_pak, original_pak)

            sig_backup = Path(str(original_pak.with_suffix(".sig")) + STOCK_SUFFIX)
            if sig_backup.exists() and not original_pak.with_suffix(".sig").exists():
                os.replace(sig_backup, original_pak.with_suffix(".sig"))

            try:
                mp.unlink()
            except Exception:
                pass
            self.log("STOCK MODE RESTORED.")
            self.auto_setup(False)
            messagebox.showinfo(APP_NAME, "Stock mode restored successfully.")
        except Exception as e:
            self.log(f"RESTORE ERROR: {e}")
            messagebox.showerror(APP_NAME, str(e))

    def cleanup_old_patch_paks(self):
        if not self.paks_dir:
            return
        for name in OLD_PATCH_NAMES:
            p = self.paks_dir / name
            for q in [p, p.with_suffix(".sig"), Path(str(p) + ".previous")]:
                if q.exists():
                    try:
                        q.unlink()
                        self.log(f"Removed obsolete transfer patch: {q.name}")
                    except Exception as e:
                        self.log(f"Could not remove old patch {q.name}: {e}")

    # ---------- Database ----------

    def compatible(self, db):
        try:
            c = sqlite3.connect(str(db))
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            c.close()
            return REQUIRED_TABLES.issubset(tables)
        except Exception:
            return False

    def load_db(self, db):
        db = Path(db)
        if not self.compatible(db):
            raise RuntimeError("Database is not a compatible MXGP3 DB.sqlite3.")
        if self.conn:
            self.conn.close()
        self.conn = sqlite3.connect(str(db))
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.db_path = str(db)
        self.db_label.config(text=self.db_path)
        self.class_box.set("MX2")
        self.load_riders()
        self.log(f"DB loaded: {db}")

    def load_riders(self):
        if not self.conn:
            return
        cat = self.class_box.get() or "MX2"
        rows = self.conn.execute(
            """SELECT P.Key,P.Number,P.Teams_Key
               FROM Pilots P JOIN Teams T ON P.Teams_Key=T.Key
               WHERE P.IsStrippedFromDB=0 AND P.Teams_Key IS NOT NULL AND T.Categories_Key=?
               ORDER BY P.Key""", (cat,)
        ).fetchall()
        self.riders = {}
        vals = []
        for key, num, team in rows:
            label = f"#{num}  {key.split('-', 1)[-1]}"
            self.riders[label] = (key, team)
            vals.append(label)
        self.rider_box["values"] = vals
        if vals:
            self.rider_box.set(next((x for x in vals if "Herlings" in x), vals[0]))
            self.rider_changed()

    def rider_changed(self):
        info = self.riders.get(self.rider_box.get())
        if not info or not self.conn:
            return
        _, old_team = info
        cat = self.class_box.get()
        rows = self.conn.execute("SELECT Key FROM Teams WHERE Categories_Key=? ORDER BY Ordering", (cat,)).fetchall()
        self.teams = {}
        vals = []
        for (team,) in rows:
            short = team[len(cat)+1:] if team.startswith(cat + "-") else team
            self.teams[short] = team
            vals.append(short)
        self.team_box["values"] = vals
        self.current_team.config(text=old_team)
        old_short = old_team[len(cat)+1:] if old_team.startswith(cat + "-") else old_team
        if old_short in self.teams:
            self.team_box.set(old_short)

    def db_backup(self):
        if not self.db_path:
            raise RuntimeError("No database loaded.")
        self.conn.commit()
        out = self.backup_dir() / f"DB_v06_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.sqlite3"
        shutil.copy2(self.db_path, out)
        return out

    def destination_vehicle(self, team):
        return self.conn.execute(
            """SELECT Categories_Key,CategoryEngines_Strokes,Manufacturers_Key,
                      VehiclePhysics_Key,VehicleStatistics_Key,VehicleSettingGroups_Key
               FROM Vehicles WHERE Key=?""", (team,)
        ).fetchone()

    def copy_team_filters_to_rider(self, rider, team):
        rows = self.conn.execute(
            """SELECT MultiFilterSecondaryKey,CustomizationItemType,Manufacturer,Model,Variant
               FROM CustomizationFilters WHERE Key=? ORDER BY MultiFilterSecondaryKey""", (team,)
        ).fetchall()
        if not rows:
            self.log("Destination team has no CustomizationFilters rows; rider visual filters left unchanged.")
            return 0
        self.conn.execute("DELETE FROM CustomizationFilters WHERE Key=?", (rider,))
        for sec, typ, man, model, variant in rows:
            self.conn.execute(
                """INSERT INTO CustomizationFilters
                   (Key,MultiFilterSecondaryKey,CustomizationItemType,Manufacturer,Model,Variant)
                   VALUES(?,?,?,?,?,?)""",
                (rider, sec, typ, man, model, variant),
            )
        return len(rows)

    def apply_transfer(self, rider, old_team, new_team):
        dest = self.destination_vehicle(new_team)
        if not dest:
            raise RuntimeError("Destination team has no official Vehicles row.")
        category, strokes, manufacturer, physics, stats, setting_group = dest
        current = self.conn.execute(
            "SELECT Categories_Key,CategoryEngines_Strokes,Manufacturers_Key FROM Vehicles WHERE Key=?", (rider,)
        ).fetchone()
        if not current:
            raise RuntimeError("Rider Vehicles row not found.")
        if current[0] != category:
            raise RuntimeError("v0.6 currently supports transfers inside the same class only.")

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute("UPDATE Pilots SET Teams_Key=? WHERE Key=?", (new_team, rider))
            # Change the visible bike brand directly. Keep the rider's category/settings stable unless the
            # destination row supplies explicit physics/stat references.
            self.conn.execute("UPDATE Vehicles SET Manufacturers_Key=?, CategoryEngines_Strokes=? WHERE Key=?", (manufacturer, strokes, rider))
            if physics is not None:
                self.conn.execute("UPDATE Vehicles SET VehiclePhysics_Key=? WHERE Key=?", (physics, rider))
            if stats is not None:
                self.conn.execute("UPDATE Vehicles SET VehicleStatistics_Key=? WHERE Key=?", (stats, rider))

            filter_count = self.copy_team_filters_to_rider(rider, new_team)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        got_team = self.conn.execute("SELECT Teams_Key FROM Pilots WHERE Key=?", (rider,)).fetchone()
        got_man = self.conn.execute("SELECT Manufacturers_Key FROM Vehicles WHERE Key=?", (rider,)).fetchone()
        if not got_team or got_team[0] != new_team:
            raise RuntimeError("Direct DB team verification failed.")
        if not got_man or got_man[0] != manufacturer:
            raise RuntimeError("Direct DB bike manufacturer verification failed.")

        self.log(f"DIRECT TEAM: {rider}: {old_team} -> {new_team}")
        self.log(f"DIRECT BIKE: {rider} -> {manufacturer}")
        self.log(f"TEAM VISUAL FILTERS COPIED: {filter_count}")

    def transfer(self):
        if self.game_running():
            return messagebox.showwarning(APP_NAME, "Close MXGP3 before transferring a rider.")
        if not self.loose_mode_active():
            return messagebox.showwarning(APP_NAME, "Enable LOOSE FILES MODE first. v0.6 will not create another override PAK.")
        if not self.conn or Path(self.db_path).resolve() != self.loose_db_path().resolve():
            self.load_db(self.loose_db_path())

        rider_info = self.riders.get(self.rider_box.get())
        new_team = self.teams.get(self.team_box.get())
        if not rider_info or not new_team:
            return
        rider, old_team = rider_info
        if old_team == new_team:
            return messagebox.showinfo(APP_NAME, "Rider is already in that team.")
        dest = self.destination_vehicle(new_team)
        brand = dest[2] if dest else "?"
        if not messagebox.askyesno(
            APP_NAME,
            f"DIRECT transfer in the loose game database?\n\n{rider}\n{old_team}\n→\n{new_team}\nBike brand → {brand}\n\nNo PAK patch will be created."
        ):
            return

        backup = self.db_backup()
        try:
            self.apply_transfer(rider, old_team, new_team)
            # Force SQLite data to disk, then independently reopen the actual loose file.
            self.conn.commit()
            self.conn.close()
            self.conn = None
            verify = sqlite3.connect(str(self.loose_db_path()))
            got = verify.execute("SELECT P.Teams_Key,V.Manufacturers_Key FROM Pilots P JOIN Vehicles V ON V.Key=P.Key WHERE P.Key=?", (rider,)).fetchone()
            verify.close()
            if not got or got[0] != new_team or got[1] != brand:
                raise RuntimeError("Independent verification of the loose game DB failed.")
            self.log(f"VERIFIED ON DISK: {rider} -> {new_team} / {brand}")
            self.load_db(self.loose_db_path())
            messagebox.showinfo(APP_NAME, f"Transfer written directly into MXGP3.\n\nVerified on disk:\n{rider} -> {new_team}\nBike -> {brand}\n\nStart the game and check Quick Race.")
        except Exception as e:
            try:
                if self.conn:
                    self.conn.close()
                shutil.copy2(backup, self.loose_db_path())
                self.load_db(self.loose_db_path())
                self.log(f"Transfer failed; loose DB restored from {backup}")
            except Exception as re_err:
                self.log(f"ROLLBACK WARNING: {re_err}")
            messagebox.showerror(APP_NAME, str(e))


if __name__ == "__main__":
    App().mainloop()
