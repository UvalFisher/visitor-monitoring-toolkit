import os
import re
import numpy as np
import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import matplotlib.pyplot as plt

# ----------------------------
# Expected per-file CSV format:
# columns: metric, sensor, value
# rows include:
#   metric = "total_no_dir"
#   sensor in {"Manual","IR","BLE"}
# ----------------------------

FILENAME_RE = re.compile(r"summary_(\d{4}-\d{2}-\d{2})_(\d{4})-(\d{4})\.csv$", re.IGNORECASE)


def parse_datetime_from_filename(path):
    """
    Returns pandas.Timestamp for the start datetime inferred from:
      summary_YYYY-MM-DD_HHMM-HHMM.csv
    Fallback: file mtime
    """
    name = os.path.basename(path)
    m = FILENAME_RE.search(name)
    if m:
        date_s, hhmm_start, _hhmm_end = m.groups()
        hh = int(hhmm_start[:2])
        mm = int(hhmm_start[2:])
        return pd.Timestamp(date_s) + pd.Timedelta(hours=hh, minutes=mm)
    return pd.to_datetime(os.path.getmtime(path), unit="s")


def date_label_from_filename(fname: str) -> str:
    """Return YYYY-MM-DD from filename, else fallback to filename."""
    m = FILENAME_RE.search(fname)
    return m.group(1) if m else fname


def safe_ratio(num, den):
    if den is None or pd.isna(den) or float(den) == 0.0:
        return np.nan
    return float(num) / float(den)


def mean_abs(x):
    x = pd.to_numeric(x, errors="coerce").astype(float)
    if x.size == 0:
        return np.nan
    return float(np.nanmean(np.abs(x.values)))


def mean_pct_abs(err, manual):
    # mean(|err|/manual)*100 over manual>0
    e = pd.to_numeric(err, errors="coerce").astype(float)
    m = pd.to_numeric(manual, errors="coerce").astype(float)
    ok = (~np.isnan(e)) & (~np.isnan(m)) & (m > 0)
    if not np.any(ok):
        return np.nan
    return float(np.nanmean(np.abs(e[ok] / m[ok])) * 100.0)


def read_one_summary_csv(path):
    df = pd.read_csv(path)

    needed = {"metric", "sensor", "value"}
    if not needed.issubset(df.columns):
        raise ValueError(f"{os.path.basename(path)} missing columns. Need {needed}, got {df.columns.tolist()}")

    d = df.copy()
    d["metric"] = d["metric"].astype(str).str.strip()
    d["sensor"] = d["sensor"].astype(str).str.strip()
    d["value"] = pd.to_numeric(d["value"], errors="coerce")

    d = d[d["metric"].str.lower() == "total_no_dir"]
    if d.empty:
        raise ValueError(f"{os.path.basename(path)} has no rows with metric=total_no_dir")

    # pivot to Manual/IR/BLE
    p = d.pivot_table(index=None, columns="sensor", values="value", aggfunc="sum")

    def get_val(col):
        if col not in p.columns:
            return np.nan
        v = p[col]
        try:
            return float(v.iloc[0])
        except Exception:
            try:
                return float(v)
            except Exception:
                return np.nan

    manual = get_val("Manual")
    ir = get_val("IR")
    ble = get_val("BLE")

    dt = parse_datetime_from_filename(path)

    return {
        "file": os.path.basename(path),
        "datetime": dt,
        "Manual": manual,
        "IR": ir,
        "BLE": ble,
        "factor_IR_file": safe_ratio(manual, ir),
        "factor_BLE_file": safe_ratio(manual, ble),
    }


def compute_global_factors(rows_df):
    """
    Robust global factors:
      factor = sum(Manual) / sum(Sensor) over rows with Sensor>0 and Manual not-na
    """
    def sum_ratio(sensor_col):
        ok = rows_df[["Manual", sensor_col]].dropna()
        ok = ok[ok[sensor_col] > 0]
        if ok.empty:
            return np.nan
        return ok["Manual"].sum() / ok[sensor_col].sum()

    return {
        "factor_IR_global": sum_ratio("IR"),
        "factor_BLE_global": sum_ratio("BLE"),
    }


def compute_factor_std(rows_df, col):
    s = pd.to_numeric(rows_df[col], errors="coerce").dropna()
    if s.size <= 1:
        return np.nan
    return float(s.std(ddof=1))


