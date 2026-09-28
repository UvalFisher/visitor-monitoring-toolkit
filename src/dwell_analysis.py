import os
import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import matplotlib.pyplot as plt


class DwellTimeByHourUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Dwell Time by Hour")
        self.root.geometry("850x650")

        self.file_paths = []

        self.build_ui()

    # =========================================================
    # UI
    # =========================================================
    def build_ui(self):
        main = ttk.Frame(self.root, padding=15)
        main.pack(fill="both", expand=True)

        # -----------------------------------------------------
        # FILE SELECTION
        # -----------------------------------------------------
        file_frame = ttk.LabelFrame(
            main,
            text="CSV Files",
            padding=10
        )
        file_frame.pack(fill="both", expand=True, pady=8)

        button_row = ttk.Frame(file_frame)
        button_row.pack(fill="x", pady=(0, 8))

        ttk.Button(
            button_row,
            text="Add CSV Files",
            command=self.add_files
        ).pack(side="left", padx=(0, 5))

        ttk.Button(
            button_row,
            text="Remove Selected",
            command=self.remove_selected
        ).pack(side="left", padx=5)

        ttk.Button(
            button_row,
            text="Clear All",
            command=self.clear_files
        ).pack(side="left", padx=5)

        self.file_count_label = ttk.Label(
            button_row,
            text="0 files selected"
        )
        self.file_count_label.pack(side="right")

        # List of selected files
        list_frame = ttk.Frame(file_frame)
        list_frame.pack(fill="both", expand=True)

        self.file_listbox = tk.Listbox(
            list_frame,
            height=8,
            selectmode=tk.EXTENDED
        )
        self.file_listbox.pack(
            side="left",
            fill="both",
            expand=True
        )

        scrollbar = ttk.Scrollbar(
            list_frame,
            orient="vertical",
            command=self.file_listbox.yview
        )
        scrollbar.pack(
            side="right",
            fill="y"
        )

        self.file_listbox.config(
            yscrollcommand=scrollbar.set
        )

        # -----------------------------------------------------
        # OPTIONS
        # -----------------------------------------------------
        options_frame = ttk.LabelFrame(
            main,
            text="Analysis Options",
            padding=10
        )
        options_frame.pack(fill="x", pady=8)

        ttk.Label(
            options_frame,
            text="Minimum dwell time (seconds):"
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=5,
            pady=5
        )

        self.min_dwell_var = tk.StringVar(value="0")

        ttk.Entry(
            options_frame,
            textvariable=self.min_dwell_var,
            width=10
        ).grid(
            row=0,
            column=1,
            sticky="w",
            padx=5,
            pady=5
        )

        ttk.Label(
            options_frame,
            text="Maximum dwell time (seconds):"
        ).grid(
            row=1,
            column=0,
            sticky="w",
            padx=5,
            pady=5
        )

        self.max_dwell_var = tk.StringVar(value="")

        ttk.Entry(
            options_frame,
            textvariable=self.max_dwell_var,
            width=10
        ).grid(
            row=1,
            column=1,
            sticky="w",
            padx=5,
            pady=5
        )

        ttk.Label(
            options_frame,
            text="Leave empty for no maximum"
        ).grid(
            row=1,
            column=2,
            sticky="w",
            padx=5,
            pady=5
        )

        # Median
        self.show_median_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(
            options_frame,
            text="Show median dwell time",
            variable=self.show_median_var
        ).grid(
            row=2,
            column=0,
            columnspan=3,
            sticky="w",
            padx=5,
            pady=5
        )

        # Counts
        self.show_count_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(
            options_frame,
            text="Show number of visits per hour",
            variable=self.show_count_var
        ).grid(
            row=3,
            column=0,
            columnspan=3,
            sticky="w",
            padx=5,
            pady=5
        )

        # Individual files
        self.separate_files_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(
            options_frame,
            text="Show mean dwell separately for each CSV",
            variable=self.separate_files_var
        ).grid(
            row=4,
            column=0,
            columnspan=3,
            sticky="w",
            padx=5,
            pady=5
        )

        # -----------------------------------------------------
        # ACTION BUTTONS
        # -----------------------------------------------------
        action_frame = ttk.Frame(main)
        action_frame.pack(fill="x", pady=12)

        ttk.Button(
            action_frame,
            text="Create Graphs",
            command=self.create_graph
        ).pack(
            side="left",
            padx=(0, 8)
        )

        ttk.Button(
            action_frame,
            text="Export Summary CSV",
            command=self.export_summary
        ).pack(
            side="left"
        )

        # -----------------------------------------------------
        # INFO
        # -----------------------------------------------------
        info = (
            "Visits are grouped by the hour of global_start. "
            "Dwell time is converted from seconds to minutes."
        )

        ttk.Label(
            main,
            text=info
        ).pack(
            anchor="w",
            pady=(5, 0)
        )

    # =========================================================
    # FILE MANAGEMENT
    # =========================================================
    def add_files(self):
        """
        Add CSV files without deleting files that were
        previously selected.
        """
        files = filedialog.askopenfilenames(
            title="Add CSV Files",
            filetypes=[
                ("CSV files", "*.csv"),
                ("All files", "*.*")
            ]
        )

        if not files:
            return

        for file_path in files:

            # Avoid adding the same file twice
            if file_path not in self.file_paths:
                self.file_paths.append(file_path)

        self.update_file_list()

    def remove_selected(self):
        """
        Remove selected files from the list.
        """
        selected_indices = list(
            self.file_listbox.curselection()
        )

        if not selected_indices:
            return

        # Delete from bottom to top
        for index in reversed(selected_indices):
            del self.file_paths[index]

        self.update_file_list()

    def clear_files(self):
        """
        Remove all files.
        """
        self.file_paths = []
        self.update_file_list()

    def update_file_list(self):
        """
        Refresh the visible list of selected files.
        """
        self.file_listbox.delete(0, tk.END)

        for file_path in self.file_paths:

            # Show folder + filename
            self.file_listbox.insert(
                tk.END,
                file_path
            )

        self.file_count_label.config(
            text=f"{len(self.file_paths)} files selected"
        )

    # =========================================================
    # LOAD DATA
    # =========================================================
    def load_data(self):

        if not self.file_paths:

            messagebox.showwarning(
                "No Files",
                "Please add at least one CSV file."
            )

            return None

        all_data = []

        for file_path in self.file_paths:

            try:
                df = pd.read_csv(file_path)

            except Exception as e:

                messagebox.showerror(
                    "File Error",
                    f"Could not read:\n\n"
                    f"{file_path}\n\n"
                    f"{e}"
                )

                continue

            # -------------------------------------------------
            # Check columns
            # -------------------------------------------------
            required_columns = [
                "global_start",
                "dwell_sec"
            ]

            missing = [
                column
                for column in required_columns
                if column not in df.columns
            ]

            if missing:

                messagebox.showerror(
                    "Missing Columns",
                    f"File:\n"
                    f"{os.path.basename(file_path)}\n\n"
                    f"Missing columns:\n"
                    f"{', '.join(missing)}"
                )

                continue

            # -------------------------------------------------
            # Timestamp
            # -------------------------------------------------
            df["global_start"] = pd.to_datetime(
                df["global_start"],
                errors="coerce",
                dayfirst=True
            )

            # -------------------------------------------------
            # Dwell
            # -------------------------------------------------
            df["dwell_sec"] = pd.to_numeric(
                df["dwell_sec"],
                errors="coerce"
            )

            df = df.dropna(
                subset=[
                    "global_start",
                    "dwell_sec"
                ]
            )

            # Store source file
            df["source_file"] = os.path.basename(
                file_path
            )

            all_data.append(df)

        if not all_data:

            messagebox.showwarning(
                "No Data",
                "No valid data could be loaded."
            )

            return None

        # Combine everything
        combined = pd.concat(
            all_data,
            ignore_index=True
        )

        # -----------------------------------------------------
        # Minimum dwell
        # -----------------------------------------------------
        try:
            min_dwell = float(
                self.min_dwell_var.get()
            )

        except ValueError:

            messagebox.showerror(
                "Invalid Value",
                "Minimum dwell time must be a number."
            )

            return None

        combined = combined[
            combined["dwell_sec"] >= min_dwell
        ].copy()

        # -----------------------------------------------------
        # Maximum dwell
        # -----------------------------------------------------
        max_text = self.max_dwell_var.get().strip()

        if max_text:

            try:
                max_dwell = float(max_text)

            except ValueError:

                messagebox.showerror(
                    "Invalid Value",
                    "Maximum dwell time must be a number."
                )

                return None

            combined = combined[
                combined["dwell_sec"] <= max_dwell
            ].copy()

        if combined.empty:

            messagebox.showwarning(
                "No Data",
                "No visits remain after filtering."
            )

            return None

        # -----------------------------------------------------
        # Hour
        # -----------------------------------------------------
        combined["hour"] = (
            combined["global_start"].dt.hour
        )

        # Convert seconds → minutes
        combined["dwell_min"] = (
            combined["dwell_sec"] / 60
        )

        return combined

    # =========================================================
    # SUMMARY
    # =========================================================
    def calculate_summary(self, df):

        summary = (
            df
            .groupby("hour")
            .agg(
                mean_dwell_min=(
                    "dwell_min",
                    "mean"
                ),
                median_dwell_min=(
                    "dwell_min",
                    "median"
                ),
                std_dwell_min=(
                    "dwell_min",
                    "std"
                ),
                visit_count=(
                    "dwell_min",
                    "count"
                )
            )
            .reset_index()
        )

        # Make sure hours 0–23 exist
        hours = pd.DataFrame({
            "hour": range(24)
        })

        summary = hours.merge(
            summary,
            on="hour",
            how="left"
        )

        return summary

    # =========================================================
    # GRAPHS
    # =========================================================
    def create_graph(self):

        df = self.load_data()

        if df is None:
            return

        summary = self.calculate_summary(df)

        # =====================================================
        # GRAPH 1 - DWELL
        # =====================================================
        plt.figure(
            figsize=(12, 6)
        )

        valid = summary.dropna(
            subset=["mean_dwell_min"]
        )

        plt.plot(
            valid["hour"],
            valid["mean_dwell_min"],
            marker="o",
            linewidth=2,
            label="Mean"
        )

        # Median
        if self.show_median_var.get():

            valid_median = summary.dropna(
                subset=["median_dwell_min"]
            )

            plt.plot(
                valid_median["hour"],
                valid_median["median_dwell_min"],
                marker="s",
                linestyle="--",
                linewidth=2,
                label="Median"
            )

        # -----------------------------------------------------
        # Individual CSVs
        # -----------------------------------------------------
        if (
            self.separate_files_var.get()
            and len(self.file_paths) > 1
        ):

            for file_name, group in df.groupby(
                "source_file"
            ):

                file_summary = (
                    group
                    .groupby("hour")["dwell_min"]
                    .mean()
                )

                plt.plot(
                    file_summary.index,
                    file_summary.values,
                    marker=".",
                    linestyle=":",
                    alpha=0.65,
                    label=file_name
                )

        plt.xlabel(
            "Hour of Day"
        )

        plt.ylabel(
            "Dwell Time (minutes)"
        )

        plt.title(
            "Dwell Time by Hour of Day"
        )

        plt.xticks(
            range(24),
            [
                f"{hour:02d}:00"
                for hour in range(24)
            ],
            rotation=45
        )

        plt.grid(
            True,
            alpha=0.3
        )

        plt.legend()

        plt.tight_layout()

        plt.show()

        # =====================================================
        # GRAPH 2 - NUMBER OF VISITS
        # =====================================================
        if self.show_count_var.get():

            valid_count = summary[
                summary["visit_count"].notna()
            ]

            plt.figure(
                figsize=(12, 5)
            )

            plt.bar(
                valid_count["hour"],
                valid_count["visit_count"]
            )

            plt.xlabel(
                "Hour of Day"
            )

            plt.ylabel(
                "Number of Visits"
            )

            plt.title(
                "Number of Visits by Hour"
            )

            plt.xticks(
                range(24),
                [
                    f"{hour:02d}:00"
                    for hour in range(24)
                ],
                rotation=45
            )

            plt.grid(
                axis="y",
                alpha=0.3
            )

            plt.tight_layout()

            plt.show()

    # =========================================================
    # EXPORT SUMMARY
    # =========================================================
    def export_summary(self):

        df = self.load_data()

        if df is None:
            return

        summary = self.calculate_summary(df)

        save_path = filedialog.asksaveasfilename(
            title="Save Hourly Dwell Summary",
            defaultextension=".csv",
            filetypes=[
                ("CSV files", "*.csv")
            ],
            initialfile="hourly_dwell_summary.csv"
        )

        if not save_path:
            return

        summary.to_csv(
            save_path,
            index=False
        )

        messagebox.showinfo(
            "Saved",
            f"Summary saved successfully:\n\n"
            f"{save_path}"
        )


# =============================================================
# RUN
# =============================================================
if __name__ == "__main__":

    root = tk.Tk()

    app = DwellTimeByHourUI(root)

    root.mainloop()