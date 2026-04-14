#!/usr/bin/env python3
"""Windows-friendly desktop wrapper for clean_and_fit_pdf.py."""

from __future__ import annotations

import os
import queue
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from clean_and_fit_pdf import (
    OBJECT_STREAM_CHOICES,
    ProcessingOptions,
    default_output_path,
    format_result_summary,
    load_pdf_backend,
    load_pymupdf,
    load_pikepdf,
    process_pdf,
    resolve_pdftoppm,
)


class CleanAndFitPdfApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Clean and Fit PDF")
        self.geometry("920x720")
        self.minsize(800, 640)

        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.latest_output: Path | None = None
        self.last_auto_output = ""

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.page_var = tk.StringVar(value="1")
        self.wrapper_groups_var = tk.StringVar(value="2")
        self.padding_var = tk.StringVar(value="0")
        self.dpi_var = tk.StringVar(value="1200")
        self.pdftoppm_var = tk.StringVar()
        self.deps_dir_var = tk.StringVar(value=str(Path(".pydeps")))
        self.precision_var = tk.StringVar(value="6")
        self.object_streams_var = tk.StringVar(value="disable")
        self.tmp_dir_var = tk.StringVar(value=str(Path("tmp/pdfs")))
        self.acrobat_fix_var = tk.BooleanVar(value=True)
        self.linearize_var = tk.BooleanVar(value=False)
        self.keep_temp_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Choose an input PDF to begin.")

        self._build_ui()
        self.input_var.trace_add("write", self._handle_input_change)
        self._apply_environment_hints()
        self.after(125, self._poll_queue)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root = ttk.Frame(self, padding=14)
        root.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        files_frame = ttk.LabelFrame(root, text="Files", padding=10)
        files_frame.grid(row=0, column=0, sticky="ew")
        files_frame.columnconfigure(1, weight=1)

        self._add_path_row(
            files_frame,
            row=0,
            label="Input PDF",
            variable=self.input_var,
            browse_command=self._choose_input_pdf,
        )
        self._add_path_row(
            files_frame,
            row=1,
            label="Output PDF",
            variable=self.output_var,
            browse_command=self._choose_output_pdf,
            browse_label="Save As...",
        )

        options_frame = ttk.LabelFrame(root, text="Options", padding=10)
        options_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for column in range(4):
            options_frame.columnconfigure(column, weight=1)

        self._add_labeled_entry(options_frame, 0, 0, "Page", self.page_var, width=10)
        self._add_labeled_entry(
            options_frame, 0, 1, "Wrapper Groups", self.wrapper_groups_var, width=10
        )
        self._add_labeled_entry(
            options_frame, 0, 2, "Padding (pt)", self.padding_var, width=10
        )
        self._add_labeled_entry(options_frame, 0, 3, "DPI", self.dpi_var, width=10)
        self._add_labeled_entry(
            options_frame, 1, 0, "Precision", self.precision_var, width=10
        )

        object_streams_frame = ttk.Frame(options_frame)
        object_streams_frame.grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        ttk.Label(object_streams_frame, text="Object Streams").grid(
            row=0, column=0, sticky="w"
        )
        self.object_streams_combo = ttk.Combobox(
            object_streams_frame,
            state="readonly",
            values=sorted(OBJECT_STREAM_CHOICES),
            textvariable=self.object_streams_var,
            width=16,
        )
        self.object_streams_combo.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        toggles_frame = ttk.Frame(options_frame)
        toggles_frame.grid(row=1, column=2, columnspan=2, sticky="w", padx=4, pady=4)
        self.acrobat_fix_check = ttk.Checkbutton(
            toggles_frame, text="Acrobat fix", variable=self.acrobat_fix_var
        )
        self.acrobat_fix_check.grid(row=0, column=0, sticky="w")
        self.linearize_check = ttk.Checkbutton(
            toggles_frame, text="Linearize PDF", variable=self.linearize_var
        )
        self.linearize_check.grid(row=1, column=0, sticky="w")
        self.keep_temp_check = ttk.Checkbutton(
            toggles_frame, text="Keep temp files", variable=self.keep_temp_var
        )
        self.keep_temp_check.grid(row=2, column=0, sticky="w")

        advanced_frame = ttk.LabelFrame(root, text="Advanced", padding=10)
        advanced_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        advanced_frame.columnconfigure(1, weight=1)

        self._add_path_row(
            advanced_frame,
            row=0,
            label="Fallback pdftoppm",
            variable=self.pdftoppm_var,
            browse_command=self._choose_pdftoppm,
            browse_label="Browse...",
        )
        self._add_path_row(
            advanced_frame,
            row=1,
            label="Deps Dir",
            variable=self.deps_dir_var,
            browse_command=self._choose_deps_dir,
            browse_label="Browse...",
        )
        self._add_path_row(
            advanced_frame,
            row=2,
            label="Temp Dir",
            variable=self.tmp_dir_var,
            browse_command=self._choose_tmp_dir,
            browse_label="Browse...",
        )
        ttk.Label(
            advanced_frame,
            text="Optional: only needed if the built-in PyMuPDF renderer is unavailable.",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        log_frame = ttk.LabelFrame(root, text="Progress", padding=10)
        log_frame.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = ScrolledText(log_frame, wrap="word", height=16)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

        actions = ttk.Frame(root)
        actions.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        actions.columnconfigure(1, weight=1)

        self.run_button = ttk.Button(actions, text="Run", command=self._start_run)
        self.run_button.grid(row=0, column=0, sticky="w")
        self.open_button = ttk.Button(
            actions,
            text="Open Output Folder",
            command=self._open_output_folder,
            state="disabled",
        )
        self.open_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(actions, textvariable=self.status_var).grid(
            row=0, column=2, sticky="e"
        )

    def _add_path_row(
        self,
        parent: ttk.LabelFrame | ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        browse_command,
        browse_label: str = "Browse...",
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", padx=(8, 8), pady=4)
        ttk.Button(parent, text=browse_label, command=browse_command).grid(
            row=row, column=2, sticky="e", pady=4
        )

    def _add_labeled_entry(
        self,
        parent: ttk.LabelFrame,
        row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
        width: int,
    ) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=column, sticky="ew", padx=4, pady=4)
        ttk.Label(frame, text=label).grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=variable, width=width).grid(
            row=1, column=0, sticky="ew", pady=(4, 0)
        )

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _handle_input_change(self, *_args) -> None:
        raw_input = self.input_var.get().strip()
        if not raw_input:
            return
        try:
            suggested = str(default_output_path(Path(raw_input)))
        except Exception:
            return
        current_output = self.output_var.get().strip()
        if not current_output or current_output == self.last_auto_output:
            self.output_var.set(suggested)
        self.last_auto_output = suggested

    def _apply_environment_hints(self) -> None:
        notes = []
        deps_dir = Path(self.deps_dir_var.get().strip() or ".pydeps")

        try:
            load_pdf_backend(deps_dir)
        except Exception as exc:
            notes.append(
                "PDF reader library missing. Install pypdf or PyPDF2 into the active "
                "Python or the dependency folder. "
                + str(exc)
            )

        try:
            load_pymupdf(deps_dir)
        except Exception:
            explicit_pdftoppm = self.pdftoppm_var.get().strip()
            try:
                resolve_pdftoppm(Path(explicit_pdftoppm) if explicit_pdftoppm else None)
            except Exception:
                notes.append(
                    "Built-in PyMuPDF rendering is unavailable, and pdftoppm was not "
                    "detected either. Add PyMuPDF to the runtime or browse to "
                    "pdftoppm.exe before running."
                )

        try:
            load_pikepdf(deps_dir)
        except Exception as exc:
            self.acrobat_fix_var.set(False)
            notes.append(
                "Acrobat fix has been unchecked because pikepdf is not ready in this "
                "Python environment. You can still run without it. "
                + str(exc)
            )

        if notes:
            self._append_log("Environment notes:")
            for note in notes:
                self._append_log(f"- {note}")
            self._append_log("")
            self.status_var.set("Review the environment notes below.")

    def _choose_input_pdf(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose Input PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if selected:
            self.input_var.set(selected)

    def _choose_output_pdf(self) -> None:
        initial_name = Path(self.output_var.get()).name if self.output_var.get() else ""
        selected = filedialog.asksaveasfilename(
            title="Choose Output PDF",
            defaultextension=".pdf",
            initialfile=initial_name,
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if selected:
            self.output_var.set(selected)

    def _choose_pdftoppm(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose pdftoppm.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if selected:
            self.pdftoppm_var.set(selected)

    def _choose_deps_dir(self) -> None:
        selected = filedialog.askdirectory(title="Choose Dependency Directory")
        if selected:
            self.deps_dir_var.set(selected)

    def _choose_tmp_dir(self) -> None:
        selected = filedialog.askdirectory(title="Choose Temporary Directory")
        if selected:
            self.tmp_dir_var.set(selected)

    def _build_options(self) -> ProcessingOptions:
        input_pdf = self.input_var.get().strip()
        output_pdf = self.output_var.get().strip()
        if not input_pdf:
            raise ValueError("Choose an input PDF first.")

        return ProcessingOptions(
            input_pdf=Path(input_pdf),
            output_pdf=Path(output_pdf) if output_pdf else None,
            page=int(self.page_var.get().strip()),
            wrapper_groups=int(self.wrapper_groups_var.get().strip()),
            padding=float(self.padding_var.get().strip()),
            acrobat_fix=self.acrobat_fix_var.get(),
            dpi=int(self.dpi_var.get().strip()),
            pdftoppm=Path(self.pdftoppm_var.get().strip())
            if self.pdftoppm_var.get().strip()
            else None,
            deps_dir=Path(self.deps_dir_var.get().strip()),
            precision=int(self.precision_var.get().strip()),
            linearize=self.linearize_var.get(),
            object_streams=self.object_streams_var.get().strip(),
            tmp_dir=Path(self.tmp_dir_var.get().strip()),
            keep_temp=self.keep_temp_var.get(),
        )

    def _set_running(self, is_running: bool) -> None:
        state = "disabled" if is_running else "normal"
        self.run_button.configure(state=state)
        self.open_button.configure(
            state="disabled" if is_running or self.latest_output is None else "normal"
        )

    def _start_run(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        try:
            options = self._build_options()
        except Exception as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self)
            return

        self.latest_output = None
        self._clear_log()
        self._append_log("Starting PDF cleanup and fit job.")
        self.status_var.set("Running...")
        self._set_running(True)

        def worker() -> None:
            try:
                result = process_pdf(
                    options, progress=lambda message: self.queue.put(("log", message))
                )
            except Exception as exc:
                self.queue.put(
                    (
                        "error",
                        str(exc),
                        traceback.format_exc(),
                    )
                )
                return
            self.queue.put(("done", result))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload, *extra = self.queue.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "done":
                    result = payload
                    self.latest_output = result.output_pdf
                    for line in format_result_summary(result):
                        self._append_log(line)
                    self.status_var.set("Finished")
                    self._set_running(False)
                    messagebox.showinfo(
                        "Completed",
                        f"Created:\n{result.output_pdf}",
                        parent=self,
                    )
                elif kind == "error":
                    self._append_log("")
                    self._append_log("The job failed.")
                    self._append_log(str(payload))
                    if extra:
                        self._append_log("")
                        self._append_log(str(extra[0]))
                    self.status_var.set("Failed")
                    self._set_running(False)
                    messagebox.showerror("Processing Failed", str(payload), parent=self)
        except queue.Empty:
            pass
        self.after(125, self._poll_queue)

    def _open_output_folder(self) -> None:
        if self.latest_output is None:
            return
        os.startfile(self.latest_output.parent)


def main() -> None:
    app = CleanAndFitPdfApp()
    app.mainloop()


if __name__ == "__main__":
    main()
