import os
import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import matplotlib.pyplot as plt


class VisitorVolumeUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Visitor Volume Over Time")
        self.root.geometry("700x420")

        self.df = None
        self.file_path = ""
        self.result_df = None

        self.build_ui()

    # -----------------------------
    # UI
    # -----------------------------
    def build_ui(self):
        main = ttk.Frame(self.root, padding=15)
        main.pack(fill="both", expand=True)

        file_frame = ttk.LabelFrame(main, text="CSV File", padding=10)
        file_frame.pack(fill="x", pady=8)

        self.file_label = ttk.Label(file_frame, text="No file selected")
        self.file_label.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ttk.Button(
            file_frame,
            text="Choose CSV",
            command=self.load_csv
        ).pack(side="right")

        # Time inputs
        time_frame = ttk.LabelFrame(main, text="Time Range", padding=10)
        time_frame.pack(fill="x", pady=8)

        ttk.Label(
            time_frame,
            text="Start date (YYYY-MM-DD):"
        ).grid(row=0, column=0, padx=5, pady=5)

        self.start_date_entry = ttk.Entry(time_frame, width=15)
        self.start_date_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(
            time_frame,
            text="Start hour (HH:MM):"
        ).grid(row=0, column=2, padx=5, pady=5)

        self.start_time_entry = ttk.Entry(time_frame, width=10)
        self.start_time_entry.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(
            time_frame,
            text="End date (YYYY-MM-DD):"
        ).grid(row=1, column=0, padx=5, pady=5)

        self.end_date_entry = ttk.Entry(time_frame, width=15)
        self.end_date_entry.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(
            time_frame,
            text="End hour (HH:MM):"
        ).grid(row=1, column=2, padx=5, pady=5)

        self.end_time_entry = ttk.Entry(time_frame, width=10)
        self.end_time_entry.grid(row=1, column=3, padx=5, pady=5)

        # Resolution
        options_frame = ttk.LabelFrame(main, text="Options", padding=10)
        options_frame.pack(fill="x", pady=8)

        ttk.Label(
            options_frame,
            text="Step (minutes):"
        ).grid(row=0, column=0, padx=5, pady=5)

        self.step_var = tk.StringVar(value="1")

        self.step_combo = ttk.Combobox(
            options_frame,
            textvariable=self.step_var,
            values=["1", "5", "10", "15", "30", "60"],
            state="readonly",
            width=10
        )
        self.step_combo.grid(row=0, column=1, padx=5, pady=5)

        # Buttons
        button_frame = ttk.Frame(main)
        button_frame.pack(fill="x", pady=10)

        ttk.Button(
            button_frame,
            text="Plot",
            command=self.plot_graph
        ).pack(side="left", padx=5)

        ttk.Button(
            button_frame,
            text="Auto Fill Range",
            command=self.fill_range_from_data
        ).pack(side="left", padx=5)

        ttk.Button(
            button_frame,
            text="Export Excel",
            command=self.export_excel
        ).pack(side="left", padx=5)

    # -----------------------------
    # Load CSV
    # -----------------------------
    def load_csv(self):
        path = filedialog.askopenfilename(
            filetypes=[("CSV", "*.csv")]
        )

        if not path:
            return

        try:
            df = pd.read_csv(path)

            required = {
                "first_timestamp_A_visit",
                "last_timestamp_A_visit",
                "first_timestamp_B_visit",
                "last_timestamp_B_visit"
            }

            missing = required - set(df.columns)

            if missing:
                messagebox.showerror(
                    "Missing columns",
                    f"Missing:\n{missing}"
                )
                return

            # Convert timestamps to datetime
            for col in required:
                df[col] = pd.to_datetime(
                    df[col],
                    errors="coerce"
                )

            df = df.dropna(
                how="all",
                subset=required
            ).copy()

            # -----------------------------
            # CREATE VISIT INTERVAL
            # -----------------------------
            starts = []
            ends = []

            for _, row in df.iterrows():

                times_start = []
                times_end = []

                if pd.notna(row["first_timestamp_A_visit"]):
                    times_start.append(
                        row["first_timestamp_A_visit"]
                    )

                if pd.notna(row["first_timestamp_B_visit"]):
                    times_start.append(
                        row["first_timestamp_B_visit"]
                    )

                if pd.notna(row["last_timestamp_A_visit"]):
                    times_end.append(
                        row["last_timestamp_A_visit"]
                    )

                if pd.notna(row["last_timestamp_B_visit"]):
                    times_end.append(
                        row["last_timestamp_B_visit"]
                    )

                if not times_start or not times_end:
                    starts.append(pd.NaT)
                    ends.append(pd.NaT)
                    continue

                # Overlapping interval between sensors A and B
                start = max(times_start)
                end = min(times_end)

                if end < start:
                    starts.append(pd.NaT)
                    ends.append(pd.NaT)
                else:
                    starts.append(start)
                    ends.append(end)

            df["visit_start"] = starts
            df["visit_end"] = ends

            df = df.dropna(
                subset=["visit_start", "visit_end"]
            )

            if df.empty:
                messagebox.showerror(
                    "No data",
                    "No valid visits after processing."
                )
                return

            self.df = df
            self.file_path = path

            # Clear previous plot/export results
            self.result_df = None

            self.file_label.config(
                text=os.path.basename(path)
            )

            messagebox.showinfo(
                "Loaded",
                f"{len(df)} valid visits created."
            )

        except Exception as e:
            messagebox.showerror(
                "Error",
                str(e)
            )

    # -----------------------------
    # Auto range
    # -----------------------------
    def fill_range_from_data(self):

        if self.df is None:
            messagebox.showwarning(
                "No file",
                "Load a file first."
            )
            return

        start = self.df["visit_start"].min()
        end = self.df["visit_end"].max()

        self.start_date_entry.delete(0, tk.END)
        self.start_date_entry.insert(
            0,
            start.strftime("%Y-%m-%d")
        )

        self.start_time_entry.delete(0, tk.END)
        self.start_time_entry.insert(
            0,
            start.strftime("%H:%M")
        )

        self.end_date_entry.delete(0, tk.END)
        self.end_date_entry.insert(
            0,
            end.strftime("%Y-%m-%d")
        )

        self.end_time_entry.delete(0, tk.END)
        self.end_time_entry.insert(
            0,
            end.strftime("%H:%M")
        )

    # -----------------------------
    # Calculate visitor volume
    # -----------------------------
    def calculate_volume(self):

        if self.df is None:
            messagebox.showwarning(
                "No file",
                "Load a file first."
            )
            return None

        try:
            start = pd.to_datetime(
                f"{self.start_date_entry.get()} "
                f"{self.start_time_entry.get()}"
            )

            end = pd.to_datetime(
                f"{self.end_date_entry.get()} "
                f"{self.end_time_entry.get()}"
            )

            step = int(self.step_var.get())

        except Exception:
            messagebox.showerror(
                "Error",
                "Invalid date/time format"
            )
            return None

        if end < start:
            messagebox.showerror(
                "Error",
                "End time must be after start time."
            )
            return None

        time_points = pd.date_range(
            start=start,
            end=end,
            freq=f"{step}min"
        )

        df = self.df[
            (self.df["visit_end"] >= start) &
            (self.df["visit_start"] <= end)
        ]

        counts = []

        for t in time_points:

            c = (
                (df["visit_start"] <= t) &
                (df["visit_end"] >= t)
            ).sum()

            counts.append(c)

        self.result_df = pd.DataFrame({
            "Time": time_points,
            "Visitors": counts
        })

        return self.result_df

    # -----------------------------
    # Plot
    # -----------------------------
    def plot_graph(self):

        result = self.calculate_volume()

        if result is None:
            return

        plt.figure(figsize=(12, 6))

        plt.plot(
            result["Time"],
            result["Visitors"],
            marker="o"
        )

        plt.xlabel("Time")
        plt.ylabel("Visitors")
        plt.title("Visitor Volume Over Time")

        plt.xticks(rotation=45)
        plt.grid(True)
        plt.tight_layout()

        plt.show()

    # -----------------------------
    # Export Excel - Horizontal
    # -----------------------------
    def export_excel(self):

        # Recalculate according to the current selected
        # range and step
        result = self.calculate_volume()

        if result is None or result.empty:
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[
                ("Excel file", "*.xlsx")
            ],
            title="Save visitor volume"
        )

        if not path:
            return

        try:

            # Horizontal structure:
            #
            # Time       10:00   10:01   10:02 ...
            # Visitors   3       4       2     ...

            export_df = pd.DataFrame([
                ["Time"] + list(result["Time"]),
                ["Visitors"] + list(result["Visitors"])
            ])

            with pd.ExcelWriter(
                path,
                engine="openpyxl"
            ) as writer:

                export_df.to_excel(
                    writer,
                    index=False,
                    header=False,
                    sheet_name="Visitor Volume"
                )

                worksheet = writer.sheets[
                    "Visitor Volume"
                ]

                # Format all timestamps in first row
                # starting from column B
                for cell in worksheet[1][1:]:
                    cell.number_format = (
                        "dd/mm/yyyy hh:mm:ss"
                    )

                # Width of first column
                worksheet.column_dimensions[
                    "A"
                ].width = 12

                # Give timestamp columns enough width
                for column_cells in worksheet.iter_cols(
                    min_col=2,
                    max_col=worksheet.max_column
                ):
                    worksheet.column_dimensions[
                        column_cells[0].column_letter
                    ].width = 20

            messagebox.showinfo(
                "Saved",
                f"Excel file saved successfully:\n{path}"
            )

        except Exception as e:
            messagebox.showerror(
                "Export error",
                str(e)
            )


if __name__ == "__main__":
    root = tk.Tk()

    app = VisitorVolumeUI(root)

    root.mainloop()