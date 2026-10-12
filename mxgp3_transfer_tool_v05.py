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
VERSION = "0.5"
STEAM_APP_ID = "561600"
REQUIRED_TABLES = {"Pilots", "Teams", "PilotsInRosters", "Vehicles", "CustomizationFilters", "CustomizationItems"}
MOD_PAK_NAME = "pakchunk0-WindowsNoEditor_999_P.pak"
LEGACY_TOOL_PAKS = [
    "pakchunk0-WindowsNoEditor_MXGP3TransferTool_P.pak",
    "pakchunk99-MXGP3TransferTool_P.pak",
    "pakchunk0-WindowsNoEditor_999_P.pak",
]
DB_SUFFIX = "content/assets/data/db/nocook/db.sqlite3"
PILOT_GEAR_TYPES = ["Boots", "Goggles", "Helmet", "NeckBrace"]
VEHICLE_TYPES = [
    "BarPad", "BrakeBack", "BrakeFront", "Exhaust", "Fork", "Handgrip",
    "Handguards", "Handlebar", "RimBack", "RimFront", "TyreBack", "TyreFront"
]


def hidden_flags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def resource_path(name):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry("950x720")
        self.minsize(860, 640)
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
        self.build_ui()
        self.after(250, self.auto_setup)

    def build_ui(self):
        ttk.Label(self, text="MXGP3 TRANSFER TOOL", font=("Segoe UI", 20, "bold")).pack(pady=(16, 2))
        ttk.Label(self, text="v0.5 FULL TRANSFER + VISUAL SYNC — Cro14").pack(pady=(0, 12))

        setup = ttk.LabelFrame(self, text="Automatic setup")
        setup.pack(fill="x", padx=18, pady=7)
        setup.columnconfigure(1, weight=1)
        ttk.Label(setup, text="Game:").grid(row=0, column=0, sticky="w", padx=10, pady=4)
        self.game_label = ttk.Label(setup, text="Searching...")
        self.game_label.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(setup, text="Original PAK:").grid(row=1, column=0, sticky="w", padx=10, pady=4)
        self.pak_label = ttk.Label(setup, text="Searching...")
        self.pak_label.grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(setup, text="Working DB:").grid(row=2, column=0, sticky="w", padx=10, pady=4)
        self.db_label = ttk.Label(setup, text="Preparing...")
        self.db_label.grid(row=2, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(setup, text="AUTO SETUP", command=lambda: self.auto_setup(True)).grid(row=0, column=2, rowspan=2, padx=8, pady=8)
        ttk.Button(setup, text="RESET STOCK", command=self.reset_stock).grid(row=2, column=2, padx=8, pady=8)

        tr = ttk.LabelFrame(self, text="Full rider transfer")
        tr.pack(fill="x", padx=18, pady=7)
        tr.columnconfigure(1, weight=1)
        ttk.Label(tr, text="Class:").grid(row=0, column=0, sticky="w", padx=10, pady=7)
        self.class_box = ttk.Combobox(tr, state="readonly", values=["MX2", "MXGP"])
        self.class_box.grid(row=0, column=1, sticky="ew", padx=10, pady=7)
        self.class_box.bind("<<ComboboxSelected>>", lambda _e: self.load_riders())
        ttk.Label(tr, text="Rider:").grid(row=1, column=0, sticky="w", padx=10, pady=7)
        self.rider_box = ttk.Combobox(tr, state="readonly")
        self.rider_box.grid(row=1, column=1, sticky="ew", padx=10, pady=7)
        self.rider_box.bind("<<ComboboxSelected>>", lambda _e: self.rider_changed())
        ttk.Label(tr, text="Current team:").grid(row=2, column=0, sticky="w", padx=10, pady=7)
        self.current_team = ttk.Label(tr, text="-")
        self.current_team.grid(row=2, column=1, sticky="w", padx=10, pady=7)
        ttk.Label(tr, text="New team:").grid(row=3, column=0, sticky="w", padx=10, pady=7)
        self.team_box = ttk.Combobox(tr, state="readonly")
        self.team_box.grid(row=3, column=1, sticky="ew", padx=10, pady=7)
        ttk.Button(tr, text="FULL TRANSFER — AUTO INSTALL", command=self.transfer).grid(row=4, column=0, columnspan=2, pady=14, ipadx=42, ipady=7)

        tools = ttk.LabelFrame(self, text="Patch")
        tools.pack(fill="x", padx=18, pady=7)
        ttk.Button(tools, text="Reinstall current DB", command=self.install_current).pack(side="left", padx=10, pady=9)
        ttk.Button(tools, text="Remove patch", command=self.remove_patch).pack(side="left", padx=10, pady=9)
        ttk.Label(tools, text=f"Patch: {MOD_PAK_NAME}").pack(side="left", padx=12)

        lf = ttk.LabelFrame(self, text="Log / diagnostics")
        lf.pack(fill="both", expand=True, padx=18, pady=(7, 18))
        self.logbox = tk.Text(lf, height=14, state="disabled", font=("Consolas", 9))
        self.logbox.pack(fill="both", expand=True, padx=8, pady=8)
        self.log("v0.5 changes team + rider vehicle manufacturer + official visual filters.")
        self.log("Patch uses canonical pakchunk0 ... _999_P priority naming and verifies the DB inside the installed PAK.")

    def log(self, text):
        self.logbox.config(state="normal")
        self.logbox.insert("end", str(text) + "\n")
        self.logbox.see("end")
        self.logbox.config(state="disabled")
        self.update_idletasks()

    def app_dir(self):
        p = Path(os.getenv("APPDATA") or Path.home()) / "MXGP3TransferTool"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def config_path(self):
        return self.app_dir() / "config.json"

    def working_db(self):
        p = self.app_dir() / "working"
        p.mkdir(parents=True, exist_ok=True)
        return p / "DB.sqlite3"

    def backup_dir(self):
        p = self.app_dir() / "backups"
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
        except Exception:
            pass

    def run(self, args, timeout=180, binary=False):
        p = subprocess.run(
            [str(x) for x in args], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if binary else subprocess.STDOUT,
            text=not binary, errors=None if binary else "replace",
            timeout=timeout, creationflags=hidden_flags())
        return p

    def auto_setup(self, show=False):
        try:
            self.log("--- AUTO SETUP ---")
            self.repak_path = resource_path("repak.exe")
            if not self.repak_path.exists():
                raise RuntimeError("Bundled repak.exe missing.")
            game = self.detect_game()
            if not game:
                raise RuntimeError("MXGP3 Steam installation not detected.")
            self.game_path = str(game)
            self.game_label.config(text=self.game_path)
            self.paks_dir = self.find_paks(game)
            self.main_pak = self.find_main_pak(self.paks_dir)
            if not self.main_pak:
                raise RuntimeError("Original MXGP3 PAK not found.")
            self.pak_label.config(text=str(self.main_pak))
            self.inspect_pak()
            self.log(f"PAK version: {self.pak_version}")
            self.log(f"Mount: {self.pak_mount}")
            self.log(f"DB entry: {self.db_entry}")
            db = self.working_db()
            if not db.exists() or not self.compatible(db):
                self.extract_stock_db(db)
            self.load_db(db)
            self.save_config()
            if show:
                messagebox.showinfo(APP_NAME, "Setup complete.")
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
                for hive, key, val in [
                    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")]:
                    try:
                        with winreg.OpenKey(hive, key) as k:
                            roots.append(Path(winreg.QueryValueEx(k, val)[0]))
                    except OSError:
                        pass
            except Exception:
                pass
        roots += [Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam"]
        seen = set()
        for root in roots:
            if not root.exists() or str(root).lower() in seen:
                continue
            seen.add(str(root).lower())
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
                    g = lib / "steamapps" / "common" / m.group(1)
                    if self.find_paks(g):
                        return g
        return None

    def find_paks(self, game):
        if not game:
            return None
        game = Path(game)
        for p in [game / "mxgp3" / "Content" / "Paks", game / "MXGP3" / "Content" / "Paks", game / "Content" / "Paks"]:
            if p.exists():
                return p
        return None

    def find_main_pak(self, paks):
        if not paks:
            return None
        for name in ["pakchunk0-WindowsNoEditor.pak", "MXGP3-WindowsNoEditor.pak"]:
            p = Path(paks) / name
            if p.exists():
                return p
        originals = [p for p in Path(paks).glob("*.pak") if p.name not in LEGACY_TOOL_PAKS and "TransferTool" not in p.name]
        return max(originals, key=lambda p: p.stat().st_size) if originals else None

    def inspect_pak(self):
        p = self.run([self.repak_path, "info", self.main_pak], timeout=60)
        if p.returncode:
            raise RuntimeError("Could not inspect stock PAK.\n" + p.stdout[-2000:])
        mount = re.search(r"^mount point:\s*(.+)$", p.stdout, re.M | re.I)
        ver = re.search(r"^version:\s*(V[0-9]+[AB]?)$", p.stdout, re.M | re.I)
        if not mount or not ver:
            raise RuntimeError("Could not read PAK mount/version.")
        self.pak_mount = mount.group(1).strip()
        self.pak_version = ver.group(1).strip().upper()
        p = self.run([self.repak_path, "list", "-s", self.pak_mount, self.main_pak], timeout=120)
        if p.returncode:
            raise RuntimeError("Could not list stock PAK.\n" + p.stdout[-2000:])
        entries = [x.strip().replace("\\", "/") for x in p.stdout.splitlines()]
        found = [x for x in entries if x.lower().endswith(DB_SUFFIX)]
        if not found:
            raise RuntimeError("DB.sqlite3 not found inside stock PAK.")
        self.db_entry = next((x for x in found if x.lower().startswith("mxgp3/")), found[0])

    def extract_stock_db(self, dest):
        p = self.run([self.repak_path, "get", "-s", self.pak_mount, self.main_pak, self.db_entry], timeout=120, binary=True)
        if p.returncode:
            raise RuntimeError("Could not extract stock DB.\n" + p.stderr.decode("utf-8", errors="replace")[-2000:])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(p.stdout)
        if not self.compatible(dest):
            raise RuntimeError("Extracted DB is not compatible.")
        self.log(f"Stock DB extracted: {dest}")

    def compatible(self, db):
        try:
            c = sqlite3.connect(str(db))
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            c.close()
            return REQUIRED_TABLES.issubset(tables)
        except Exception:
            return False

    def load_db(self, db):
        if self.conn:
            self.conn.close()
        self.conn = sqlite3.connect(str(db))
        self.db_path = str(db)
        self.db_label.config(text=self.db_path)
        self.class_box.set("MX2")
        self.load_riders()
        self.log(f"DB loaded: {db}")

    def load_riders(self):
        if not self.conn:
            return
        cat = self.class_box.get() or "MX2"
        rows = self.conn.execute("""SELECT P.Key,P.Number,P.Teams_Key FROM Pilots P JOIN Teams T ON P.Teams_Key=T.Key WHERE P.IsStrippedFromDB=0 AND T.Categories_Key=? ORDER BY P.Key""", (cat,)).fetchall()
        self.riders = {}
        vals = []
        for key, num, team in rows:
            label = f"#{num}  {key.split('-',1)[-1]}"
            self.riders[label] = (key, team)
            vals.append(label)
        self.rider_box["values"] = vals
        if vals:
            self.rider_box.set(next((x for x in vals if "Herlings" in x), vals[0]))
            self.rider_changed()

    def rider_changed(self):
        item = self.riders.get(self.rider_box.get())
        if not item:
            return
        _, old = item
        cat = self.class_box.get()
        rows = self.conn.execute("SELECT Key FROM Teams WHERE Categories_Key=? ORDER BY Ordering", (cat,)).fetchall()
        self.teams = {}
        vals = []
        for (key,) in rows:
            short = key[len(cat)+1:] if key.startswith(cat + "-") else key
            self.teams[short] = key
            vals.append(short)
        self.team_box["values"] = vals
        self.current_team.config(text=old)
        oldshort = old[len(cat)+1:] if old.startswith(cat + "-") else old
        if oldshort in self.teams:
            self.team_box.set(oldshort)

    def backup_db(self):
        self.conn.commit()
        out = self.backup_dir() / f"DB_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.sqlite3"
        shutil.copy2(self.db_path, out)
        return out

    def sync_visual_filters(self, rider, team):
        c = self.conn
        old = c.execute("SELECT MultiFilterSecondaryKey,CustomizationItemType,Manufacturer,Model,Variant FROM CustomizationFilters WHERE Key=? ORDER BY MultiFilterSecondaryKey", (rider,)).fetchall()
        team_filters = c.execute("SELECT CustomizationItemType,Manufacturer,Model,Variant FROM CustomizationFilters WHERE Key=? ORDER BY MultiFilterSecondaryKey", (team,)).fetchall()
        if not team_filters:
            self.log("No destination team customization filters found; visual filter sync skipped.")
            return

        new_filters = []
        # Keep personal helmet/boots/goggles/neckbrace when those official rider items exist.
        for typ in PILOT_GEAR_TYPES:
            exists = c.execute("SELECT 1 FROM CustomizationItems WHERE CustomizationItemTypes_Key=? AND Manufacturers_Key='Official' AND Model='Official' AND Variant=? LIMIT 1", (typ, rider)).fetchone()
            if exists:
                new_filters.append((typ, "Official", "Official", rider))

        # Force destination team suit/livery if present.
        for typ in ["Suit", "Livery"]:
            exists = c.execute("SELECT 1 FROM CustomizationItems WHERE CustomizationItemTypes_Key=? AND Manufacturers_Key='Official' AND Model='Official' AND Variant=? LIMIT 1", (typ, team)).fetchone()
            if exists:
                new_filters.append((typ, "Official", "Official", team))

        # Clone destination team's official bike-part filters.
        for typ, man, model, variant in team_filters:
            if typ in VEHICLE_TYPES:
                new_filters.append((typ, man, model, variant))

        # Preserve any types that neither our gear nor destination filters covered.
        covered = {x[0] for x in new_filters}
        for _sec, typ, man, model, variant in old:
            if typ != "%" and typ not in covered:
                new_filters.append((typ, man, model, variant))
                covered.add(typ)

        if not new_filters:
            self.log("Visual filter sync produced no rows; keeping original rider filters.")
            return
        c.execute("DELETE FROM CustomizationFilters WHERE Key=?", (rider,))
        for i, row in enumerate(new_filters):
            c.execute("INSERT INTO CustomizationFilters(Key,MultiFilterSecondaryKey,CustomizationItemType,Manufacturer,Model,Variant) VALUES(?,?,?,?,?,?)", (rider, i, *row))
        self.log(f"Visual filters synced: {len(new_filters)} rows for {rider}")

    def apply_full_transfer_to_db(self, rider, old_team, new_team):
        c = self.conn
        dest = c.execute("SELECT Categories_Key,CategoryEngines_Strokes,Manufacturers_Key FROM Vehicles WHERE Key=?", (new_team,)).fetchone()
        if not dest:
            raise RuntimeError("Destination team has no official Vehicles row.")
        category, strokes, manufacturer = dest
        rider_vehicle = c.execute("SELECT Categories_Key FROM Vehicles WHERE Key=?", (rider,)).fetchone()
        if not rider_vehicle:
            raise RuntimeError("Rider vehicle row not found.")
        if rider_vehicle[0] != category:
            raise RuntimeError("v0.5 only supports same-class transfers.")

        c.execute("UPDATE Pilots SET Teams_Key=? WHERE Key=?", (new_team, rider))
        c.execute("UPDATE Vehicles SET Manufacturers_Key=?, CategoryEngines_Strokes=? WHERE Key=?", (manufacturer, strokes, rider))
        self.sync_visual_filters(rider, new_team)
        c.commit()

        p = c.execute("SELECT Teams_Key FROM Pilots WHERE Key=?", (rider,)).fetchone()
        v = c.execute("SELECT Manufacturers_Key FROM Vehicles WHERE Key=?", (rider,)).fetchone()
        if not p or p[0] != new_team:
            raise RuntimeError("Pilot team DB verification failed.")
        if not v or v[0] != manufacturer:
            raise RuntimeError("Rider vehicle manufacturer DB verification failed.")
        self.log(f"TEAM: {rider}: {old_team} -> {new_team}")
        self.log(f"BIKE MANUFACTURER: {rider} -> {manufacturer}")

    def transfer(self):
        if not self.conn:
            return messagebox.showwarning(APP_NAME, "Run AUTO SETUP first.")
        rider_info = self.riders.get(self.rider_box.get())
        new_team = self.teams.get(self.team_box.get())
        if not rider_info or not new_team:
            return
        rider, old_team = rider_info
        if old_team == new_team:
            return messagebox.showinfo(APP_NAME, "Rider is already in that team.")
        if not messagebox.askyesno(APP_NAME, f"Full transfer?\n\n{rider}\n{old_team}\n→\n{new_team}\n\nThis also syncs bike brand and official team visuals."):
            return
        backup = self.backup_db()
        try:
            self.apply_full_transfer_to_db(rider, old_team, new_team)
            installed = self.build_patch()
            self.verify_transfer_inside_pak(installed, rider, new_team)
            self.load_riders()
            messagebox.showinfo(APP_NAME, "Transfer written and verified inside the installed patch.\n\nStart MXGP3 and test Quick Race.")
        except Exception as e:
            try:
                if self.conn:
                    self.conn.close()
                shutil.copy2(backup, self.db_path)
                self.load_db(Path(self.db_path))
            except Exception:
                pass
            messagebox.showerror(APP_NAME, str(e))

    def build_patch(self):
        if not all([self.db_path, self.repak_path, self.paks_dir, self.pak_mount, self.pak_version, self.db_entry]):
            raise RuntimeError("Setup incomplete.")
        final = Path(self.paks_dir) / MOD_PAK_NAME
        with tempfile.TemporaryDirectory(prefix="MXGP3TT_") as td:
            td = Path(td)
            stage = td / "stage"
            target = stage.joinpath(*Path(self.db_entry).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.db_path, target)
            outpak = td / MOD_PAK_NAME
            p = self.run([self.repak_path, "pack", stage, "-m", self.pak_mount, "--version", self.pak_version, outpak], timeout=180)
            if p.returncode or not outpak.exists():
                raise RuntimeError("repak pack failed.\n" + (p.stdout[-3000:] if p.stdout else ""))
            self.verify_pak(outpak)
            self.cleanup_old(except_name=MOD_PAK_NAME)
            tmp = Path(str(final) + ".new")
            shutil.copy2(outpak, tmp)
            self.verify_pak(tmp)
            os.replace(tmp, final)
            self.verify_pak(final)
        sig = self.main_pak.with_suffix(".sig") if self.main_pak else None
        if sig and sig.exists():
            self.log("WARNING: stock PAK has a .sig. v0.5 does NOT copy a fake signature; if MXGP3 enforces signing, the patch may be ignored.")
        self.log(f"Installed canonical patch: {final}")
        return final

    def verify_pak(self, pak):
        p = self.run([self.repak_path, "list", "-s", self.pak_mount, pak], timeout=60)
        if p.returncode:
            raise RuntimeError("Patch verification failed.\n" + p.stdout[-2000:])
        entries = {x.strip().replace("\\", "/").lower() for x in p.stdout.splitlines() if x.strip()}
        if self.db_entry.lower() not in entries:
            raise RuntimeError("Patch does not contain DB at the exact stock path.")

    def verify_transfer_inside_pak(self, pak, rider, team):
        p = self.run([self.repak_path, "get", "-s", self.pak_mount, pak, self.db_entry], timeout=60, binary=True)
        if p.returncode:
            raise RuntimeError("Could not read DB back from installed patch.")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite3") as f:
            f.write(p.stdout)
            temp = f.name
        try:
            c = sqlite3.connect(temp)
            got = c.execute("SELECT Teams_Key FROM Pilots WHERE Key=?", (rider,)).fetchone()
            c.close()
            if not got or got[0] != team:
                raise RuntimeError("Installed patch DB does not contain the requested transfer.")
            self.log(f"VERIFIED INSIDE PAK: {rider} -> {team}")
        finally:
            try: os.unlink(temp)
            except Exception: pass

    def cleanup_old(self, except_name=None):
        for name in LEGACY_TOOL_PAKS:
            if name == except_name:
                continue
            p = Path(self.paks_dir) / name
            for q in [p, p.with_suffix(".sig")]:
                if q.exists():
                    try:
                        q.unlink()
                        self.log(f"Removed old patch: {q.name}")
                    except Exception:
                        pass

    def install_current(self):
        try:
            p = self.build_patch()
            messagebox.showinfo(APP_NAME, f"Installed:\n{p}")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def remove_patch(self, silent=False):
        if not self.paks_dir:
            if not silent: messagebox.showwarning(APP_NAME, "Run setup first.")
            return
        removed = []
        for name in LEGACY_TOOL_PAKS:
            p = Path(self.paks_dir) / name
            for q in [p, p.with_suffix(".sig")]:
                if q.exists():
                    try:
                        q.unlink(); removed.append(q.name)
                    except Exception:
                        pass
        if not silent:
            messagebox.showinfo(APP_NAME, "Removed: " + (", ".join(removed) if removed else "nothing"))

    def reset_stock(self):
        try:
            if not self.main_pak:
                self.auto_setup(False)
            if self.conn:
                self.conn.close(); self.conn = None
            self.extract_stock_db(self.working_db())
            self.load_db(self.working_db())
            self.remove_patch(True)
            self.log("Reset to stock DB and removed Transfer Tool patches.")
            messagebox.showinfo(APP_NAME, "Reset complete.")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))


if __name__ == "__main__":
    App().mainloop()
