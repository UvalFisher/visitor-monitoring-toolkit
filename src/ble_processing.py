import os
import re
import numpy as np
import pandas as pd
from datetime import timedelta

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# =========================
# PARAMETERS
# =========================
DEFAULT_GAP_MINUTES = 15

# Raw timestamp parsing:
# True  = DD/MM/YYYY
# False = MM/DD/YYYY
RAW_DAYFIRST = True

# Device merge (randomization) parameters
DISAPPEAR_WINDOW = 4   # seconds
NEW_MAC_WINDOW   = 4   # seconds
NEW_MAC_EARLY_WINDOW = 2  # seconds: new MAC may appear up to 2 sec before old MAC disappears
FIRST_SYNC       = 4   # seconds

RAW_REQUIRED = {"MAC", "RSSI", "timestamp"}
RAW_OPTIONAL = ["name", "manufacturer", "serviceUUID"]

# Base concurrency cap for metadata merges (when no randomization evidence exists)
MAX_CONCURRENT_MACS = 3


# =========================
# Utils
# =========================
def read_csv_safely(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="latin1")


def normalize_text(s):
    """
    Goal: turn junky BLE names like:
      "Charge 6<garbage>1E<garbage>m<garbage>L..."
    into:
      "Charge 6"

    Strategy:
      1) Keep only printable ASCII
      2) If has ')' keep up to last ')'
      3) Token-wise truncation: stop when token starts with a digit (e.g., "1EmL")
      4) Final cleanup to keep sane chars only
    """
    if pd.isna(s):
        return s

    s = str(s)

    # 1) Keep only printable ASCII
    s = ''.join(ch for ch in s if 32 <= ord(ch) <= 126)

    # 2) Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()

    # 3) If we have "(...)" suffix keep it through last ')'
    if ')' in s:
        s = s[:s.rfind(')') + 1].strip()

    # 4) Token truncation: stop at first token starting with a digit
    tokens = s.split()
    kept = []
    for t in tokens:
        if re.match(r'^\d', t):
            break
        kept.append(t)
    s = " ".join(kept).strip()

    # 5) Final cleanup: keep only sane characters
    s = re.sub(r'[^A-Za-z0-9 ()_\-]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def pick_earlier_sensor(ts_a, ts_b):
    if pd.isna(ts_a) and pd.isna(ts_b):
        return None
    if pd.isna(ts_a):
        return "B"
    if pd.isna(ts_b):
        return "A"
    if ts_a < ts_b:
        return "A"
    if ts_b < ts_a:
        return "B"
    return "tie"


def infer_direction_from_row(first_A, first_B, last_A, last_B,
                             first_rssi_A=np.nan, first_rssi_B=np.nan,
                             last_rssi_A=np.nan, last_rssi_B=np.nan):
    """
    Direction logic consistent with your visit logic:
      - Earlier sensor => opposite direction (A first => direction B, B first => direction A)
      - Tie on first => compare last timestamps (also opposite mapping)
      - If still tie => RSSI tie-break:
            If first RSSI A > first RSSI B => direction B
            If first RSSI B > first RSSI A => direction A
            If still equal => last RSSI:
                If last RSSI A > last RSSI B => direction A
                If last RSSI B > last RSSI A => direction B
      - Otherwise Unknown
    """
    earliest = pick_earlier_sensor(first_A, first_B)
    if earliest == "A":
        return "B"
    if earliest == "B":
        return "A"
    if earliest == "tie":
        last_cmp = pick_earlier_sensor(last_A, last_B)
        if last_cmp == "A":
            return "B"
        if last_cmp == "B":
            return "A"

        # still tie: RSSI rules
        if pd.notna(first_rssi_A) and pd.notna(first_rssi_B):
            if first_rssi_A > first_rssi_B:
                return "B"
            if first_rssi_B > first_rssi_A:
                return "A"

        if pd.notna(last_rssi_A) and pd.notna(last_rssi_B):
            if last_rssi_A > last_rssi_B:
                return "A"
            if last_rssi_B > last_rssi_A:
                return "B"

        return "Unknown"
    return "Unknown"


# =========================
# Step 0: prepare raw
# =========================
def prepare_raw_df(df: pd.DataFrame, sensor_label: str) -> pd.DataFrame:
    missing = RAW_REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"CSV for sensor {sensor_label} is missing columns: {missing}")

    d = df.copy()
    for col in RAW_OPTIONAL:
        if col not in d.columns:
            d[col] = np.nan

    d["timestamp"] = pd.to_datetime(d["timestamp"], dayfirst=RAW_DAYFIRST, errors="coerce")
    d = d.dropna(subset=["timestamp", "MAC"])
    if d.empty:
        raise ValueError(
            f"Sensor {sensor_label} has 0 valid rows after timestamp parsing (RAW_DAYFIRST={RAW_DAYFIRST})."
        )

    d["MAC"] = d["MAC"].astype(str)
    d["sensor"] = sensor_label
    return d[["MAC", "timestamp", "RSSI", "name", "manufacturer", "serviceUUID", "sensor"]]


