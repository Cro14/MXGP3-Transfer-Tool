import os
import shutil
import sqlite3
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "MXGP3 Transfer Tool"
VERSION = "0.1"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry("760x520")
        self.minsize(720, 500)
        self.conn = None
        self.db_path = None
        self.riders = {}
        self.teams = {}
        self._build_ui()

    def _build_ui(self):
        ttk.Label(self, text="MXGP3 TRANSFER TOOL", font=("Segoe UI", 20, "bold")).pack(pady=(18, 2))
        ttk.Label(self, text="v0.1 TEST BUILD — Cro14 / Jeffrey Helings").pack(pady=(0, 14))

        dbf = ttk.LabelFrame(self, text="Database")
        dbf.pack(fill="x", padx=18, pady=8)
        self.db_label = ttk.Label(dbf, text="No DB.sqlite3 selected")
        self.db_label.pack(side="left", fill="x", expand=True, padx=10, pady=10)
        ttk.Button(dbf, text="Open DB.sqlite3", command=self.open_db).pack(side="right", padx=10, pady=10)

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

        ttk.Button(tf, text="TRANSFER RIDER", command=self.transfer).grid(row=4, column=0, columnspan=2, pady=14, ipadx=30, ipady=5)

        sf = ttk.LabelFrame(self, text="Safety")
        sf.pack(fill="x", padx=18, pady=8)
        ttk.Button(sf, text="Create Backup", command=self.backup_manual).pack(side="left", padx=10, pady=10)
        ttk.Button(sf, text="Restore Backup", command=self.restore_backup).pack(side="left", padx=10, pady=10)

        lf = ttk.LabelFrame(self, text="Log")
        lf.pack(fill="both", expand=True, padx=18, pady=(8, 18))
        self.logbox = tk.Text(lf, height=8, state="disabled", font=("Consolas", 9))
        self.logbox.pack(fill="both", expand=True, padx=8, pady=8)
        self.log("Ready. Open the extracted MXGP3 DB.sqlite3.")

    def log(self, text):
        self.logbox.config(state="normal")
        self.logbox.insert("end", text + "\n")
        self.logbox.see("end")
        self.logbox.config(state="disabled")

    def open_db(self):
        path = filedialog.askopenfilename(title="Select MXGP3 DB.sqlite3", filetypes=[("SQLite database", "*.sqlite3"), ("All files", "*.*")])
        if not path:
            return
        try:
            c = sqlite3.connect(path)
            required = {"Pilots", "Teams", "PilotsInRosters"}
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = required - tables
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
            self.log(f"Loaded: {path}")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def load_riders(self):
        if not self.conn:
            return
        cat = self.class_box.get()
        rows = self.conn.execute(
            """SELECT P.Key, P.Number, P.Teams_Key
               FROM Pilots P JOIN Teams T ON P.Teams_Key=T.Key
               WHERE P.IsStrippedFromDB=0 AND P.Teams_Key IS NOT NULL AND T.Categories_Key=?
               ORDER BY P.Key""", (cat,)
        ).fetchall()
        self.riders = {}
        values = []
        for key, number, team in rows:
            label = f"#{number}  {key.split('-',1)[-1]}"
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
        key, old_team = item
        cat = self.class_box.get()
        rows = self.conn.execute("SELECT Key FROM Teams WHERE Categories_Key=? ORDER BY Ordering", (cat,)).fetchall()
        self.teams = {}
        names = []
        for (team_key,) in rows:
            short = team_key[len(cat)+1:] if team_key.startswith(cat + "-") else team_key
            self.teams[short] = team_key
            names.append(short)
        self.team_box["values"] = names
        self.current_team.config(text=old_team)
        old_short = old_team[len(cat)+1:] if old_team.startswith(cat + "-") else old_team
        if old_short in self.teams:
            self.team_box.set(old_short)

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
        bak = filedialog.askopenfilename(title="Select backup", filetypes=[("Backup", "*.bak"), ("All files", "*.*")])
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

    def transfer(self):
        if not self.conn:
            messagebox.showwarning(APP_NAME, "Load DB.sqlite3 first.")
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
            messagebox.showinfo(APP_NAME, "Transfer saved.\n\nv0.1 changes team assignment only; bike/gear graphics are not synchronized yet.")
            self.load_riders()
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass
            messagebox.showerror(APP_NAME, str(e))

if __name__ == "__main__":
    App().mainloop()
