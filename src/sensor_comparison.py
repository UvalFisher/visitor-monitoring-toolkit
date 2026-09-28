import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import to_rgba
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox

# ==========================================================
#                   CSV SAFE READ
# ==========================================================
def read_csv_safely(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="latin1")

# ==========================================================
#           STANDARDIZATION FUNCTIONS PER SENSOR
# ==========================================================

def standardize_camera_specific(df):
    d = pd.DataFrame({
        "timestamp": pd.to_datetime(df["Time"], dayfirst=True, errors="coerce"),
        "count": pd.to_numeric(df["Visitors"], errors="coerce").fillna(0.0)
    }).dropna(subset=["timestamp"])
    return d

def standardize_manual_specific(df):
    ts = pd.to_datetime(
        df["Date"].astype(str) + " " + df["Time"].astype(str),
        dayfirst=True, errors="coerce"
    )
    d = pd.DataFrame({
        "timestamp": ts,
        "direction": df["direction"].astype(str).str.upper().str.strip(),
        "count": pd.to_numeric(df["Value"], errors="coerce").fillna(0.0)
    }).dropna(subset=["timestamp", "direction"])
    d = d[d["direction"].isin(["A", "B"])]
    return d

def standardize_ble_specific(df):
    """
    Standardize BLE to columns: timestamp, direction, count.

    Supports 3 possible formats:

    (A) device_visits format
        Required:
          - 'direction'
        Timestamp chosen by priority:
          1) 'global_start'
          2) min(first_timestamp_A_visit, first_timestamp_B_visit)
        Each row = one VISIT -> count = 1

    (B) per_device format
        Required:
          - 'first_timestamp_A_device'
          - 'first_timestamp_B_device'
          - 'direction'
        Timestamp = min(first A/B)
        Each row = one device -> count = 1

    (C) old format
        Required:
          - 'first_timestamp'
          - 'direction'
        Each row = one record -> count = 1
    """

    # --- A) device_visits format ---
    cols_visits = {"direction"}
    has_visits_ts = ("global_start" in df.columns) or (
        ("first_timestamp_A_visit" in df.columns) and ("first_timestamp_B_visit" in df.columns)
    )

    if cols_visits.issubset(df.columns) and has_visits_ts:
        dircol = df["direction"].astype(str).str.upper().str.strip()
        keep = dircol.isin(["A", "B"])

        if "global_start" in df.columns:
            ts = pd.to_datetime(df["global_start"], dayfirst=True, errors="coerce")
        else:
            ts_A = pd.to_datetime(df["first_timestamp_A_visit"], dayfirst=True, errors="coerce")
            ts_B = pd.to_datetime(df["first_timestamp_B_visit"], dayfirst=True, errors="coerce")
            ts = pd.concat([ts_A, ts_B], axis=1).min(axis=1)

        d = pd.DataFrame({
            "timestamp": ts,
            "direction": dircol,
            "count": 1.0
        })

        d = d[keep].dropna(subset=["timestamp", "direction"])
        return d

    # --- B) previous per_device format ---
    cols_new = {"first_timestamp_A_device", "first_timestamp_B_device", "direction"}
    if cols_new.issubset(df.columns):
        ts_A = pd.to_datetime(df["first_timestamp_A_device"], dayfirst=True, errors="coerce")
        ts_B = pd.to_datetime(df["first_timestamp_B_device"], dayfirst=True, errors="coerce")
        ts = pd.concat([ts_A, ts_B], axis=1).min(axis=1)

        dircol = df["direction"].astype(str).str.upper().str.strip()
        d = pd.DataFrame({
            "timestamp": ts,
            "direction": dircol,
            "count": 1.0
        }).dropna(subset=["timestamp", "direction"])
        d = d[d["direction"].isin(["A", "B"])]
        return d

    # --- C) old format ---
    cols_old = {"first_timestamp", "direction"}
    if cols_old.issubset(df.columns):
        ts = pd.to_datetime(df["first_timestamp"], dayfirst=True, errors="coerce")
        dircol = df["direction"].astype(str).str.upper().str.strip()
        d = pd.DataFrame({
            "timestamp": ts,
            "direction": dircol,
            "count": 1.0
        }).dropna(subset=["timestamp", "direction"])
        d = d[d["direction"].isin(["A", "B"])]
        return d

    raise ValueError(
        "BLE CSV format not recognized.\n"
        "Expected one of:\n"
        "A) device_visits format with direction + (global_start OR first_timestamp_A_visit & first_timestamp_B_visit)\n"
        "B) per_device format with first_timestamp_A_device, first_timestamp_B_device, direction\n"
        "C) old format with first_timestamp, direction"
    )