# =========================
# Step 1: raw -> per-MAC events
# =========================
def process_one_mac_to_events(df_a_mac: pd.DataFrame, df_b_mac: pd.DataFrame, gap_seconds: float):
    df = pd.concat([df_a_mac, df_b_mac], ignore_index=True).sort_values("timestamp")

    def pick_field(df_a, df_b, col):
        if df_a[col].notna().any():
            return df_a[col].dropna().iloc[0]
        if df_b[col].notna().any():
            return df_b[col].dropna().iloc[0]
        return np.nan

    name = pick_field(df_a_mac, df_b_mac, "name")
    manu = pick_field(df_a_mac, df_b_mac, "manufacturer")
    suuid = pick_field(df_a_mac, df_b_mac, "serviceUUID")

    diffs = df["timestamp"].diff().dt.total_seconds()
    df["event_id"] = (diffs.isna() | (diffs > gap_seconds)).cumsum()

    out = []
    mac_value = df["MAC"].iloc[0]

    for _, g in df.groupby("event_id"):
        # Keep only events where BOTH sensors saw this MAC in this event window
        if not ({"A", "B"} <= set(g["sensor"])):
            continue

        g_a = g[g["sensor"] == "A"]
        g_b = g[g["sensor"] == "B"]

        first_ts_a = g_a["timestamp"].min()
        last_ts_a  = g_a["timestamp"].max()
        first_row_a = g_a.loc[g_a["timestamp"].idxmin()]
        last_row_a  = g_a.loc[g_a["timestamp"].idxmax()]

        first_ts_b = g_b["timestamp"].min()
        last_ts_b  = g_b["timestamp"].max()
        first_row_b = g_b.loc[g_b["timestamp"].idxmin()]
        last_row_b  = g_b.loc[g_b["timestamp"].idxmax()]

        out.append({
            "MAC": mac_value,
            "name": name,
            "manufacturer": manu,
            "serviceUUID": suuid,

            "first_timestamp_A": first_ts_a,
            "first_RSSI_A": first_row_a["RSSI"],
            "last_timestamp_A": last_ts_a,
            "last_RSSI_A": last_row_a["RSSI"],

            "first_timestamp_B": first_ts_b,
            "first_RSSI_B": first_row_b["RSSI"],
            "last_timestamp_B": last_ts_b,
            "last_RSSI_B": last_row_b["RSSI"],
        })

    return out


def build_events_from_two_sensors(df_a_raw: pd.DataFrame, df_b_raw: pd.DataFrame, gap_minutes: float):
    gap_seconds = float(gap_minutes) * 60.0

    df_a = prepare_raw_df(df_a_raw, "A")
    df_b = prepare_raw_df(df_b_raw, "B")

    common_macs = set(df_a["MAC"]).intersection(set(df_b["MAC"]))
    if not common_macs:
        return pd.DataFrame()

    rows = []
    for mac in sorted(common_macs):
        rows.extend(process_one_mac_to_events(
            df_a[df_a["MAC"] == mac],
            df_b[df_b["MAC"] == mac],
            gap_seconds=gap_seconds
        ))

    if not rows:
        return pd.DataFrame()

    ev = pd.DataFrame(rows)
    ev["global_start"] = ev[["first_timestamp_A", "first_timestamp_B"]].min(axis=1)
    ev["global_end"]   = ev[["last_timestamp_A", "last_timestamp_B"]].max(axis=1)
    ev = ev.sort_values("global_start").reset_index(drop=True)
    return ev


