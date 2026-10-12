import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_NAME = "MXGP3 Slot Hijack Test"
VERSION = "0.7"
STEAM_APP_ID = "561600"
STOCK_SUFFIX = ".MXGP3TransferTool.stock"
REQUIRED_TABLES = {"Pilots", "PilotsInRosters", "Teams", "Vehicles"}


def hidden_flags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry("930x690")
        self.minsize(850, 620)

        self.game = None
        self.paks_dir = None
        self.db_path = None
        self.conn = None
        self.sources = {}
        self.targets = {}
        self.config = self.load_config()

        self.build_ui()
        self.after(250, self.auto_setup)

    # ---------- UI ----------

    def build_ui(self):
        ttk.Label(self, text="MXGP3 SLOT HIJACK TEST", font=("Segoe UI", 20, "bold")).pack(pady=(14, 2))
        ttk.Label(self, text="v0.7 — old-MXGP style slot replacement experiment").pack(pady=(0, 10))

        setup = ttk.LabelFrame(self, text="Game database")
        setup.pack(fill="x", padx=18, pady=7)
        setup.columnconfigure(1, weight=1)

        ttk.Label(setup, text="Game:").grid(row=0, column=0, sticky="w", padx=10, pady=5)
        self.game_label = ttk.Label(setup, text="Searching...")
        self.game_label.grid(row=0, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(setup, text="DB:").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        self.db_label = ttk.Label(setup, text="Searching...")
        self.db_label.grid(row=1, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(setup, text="Load mode:").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        self.mode_label = ttk.Label(setup, text="Checking...")
        self.mode_label.grid(row=2, column=1, sticky="ew", padx=8, pady=5)

        ttk.Button(setup, text="RE-SCAN", command=lambda: self.auto_setup(True)).grid(row=0, column=2, padx=7, pady=5)
        ttk.Button(setup, text="BROWSE DB", command=self.browse_db).grid(row=1, column=2, padx=7, pady=5)

        test = ttk.LabelFrame(self, text="Slot replacement test")
        test.pack(fill="x", padx=18, pady=7)
        test.columnconfigure(1, weight=1)

        ttk.Label(test, text="Class:").grid(row=0, column=0, sticky="w", padx=10, pady=7)
        self.class_box = ttk.Combobox(test, state="readonly", values=["MX2", "MXGP"])
        self.class_box.grid(row=0, column=1, sticky="ew", padx=10, pady=7)
        self.class_box.bind("<<ComboboxSelected>>", lambda _e: self.load_slots())

        ttk.Label(test, text="Source identity:").grid(row=1, column=0, sticky="w", padx=10, pady=7)
        self.source_box = ttk.Combobox(test, state="readonly")
        self.source_box.grid(row=1, column=1, sticky="ew", padx=10, pady=7)
        self.source_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_preview())

        ttk.Label(test, text="Destination slot:").grid(row=2, column=0, sticky="w", padx=10, pady=7)
        self.target_box = ttk.Combobox(test, state="readonly")
        self.target_box.grid(row=2, column=1, sticky="ew", padx=10, pady=7)
        self.target_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_preview())

        ttk.Label(test, text="Source data:").grid(row=3, column=0, sticky="nw", padx=10, pady=7)
        self.source_info = ttk.Label(test, text="-")
        self.source_info.grid(row=3, column=1, sticky="w", padx=10, pady=7)

        ttk.Label(test, text="Slot kept native:").grid(row=4, column=0, sticky="nw", padx=10, pady=7)
        self.target_info = ttk.Label(test, text="-")
        self.target_info.grid(row=4, column=1, sticky="w", padx=10, pady=7)

        self.test_button = ttk.Button(test, text="HIJACK DESTINATION SLOT — TEST", command=self.apply_hijack)
        self.test_button.grid(row=5, column=0, columnspan=2, pady=14, ipadx=35, ipady=6)

        tools = ttk.LabelFrame(self, text="Safety / test")
        tools.pack(fill="x", padx=18, pady=7)
        ttk.Button(tools, text="RESTORE LAST BACKUP", command=self.restore_last_backup).pack(side="left", padx=10, pady=9)
        ttk.Label(
            tools,
            text="Expected test: Herlings identity data on Anstie slot, but Anstie's Rockstar/Husqvarna slot stays native."
        ).pack(side="left", padx=10)

        logf = ttk.LabelFrame(self, text="Log / what to look for in game")
        logf.pack(fill="both", expand=True, padx=18, pady=(7, 18))
        self.logbox = tk.Text(logf, height=15, state="disabled", font=("Consolas", 9))
        self.logbox.pack(fill="both", expand=True, padx=8, pady=8)
        self.log("This build does NOT transfer a rider by changing Teams_Key.")
        self.log("It keeps the destination slot's team and vehicle untouched, and copies only identity/roster data onto that slot.")
        self.log("If MX2-Anstie becomes #84 Netherlands while still Rockstar/Husqvarna, the slot-hijack mechanism works.")

    def log(self, text):
        self.logbox.config(state="normal")
        self.logbox.insert("end", str(text) + "\n")
        self.logbox.see("end")
        self.logbox.config(state="disabled")
        self.update_idletasks()

    # ---------- App data ----------

    def app_dir(self):
        p = Path(os.getenv("APPDATA") or Path.home()) / "MXGP3SlotHijack"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def config_path(self):
        return self.app_dir() / "config.json"

    def backup_dir(self):
        p = self.app_dir() / "backups"
        p.mkdir(parents=True, exist_ok=True)
        return p

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
            self.config["game"] = str(self.game) if self.game else None
            self.config["db"] = str(self.db_path) if self.db_path else None
            self.config_path().write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        except Exception as e:
            self.log(f"Config warning: {e}")

    # ---------- Detection ----------

    def game_running(self):
        if os.name != "nt":
            return False
        try:
            p = subprocess.run(
                ["tasklist"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace", timeout=15, creationflags=hidden_flags()
            )
            low = p.stdout.lower()
            return "mxgp3.exe" in low or "mxgp3-win64-shipping.exe" in low
        except Exception:
            return False

    def auto_setup(self, show=False):
        try:
            self.game = self.detect_game()
            if not self.game:
                raise RuntimeError("MXGP3 Steam installation not detected.")
            self.paks_dir = self.find_paks(self.game)
            self.game_label.config(text=str(self.game))

            db = self.find_loose_db(self.game)
            if not db:
                last = self.config.get("db")
                if last and self.compatible(Path(last)):
                    db = Path(last)
            if not db:
                raise RuntimeError(
                    "Loose DB.sqlite3 not found. Enable Loose Files Mode with v0.6 first, or use BROWSE DB."
                )
            self.load_db(db)
            self.update_mode_status()
            self.save_config()
            if show:
                messagebox.showinfo(APP_NAME, "Slot test database loaded.")
        except Exception as e:
            self.log(f"SETUP ERROR: {e}")
            self.mode_label.config(text="SETUP INCOMPLETE")
            if show:
                messagebox.showerror(APP_NAME, str(e))

    def detect_game(self):
        last = self.config.get("game")
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
                for hive, key, value in checks:
                    try:
                        with winreg.OpenKey(hive, key) as k:
                            roots.append(Path(winreg.QueryValueEx(k, value)[0]))
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
            k = str(root).lower()
            if k in seen or not root.exists():
                continue
            seen.add(k)
            libs = [root]
            vdf = root / "steamapps" / "libraryfolders.vdf"
            if vdf.exists():
                txt = vdf.read_text(encoding="utf-8", errors="ignore")
                libs += [Path(x.replace("\\\\", "\\")) for x in re.findall(r'"path"\s+"([^"]+)"', txt, re.I)]
            for lib in libs:
                mf = lib / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
                if not mf.exists():
                    continue
                txt = mf.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r'"installdir"\s+"([^"]+)"', txt, re.I)
                if m:
                    game = lib / "steamapps" / "common" / m.group(1)
                    if self.find_paks(game):
                        return game
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

    def find_loose_db(self, game):
        game = Path(game)
        candidates = [
            game / "mxgp3" / "Content" / "assets" / "data" / "db" / "NoCook" / "DB.sqlite3",
            game / "MXGP3" / "Content" / "assets" / "data" / "db" / "NoCook" / "DB.sqlite3",
            game / "Content" / "assets" / "data" / "db" / "NoCook" / "DB.sqlite3",
        ]
        return next((p for p in candidates if self.compatible(p)), None)

    def update_mode_status(self):
        if not self.paks_dir:
            self.mode_label.config(text="PAK folder not detected")
            return
        active = self.paks_dir / "pakchunk0-WindowsNoEditor.pak"
        backed = Path(str(active) + STOCK_SUFFIX)
        if not active.exists() and backed.exists():
            self.mode_label.config(text="LOOSE FILES MODE DETECTED — good for this test")
        elif active.exists():
            self.mode_label.config(text="WARNING: STOCK PAK IS ACTIVE — loose DB may be ignored")
            self.log("WARNING: pakchunk0-WindowsNoEditor.pak is still active. If the test changes nothing in game, this is the first thing to fix.")
        else:
            self.mode_label.config(text="Custom/unknown PAK state — test carefully")

    def browse_db(self):
        path = filedialog.askopenfilename(
            title="Select MXGP3 DB.sqlite3",
            filetypes=[("SQLite database", "*.sqlite3"), ("All files", "*.*")]
        )
        if not path:
            return
        p = Path(path)
        if not self.compatible(p):
            return messagebox.showerror(APP_NAME, "That is not a compatible MXGP3 DB.sqlite3.")
        self.load_db(p)
        self.save_config()

    # ---------- Database ----------

    def compatible(self, db):
        try:
            if not db or not Path(db).exists():
                return False
            c = sqlite3.connect(str(db))
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            c.close()
            return REQUIRED_TABLES.issubset(tables)
        except Exception:
            return False

    def load_db(self, db):
        if self.conn:
            self.conn.close()
        self.db_path = Path(db)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.db_label.config(text=str(self.db_path))
        self.class_box.set("MX2")
        self.load_slots()
        self.log(f"DB loaded: {self.db_path}")

    def load_slots(self):
        if not self.conn:
            return
        cat = self.class_box.get() or "MX2"
        rows = self.conn.execute(
            """SELECT P.Key,P.Number,P.Nations_Key,P.Teams_Key,P.PilotGroups_Key,
                      COALESCE(V.Manufacturers_Key,'?')
               FROM Pilots P
               JOIN Teams T ON P.Teams_Key=T.Key
               LEFT JOIN Vehicles V ON V.Key=P.Key
               WHERE P.IsStrippedFromDB=0 AND P.Teams_Key IS NOT NULL AND T.Categories_Key=?
               ORDER BY P.Key""", (cat,)
        ).fetchall()
        self.sources = {}
        self.targets = {}
        labels = []
        for key, num, nation, team, group, bike in rows:
            label = f"#{num}  {key.split('-', 1)[-1]}  [{team.split('-', 1)[-1]} / {bike}]"
            data = (key, num, nation, team, group, bike)
            self.sources[label] = data
            self.targets[label] = data
            labels.append(label)
        self.source_box["values"] = labels
        self.target_box["values"] = labels
        if labels:
            src = next((x for x in labels if "Herlings" in x), labels[0])
            dst = next((x for x in labels if "Anstie" in x), labels[1] if len(labels) > 1 else labels[0])
            self.source_box.set(src)
            self.target_box.set(dst)
            self.refresh_preview()

    def refresh_preview(self):
        src = self.sources.get(self.source_box.get())
        dst = self.targets.get(self.target_box.get())
        if not src or not dst:
            return
        self.source_info.config(text=f"{src[0]}  |  #{src[1]}  |  {src[2]}  |  group {src[4]}")
        self.target_info.config(text=f"{dst[0]}  |  team {dst[3]}  |  bike {dst[5]}  (team + vehicle will NOT be changed)")

    def backup_db(self):
        self.conn.commit()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out = self.backup_dir() / f"DB_before_slot_hijack_{stamp}.sqlite3"
        shutil.copy2(self.db_path, out)
        self.config["last_backup"] = str(out)
        self.save_config()
        return out

    def apply_hijack(self):
        if self.game_running():
            return messagebox.showwarning(APP_NAME, "Close MXGP3 before running the slot test.")
        if not self.conn:
            return messagebox.showwarning(APP_NAME, "Load the MXGP3 database first.")

        src = self.sources.get(self.source_box.get())
        dst = self.targets.get(self.target_box.get())
        if not src or not dst:
            return
        source_key, source_num, source_nation, source_team, source_group, source_bike = src
        target_key, target_num, target_nation, target_team, target_group, target_bike = dst
        cat = self.class_box.get()
        if source_key == target_key:
            return messagebox.showinfo(APP_NAME, "Choose a different destination slot.")

        msg = (
            "SLOT HIJACK TEST\n\n"
            f"Identity source: {source_key}  #{source_num}  {source_nation}\n"
            f"Destination slot: {target_key}\n"
            f"KEEP native team: {target_team}\n"
            f"KEEP native bike: {target_bike}\n\n"
            f"The {cat} roster entry for {source_key} will be removed and the destination slot will take its roster position.\n"
            "The destination KEY is intentionally NOT renamed, so the displayed rider name may remain the destination rider.\n\n"
            "Continue?"
        )
        if not messagebox.askyesno(APP_NAME, msg):
            return

        backup = self.backup_db()
        try:
            source_order_row = self.conn.execute(
                "SELECT Ordering FROM PilotsInRosters WHERE Rosters_Key=? AND Pilots_Key=?",
                (cat, source_key)
            ).fetchone()
            if not source_order_row:
                raise RuntimeError(f"{source_key} is not in the {cat} roster.")
            source_order = source_order_row[0]

            native_team_before = self.conn.execute("SELECT Teams_Key FROM Pilots WHERE Key=?", (target_key,)).fetchone()[0]
            native_vehicle_before = self.conn.execute(
                "SELECT Categories_Key,CategoryEngines_Strokes,Manufacturers_Key,VehiclePhysics_Key,VehicleStatistics_Key,VehicleSettingGroups_Key FROM Vehicles WHERE Key=?",
                (target_key,)
            ).fetchone()
            if not native_vehicle_before:
                raise RuntimeError("Destination slot has no Vehicles row.")

            self.conn.execute("BEGIN IMMEDIATE")
            try:
                # Old-MXGP-style tactic: copy identity onto a slot that already owns the desired team/bike.
                # Deliberately DO NOT touch target Teams_Key, target Key, target Vehicles or target customization.
                self.conn.execute(
                    "UPDATE Pilots SET Number=?, Nations_Key=?, PilotGroups_Key=? WHERE Key=?",
                    (source_num, source_nation, source_group, target_key)
                )

                # Put destination slot where the source rider was in the selected championship roster.
                self.conn.execute(
                    "DELETE FROM PilotsInRosters WHERE Rosters_Key=? AND Pilots_Key=?",
                    (cat, source_key)
                )
                existing_target = self.conn.execute(
                    "SELECT 1 FROM PilotsInRosters WHERE Rosters_Key=? AND Pilots_Key=?",
                    (cat, target_key)
                ).fetchone()
                if existing_target:
                    self.conn.execute(
                        "UPDATE PilotsInRosters SET Ordering=? WHERE Rosters_Key=? AND Pilots_Key=?",
                        (source_order, cat, target_key)
                    )
                else:
                    self.conn.execute(
                        "INSERT INTO PilotsInRosters(Rosters_Key,Pilots_Key,Ordering) VALUES(?,?,?)",
                        (cat, target_key, source_order)
                    )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

            got = self.conn.execute(
                "SELECT Number,Nations_Key,Teams_Key,PilotGroups_Key FROM Pilots WHERE Key=?",
                (target_key,)
            ).fetchone()
            vehicle_after = self.conn.execute(
                "SELECT Categories_Key,CategoryEngines_Strokes,Manufacturers_Key,VehiclePhysics_Key,VehicleStatistics_Key,VehicleSettingGroups_Key FROM Vehicles WHERE Key=?",
                (target_key,)
            ).fetchone()
            src_roster = self.conn.execute(
                "SELECT 1 FROM PilotsInRosters WHERE Rosters_Key=? AND Pilots_Key=?",
                (cat, source_key)
            ).fetchone()
            dst_roster = self.conn.execute(
                "SELECT Ordering FROM PilotsInRosters WHERE Rosters_Key=? AND Pilots_Key=?",
                (cat, target_key)
            ).fetchone()

            if not got or got[0] != source_num or got[1] != source_nation or got[3] != source_group:
                raise RuntimeError("Identity copy verification failed.")
            if got[2] != native_team_before:
                raise RuntimeError("Destination team changed unexpectedly; rollback required.")
            if vehicle_after != native_vehicle_before:
                raise RuntimeError("Destination vehicle changed unexpectedly; rollback required.")
            if src_roster:
                raise RuntimeError("Source rider is still present in the selected roster.")
            if not dst_roster or dst_roster[0] != source_order:
                raise RuntimeError("Destination roster position verification failed.")

            self.conn.commit()
            self.log("--- SLOT HIJACK WRITTEN + VERIFIED ---")
            self.log(f"SOURCE REMOVED FROM {cat} ROSTER: {source_key}")
            self.log(f"DEST SLOT: {target_key}")
            self.log(f"IDENTITY NOW: #{source_num} / {source_nation} / group {source_group}")
            self.log(f"NATIVE TEAM KEPT: {native_team_before}")
            self.log(f"NATIVE VEHICLE KEPT: {native_vehicle_before[2]}")
            self.log(f"ROSTER ORDER: {source_order}")
            self.log(f"BACKUP: {backup}")
            self.log("IN GAME TEST: the destination slot should now show #84/Netherlands for Herlings test, while remaining Rockstar/Husqvarna. The visible surname may still say Anstie.")

            messagebox.showinfo(
                APP_NAME,
                "Slot hijack written and verified on disk.\n\n"
                f"Destination slot: {target_key}\n"
                f"Identity: #{source_num} / {source_nation}\n"
                f"Native team: {native_team_before}\n"
                f"Native bike: {native_vehicle_before[2]}\n\n"
                "Start Quick Race. For Herlings -> Anstie, look for an Anstie-named slot with #84 / Netherlands that is still Rockstar Husqvarna."
            )
            self.load_slots()
        except Exception as e:
            try:
                if self.conn:
                    self.conn.close()
                    self.conn = None
                shutil.copy2(backup, self.db_path)
                self.load_db(self.db_path)
                self.log(f"FAILED — restored DB from backup: {backup}")
            except Exception as restore_err:
                self.log(f"ROLLBACK WARNING: {restore_err}")
            messagebox.showerror(APP_NAME, str(e))

    def restore_last_backup(self):
        if self.game_running():
            return messagebox.showwarning(APP_NAME, "Close MXGP3 before restoring a backup.")
        backup = self.config.get("last_backup")
        if not backup or not Path(backup).exists():
            return messagebox.showinfo(APP_NAME, "No slot-hijack backup found yet.")
        if not self.db_path:
            return messagebox.showwarning(APP_NAME, "Load the game DB first.")
        if not messagebox.askyesno(APP_NAME, f"Restore this backup?\n\n{backup}"):
            return
        try:
            if self.conn:
                self.conn.close()
                self.conn = None
            shutil.copy2(backup, self.db_path)
            self.load_db(self.db_path)
            self.log(f"RESTORED: {backup}")
            messagebox.showinfo(APP_NAME, "Database restored from the last backup.")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))


if __name__ == "__main__":
    App().mainloop()