def parse_mixed_datetime(series, prefer_dayfirst=True):
    """
    Robust datetime parser for mixed formats, for example:
      19/05/2026 00:00:00
      5/20/2026 5:00:00 PM
      20/05/2026 17:00
    """
    ser = series.astype(str).str.strip()

    # First try with the requested convention.
    out = pd.to_datetime(ser, dayfirst=prefer_dayfirst, errors="coerce")

    # Then try the opposite convention only for failed rows.
    missing = out.isna()
    if missing.any():
        out2 = pd.to_datetime(ser[missing], dayfirst=not prefer_dayfirst, errors="coerce")
        out.loc[missing] = out2

    return out


def try_standardize_ir_directional(df):
    """
    IR directional file.

    Supports both:
    OLD format:
      Date | Time Gap | Sensor Name | Visitors
      where Time Gap can be only "05:00 - 06:00"

    NEW format:
      Date can be a full timestamp, for example "19/05/2026 00:00:00"
      Time Gap can include full datetime range, for example:
      "5/20/2026 5:00:00 PM - 5/20/2026 6:00:00 PM"

    Required columns, case-insensitive:
      - Sensor Name
      - Time Gap
      - Visitors
    Optional:
      - Date
    """
    lower = [c.lower().strip() for c in df.columns]
    mapping = dict(zip(df.columns, lower))
    dfr = df.rename(columns=mapping)

    required = {"sensor name", "time gap", "visitors"}
    if not required.issubset(set(dfr.columns)):
        raise ValueError("IR file must contain 'Sensor Name', 'Time Gap', and 'Visitors'.")

    time_gap = dfr["time gap"].astype(str).str.strip()
    start_part = time_gap.str.split(r"\s+-\s+", n=1, expand=True)[0].str.strip()

    # If Time Gap already contains a date, parse it directly.
    ts_from_gap = parse_mixed_datetime(start_part, prefer_dayfirst=True)

    # If Time Gap is only a clock range, combine it with Date.
    ts = ts_from_gap.copy()
    if "date" in dfr.columns:
        failed = ts.isna()
        if failed.any():
            date_part = dfr.loc[failed, "date"].astype(str).str.strip()

            # When Date is a full timestamp, keep only the date part before combining.
            date_only = parse_mixed_datetime(date_part, prefer_dayfirst=True).dt.strftime("%d/%m/%Y")
            combined = date_only + " " + start_part.loc[failed]
            ts.loc[failed] = parse_mixed_datetime(combined, prefer_dayfirst=True)

        # Last fallback: if Time Gap cannot be parsed at all, use Date itself.
        failed = ts.isna()
        if failed.any():
            ts.loc[failed] = parse_mixed_datetime(dfr.loc[failed, "date"], prefer_dayfirst=True)

    counts = pd.to_numeric(dfr["visitors"], errors="coerce").fillna(0.0)

    def dir_from_name(name):
        if name is None:
            return None
        s = str(name).strip().upper()
        if not s:
            return None
        if s[0] in ("A", "B"):
            return s[0]
        if s[-1] in ("A", "B"):
            return s[-1]
        for ch in s:
            if ch in ("A", "B"):
                return ch
        return None

    directions = dfr["sensor name"].map(dir_from_name)

    d = pd.DataFrame({
        "timestamp": ts,
        "direction": directions,
        "count": counts
    }).dropna(subset=["timestamp", "direction"])

    d = d[d["direction"].isin(["A", "B"])]
    return d