# =========================
# Step 2: events -> Device_ID
# =========================
class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> int:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return rx

        if self.rank[rx] < self.rank[ry]:
            self.parent[rx] = ry
            return ry
        if self.rank[ry] < self.rank[rx]:
            self.parent[ry] = rx
            return rx

        self.parent[ry] = rx
        self.rank[rx] += 1
        return rx


def assign_device_ids(df_events: pd.DataFrame) -> pd.DataFrame:
    df = df_events.copy().reset_index(drop=True)

    for c in ["first_timestamp_A", "last_timestamp_A", "first_timestamp_B", "last_timestamp_B", "global_start", "global_end"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")

    df["MAC"] = df["MAC"].astype(str)
    df["name_norm"] = df["name"].apply(normalize_text) if "name" in df.columns else np.nan

    # --- NEW: per-event direction (used in manufacturer_overlap rule) ---
    df["event_direction"] = df.apply(
        lambda r: infer_direction_from_row(
            r.get("first_timestamp_A", np.nan),
            r.get("first_timestamp_B", np.nan),
            r.get("last_timestamp_A", np.nan),
            r.get("last_timestamp_B", np.nan),
            r.get("first_RSSI_A", np.nan),
            r.get("first_RSSI_B", np.nan),
            r.get("last_RSSI_A", np.nan),
            r.get("last_RSSI_B", np.nan),
        ),
        axis=1
    )

    n = len(df)
    uf = UnionFind(n)

    # Pairwise reasons (for merge_reason column)
    merge_reason = {}

    def record(a, b, why):
        merge_reason[(a, b)] = merge_reason[(b, a)] = why

    def get_root(i):
        return uf.find(i)

    # --- Dynamic member-tracking for concurrency rule ---
    root_to_members_dyn = {i: {i} for i in range(n)}

    # --- Track whether a component has any randomization evidence ---
    root_has_randomization = {i: False for i in range(n)}

    def merge_members(ra, rb, new_r):
        s = set()
        s |= root_to_members_dyn.pop(ra, set())
        s |= root_to_members_dyn.pop(rb, set())
        root_to_members_dyn[new_r] = s

        rr = root_has_randomization.pop(ra, False) or root_has_randomization.pop(rb, False)
        root_has_randomization[new_r] = rr

    # --- Concurrency check helper ---
    def max_concurrent_events(indices):
        """
        Sweep-line on global_start/global_end to count concurrent event-rows.
        End points processed before start points at same time (touching != overlap).
        """
        pts = []
        for i in indices:
            s = df.at[i, "global_start"]
            e = df.at[i, "global_end"]
            if pd.isna(s) or pd.isna(e):
                continue
            pts.append((s, +1))
            pts.append((e, -1))
        pts.sort(key=lambda x: (x[0], x[1]))  # -1 before +1 at same timestamp

        cur = 0
        mx = 0
        for _, delta in pts:
            cur += delta
            if cur > mx:
                mx = cur
        return mx

    def union_with_aux(a, b, why):
        ra, rb = get_root(a), get_root(b)
        if ra == rb:
            return ra

        new_r = uf.union(ra, rb)
        new_r = get_root(new_r)

        # merge member sets for concurrency tracking + randomization flag
        merge_members(ra, rb, new_r)
        if why == "randomization_link":
            root_has_randomization[new_r] = True

        record(a, b, why)
        return new_r

    # ---------- Overlap helpers ----------
    def interval_overlap(s1, e1, s2, e2):
        return (pd.notna(s1) and pd.notna(e1) and pd.notna(s2) and pd.notna(e2) and s1 <= e2 and s2 <= e1)

    # ---------- Rule 0: SAME MAC ALWAYS MERGES ----------
    for mac, idxs in df.groupby("MAC").groups.items():
        idxs = list(idxs)
        if len(idxs) < 2:
            continue
        base = idxs[0]
        for j in idxs[1:]:
            union_with_aux(base, j, "same_mac")

    # ==========================================================
    # Rule 2: RANDOMIZATION CHAINING (WITH "NO 2 -> 1" CONSTRAINT)
    # ==========================================================
    inbound_parent = {}  # child_index -> parent_index that claimed it first

    for i in range(n):
        la, lb = df.at[i, "last_timestamp_A"], df.at[i, "last_timestamp_B"]
        if pd.isna(la) or pd.isna(lb):
            continue
        if abs((la - lb).total_seconds()) > DISAPPEAR_WINDOW:
            continue

        disappearance = max(la, lb)
        window_start = disappearance - timedelta(seconds=NEW_MAC_EARLY_WINDOW)
        window_end = disappearance + timedelta(seconds=NEW_MAC_WINDOW)

        candidates = []
        for j in range(n):
            if j == i:
                continue

            fjA = df.at[j, "first_timestamp_A"]
            fjB = df.at[j, "first_timestamp_B"]
            if pd.notna(fjA) and pd.notna(fjB):
                fj = min(fjA, fjB)
            else:
                fj = fjA if pd.notna(fjA) else fjB

            if pd.isna(fj) or fj < window_start or fj > window_end:
                continue

            # FIRST_SYNC check if both exist
            if (pd.notna(fjA) and pd.notna(fjB)) and abs((fjA - fjB).total_seconds()) > FIRST_SYNC:
                continue

            candidates.append(j)

        if not candidates:
            continue

        def meta_score(j):
            s = 0
            for col in ["name_norm", "manufacturer", "serviceUUID"]:
                if pd.notna(df.at[i, col]) and df.at[i, col] == df.at[j, col]:
                    s += 1
            return s

        def delta(i_, j_):
            vals = []
            for col in ["first_RSSI_A", "first_RSSI_B"]:
                if pd.notna(df.at[i_, col]) and pd.notna(df.at[j_, col]):
                    vals.append(abs(df.at[i_, col] - df.at[j_, col]))
            return sum(vals) if vals else 9999

        best = min(candidates, key=lambda j: (-meta_score(j), delta(i, j)))

        # Chain constraint: prevent 2 unrelated -> 1
        if best in inbound_parent:
            k = inbound_parent[best]
            if get_root(i) != get_root(k):
                continue

        union_with_aux(i, best, "randomization_link")
        inbound_parent[best] = i

    # ==========================================================
    # Rule 1: METADATA OVERLAP UNION
    # ==========================================================
    def allow_metadata_union(a, b, cap):
        ra, rb = get_root(a), get_root(b)
        if ra == rb:
            return False

        merged = root_to_members_dyn.get(ra, {a}) | root_to_members_dyn.get(rb, {b})
        mx = max_concurrent_events(merged)
        return mx <= cap

    def component_cap_for_roots(ra, rb):
        has_rand = root_has_randomization.get(ra, False) or root_has_randomization.get(rb, False)
        return (10**9) if has_rand else MAX_CONCURRENT_MACS

    def apply_overlap_rule_generic(column, tag):
        non_null = df[df[column].notna()].copy()
        groups = non_null.groupby(column).groups

        for key, idxs in groups.items():
            idxs = list(idxs)
            if len(idxs) < 2:
                continue

            for i1 in range(len(idxs)):
                for i2 in range(i1 + 1, len(idxs)):
                    a, b = idxs[i1], idxs[i2]

                    overlaps = (
                        interval_overlap(df.at[a, "first_timestamp_A"], df.at[a, "last_timestamp_A"],
                                         df.at[b, "first_timestamp_A"], df.at[b, "last_timestamp_A"]) or
                        interval_overlap(df.at[a, "first_timestamp_B"], df.at[a, "last_timestamp_B"],
                                         df.at[b, "first_timestamp_B"], df.at[b, "last_timestamp_B"])
                    )
                    if not overlaps:
                        continue

                    ra, rb = get_root(a), get_root(b)
                    cap = component_cap_for_roots(ra, rb)
                    if not allow_metadata_union(a, b, cap):
                        continue

                    union_with_aux(a, b, tag)

    def greedy_split_by_overlap_similarity(indices, cap):
        idx_sorted = sorted(
            indices,
            key=lambda i: (df.at[i, "global_start"] if pd.notna(df.at[i, "global_start"]) else pd.Timestamp.max)
        )

        clusters = []
        for i in idx_sorted:
            placed = False
            for c in clusters:
                mx = max_concurrent_events(c + [i])
                if mx <= cap:
                    c.append(i)
                    placed = True
                    break
            if not placed:
                clusters.append([i])
        return clusters

    def apply_manufacturer_overlap_updated():
        non_null = df[df["manufacturer"].notna()].copy()
        groups = non_null.groupby("manufacturer").groups

        for manu, idxs_all in groups.items():
            idxs_all = list(idxs_all)
            if len(idxs_all) < 2:
                continue

            # only same direction A/B (skip Unknown)
            dir_to_idxs = {}
            for i in idxs_all:
                ddir = df.at[i, "event_direction"]
                if ddir not in ("A", "B"):
                    continue
                dir_to_idxs.setdefault(ddir, []).append(i)

            for ddir, idxs in dir_to_idxs.items():
                if len(idxs) < 2:
                    continue

                edges = []
                for i1 in range(len(idxs)):
                    for i2 in range(i1 + 1, len(idxs)):
                        a, b = idxs[i1], idxs[i2]
                        overlaps = (
                            interval_overlap(df.at[a, "first_timestamp_A"], df.at[a, "last_timestamp_A"],
                                             df.at[b, "first_timestamp_A"], df.at[b, "last_timestamp_A"]) or
                            interval_overlap(df.at[a, "first_timestamp_B"], df.at[a, "last_timestamp_B"],
                                             df.at[b, "first_timestamp_B"], df.at[b, "last_timestamp_B"])
                        )
                        if overlaps:
                            edges.append((a, b))

                if not edges:
                    continue

                cap = MAX_CONCURRENT_MACS

                if max_concurrent_events(idxs) > cap:
                    clusters = greedy_split_by_overlap_similarity(idxs, cap)
                else:
                    clusters = [idxs]

                cluster_sets = [set(c) for c in clusters]
                for cset in cluster_sets:
                    c_edges = [(a, b) for (a, b) in edges if (a in cset and b in cset)]
                    for a, b in c_edges:
                        ra, rb = get_root(a), get_root(b)
                        cap_ab = component_cap_for_roots(ra, rb)
                        if not allow_metadata_union(a, b, cap_ab):
                            continue
                        union_with_aux(a, b, "manufacturer_overlap")

    apply_overlap_rule_generic("name_norm", "name_overlap")
    apply_manufacturer_overlap_updated()
    apply_overlap_rule_generic("serviceUUID", "uuid_overlap")

    # ==========================================================
    # Build Device_IDs ordered by earliest global_start
    # ==========================================================
    root_to_members_final = {}
    for i in range(n):
        r = get_root(i)
        root_to_members_final.setdefault(r, []).append(i)

    ordered_roots = sorted(
        root_to_members_final.keys(),
        key=lambda r: df.loc[root_to_members_final[r], "global_start"].fillna(pd.Timestamp.max).min()
    )
    root_to_id = {root: idx + 1 for idx, root in enumerate(ordered_roots)}
    df["Device_ID"] = [root_to_id[get_root(i)] for i in range(n)]

    reasons = []
    for i in range(n):
        r = get_root(i)
        members = root_to_members_final[r]
        if len(members) == 1:
            reasons.append("root")
            continue
        rlist = [merge_reason.get((i, j)) for j in members if (i, j) in merge_reason]
        rlist = [x for x in rlist if x]
        reasons.append(",".join(sorted(set(rlist))) if rlist else "merged_via_chain")
    df["merge_reason"] = reasons

    df = df.sort_values("global_start").reset_index(drop=True)
    return df


# =========================
# Step 3: Device_ID -> Visits
# =========================
def compute_device_visits(df_events_with_device: pd.DataFrame, gap_minutes: float) -> pd.DataFrame:
    d = df_events_with_device.copy()
    for c in ["first_timestamp_A", "last_timestamp_A", "first_timestamp_B", "last_timestamp_B", "global_start", "global_end"]:
        d[c] = pd.to_datetime(d[c], errors="coerce")

    gap_sec = float(gap_minutes) * 60.0

    rows = []
    for dev_id, g in d.groupby("Device_ID"):
        g = g.sort_values("global_start").copy()

        prev_end = g["global_end"].shift(1)
        gap_series = (g["global_start"] - prev_end).dt.total_seconds()
        new_visit = gap_series.isna() | (gap_series > gap_sec)
        g["Visit_ID"] = new_visit.cumsum()

        for visit_id, gv in g.groupby("Visit_ID"):
            first_A = gv["first_timestamp_A"].min()
            last_A  = gv["last_timestamp_A"].max()
            first_B = gv["first_timestamp_B"].min()
            last_B  = gv["last_timestamp_B"].max()

            diff_first_sec = (first_A - first_B).total_seconds() if (pd.notna(first_A) and pd.notna(first_B)) else np.nan
            diff_last_sec  = (last_A - last_B).total_seconds() if (pd.notna(last_A) and pd.notna(last_B)) else np.nan

            if pd.isna(first_A) or pd.isna(last_A) or pd.isna(first_B) or pd.isna(last_B):
                dwell_sec = np.nan
                first_dwell = pd.NaT
                last_dwell = pd.NaT
            else:
                first_dwell = max(first_A, first_B)
                last_dwell = min(last_A, last_B)

                if last_dwell < first_dwell:
                    dwell_sec = 0.0
                else:
                    dwell_sec = float((last_dwell - first_dwell).total_seconds())

            gv2 = gv.copy()
            gv2["global_start"] = pd.to_datetime(gv2["global_start"], errors="coerce")
            gv2["global_end"] = pd.to_datetime(gv2["global_end"], errors="coerce")

            idx_first = gv2["global_start"].idxmin()
            idx_last = gv2["global_end"].idxmax()

            first_rssi_A = gv2.loc[idx_first, "first_RSSI_A"] if "first_RSSI_A" in gv2.columns else np.nan
            first_rssi_B = gv2.loc[idx_first, "first_RSSI_B"] if "first_RSSI_B" in gv2.columns else np.nan
            last_rssi_A = gv2.loc[idx_last, "last_RSSI_A"] if "last_RSSI_A" in gv2.columns else np.nan
            last_rssi_B = gv2.loc[idx_last, "last_RSSI_B"] if "last_RSSI_B" in gv2.columns else np.nan

            direction = infer_direction_from_row(
                first_A, first_B, last_A, last_B,
                first_rssi_A, first_rssi_B,
                last_rssi_A, last_rssi_B
            )

            rows.append({
                "Device_ID": int(dev_id),
                "Visit_ID": int(visit_id),

                "global_start": gv["global_start"].min(),
                "global_end": gv["global_end"].max(),

                "first_timestamp_A_visit": first_A,
                "last_timestamp_A_visit": last_A,
                "first_timestamp_B_visit": first_B,
                "last_timestamp_B_visit": last_B,

                "first_dwell": first_dwell,
                "last_dwell": last_dwell,

                "diff_first_sec": abs(diff_first_sec) if pd.notna(diff_first_sec) else np.nan,
                "diff_last_sec": abs(diff_last_sec) if pd.notna(diff_last_sec) else np.nan,

                "dwell_sec": dwell_sec,
                "direction": direction,
            })

    out = pd.DataFrame(rows).sort_values(["global_start", "Device_ID", "Visit_ID"]).reset_index(drop=True)
    return out


# =========================
# UI
# =========================
class MakeCSVsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("BLE – Create events_with_device + device_visits")
        self.root.geometry("900x280")

        self.path_a = None
        self.path_b = None

        frm = ttk.Frame(root, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        row = 0
        ttk.Button(frm, text="Select Sensor A CSV", command=self.pick_a).grid(row=row, column=0, sticky="w")
        self.lbl_a = ttk.Label(frm, text="No file selected")
        self.lbl_a.grid(row=row, column=1, sticky="w", padx=10)

        row += 1
        ttk.Button(frm, text="Select Sensor B CSV", command=self.pick_b).grid(row=row, column=0, sticky="w")
        self.lbl_b = ttk.Label(frm, text="No file selected")
        self.lbl_b.grid(row=row, column=1, sticky="w", padx=10)

        row += 1
        ttk.Label(frm, text="Gap minutes (event split + visit split):").grid(row=row, column=0, sticky="w", pady=(10, 0))
        self.gap_var = tk.DoubleVar(value=float(DEFAULT_GAP_MINUTES))
        ttk.Entry(frm, textvariable=self.gap_var, width=10).grid(row=row, column=1, sticky="w", pady=(10, 0))

        row += 1
        ttk.Button(frm, text="RUN + SAVE CSVs", command=self.run).grid(row=row, column=0, columnspan=2, pady=15)

        ttk.Label(
            frm,
            text=f"RAW_DAYFIRST = {RAW_DAYFIRST} | MAX_CONCURRENT_MACS = {MAX_CONCURRENT_MACS} (cap for manufacturer when no randomization)"
        ).grid(row=row + 1, column=0, columnspan=2, sticky="w")

        ttk.Label(
            frm,
            text="Manufacturer rule: only same event_direction (A/B). If >3 overlap and no randomization → split by overlap similarity."
        ).grid(row=row + 2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Label(
            frm,
            text="Name normalization: stops at tokens starting with digits (e.g., 'Charge 6 1EmL' -> 'Charge 6')"
        ).grid(row=row + 3, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def pick_a(self):
        p = filedialog.askopenfilename(title="Select Sensor A CSV", filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if p:
            self.path_a = p
            self.lbl_a.config(text=os.path.basename(p))

    def pick_b(self):
        p = filedialog.askopenfilename(title="Select Sensor B CSV", filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if p:
            self.path_b = p
            self.lbl_b.config(text=os.path.basename(p))

    def run(self):
        if not self.path_a or not self.path_b:
            messagebox.showerror("Missing files", "Select both sensor A and sensor B CSV.")
            return

        try:
            gap_minutes = float(self.gap_var.get())
            if gap_minutes <= 0:
                raise ValueError("gap_minutes must be > 0")

            df_a_raw = read_csv_safely(self.path_a)
            df_b_raw = read_csv_safely(self.path_b)

            events = build_events_from_two_sensors(df_a_raw, df_b_raw, gap_minutes=gap_minutes)
            if events.empty:
                messagebox.showinfo("No events", "No per-MAC events found where both sensors saw the MAC.")
                return

            events_with_device = assign_device_ids(events)
            visits = compute_device_visits(events_with_device, gap_minutes=gap_minutes)

            # NEW: save only visits with dwell_sec > 0
            visits_dwell_positive = visits[visits["dwell_sec"] > 0].copy()

            out_dir = filedialog.askdirectory(title="Select folder to save outputs")
            if not out_dir:
                return

            base = os.path.splitext(os.path.basename(self.path_a))[0]
            out1 = os.path.join(out_dir, f"{base}_events_with_device.csv")
            out2 = os.path.join(out_dir, f"{base}_device_visits.csv")
            out3 = os.path.join(out_dir, f"{base}_device_visits_dwell_positive.csv")

            events_with_device.to_csv(out1, index=False)
            visits.to_csv(out2, index=False)
            visits_dwell_positive.to_csv(out3, index=False)

            messagebox.showinfo("Done", f"Saved:\n{out1}\n{out2}\n{out3}")

        except Exception as e:
            messagebox.showerror("Error", f"{e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = MakeCSVsApp(root)
    root.mainloop()