def plot_total_no_dir(rows_df, factor_ir, factor_ble, factor_ir_std, factor_ble_std, use_ir=True, use_ble=True):
    d = rows_df.copy().reset_index(drop=True)

    labels = [date_label_from_filename(f) for f in d["file"]]
    x = np.arange(len(d))
    width = 0.25

    # adjusted series (may remain NaN if not used)
    d["IR_adj"] = d["IR"] * factor_ir if (use_ir and not pd.isna(factor_ir)) else np.nan
    d["BLE_adj"] = d["BLE"] * factor_ble if (use_ble and not pd.isna(factor_ble)) else np.nan

    # -----------------------------
    # Plot 1: raw totals (bars)
    # -----------------------------
    plt.figure(figsize=(11, 5))

    # We keep Manual at left, and place chosen sensors to the right.
    offsets = []
    series = []

    # Manual always shown
    offsets.append(-width)
    series.append(("Manual (raw)", d["Manual"], None))

    if use_ble:
        offsets.append(0.0)
        series.append(("BLE (raw)", d["BLE"], "orange"))

    if use_ir:
        # if BLE is not used, put IR at 0.0; else at +width
        off = (width if use_ble else 0.0)
        offsets.append(off)
        series.append(("IR (raw)", d["IR"], "tab:green"))

    for off, (lab, y, col) in zip(offsets, series):
        if col is None:
            plt.bar(x + off, y, width, label=lab)
        else:
            plt.bar(x + off, y, width, label=lab, color=col)

    plt.xlabel("Date")
    plt.ylabel("Visitors (total_no_dir)")
    plt.title("total_no_dir (raw)")
    plt.xticks(x, labels, rotation=45, ha="right")
    plt.legend()
    plt.tight_layout()

    # -----------------------------
    # Plot 2: adjusted totals (bars)
    # -----------------------------
    plt.figure(figsize=(11, 5))

    offsets = []
    series = []

    offsets.append(-width)
    series.append(("Manual (raw)", d["Manual"], None))

    if use_ble:
        label_ble = (
            f"BLE × factor ({factor_ble:.3f}±{factor_ble_std:.3f})"
            if not pd.isna(factor_ble) else "BLE × factor (n/a)"
        )
        offsets.append(0.0)
        series.append((label_ble, d["BLE_adj"], "orange"))

    if use_ir:
        label_ir = (
            f"IR × factor ({factor_ir:.3f}±{factor_ir_std:.3f})"
            if not pd.isna(factor_ir) else "IR × factor (n/a)"
        )
        off = (width if use_ble else 0.0)
        offsets.append(off)
        series.append((label_ir, d["IR_adj"], "tab:green"))

    for off, (lab, y, col) in zip(offsets, series):
        if col is None:
            plt.bar(x + off, y, width, label=lab)
        else:
            plt.bar(x + off, y, width, label=lab, color=col)

    plt.xlabel("Date")
    plt.ylabel("Visitors (total_no_dir)")
    plt.title("total_no_dir (adjusted using factors)")
    plt.xticks(x, labels, rotation=45, ha="right")
    plt.legend()
    plt.tight_layout()

    # ============================================================
    # ERROR CALCULATIONS (vs Manual)
    # ============================================================
    if use_ble:
        d["BLE_err_raw"] = d["BLE"] - d["Manual"]
        d["BLE_err_adj"] = d["BLE_adj"] - d["Manual"]
        ble_mae_raw = mean_abs(d["BLE_err_raw"])
        ble_mae_adj = mean_abs(d["BLE_err_adj"])
        ble_mape_raw = mean_pct_abs(d["BLE_err_raw"], d["Manual"])
        ble_mape_adj = mean_pct_abs(d["BLE_err_adj"], d["Manual"])
    else:
        d["BLE_err_raw"] = np.nan
        d["BLE_err_adj"] = np.nan
        ble_mae_raw = ble_mae_adj = ble_mape_raw = ble_mape_adj = np.nan

    if use_ir:
        d["IR_err_raw"] = d["IR"] - d["Manual"]
        d["IR_err_adj"] = d["IR_adj"] - d["Manual"]
        ir_mae_raw = mean_abs(d["IR_err_raw"])
        ir_mae_adj = mean_abs(d["IR_err_adj"])
        ir_mape_raw = mean_pct_abs(d["IR_err_raw"], d["Manual"])
        ir_mape_adj = mean_pct_abs(d["IR_err_adj"], d["Manual"])
    else:
        d["IR_err_raw"] = np.nan
        d["IR_err_adj"] = np.nan
        ir_mae_raw = ir_mae_adj = ir_mape_raw = ir_mape_adj = np.nan

    print("==== FACTORS (vs Manual) ====")
    if use_ir:
        print(f"IR  factor: {factor_ir:.4f} | std (per-file): {factor_ir_std:.4f}")
    if use_ble:
        print(f"BLE factor: {factor_ble:.4f} | std (per-file): {factor_ble_std:.4f}")

    print("==== ERROR SUMMARY vs Manual (total_no_dir) ====")
    if use_ble:
        print(f"BLE MAE raw: {ble_mae_raw:.2f} | BLE MAE adj: {ble_mae_adj:.2f}")
        print(f"BLE MAPE raw: {ble_mape_raw:.2f}% | BLE MAPE adj: {ble_mape_adj:.2f}%")
    if use_ir:
        print(f"IR  MAE raw: {ir_mae_raw:.2f} | IR  MAE adj: {ir_mae_adj:.2f}")
        print(f"IR  MAPE raw: {ir_mape_raw:.2f}% | IR  MAPE adj: {ir_mape_adj:.2f}%")

    # ============================================================
    # Plot 3: Absolute error per file (raw vs adjusted) — only selected sensors
    # ============================================================
    plt.figure(figsize=(12, 5))
    w = 0.22

    bars = []
    if use_ble:
        bars += [
            ("BLE |err| raw", np.abs(d["BLE_err_raw"]), "orange", f"MAE={ble_mae_raw:.1f}"),
            ("BLE |err| adj", np.abs(d["BLE_err_adj"]), "darkorange", f"MAE={ble_mae_adj:.1f}"),
        ]
    if use_ir:
        bars += [
            ("IR |err| raw", np.abs(d["IR_err_raw"]), "tab:green", f"MAE={ir_mae_raw:.1f}"),
            ("IR |err| adj", np.abs(d["IR_err_adj"]), "green", f"MAE={ir_mae_adj:.1f}"),
        ]

    if not bars:
        plt.close()
    else:
        # center bars around x
        n = len(bars)
        offsets = (np.arange(n) - (n - 1) / 2.0) * w

        for off, (lab, y, col, mae_txt) in zip(offsets, bars):
            plt.bar(x + off, y, w, label=f"{lab} ({mae_txt})", color=col)

        plt.axhline(0, linewidth=1)
        plt.xlabel("Date")
        plt.ylabel("Absolute error (|Sensor − Manual|)")
        plt.title("Absolute error per file (raw vs adjusted)")
        plt.xticks(x, labels, rotation=45, ha="right")
        plt.legend()
        plt.tight_layout()

    # ============================================================
    # Plot 4: Percent error per file (raw vs adjusted) — only selected sensors
    # ============================================================
    manual = pd.to_numeric(d["Manual"], errors="coerce").astype(float)

    with np.errstate(divide="ignore", invalid="ignore"):
        if use_ble:
            d["BLE_pct_raw"] = (d["BLE_err_raw"] / manual) * 100.0
            d["BLE_pct_adj"] = (d["BLE_err_adj"] / manual) * 100.0
        else:
            d["BLE_pct_raw"] = np.nan
            d["BLE_pct_adj"] = np.nan

        if use_ir:
            d["IR_pct_raw"] = (d["IR_err_raw"] / manual) * 100.0
            d["IR_pct_adj"] = (d["IR_err_adj"] / manual) * 100.0
        else:
            d["IR_pct_raw"] = np.nan
            d["IR_pct_adj"] = np.nan

    plt.figure(figsize=(12, 5))

    bars = []
    if use_ble:
        bars += [
            ("BLE %err raw", d["BLE_pct_raw"], "orange", f"MAPE={ble_mape_raw:.1f}%"),
            ("BLE %err adj", d["BLE_pct_adj"], "darkorange", f"MAPE={ble_mape_adj:.1f}%"),
        ]
    if use_ir:
        bars += [
            ("IR %err raw", d["IR_pct_raw"], "tab:green", f"MAPE={ir_mape_raw:.1f}%"),
            ("IR %err adj", d["IR_pct_adj"], "green", f"MAPE={ir_mape_adj:.1f}%"),
        ]

    if not bars:
        plt.close()
    else:
        n = len(bars)
        offsets = (np.arange(n) - (n - 1) / 2.0) * w

        for off, (lab, y, col, mape_txt) in zip(offsets, bars):
            plt.bar(x + off, y, w, label=f"{lab} ({mape_txt})", color=col)

        plt.axhline(0, linewidth=1)
        plt.xlabel("Date")
        plt.ylabel("Percent error ((Sensor − Manual) / Manual × 100)")
        plt.title("Percent error per file (raw vs adjusted)")
        plt.xticks(x, labels, rotation=45, ha="right")
        plt.legend()
        plt.tight_layout()

    plt.show()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Summary CSVs → factors + plots + error + factor std")
        self.geometry("1100x730")

        self.folder_var = tk.StringVar(value="")
        self.factor_mode_var = tk.StringVar(value="global")  # global or mean_of_files

        # NEW: sensor selection
        self.use_ble_var = tk.BooleanVar(value=True)
        self.use_ir_var = tk.BooleanVar(value=True)

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Button(top, text="Choose Folder…", command=self.choose_folder).pack(side="left")
        ttk.Label(top, textvariable=self.folder_var).pack(side="left", padx=10)

        opts = ttk.Frame(self)
        opts.pack(fill="x", padx=10)

        ttk.Label(opts, text="Factor mode:").pack(side="left")
        ttk.Radiobutton(
            opts, text="Global (sum Manual / sum Sensor)", value="global",
            variable=self.factor_mode_var
        ).pack(side="left", padx=8)
        ttk.Radiobutton(
            opts, text="Mean of per-file ratios", value="mean_of_files",
            variable=self.factor_mode_var
        ).pack(side="left", padx=8)

        # NEW: Sensor selection UI
        sel = ttk.Frame(self)
        sel.pack(fill="x", padx=10, pady=(6, 0))
        ttk.Label(sel, text="Sensors:").pack(side="left")
        ttk.Checkbutton(sel, text="BLE", variable=self.use_ble_var).pack(side="left", padx=8)
        ttk.Checkbutton(sel, text="IR", variable=self.use_ir_var).pack(side="left", padx=8)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=10)

        ttk.Button(btns, text="Load + Compute", command=self.load_and_compute).pack(side="left")
        ttk.Button(btns, text="Plot (raw + adjusted + error)", command=self.plot).pack(side="left", padx=8)
        ttk.Button(btns, text="Export combined table CSV…", command=self.export_table).pack(side="left", padx=8)

        cols = ("date", "Manual", "IR", "BLE", "factor_IR_file", "factor_BLE_file", "file")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c)
            if c == "file":
                self.tree.column(c, width=380, anchor="w")
            elif c == "date":
                self.tree.column(c, width=120, anchor="center")
            else:
                self.tree.column(c, width=130, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        self.summary_lbl = ttk.Label(bottom, text="Choose a folder with summary_*.csv files.")
        self.summary_lbl.pack(side="left")

        self.rows_df = None
        self.factor_ir = np.nan
        self.factor_ble = np.nan
        self.factor_ir_std = np.nan
        self.factor_ble_std = np.nan

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Select folder with summary CSV files")
        if folder:
            self.folder_var.set(folder)

    def _validate_sensor_selection(self):
        use_ble = bool(self.use_ble_var.get())
        use_ir = bool(self.use_ir_var.get())
        if not use_ble and not use_ir:
            messagebox.showerror("No sensors selected", "Please select BLE and/or IR.")
            return False
        return True

    def load_and_compute(self):
        if not self._validate_sensor_selection():
            return

        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Folder missing", "Please choose a valid folder.")
            return

        csvs = [os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(".csv")]
        if not csvs:
            messagebox.showerror("No CSVs", "No .csv files found in the selected folder.")
            return

        rows, bad = [], []
        for p in sorted(csvs):
            try:
                rows.append(read_one_summary_csv(p))
            except Exception as e:
                bad.append((os.path.basename(p), str(e)))

        if not rows:
            messagebox.showerror(
                "No valid summary files",
                "None of the CSVs matched the expected format.\n\n" +
                "\n".join([f"{fn}: {err}" for fn, err in bad[:10]])
            )
            return

        df = pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)
        self.rows_df = df

        use_ble = bool(self.use_ble_var.get())
        use_ir = bool(self.use_ir_var.get())

        # factors
        if self.factor_mode_var.get() == "global":
            f = compute_global_factors(df)
            self.factor_ir = f["factor_IR_global"] if use_ir else np.nan
            self.factor_ble = f["factor_BLE_global"] if use_ble else np.nan
        else:
            self.factor_ir = (df["factor_IR_file"].dropna().mean()
                              if (use_ir and df["factor_IR_file"].dropna().size) else np.nan)
            self.factor_ble = (df["factor_BLE_file"].dropna().mean()
                               if (use_ble and df["factor_BLE_file"].dropna().size) else np.nan)

        # factor std (per-file variability)
        self.factor_ir_std = compute_factor_std(df, "factor_IR_file") if use_ir else np.nan
        self.factor_ble_std = compute_factor_std(df, "factor_BLE_file") if use_ble else np.nan

        # refresh table
        for item in self.tree.get_children():
            self.tree.delete(item)

        for _, r in df.iterrows():
            self.tree.insert("", "end", values=(
                date_label_from_filename(r["file"]),
                f'{r["Manual"]:.0f}' if not pd.isna(r["Manual"]) else "",
                f'{r["IR"]:.0f}' if not pd.isna(r["IR"]) else "",
                f'{r["BLE"]:.0f}' if not pd.isna(r["BLE"]) else "",
                f'{r["factor_IR_file"]:.3f}' if not pd.isna(r["factor_IR_file"]) else "",
                f'{r["factor_BLE_file"]:.3f}' if not pd.isna(r["factor_BLE_file"]) else "",
                r["file"],
            ))

        # summary label
        parts = [f"Loaded {len(df)} file(s)"]
        if use_ir:
            parts.append(f"IR factor = {self.factor_ir:.3f} ± {self.factor_ir_std:.3f}")
        if use_ble:
            parts.append(f"BLE factor = {self.factor_ble:.3f} ± {self.factor_ble_std:.3f}")
        if bad:
            parts.append(f"(Skipped {len(bad)} file(s))")
        self.summary_lbl.config(text=" | ".join(parts))

        if bad:
            messagebox.showwarning(
                "Some files skipped",
                "Some CSVs were skipped because they didn't match the expected format.\n\n" +
                "\n".join([f"{fn}: {err}" for fn, err in bad[:12]])
            )

    def plot(self):
        if not self._validate_sensor_selection():
            return
        if self.rows_df is None or self.rows_df.empty:
            messagebox.showerror("Nothing loaded", "Click 'Load + Compute' first.")
            return

        use_ble = bool(self.use_ble_var.get())
        use_ir = bool(self.use_ir_var.get())

        plot_total_no_dir(
            self.rows_df,
            self.factor_ir, self.factor_ble,
            self.factor_ir_std, self.factor_ble_std,
            use_ir=use_ir,
            use_ble=use_ble
        )

    def export_table(self):
        if not self._validate_sensor_selection():
            return
        if self.rows_df is None or self.rows_df.empty:
            messagebox.showerror("Nothing loaded", "Click 'Load + Compute' first.")
            return

        out_path = filedialog.asksaveasfilename(
            title="Save combined table as CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")]
        )
        if not out_path:
            return

        use_ble = bool(self.use_ble_var.get())
        use_ir = bool(self.use_ir_var.get())

        d = self.rows_df.copy()
        d["factor_IR_used"] = self.factor_ir if use_ir else np.nan
        d["factor_BLE_used"] = self.factor_ble if use_ble else np.nan
        d["factor_IR_std"] = self.factor_ir_std if use_ir else np.nan
        d["factor_BLE_std"] = self.factor_ble_std if use_ble else np.nan

        d["IR_adj"] = d["IR"] * self.factor_ir if (use_ir and not pd.isna(self.factor_ir)) else np.nan
        d["BLE_adj"] = d["BLE"] * self.factor_ble if (use_ble and not pd.isna(self.factor_ble)) else np.nan

        # raw errors
        d["BLE_err_raw"] = (d["BLE"] - d["Manual"]) if use_ble else np.nan
        d["IR_err_raw"] = (d["IR"] - d["Manual"]) if use_ir else np.nan

        # adjusted errors
        d["BLE_err_adj"] = (d["BLE_adj"] - d["Manual"]) if use_ble else np.nan
        d["IR_err_adj"] = (d["IR_adj"] - d["Manual"]) if use_ir else np.nan

        d.to_csv(out_path, index=False)
        messagebox.showinfo("Saved", f"Saved:\n{out_path}")


if __name__ == "__main__":
    App().mainloop()