def standardize_pressure_counter_specific(path):
    """
    Pressure counter CSV.

    Supports the exported format like:
      Period,19th May 2026 -> 19th May 2026,
      ,,
      Time,B,A
      19/05/2026 00:00,0,0

    Also supports a normal CSV with columns:
      Time, B, A
    """
    # Try normal CSV first.
    df0 = read_csv_safely(path)

    # If the real header is hidden in row 3, read again with skiprows=2.
    normalized_cols = {str(c).strip().lower() for c in df0.columns}
    if not {"time", "a", "b"}.issubset(normalized_cols):
        try:
            df = pd.read_csv(path, skiprows=2, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(path, skiprows=2, encoding="latin1")
    else:
        df = df0

    df.columns = [str(c).strip() for c in df.columns]
    colmap = {c.lower(): c for c in df.columns}

    if not {"time", "a", "b"}.issubset(set(colmap.keys())):
        raise ValueError("Pressure counter CSV must contain columns: Time, A, B.")

    ts = parse_mixed_datetime(df[colmap["time"]], prefer_dayfirst=True)

    rows = []
    for direction in ["A", "B"]:
        counts = pd.to_numeric(df[colmap[direction.lower()]], errors="coerce").fillna(0.0)
        tmp = pd.DataFrame({
            "timestamp": ts,
            "direction": direction,
            "count": counts
        })
        rows.append(tmp)

    d = pd.concat(rows, ignore_index=True).dropna(subset=["timestamp", "direction"])
    d = d[d["direction"].isin(["A", "B"])]
    return d

# ==========================================================
#               AGGREGATION / PLOTTING HELPERS
# ==========================================================

def hourly_bins(df, directional=False):
    dd = df.copy()
    dd["hour"] = dd["timestamp"].dt.floor("h")
    if directional:
        return dd.groupby(["hour", "direction"], as_index=False)["count"].sum()
    else:
        return dd.groupby(["hour"], as_index=False)["count"].sum()

def total_by_direction(df):
    if df.empty:
        return {"A": 0.0, "B": 0.0}
    g = df.groupby("direction")["count"].sum()
    return {"A": float(g.get("A", 0.0)), "B": float(g.get("B", 0.0))}

def add_bar_labels(ax):
    for p in ax.patches:
        h = p.get_height()
        if np.isfinite(h) and h != 0:
            ax.annotate(f"{h:.0f}",
                        (p.get_x() + p.get_width()/2, h),
                        ha="center", va="bottom",
                        xytext=(0, 3), textcoords="offset points",
                        fontsize=9)

def add_line_point_labels(ax, xvals, yvals):
    for xv, yv in zip(xvals, yvals):
        if np.isfinite(yv) and yv != 0:
            ax.annotate(f"{yv:.0f}",
                        (xv, yv),
                        ha="center", va="bottom",
                        xytext=(0, 4), textcoords="offset points",
                        fontsize=8)

def format_hour_axis(ax, start_dt, end_dt):
    ax.set_xlim(start_dt, end_dt)
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %H:%M'))
    for label in ax.get_xticklabels():
        label.set_rotation(45)
        label.set_ha('right')

# ==========================================================
#                       COLORS / ORDER
# ==========================================================
SENSOR_COLORS = {}  # dynamic cache

def get_sensor_color(sensor, sensor_order):
    """
    Stable color by sensor_order, regardless of whether IR is included.
    """
    if sensor in SENSOR_COLORS:
        return SENSOR_COLORS[sensor]
    prop_cycle = plt.rcParams['axes.prop_cycle'].by_key().get('color', [])
    idx = sensor_order.index(sensor) if sensor in sensor_order else len(SENSOR_COLORS)
    color = prop_cycle[idx % max(1, len(prop_cycle))] if prop_cycle else None
    SENSOR_COLORS[sensor] = color
    return color

# ==========================================================
#                       MAIN LOGIC
# ==========================================================

def run(manual_path, ble_path, date_str, start, end, outbase=None,
        use_ir=False, ir_path=None,
        use_pressure=False, pressure_path=None):

    if not manual_path or not os.path.isfile(manual_path):
        raise ValueError("Manual CSV path is missing or invalid.")
    if not ble_path or not os.path.isfile(ble_path):
        raise ValueError("BLE CSV path is missing or invalid.")

    if use_ir:
        if (not ir_path) or (not os.path.isfile(ir_path)):
            raise ValueError("IR is enabled but IR XLSX path is missing/invalid.")

    if use_pressure:
        if (not pressure_path) or (not os.path.isfile(pressure_path)):
            raise ValueError("Pressure counter is enabled but CSV path is missing/invalid.")

    manual_df = read_csv_safely(manual_path)
    ble_df = read_csv_safely(ble_path)

    man_std = standardize_manual_specific(manual_df)
    ble_std = standardize_ble_specific(ble_df)

    if use_ir:
        ir_df = pd.read_excel(ir_path)
        ir_std = try_standardize_ir_directional(ir_df)
    else:
        ir_std = None

    if use_pressure:
        pressure_std = standardize_pressure_counter_specific(pressure_path)
    else:
        pressure_std = None

    d = datetime.strptime(date_str, "%d/%m/%Y").date()
    start_dt = datetime.strptime(f"{d.strftime('%Y-%m-%d')} {start}", "%Y-%m-%d %H:%M")
    end_dt   = datetime.strptime(f"{d.strftime('%Y-%m-%d')} {end}",   "%Y-%m-%d %H:%M")

    man_f = man_std[(man_std["timestamp"] >= start_dt) & (man_std["timestamp"] <= end_dt)].copy()
    ble_f = ble_std[(ble_std["timestamp"] >= start_dt) & (ble_std["timestamp"] <= end_dt)].copy()
    if use_ir:
        ir_f = ir_std[(ir_std["timestamp"] >= start_dt) & (ir_std["timestamp"] <= end_dt)].copy()
    if use_pressure:
        pressure_f = pressure_std[(pressure_std["timestamp"] >= start_dt) & (pressure_std["timestamp"] <= end_dt)].copy()

    # active sensors
    sensors = ["Manual", "BLE"] + (["IR"] if use_ir else []) + (["Pressure"] if use_pressure else [])
    sensor_order = ["Manual", "BLE", "IR", "Pressure"]  # fixed to keep consistent colors

    # ---------- Totals (no direction) ----------
    totals_no_dir = {
        "Manual": float(man_f["count"].sum()),
        "BLE": float(ble_f["count"].sum()),
    }
    if use_ir:
        totals_no_dir["IR"] = float(ir_f["count"].sum())
    if use_pressure:
        totals_no_dir["Pressure"] = float(pressure_f["count"].sum())

    hourlies_no_dir = {
        "Manual": hourly_bins(man_f.assign(direction=None).drop(columns=["direction"]), False),
        "BLE": hourly_bins(ble_f.assign(direction=None).drop(columns=["direction"]), False),
    }
    if use_ir:
        hourlies_no_dir["IR"] = hourly_bins(ir_f.assign(direction=None).drop(columns=["direction"]), False)
    if use_pressure:
        hourlies_no_dir["Pressure"] = hourly_bins(pressure_f.assign(direction=None).drop(columns=["direction"]), False)

    # ---------- Totals with direction ----------
    per_sensor_dir_totals = {
        "Manual": total_by_direction(man_f),
        "BLE": total_by_direction(ble_f),
    }
    per_sensor_hourly_dir = {
        "Manual": hourly_bins(man_f, True),
        "BLE": hourly_bins(ble_f, True),
    }
    if use_ir:
        per_sensor_dir_totals["IR"] = total_by_direction(ir_f)
        per_sensor_hourly_dir["IR"] = hourly_bins(ir_f, True)
    if use_pressure:
        per_sensor_dir_totals["Pressure"] = total_by_direction(pressure_f)
        per_sensor_hourly_dir["Pressure"] = hourly_bins(pressure_f, True)

    per_sensor_pct = {}
    for s in sensors:
        ab = per_sensor_dir_totals.get(s, {"A": 0.0, "B": 0.0})
        a, b = ab.get("A", 0.0), ab.get("B", 0.0)
        den = a + b
        per_sensor_pct[s] = {
            "A": (a/den*100.0) if den > 0 else np.nan,
            "B": (b/den*100.0) if den > 0 else np.nan
        }

    tag = f"{d.strftime('%Y-%m-%d')}_{start.replace(':','')}-{end.replace(':','')}"
    suffix_parts = ["manual", "ble"]
    if use_ir:
        suffix_parts.append("ir")
    if use_pressure:
        suffix_parts.append("pressure")
    suffix = "_".join(suffix_parts)
    outdir = os.path.join(outbase or os.getcwd(), f"sensor_comparison_{suffix}_{tag}")
    os.makedirs(outdir, exist_ok=True)

    # ==========================================================
    # 1) Total no direction (bar)
    # ==========================================================
    fig, ax = plt.subplots()
    xlabels = sensors
    x = np.arange(len(xlabels))
    vals = [totals_no_dir[k] for k in xlabels]
    bars = ax.bar(x, vals)
    for i, label in enumerate(xlabels):
        bars[i].set_color(get_sensor_color(label, sensor_order))
    ax.set_xticks(x, xlabels, rotation=15)
    ax.set_ylabel("Total count (A+B)")
    ax.set_title(f"Total counts (no direction) — {tag}")
    add_bar_labels(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, f"1_total_no_direction_{suffix}_{tag}.png"),
                dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ==========================================================
    # 2) Hourly no direction (lines)
    # ==========================================================
    fig, ax = plt.subplots()
    for label in sensors:
        dfh = hourlies_no_dir.get(label)
        if dfh is None or dfh.empty:
            continue
        color = get_sensor_color(label, sensor_order)
        ax.plot(dfh["hour"], dfh["count"], label=label,
                marker="o", linestyle="-", color=color)
        add_line_point_labels(ax, dfh["hour"], dfh["count"])
    format_hour_axis(ax, start_dt, end_dt)
    ax.set_xlabel("Hour")
    ax.set_ylabel("Count (A+B)")
    ax.set_title(f"Hourly totals (no direction) — {tag}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, f"2_hourly_no_direction_{suffix}_{tag}.png"),
                dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ==========================================================
    # 3) Totals with direction (bars: A dashed outline, B filled)
    # ==========================================================
    fig, ax = plt.subplots()
    x = np.arange(len(sensors))
    w = 0.35
    for i, s in enumerate(sensors):
        col = get_sensor_color(s, sensor_order)
        a_val = per_sensor_dir_totals[s]["A"]
        b_val = per_sensor_dir_totals[s]["B"]
        ax.bar(i - w/2, a_val, w,
               edgecolor=col, facecolor='none',
               linestyle='--', linewidth=2)
        ax.bar(i + w/2, b_val, w, color=col)
    ax.set_xticks(x, sensors, rotation=15)
    ax.set_ylabel("Total count")
    ax.set_title(f"Total counts by direction — {tag}")

    handles, labels = [], []
    for s in sensors:
        col = get_sensor_color(s, sensor_order)
        la, = ax.plot([], [], linestyle="--", color=col, label=f"{s} A")
        lb, = ax.plot([], [], linestyle="-", color=col, label=f"{s} B")
        handles.extend([la, lb])
        labels.extend([f"{s} A", f"{s} B"])
    ax.legend(
        handles,
        labels,
        ncols=2,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12)
    )
    add_bar_labels(ax)
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    fig.savefig(os.path.join(outdir, f"3_total_with_direction_{suffix}_{tag}.png"),
                dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ==========================================================
    # 4A) Hourly Direction A
    # ==========================================================
    fig, ax = plt.subplots()
    for sensor in sensors:
        dfh = per_sensor_hourly_dir.get(sensor)
        if dfh is None or dfh.empty:
            continue
        piv = dfh.pivot_table(index="hour", columns="direction", values="count", aggfunc="sum").fillna(0.0)
        col = get_sensor_color(sensor, sensor_order)
        if "A" in piv:
            ax.plot(piv.index, piv["A"], linestyle="--", marker="o", color=col, label=sensor)
            add_line_point_labels(ax, piv.index, piv["A"])
    format_hour_axis(ax, start_dt, end_dt)
    ax.set_xlabel("Hour")
    ax.set_ylabel("Count")
    ax.set_title(f"Hourly — Direction A (A dashed) — {tag}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, f"4A_hourly_direction_A_{suffix}_{tag}.png"),
                dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ==========================================================
    # 4B) Hourly Direction B
    # ==========================================================
    fig, ax = plt.subplots()
    for sensor in sensors:
        dfh = per_sensor_hourly_dir.get(sensor)
        if dfh is None or dfh.empty:
            continue
        piv = dfh.pivot_table(index="hour", columns="direction", values="count", aggfunc="sum").fillna(0.0)
        col = get_sensor_color(sensor, sensor_order)
        if "B" in piv:
            ax.plot(piv.index, piv["B"], linestyle="-", marker="o", color=col, label=sensor)
            add_line_point_labels(ax, piv.index, piv["B"])
    format_hour_axis(ax, start_dt, end_dt)
    ax.set_xlabel("Hour")
    ax.set_ylabel("Count")
    ax.set_title(f"Hourly — Direction B — {tag}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, f"4B_hourly_direction_B_{suffix}_{tag}.png"),
                dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ==========================================================
    # 5) Pies: %A vs %B per selected sensor(s)
    # ==========================================================
    n = len(sensors)
    fig, axes = plt.subplots(1, n, figsize=(4*n, 4))
    if n == 1:
        axes = [axes]

    for ax, s in zip(axes, sensors):
        pct = per_sensor_pct.get(s, {"A": np.nan, "B": np.nan})
        base = to_rgba(get_sensor_color(s, sensor_order))
        Acol = (base[0], base[1], base[2], 0.25)
        Bcol = (base[0], base[1], base[2], 1.0)
        vals = [
            pct["A"] if np.isfinite(pct["A"]) else 0.0,
            pct["B"] if np.isfinite(pct["B"]) else 0.0
        ]
        labels = [f"A {vals[0]:.1f}%", f"B {vals[1]:.1f}%"]
        ax.pie(vals, labels=labels, startangle=90,
               colors=[Acol, Bcol],
               wedgeprops={"edgecolor": base, "linewidth": 1})
        ax.set_title(s)

    fig.suptitle(f"%A vs %B per sensor — {tag}")
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, f"5_pies_{suffix}_{tag}.png"),
                dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ==========================================================
    # Summary CSV
    # ==========================================================
    rows = []
    for s in sensors:
        rows.append({"metric": "total_no_dir", "sensor": s, "value": totals_no_dir[s]})
    for s in sensors:
        ab = per_sensor_dir_totals[s]
        rows.append({"metric": "total_dir_A", "sensor": s, "value": ab["A"]})
        rows.append({"metric": "total_dir_B", "sensor": s, "value": ab["B"]})
    for s in sensors:
        pct = per_sensor_pct[s]
        rows.append({"metric": "percent_A", "sensor": s, "value": pct["A"]})
        rows.append({"metric": "percent_B", "sensor": s, "value": pct["B"]})

    pd.DataFrame(rows).to_csv(os.path.join(outdir, f"summary_{suffix}_{tag}.csv"), index=False)

    messagebox.showinfo("Done", f"Saved outputs to:\n{outdir}")

# ==========================================================
#                           UI
# ==========================================================
def browse(entry, filetypes):
    p = filedialog.askopenfilename(filetypes=filetypes)
    if p:
        entry.delete(0, tk.END)
        entry.insert(0, p)

def main():
    root = tk.Tk()
    root.title("Compare Sensors (Manual / BLE / optional IR / optional Pressure)")
    frm = tk.Frame(root, padx=10, pady=10)
    frm.pack(fill="both", expand=True)

    # Manual
    tk.Label(frm, text="Manual CSV:").grid(row=0, column=0, sticky="e")
    e_manual = tk.Entry(frm, width=60)
    e_manual.grid(row=0, column=1, padx=5)
    tk.Button(frm, text="Browse", command=lambda: browse(e_manual, [("CSV", "*.csv")])).grid(row=0, column=2)

    # BLE
    tk.Label(frm, text="BLE CSV (device_visits):").grid(row=1, column=0, sticky="e")
    e_ble = tk.Entry(frm, width=60)
    e_ble.grid(row=1, column=1, padx=5)
    tk.Button(frm, text="Browse", command=lambda: browse(e_ble, [("CSV", "*.csv")])).grid(row=1, column=2)

    # Use IR toggle + IR path
    use_ir_var = tk.BooleanVar(value=True)

    def update_ir_state(*_):
        state = "normal" if use_ir_var.get() else "disabled"
        e_ir.config(state=state)
        b_ir.config(state=state)

    tk.Checkbutton(frm, text="Include IR (Excel)", variable=use_ir_var,
                   command=update_ir_state).grid(row=2, column=1, sticky="w", padx=5)

    tk.Label(frm, text="IR XLSX:").grid(row=3, column=0, sticky="e")
    e_ir = tk.Entry(frm, width=60)
    e_ir.grid(row=3, column=1, padx=5)
    b_ir = tk.Button(frm, text="Browse", command=lambda: browse(e_ir, [("Excel", "*.xlsx;*.xls")]))
    b_ir.grid(row=3, column=2)

    # Use pressure counter toggle + path
    use_pressure_var = tk.BooleanVar(value=False)

    def update_pressure_state(*_):
        state = "normal" if use_pressure_var.get() else "disabled"
        e_pressure.config(state=state)
        b_pressure.config(state=state)

    tk.Checkbutton(frm, text="Include pressure counter (CSV)", variable=use_pressure_var,
                   command=update_pressure_state).grid(row=4, column=1, sticky="w", padx=5)

    tk.Label(frm, text="Pressure CSV:").grid(row=5, column=0, sticky="e")
    e_pressure = tk.Entry(frm, width=60)
    e_pressure.grid(row=5, column=1, padx=5)
    b_pressure = tk.Button(frm, text="Browse", command=lambda: browse(e_pressure, [("CSV", "*.csv")]))
    b_pressure.grid(row=5, column=2)

    # Date / time range
    tk.Label(frm, text="Date (dd/mm/YYYY):").grid(row=6, column=0, sticky="e")
    e_date = tk.Entry(frm, width=20)
    e_date.insert(0, "05/10/2025")
    e_date.grid(row=6, column=1, sticky="w", padx=5)

    tk.Label(frm, text="Start (HH:MM):").grid(row=7, column=0, sticky="e")
    e_start = tk.Entry(frm, width=10)
    e_start.insert(0, "00:00")
    e_start.grid(row=7, column=1, sticky="w", padx=5)

    tk.Label(frm, text="End (HH:MM):").grid(row=8, column=0, sticky="e")
    e_end = tk.Entry(frm, width=10)
    e_end.insert(0, "23:59")
    e_end.grid(row=8, column=1, sticky="w", padx=5)

    # Initial optional sensor states
    update_ir_state()
    update_pressure_state()

    def on_run():
        try:
            base = os.path.dirname(e_manual.get()) or os.getcwd()
            run(
                manual_path=e_manual.get().strip(),
                ble_path=e_ble.get().strip(),
                date_str=e_date.get().strip(),
                start=e_start.get().strip(),
                end=e_end.get().strip(),
                outbase=base,
                use_ir=use_ir_var.get(),
                ir_path=e_ir.get().strip(),
                use_pressure=use_pressure_var.get(),
                pressure_path=e_pressure.get().strip()
            )
        except Exception as ex:
            messagebox.showerror("Error", str(ex))

    tk.Button(frm, text="Run", command=on_run).grid(row=9, column=1, pady=10, sticky="w")
    root.mainloop()

if __name__ == "__main__":
    main()
    