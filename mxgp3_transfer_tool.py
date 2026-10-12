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
VERSION = "0.4"
STEAM_APP_ID = "561600"
REQUIRED_TABLES = {"Pilots", "Teams", "PilotsInRosters"}
MOD_PAK_NAME = "pakchunk99-MXGP3TransferTool_P.pak"
LEGACY_TOOL_PAKS = [
    "pakchunk0-WindowsNoEditor_MXGP3TransferTool_P.pak",
    "pakchunk99-MXGP3TransferTool_P.pak",
]
DB_SUFFIX = "content/assets/data/db/nocook/db.sqlite3"


def hidden_flags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def resource_path(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry("930x700")
        self.minsize(840, 620)

        self.conn = None
        self.db_path = None
        self.game_path = None
        self.paks_dir = None
        self.main_pak = None
        self.repak_path = None
        self.pak_mount = None
        self.pak_version = None
        self.db_entry = None
        self.riders = {}
        self.teams = {}
        self.config = self.load_config()

        self._build_ui()
        self.after(250, self.auto_setup)

    # ---------------- UI ----------------

    def _build_ui(self):
        ttk.Label(self, text="MXGP3 TRANSFER TOOL", font=("Segoe UI", 20, "bold")).pack(pady=(16, 2))
        ttk.Label(self, text="v0.4 SELF-CONTAINED PAK BUILD — Cro14").pack(pady=(0, 12))

        detect = ttk.LabelFrame(self, text="Automatic game setup")
        detect.pack(fill="x", padx=18, pady=7)
        detect.columnconfigure(1, weight=1)

        ttk.Label(detect, text="Game:").grid(row=0, column=0, sticky="w", padx=10, pady=4)
        self.game_label = ttk.Label(detect, text="Searching...")
        self.game_label.grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(detect, text="Original PAK:").grid(row=1, column=0, sticky="w", padx=10, pady=4)
        self.pak_label = ttk.Label(detect, text="Searching...")
        self.pak_label.grid(row=1, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(detect, text="Packer:").grid(row=2, column=0, sticky="w", padx=10, pady=4)
        self.packer_label = ttk.Label(detect, text="Bundled repak")
        self.packer_label.grid(row=2, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(detect, text="Working DB:").grid(row=3, column=0, sticky="w", padx=10, pady=4)
        self.db_label = ttk.Label(detect, text="Preparing...")
        self.db_label.grid(row=3, column=1, sticky="ew", padx=6, pady=4)

        ttk.Button(detect, text="AUTO SETUP", command=lambda: self.auto_setup(show_result=True)).grid(
            row=0, column=2, rowspan=2, padx=6, pady=8, ipadx=8, ipady=3
        )
        ttk.Button(detect, text="RESET FROM STOCK", command=self.reset_from_stock).grid(
            row=2, column=2, rowspan=2, padx=6, pady=8, ipadx=8, ipady=3
        )

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

        ttk.Button(tf, text="TRANSFER RIDER — AUTO INSTALL", command=self.transfer_and_apply).grid(
            row=4, column=0, columnspan=2, pady=14, ipadx=38, ipady=6
        )

        af = ttk.LabelFrame(self, text="Installed patch")
        af.pack(fill="x", padx=18, pady=7)
        ttk.Button(af, text="Rebuild / Reinstall Current DB", command=self.apply_current_db).pack(side="left", padx=10, pady=9)
        ttk.Button(af, text="Remove Transfer Tool PAK", command=self.remove_mod_pak).pack(side="left", padx=10, pady=9)
        ttk.Button(af, text="Import External DB", command=self.import_external_db).pack(side="left", padx=10, pady=9)

        lf = ttk.LabelFrame(self, text="Log")
        lf.pack(fill="both", expand=True, padx=18, pady=(7, 18))
        self.logbox = tk.Text(lf, height=13, state="disabled", font=("Consolas", 9))
        self.logbox.pack(fill="both", expand=True, padx=8, pady=8)
        self.log("v0.4 uses bundled repak instead of UnrealPak.exe.")
        self.log("It can extract the stock DB directly from MXGP3 and rebuild the override automatically.")

    def log(self, text):
        self.logbox.config(state="normal")
        self.logbox.insert("end", str(text) + "\n")
        self.logbox.see("end")
        self.logbox.config(state="disabled")
        self.update_idletasks()

    # ---------------- Config ----------------

    def app_data_dir(self):
        base = Path(os.getenv("APPDATA") or Path.home()) / "MXGP3TransferTool"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def config_path(self):
        return self.app_data_dir() / "config.json"

    def working_db_path(self):
        p = self.app_data_dir() / "working"
        p.mkdir(parents=True, exist_ok=True)
        return p / "DB.sqlite3"

    def backup_dir(self):
        p = self.app_data_dir() / "backups"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def load_config(self):
        try:
            if self.config_path().exists():
                return json.loads(self.config_path().read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def save_config(self):
        self.config["last_game"] = self.game_path
        try:
            self.config_path().write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        except Exception as e:
            self.log(f"Config warning: {e}")

    # ---------------- Process helpers ----------------

    def run_text(self, args, timeout=120):
        proc = subprocess.run(
            [str(a) for a in args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=hidden_flags(),
        )
        return proc.returncode, proc.stdout

    def game_is_running(self):
        if os.name != "nt":
            return False
        try:
            code, out = self.run_text(["tasklist"], timeout=15)
            if code != 0:
                return False
            low = out.lower()
            return "mxgp3.exe" in low or "mxgp3-win64-shipping.exe" in low
        except Exception:
            return False

    # ---------------- Automatic setup ----------------

    def auto_setup(self, show_result=False):
        try:
            self.log("--- AUTO SETUP ---")
            self.repak_path = self.detect_repak()
            if not self.repak_path:
                raise RuntimeError("Bundled repak.exe is missing from this build.")
            self.packer_label.config(text=f"repak: {self.repak_path}")

            game = self.detect_game_path()
            if not game:
                raise RuntimeError("MXGP3 Steam installation not detected.")
            self.game_path = str(game)
            self.game_label.config(text=self.game_path)
            self.paks_dir = self.find_paks_dir(game)
            if not self.paks_dir:
                raise RuntimeError("MXGP3 Content\\Paks folder not found.")

            self.main_pak = self.find_main_pak(self.paks_dir)
            if not self.main_pak:
                raise RuntimeError("Original MXGP3 .pak not found.")
            self.pak_label.config(text=str(self.main_pak))

            self.inspect_original_pak()
            self.log(f"Original pak version: {self.pak_version}")
            self.log(f"Original mount point: {self.pak_mount}")
            self.log(f"Original DB entry: {self.db_entry}")

            db = self.working_db_path()
            if not db.exists() or not self.is_compatible_db(db):
                self.log("No valid working DB yet. Extracting stock DB directly from the game...")
                self.extract_stock_db(db)
            self.load_database(db)
            self.save_config()

            if show_result:
                messagebox.showinfo(
                    APP_NAME,
                    "Automatic setup complete.\n\nThe tool found MXGP3, read the original PAK format and prepared the game database automatically."
                )
        except Exception as e:
            self.log(f"SETUP ERROR: {e}")
            if show_result:
                messagebox.showerror(APP_NAME, str(e))

    def detect_repak(self):
        candidates = [
            resource_path("repak.exe"),
            Path(sys.executable).parent / "repak.exe",
            Path.cwd() / "repak.exe",
        ]
        return next((p for p in candidates if p.exists()), None)

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

        roots += [
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam",
            Path(r"C:\Steam"),
        ]
        out, seen = [], set()
        for p in roots:
            key = str(p).lower()
            if key not in seen and p.exists():
                seen.add(key)
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
            key = str(p).lower()
            if key not in seen and p.exists():
                seen.add(key)
                out.append(p)
        return out

    def looks_like_game_dir(self, game):
        return bool(game and game.exists() and self.find_paks_dir(game))

    def find_paks_dir(self, game):
        game = Path(game)
        candidates = [
            game / "mxgp3" / "Content" / "Paks",
            game / "MXGP3" / "Content" / "Paks",
            game / "Content" / "Paks",
        ]
        return next((p for p in candidates if p.exists()), None)

    def find_main_pak(self, paks_dir):
        exact = [
            paks_dir / "pakchunk0-WindowsNoEditor.pak",
            paks_dir / "MXGP3-WindowsNoEditor.pak",
        ]
        for p in exact:
            if p.exists():
                return p
        paks = [p for p in paks_dir.glob("*.pak") if "MXGP3TransferTool" not in p.name]
        if not paks:
            return None
        return max(paks, key=lambda p: p.stat().st_size)

    def inspect_original_pak(self):
        code, info = self.run_text([self.repak_path, "info", self.main_pak], timeout=60)
        if code != 0:
            raise RuntimeError("repak could not read the original MXGP3 PAK.\n\n" + info[-2000:])

        mount = re.search(r"^mount point:\s*(.+)$", info, re.M | re.I)
        version = re.search(r"^version:\s*(V[0-9]+[AB]?)$", info, re.M | re.I)
        if not mount or not version:
            raise RuntimeError("Could not detect original PAK mount point/version.")
        self.pak_mount = mount.group(1).strip()
        self.pak_version = version.group(1).strip().upper()

        code, listing = self.run_text(
            [self.repak_path, "list", "-s", self.pak_mount, self.main_pak],
            timeout=120,
        )
        if code != 0:
            raise RuntimeError("Could not list the original MXGP3 PAK.\n\n" + listing[-2000:])

        candidates = []
        for line in listing.splitlines():
            clean = line.strip().replace("\\", "/")
            if clean.lower().endswith(DB_SUFFIX):
                candidates.append(clean)
        if not candidates:
            raise RuntimeError("DB.sqlite3 was not found inside the original PAK.")
        preferred = next((x for x in candidates if x.lower().startswith("mxgp3/")), candidates[0])
        self.db_entry = preferred

    def extract_stock_db(self, destination):
        if not all([self.repak_path, self.main_pak, self.pak_mount, self.db_entry]):
            raise RuntimeError("PAK metadata has not been detected yet.")
        proc = subprocess.run(
            [str(self.repak_path), "get", "-s", self.pak_mount, str(self.main_pak), self.db_entry],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            creationflags=hidden_flags(),
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace")
            raise RuntimeError("Could not extract DB.sqlite3 from the game.\n\n" + err[-2000:])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(proc.stdout)
        if not self.is_compatible_db(destination):
            try:
                destination.unlink()
            except Exception:
                pass
            raise RuntimeError("The extracted file is not a compatible MXGP3 database.")
        self.log(f"Stock DB extracted automatically: {destination}")

    # ---------------- Database ----------------

    def is_compatible_db(self, path):
        try:
            c = sqlite3.connect(str(path))
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            c.close()
            return REQUIRED_TABLES.issubset(tables)
        except Exception:
            return False

    def load_database(self, path):
        path = Path(path)
        if not self.is_compatible_db(path):
            raise RuntimeError("Not a compatible MXGP3 DB.sqlite3.")
        if self.conn:
            self.conn.close()
        self.conn = sqlite3.connect(str(path))
        self.db_path = str(path)
        self.db_label.config(text=self.db_path)
        self.class_box.set("MX2")
        self.load_riders()
        self.log(f"Working DB loaded: {path}")

    def load_riders(self):
        if not self.conn:
            return
        cat = self.class_box.get() or "MX2"
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
        if not item or not self.conn:
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
            raise RuntimeError("No working DB loaded.")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out = self.backup_dir() / f"DB_{stamp}.sqlite3"
        if self.conn:
            self.conn.commit()
        shutil.copy2(self.db_path, out)
        return out

    def rollback_db(self, backup):
        try:
            if self.conn:
                self.conn.close()
            shutil.copy2(backup, self.db_path)
            self.conn = sqlite3.connect(self.db_path)
            self.load_riders()
            self.log(f"DB rolled back from: {backup}")
        except Exception as e:
            self.log(f"ROLLBACK WARNING: {e}")

    def import_external_db(self):
        src = filedialog.askopenfilename(
            title="Import MXGP3 DB.sqlite3",
            filetypes=[("SQLite database", "*.sqlite3"), ("All files", "*.*")],
        )
        if not src:
            return
        if not self.is_compatible_db(src):
            return messagebox.showerror(APP_NAME, "That file is not a compatible MXGP3 DB.sqlite3.")
        dst = self.working_db_path()
        if self.conn:
            self.conn.close()
        shutil.copy2(src, dst)
        self.load_database(dst)
        self.log("External database imported into the tool working copy.")

    # ---------------- Transfer / patch ----------------

    def transfer_and_apply(self):
        if not self.conn:
            return messagebox.showwarning(APP_NAME, "Automatic setup has not completed yet.")
        if self.game_is_running():
            return messagebox.showwarning(APP_NAME, "Close MXGP3 before applying a transfer.")

        rider = self.riders.get(self.rider_box.get())
        new_team = self.teams.get(self.team_box.get())
        if not rider or not new_team:
            return
        rider_key, old_team = rider
        if old_team == new_team:
            return messagebox.showinfo(APP_NAME, "Rider is already in that team.")

        if not messagebox.askyesno(
            APP_NAME,
            f"Apply this transfer directly to MXGP3?\n\n{rider_key}\n{old_team}\n→\n{new_team}"
        ):
            return

        backup = None
        try:
            backup = self.create_backup()
            self.conn.execute("UPDATE Pilots SET Teams_Key=? WHERE Key=?", (new_team, rider_key))
            self.conn.commit()
            check = self.conn.execute("SELECT Teams_Key FROM Pilots WHERE Key=?", (rider_key,)).fetchone()
            if not check or check[0] != new_team:
                raise RuntimeError("Database verification failed.")

            self.log(f"Transfer DB change: {rider_key}: {old_team} -> {new_team}")
            installed = self.build_and_install_pak()
            self.load_riders()
            messagebox.showinfo(
                APP_NAME,
                f"Transfer installed.\n\n{installed}\n\nStart MXGP3 and test the rider in Quick Race."
            )
        except Exception as e:
            if backup:
                self.rollback_db(backup)
            messagebox.showerror(APP_NAME, str(e))

    def apply_current_db(self):
        if self.game_is_running():
            return messagebox.showwarning(APP_NAME, "Close MXGP3 before installing the patch.")
        try:
            out = self.build_and_install_pak()
            messagebox.showinfo(APP_NAME, f"Current DB reinstalled:\n\n{out}")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def build_and_install_pak(self):
        if not self.db_path or not Path(self.db_path).exists():
            raise RuntimeError("Working DB is missing.")
        if not all([self.repak_path, self.paks_dir, self.pak_mount, self.pak_version, self.db_entry]):
            raise RuntimeError("Run AUTO SETUP first.")

        final_pak = Path(self.paks_dir) / MOD_PAK_NAME
        with tempfile.TemporaryDirectory(prefix="MXGP3TransferTool_") as temp:
            temp = Path(temp)
            stage = temp / "stage"
            staged_db = stage.joinpath(*Path(self.db_entry).parts)
            staged_db.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.db_path, staged_db)

            output = temp / MOD_PAK_NAME
            self.log(f"Packing with repak {self.pak_version} / mount {self.pak_mount}...")
            code, out = self.run_text(
                [
                    self.repak_path,
                    "pack",
                    stage,
                    "-m", self.pak_mount,
                    "--version", self.pak_version,
                    output,
                ],
                timeout=180,
            )
            if code != 0 or not output.exists() or output.stat().st_size < 1024:
                raise RuntimeError("repak failed to build the override PAK.\n\n" + out[-3000:])

            self.verify_override_pak(output)
            self.cleanup_old_tool_paks(except_path=final_pak)

            if final_pak.exists():
                backup = Path(str(final_pak) + ".previous")
                shutil.copy2(final_pak, backup)
                self.log(f"Previous Transfer Tool PAK backed up: {backup}")

            new_path = Path(str(final_pak) + ".new")
            shutil.copy2(output, new_path)
            self.verify_override_pak(new_path)
            os.replace(new_path, final_pak)
            self.verify_override_pak(final_pak)

        self.install_sig_if_needed(final_pak)
        self.log(f"Installed override: {final_pak}")
        self.log(f"Overrides original entry: {self.db_entry}")
        return final_pak

    def verify_override_pak(self, pak):
        code, info = self.run_text([self.repak_path, "info", pak], timeout=60)
        if code != 0:
            raise RuntimeError("Built PAK failed verification.\n\n" + info[-2000:])
        code, listing = self.run_text([self.repak_path, "list", "-s", self.pak_mount, pak], timeout=60)
        if code != 0:
            raise RuntimeError("Built PAK list verification failed.\n\n" + listing[-2000:])
        normalized = {x.strip().replace("\\", "/").lower() for x in listing.splitlines() if x.strip()}
        if self.db_entry.lower() not in normalized:
            raise RuntimeError(
                "Built PAK does not contain DB.sqlite3 at the exact original path. Nothing was installed."
            )

    def cleanup_old_tool_paks(self, except_path=None):
        if not self.paks_dir:
            return
        except_path = Path(except_path) if except_path else None
        for name in LEGACY_TOOL_PAKS:
            p = Path(self.paks_dir) / name
            if except_path and p == except_path:
                continue
            for candidate in [p, p.with_suffix(".sig")]:
                if candidate.exists():
                    try:
                        candidate.unlink()
                        self.log(f"Removed old Transfer Tool file: {candidate.name}")
                    except Exception as e:
                        raise RuntimeError(f"Could not replace old Transfer Tool file: {candidate}\n{e}")

    def install_sig_if_needed(self, final_pak):
        originals = [
            Path(self.paks_dir) / "pakchunk0-WindowsNoEditor.sig",
            Path(self.paks_dir) / "MXGP3-WindowsNoEditor.sig",
        ]
        original_sig = next((p for p in originals if p.exists()), None)
        mod_sig = final_pak.with_suffix(".sig")
        if original_sig:
            try:
                shutil.copy2(original_sig, mod_sig)
                self.log(f"Matching .sig filename created: {mod_sig.name}")
            except Exception as e:
                self.log(f"SIG warning: {e}")
        elif mod_sig.exists():
            try:
                mod_sig.unlink()
            except Exception:
                pass

    def remove_mod_pak(self, silent=False):
        if not self.paks_dir:
            if silent:
                return
            return messagebox.showwarning(APP_NAME, "Run AUTO SETUP first.")
        removed = []
        for name in LEGACY_TOOL_PAKS:
            p = Path(self.paks_dir) / name
            for candidate in [p, p.with_suffix(".sig")]:
                if candidate.exists():
                    try:
                        candidate.unlink()
                        removed.append(candidate.name)
                    except Exception as e:
                        if not silent:
                            return messagebox.showerror(APP_NAME, str(e))
        if removed:
            self.log("Removed installed Transfer Tool patch: " + ", ".join(removed))
        if not silent:
            messagebox.showinfo(APP_NAME, "Transfer Tool PAK removed. Restart MXGP3.")

    def reset_from_stock(self):
        if self.game_is_running():
            return messagebox.showwarning(APP_NAME, "Close MXGP3 before resetting the tool.")
        try:
            if not all([self.repak_path, self.main_pak, self.pak_mount, self.db_entry]):
                self.auto_setup(False)
            if not self.main_pak:
                raise RuntimeError("Original MXGP3 PAK is not ready.")
            if self.conn:
                self.conn.close()
                self.conn = None
            db = self.working_db_path()
            self.extract_stock_db(db)
            self.load_database(db)
            self.remove_mod_pak(silent=True)
            self.log("Working database reset to stock and Transfer Tool PAK removed.")
            messagebox.showinfo(APP_NAME, "Reset complete. The tool is back to the original MXGP3 database.")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))


if __name__ == "__main__":
    App().mainloop()
