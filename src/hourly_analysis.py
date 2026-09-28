import os
import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import matplotlib.pyplot as plt


FACTOR = 1.2


class HourlyVisitorUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Hourly Visitor Graphs")
        self.root.geometry("780x520")

        self.file_paths = []
        self.df = None

        self.build_ui()

    # ---------------------------------------------------------
    # UI
    # ---------------------------------------------------------
    def build_ui(self):
        main = ttk.Frame(self.root, padding=15)
        main.pack(fill="both", expand=True)

        # Files
        file_frame = ttk.LabelFrame(main, text="CSV Files", padding=10)
        file_frame.pack(fill="both", expand=True, pady=(0, 10))

        button_frame = ttk.Frame(file_frame)
        button_frame.pack(fill="x", pady=(0, 10))

        ttk.Button(
            button_frame,
            text="Choose CSV Files",
            command=self.choose_files
        ).pack(side="left")

        ttk.Button(
            button_frame,
            text="Clear Files",
            command=self.clear_files
        ).pack(side="left", padx=10)

        self.file_listbox = tk.Listbox(file_frame, height=10)
        self.file_listbox.pack(fill="both", expand=True)

        # Settings
        info_frame = ttk.LabelFrame(main, text="Settings", padding=10)
        info_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(
            info_frame,
            text=f"Visitor count factor: ×{FACTOR}"
        ).pack(anchor="w")

        ttk.Label(
            info_frame,
            text=(
                "Hourly visitor counts are multiplied by 1.2 and rounded. "
                "Direction ratios are calculated from the original A/B counts."
            )
        ).pack(anchor="w")

        self.status_label = ttk.Label(
            info_frame,
            text="No files selected."
        )
        self.status_label.pack(anchor="w", pady=(5, 0))

        # Actions
        action_frame = ttk.Frame(main)
        action_frame.pack(fill="x")

        ttk.Button(
            action_frame,
            text="Create All Graphs",
            command=self.create_graphs
        ).pack(side="left")

        ttk.Button(
            action_frame,
            text="Export Data to CSV",
            command=self.export_data
        ).pack(side="left", padx=10)

    # ---------------------------------------------------------
    # File selection
    # ---------------------------------------------------------
    def choose_files(self):
        files = filedialog.askopenfilenames(
            title="Choose CSV Files",
            filetypes=[("CSV files", "*.csv")]
        )

        if not files:
            return

        for file in files:
            if file not in self.file_paths:
                self.file_paths.append(file)

        self.update_file_list()

    def clear_files(self):
        self.file_paths = []
        self.df = None

        self.file_listbox.delete(0, tk.END)
        self.status_label.config(text="No files selected.")

    def update_file_list(self):
        self.file_listbox.delete(0, tk.END)

        for path in self.file_paths:
            self.file_listbox.insert(
                tk.END,
                os.path.basename(path)
            )

        self.status_label.config(
            text=f"{len(self.file_paths)} file(s) selected."
        )

    # ---------------------------------------------------------
    # Load data
    # ---------------------------------------------------------
    def load_data(self):
        if not self.file_paths:
            messagebox.showwarning(
                "No Files",
                "Please select at least one CSV file."
            )
            return False

        dataframes = []

        for path in self.file_paths:
            try:
                df = pd.read_csv(path)

                required_columns = [
                    "global_start",
                    "direction"
                ]

                for column in required_columns:
                    if column not in df.columns:
                        messagebox.showerror(
                            "Missing Column",
                            f"'{column}' was not found in:\n\n"
                            f"{os.path.basename(path)}"
                        )
                        return False

                df["source_file"] = os.path.basename(path)

                dataframes.append(df)

            except Exception as e:
                messagebox.showerror(
                    "Error",
                    f"Could not read:\n{path}\n\n{e}"
                )
                return False

        # Combine files
        self.df = pd.concat(
            dataframes,
            ignore_index=True
        )

        # Parse timestamps
        self.df["global_start"] = pd.to_datetime(
            self.df["global_start"],
            dayfirst=True,
            errors="coerce"
        )

        bad_rows = self.df["global_start"].isna().sum()

        self.df = self.df.dropna(
            subset=["global_start"]
        ).copy()

        if self.df.empty:
            messagebox.showerror(
                "No Valid Data",
                "No valid global_start timestamps were found."
            )
            return False

        # Clean direction
        self.df["direction"] = (
            self.df["direction"]
            .astype(str)
            .str.strip()
            .str.upper()
        )

        # Only A / B directions
        valid_direction = self.df["direction"].isin(["A", "B"])

        invalid_directions = (~valid_direction).sum()

        # Date/hour
        self.df["date"] = self.df["global_start"].dt.date
        self.df["hour"] = self.df["global_start"].dt.hour

        number_days = self.df["date"].nunique()

        status = (
            f"{len(self.df):,} rows loaded | "
            f"{number_days} unique day(s)"
        )

        if bad_rows > 0:
            status += f" | {bad_rows} invalid timestamps ignored"

        if invalid_directions > 0:
            status += (
                f" | {invalid_directions} rows do not have A/B direction"
            )

        self.status_label.config(text=status)

        return True

    # ---------------------------------------------------------
    # Hourly data
    # ---------------------------------------------------------
    def calculate_hourly_data(self):
        all_hours = pd.Index(
            range(24),
            name="hour"
        )

        dates = sorted(self.df["date"].unique())

        daily_frames = []

        # -----------------------------------------------------
        # Each day
        # -----------------------------------------------------
        for date in dates:
            temp = self.df[
                self.df["date"] == date
            ]

            hourly = (
                temp.groupby("hour")
                .size()
                .reindex(all_hours, fill_value=0)
            )

            day_df = pd.DataFrame({
                "date": date,
                "hour": range(24),
                "raw_count": hourly.values
            })

            day_df["factored_count"] = (
                day_df["raw_count"] * FACTOR
            ).round().astype(int)

            daily_frames.append(day_df)

        daily = pd.concat(
            daily_frames,
            ignore_index=True
        )

        # -----------------------------------------------------
        # All days together
        # -----------------------------------------------------
        total = (
            daily.groupby("hour")["raw_count"]
            .sum()
            .reindex(all_hours, fill_value=0)
            .reset_index()
        )

        total["factored_count"] = (
            total["raw_count"] * FACTOR
        ).round().astype(int)

        # -----------------------------------------------------
        # Average day
        # -----------------------------------------------------
        number_days = len(dates)

        average = pd.DataFrame({
            "hour": range(24),
            "raw_average":
                total["raw_count"] / number_days
        })

        average["factored_average"] = (
            average["raw_average"] * FACTOR
        ).round().astype(int)

        return daily, total, average

    # ---------------------------------------------------------
    # Direction ratios
    # ---------------------------------------------------------
    def calculate_direction_ratios(self):
        # Only rows with valid direction
        direction_df = self.df[
            self.df["direction"].isin(["A", "B"])
        ].copy()

        dates = sorted(self.df["date"].unique())

        daily_ratios = []

        # -----------------------------------------------------
        # Per day
        # -----------------------------------------------------
        for date in dates:
            day_df = direction_df[
                direction_df["date"] == date
            ]

            count_a = (
                day_df["direction"] == "A"
            ).sum()

            count_b = (
                day_df["direction"] == "B"
            ).sum()

            total = count_a + count_b

            if total > 0:
                percent_a = count_a / total * 100
                percent_b = count_b / total * 100
            else:
                percent_a = 0
                percent_b = 0

            daily_ratios.append({
                "date": date,
                "A_count": count_a,
                "B_count": count_b,
                "total_direction": total,
                "A_percent": percent_a,
                "B_percent": percent_b
            })

        daily_ratio_df = pd.DataFrame(daily_ratios)

        # -----------------------------------------------------
        # All days
        # -----------------------------------------------------
        all_a = (
            direction_df["direction"] == "A"
        ).sum()

        all_b = (
            direction_df["direction"] == "B"
        ).sum()

        all_total = all_a + all_b

        if all_total > 0:
            all_a_percent = all_a / all_total * 100
            all_b_percent = all_b / all_total * 100
        else:
            all_a_percent = 0
            all_b_percent = 0

        overall_ratio = pd.DataFrame([{
            "A_count": all_a,
            "B_count": all_b,
            "total_direction": all_total,
            "A_percent": all_a_percent,
            "B_percent": all_b_percent
        }])

        return daily_ratio_df, overall_ratio

    # ---------------------------------------------------------
    # Standard graph formatting
    # ---------------------------------------------------------
    def format_hourly_graph(self, title):
        plt.title(title)
        plt.xlabel("Hour")
        plt.ylabel("Visitors")

        plt.xticks(
            range(24),
            [f"{h:02d}:00" for h in range(24)],
            rotation=45
        )

        plt.grid(
            axis="y",
            alpha=0.3
        )

        plt.tight_layout()

    # ---------------------------------------------------------
    # Create graphs
    # ---------------------------------------------------------
    def create_graphs(self):
        if not self.load_data():
            return

        daily, total, average = self.calculate_hourly_data()

        daily_ratios, overall_ratio = (
            self.calculate_direction_ratios()
        )

        dates = sorted(daily["date"].unique())

        # =====================================================
        # 1. Hourly graph for every day
        # =====================================================
        for date in dates:
            day_df = daily[
                daily["date"] == date
            ]

            plt.figure(figsize=(12, 6))

            plt.bar(
                day_df["hour"],
                day_df["factored_count"]
            )

            self.format_hourly_graph(
                f"Hourly Visitors - {date} "
                f"(×{FACTOR}, rounded)"
            )

        # =====================================================
        # 2. All days together
        # =====================================================
        plt.figure(figsize=(12, 6))

        plt.bar(
            total["hour"],
            total["factored_count"]
        )

        self.format_hourly_graph(
            f"Hourly Visitors - All Days Together "
            f"(×{FACTOR}, rounded)"
        )

        # =====================================================
        # 3. Average day
        # =====================================================
        plt.figure(figsize=(12, 6))

        plt.bar(
            average["hour"],
            average["factored_average"]
        )

        self.format_hourly_graph(
            f"Average Hourly Visitors "
            f"(All Days / {len(dates)} Days, "
            f"×{FACTOR}, rounded)"
        )

        # =====================================================
        # 4. Direction ratio per day
        # =====================================================
        for _, row in daily_ratios.iterrows():
            date = row["date"]

            a = row["A_percent"]
            b = row["B_percent"]

            a_count = int(row["A_count"])
            b_count = int(row["B_count"])

            plt.figure(figsize=(7, 6))

            bars = plt.bar(
                ["A", "B"],
                [a, b]
            )

            plt.title(
                f"Direction Ratio - {date}"
            )

            plt.ylabel("Percentage (%)")

            plt.ylim(0, 100)

            plt.grid(
                axis="y",
                alpha=0.3
            )

            # Percentage + count above bars
            for bar, percentage, count in zip(
                bars,
                [a, b],
                [a_count, b_count]
            ):
                plt.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 2,
                    f"{percentage:.1f}%\n(n={count})",
                    ha="center",
                    va="bottom"
                )

            plt.tight_layout()

        # =====================================================
        # 5. Direction ratio - all days
        # =====================================================
        row = overall_ratio.iloc[0]

        a = row["A_percent"]
        b = row["B_percent"]

        a_count = int(row["A_count"])
        b_count = int(row["B_count"])

        plt.figure(figsize=(7, 6))

        bars = plt.bar(
            ["A", "B"],
            [a, b]
        )

        plt.title(
            "Direction Ratio - All Days Together"
        )

        plt.ylabel("Percentage (%)")

        plt.ylim(0, 100)

        plt.grid(
            axis="y",
            alpha=0.3
        )

        for bar, percentage, count in zip(
            bars,
            [a, b],
            [a_count, b_count]
        ):
            plt.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 2,
                f"{percentage:.1f}%\n(n={count})",
                ha="center",
                va="bottom"
            )

        plt.tight_layout()

        plt.show()

    # ---------------------------------------------------------
    # Export calculations
    # ---------------------------------------------------------
    def export_data(self):
        if not self.load_data():
            return

        daily, total, average = self.calculate_hourly_data()

        daily_ratios, overall_ratio = (
            self.calculate_direction_ratios()
        )

        output_folder = filedialog.askdirectory(
            title="Choose Output Folder"
        )

        if not output_folder:
            return

        daily.to_csv(
            os.path.join(
                output_folder,
                "hourly_by_day.csv"
            ),
            index=False
        )

        total.to_csv(
            os.path.join(
                output_folder,
                "hourly_all_days.csv"
            ),
            index=False
        )

        average.to_csv(
            os.path.join(
                output_folder,
                "hourly_average_day.csv"
            ),
            index=False
        )

        daily_ratios.to_csv(
            os.path.join(
                output_folder,
                "direction_ratio_by_day.csv"
            ),
            index=False
        )

        overall_ratio.to_csv(
            os.path.join(
                output_folder,
                "direction_ratio_all_days.csv"
            ),
            index=False
        )

        messagebox.showinfo(
            "Done",
            "All hourly and direction data exported successfully."
        )


# -------------------------------------------------------------
# Main
# -------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = HourlyVisitorUI(root)
    root.mainloop()