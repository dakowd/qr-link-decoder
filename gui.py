"""
Desktop GUI for decoding QR codes from redirect links in a spreadsheet.

Pick a file, pick the column that holds the links, watch it run, get a
summary. No command line required. Packaged into a standalone .exe via
PyInstaller (see .github/workflows/build-windows.yml).
"""

import queue
import shutil
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from main import (
    QR_COL_NAME,
    process_rows,
    read_table,
    resolve_output_path,
    write_table,
)

APP_TITLE = "QR Link Decoder"


def guess_link_column(df):
    for col in df.columns:
        if col == QR_COL_NAME:
            continue
        sample = next((str(v).strip() for v in df[col] if str(v).strip()), "")
        if sample.startswith("http://") or sample.startswith("https://"):
            return col
    for col in df.columns:
        if col != QR_COL_NAME:
            return col
    return df.columns[0]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("720x560")
        self.minsize(640, 480)

        self.input_path = None
        self.df = None
        self.last_output_path = None
        self.cancel_event = threading.Event()
        self.log_queue = queue.Queue()
        self.running = False

        self._build_widgets()
        self.after(100, self._poll_log_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_widgets(self):
        pad = {"padx": 10, "pady": 6}

        file_frame = ttk.Frame(self)
        file_frame.pack(fill="x", **pad)
        ttk.Button(file_frame, text="Select File...", command=self.on_select_file).pack(side="left")
        self.file_label = ttk.Label(file_frame, text="No file selected", foreground="#555555")
        self.file_label.pack(side="left", padx=10)

        col_frame = ttk.Frame(self)
        col_frame.pack(fill="x", **pad)
        ttk.Label(col_frame, text="Which column has the QR links?").pack(side="left")
        self.column_var = tk.StringVar()
        self.column_combo = ttk.Combobox(
            col_frame, textvariable=self.column_var, state="disabled", width=40
        )
        self.column_combo.pack(side="left", padx=10)

        out_frame = ttk.LabelFrame(self, text="Output")
        out_frame.pack(fill="x", **pad)
        self.output_mode = tk.StringVar(value="inplace")
        ttk.Radiobutton(
            out_frame,
            text="Update the file in place (a backup copy is saved automatically)",
            variable=self.output_mode,
            value="inplace",
            command=self._sync_output_state,
        ).pack(anchor="w", padx=6, pady=(4, 0))

        save_as_row = ttk.Frame(out_frame)
        save_as_row.pack(fill="x", anchor="w", padx=6, pady=(0, 6))
        ttk.Radiobutton(
            save_as_row,
            text="Save to a new file:",
            variable=self.output_mode,
            value="saveas",
            command=self._sync_output_state,
        ).pack(side="left")
        self.output_path_var = tk.StringVar()
        self.output_entry = ttk.Entry(
            save_as_row, textvariable=self.output_path_var, width=38, state="disabled"
        )
        self.output_entry.pack(side="left", padx=6)
        self.output_browse_btn = ttk.Button(
            save_as_row, text="Browse...", command=self.on_browse_output, state="disabled"
        )
        self.output_browse_btn.pack(side="left")

        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", **pad)
        self.start_btn = ttk.Button(action_frame, text="Start", command=self.on_start, state="disabled")
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(action_frame, text="Cancel", command=self.on_cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        self.open_folder_btn = ttk.Button(
            action_frame, text="Open Output Folder", command=self.on_open_folder, state="disabled"
        )
        self.open_folder_btn.pack(side="left", padx=6)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", **pad)

        self.summary_label = ttk.Label(self, text="", font=("", 11, "bold"))
        self.summary_label.pack(fill="x", padx=10)

        log_frame = ttk.Frame(self)
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=16, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.log_text.tag_config("error", foreground="#b00020")
        self.log_text.tag_config("ok", foreground="#0a7a0a")

    def _sync_output_state(self):
        saveas = self.output_mode.get() == "saveas"
        state = "normal" if saveas else "disabled"
        self.output_entry.configure(state=state)
        self.output_browse_btn.configure(state=state)

    def _log(self, text, tag=None):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def on_select_file(self):
        path_str = filedialog.askopenfilename(
            title="Select a spreadsheet",
            filetypes=[
                ("Spreadsheets", "*.csv *.xls *.xlsx"),
                ("All files", "*.*"),
            ],
        )
        if not path_str:
            return

        path = Path(path_str)
        try:
            df = read_table(path)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Couldn't read that file:\n\n{exc}")
            return

        if df.shape[1] < 1:
            messagebox.showerror(APP_TITLE, "That file has no columns to read links from.")
            return

        self.input_path = path
        self.df = df
        self.file_label.configure(text=str(path), foreground="#000000")

        self.column_combo.configure(values=list(df.columns), state="readonly")
        self.column_var.set(guess_link_column(df))

        default_output = path if path.suffix.lower() != ".xls" else path.with_suffix(".xlsx")
        self.output_path_var.set(str(default_output))

        self.start_btn.configure(state="normal")
        self.summary_label.configure(text="")
        self._log(f"Loaded {path.name} ({len(df)} rows, columns: {', '.join(df.columns)})")

    def on_browse_output(self):
        initial = self.output_path_var.get() or "output.xlsx"
        path_str = filedialog.asksaveasfilename(
            title="Save results as",
            initialfile=Path(initial).name,
            defaultextension=Path(initial).suffix or ".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv"), ("All files", "*.*")],
        )
        if path_str:
            self.output_path_var.set(path_str)

    def on_open_folder(self):
        if not self.last_output_path:
            return
        folder = self.last_output_path.parent
        import subprocess
        import sys as _sys

        try:
            if _sys.platform == "win32":
                subprocess.run(["explorer", str(folder)])
            elif _sys.platform == "darwin":
                subprocess.run(["open", str(folder)])
            else:
                subprocess.run(["xdg-open", str(folder)])
        except Exception:
            pass

    def on_start(self):
        if self.running or self.df is None:
            return

        link_col = self.column_var.get()
        if not link_col:
            messagebox.showerror(APP_TITLE, "Pick which column holds the links first.")
            return

        if self.output_mode.get() == "saveas":
            output_path_str = self.output_path_var.get().strip()
            if not output_path_str:
                messagebox.showerror(APP_TITLE, "Choose a location to save results to.")
                return
            output_path = Path(output_path_str)
        else:
            output_path, note = resolve_output_path(self.input_path)
            if note:
                self._log(note)
            if output_path == self.input_path:
                backup_path = self.input_path.with_suffix(self.input_path.suffix + ".bak")
                shutil.copy2(self.input_path, backup_path)
                self._log(f"Backup written to {backup_path}")

        self.last_output_path = output_path
        self.cancel_event.clear()
        self.running = True
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.open_folder_btn.configure(state="disabled")
        self.summary_label.configure(text="")
        self.progress.configure(value=0, maximum=max(len(self.df), 1))
        self._log(f"\nStarting — reading links from column {link_col!r}...")

        # Reuse self.df (not a copy) so a cancelled-and-restarted run picks up
        # where it left off, same as re-running the CLI on a partially done file.
        worker = threading.Thread(
            target=self._run_worker, args=(self.df, link_col, output_path), daemon=True
        )
        worker.start()

    def _run_worker(self, df, link_col, output_path):
        def on_progress(i, total, url, status, detail):
            self.log_queue.put(("progress", i, total, url, status, detail))

        try:
            processed, failed = process_rows(
                df,
                link_col,
                output_path,
                on_progress=on_progress,
                should_cancel=self.cancel_event.is_set,
            )
            cancelled = self.cancel_event.is_set()
            self.log_queue.put(("done", processed, failed, output_path, cancelled))
        except Exception:
            self.log_queue.put(("error", traceback.format_exc()))

    def on_cancel(self):
        if self.running:
            self.cancel_event.set()
            self.cancel_btn.configure(state="disabled")
            self._log("Cancelling after the current row finishes...")

    def _poll_log_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                kind = item[0]

                if kind == "progress":
                    _, i, total, url, status, detail = item
                    self.progress.configure(maximum=total, value=i + 1)
                    if status == "ok":
                        self._log(f"[{i + 1}/{total}] {url} ... OK", tag="ok")
                    else:
                        self._log(f"[{i + 1}/{total}] {url} ... FAILED ({detail})", tag="error")

                elif kind == "done":
                    _, processed, failed, output_path, cancelled = item
                    self.running = False
                    self.start_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    self.open_folder_btn.configure(state="normal")
                    prefix = "Cancelled. " if cancelled else "Done. "
                    summary = f"{prefix}{processed} decoded, {failed} failed. Saved to {output_path}"
                    self.summary_label.configure(text=summary)
                    self._log(summary)
                    messagebox.showinfo(APP_TITLE, summary)

                elif kind == "error":
                    _, tb = item
                    self.running = False
                    self.start_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    self._log(f"Unexpected error:\n{tb}", tag="error")
                    messagebox.showerror(APP_TITLE, f"Something went wrong:\n\n{tb}")
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll_log_queue)

    def _on_close(self):
        if self.running:
            if not messagebox.askyesno(
                APP_TITLE, "A run is still in progress. Quit anyway?"
            ):
                return
            self.cancel_event.set()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
