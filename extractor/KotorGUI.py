# KotorGUI.py
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import threading
import concurrent.futures
import traceback

from ResourceManager import ResourceManager
from ResourceTypes import ResourceTypeInfo
from Sanitize import sanitize_resref
from TPCToPNG import tpc_to_png, tpc_bytes_to_png_bytes
from ErfFormat import ERF
from GFFPreview import is_gff_type, gff_to_json, tlk_to_json


class KOTOR_GUI:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("KOTOR Resource Explorer")
        self.window.geometry("1200x700")

        self.rm = None              # active manager (KEY or ERF)
        self.rm_key = None          # persistent KEY manager
        self.rm_cache = {}          # erf_path -> ERF ResourceManager
        self.game_path = None
        self.current_bif_index = None
        self.current_type_filter = "All"
        self.archives = []
        self.found_archives = []

        self._build_ui()

    # ----------------------------------------------------------------------
    def _build_ui(self):
        top = tk.Frame(self.window)
        top.pack(fill="x", padx=8, pady=8)

        tk.Button(top, text="Select Game Path...", command=self.select_game_path).pack(side="left", padx=(0, 6))
        tk.Button(top, text="Load ERF/HAK/MOD...", command=self.load_erf_file).pack(side="left", padx=4)
        self.key_label = tk.Label(top, text="No KEY/ERF loaded")
        self.key_label.pack(side="left", padx=10)

        # ---- search bar
        filter_frame = tk.Frame(self.window)
        filter_frame.pack(fill="x", padx=8, pady=(0, 8))

        tk.Label(filter_frame, text="Search ResRef:").pack(side="left")
        self.search_entry = tk.Entry(filter_frame, width=30)
        self.search_entry.pack(side="left", padx=4)

        tk.Button(filter_frame, text="Search", command=self.search_resref).pack(side="left", padx=4)
        tk.Button(filter_frame, text="Search Files...", command=self.search_files).pack(side="left", padx=4)

        # ---- type filter
        tk.Label(filter_frame, text="Type filter:").pack(side="left", padx=(20, 4))
        self.type_var = tk.StringVar(value="All")
        self.type_combo = ttk.Combobox(filter_frame, textvariable=self.type_var, state="readonly")
        self.type_combo.pack(side="left")
        self.type_combo.bind("<<ComboboxSelected>>", self.on_type_filter_changed)

        # ---- split window
        split = tk.PanedWindow(self.window, orient=tk.HORIZONTAL)
        split.pack(fill="both", expand=True, padx=8, pady=8)

        # ---- BIF list
        bif_frame = tk.Frame(split)
        tk.Label(bif_frame, text="BIF Files").pack(anchor="w")

        bif_list_frame = tk.Frame(bif_frame)
        bif_list_frame.pack(fill="both", expand=True)
        self.bif_list = tk.Listbox(bif_list_frame, exportselection=False, height=25)
        bif_scroll = tk.Scrollbar(bif_list_frame, orient="vertical", command=self.bif_list.yview)
        self.bif_list.config(yscrollcommand=bif_scroll.set)
        self.bif_list.pack(side="left", fill="both", expand=True)
        bif_scroll.pack(side="right", fill="y")
        self.bif_list.bind("<<ListboxSelect>>", self.on_bif_selected)

        split.add(bif_frame, minsize=200, stretch="never")

        # ---- Archive list
        arch_frame = tk.Frame(split)
        tk.Label(arch_frame, text="Archives (ERF/HAK/MOD)").pack(anchor="w")

        arch_list_frame = tk.Frame(arch_frame)
        arch_list_frame.pack(fill="both", expand=True)
        self.archive_list = tk.Listbox(arch_list_frame, exportselection=False, height=25)
        arch_scroll = tk.Scrollbar(arch_list_frame, orient="vertical", command=self.archive_list.yview)
        self.archive_list.config(yscrollcommand=arch_scroll.set)
        self.archive_list.pack(side="left", fill="both", expand=True)
        arch_scroll.pack(side="right", fill="y")
        self.archive_list.bind("<<ListboxSelect>>", self.on_archive_selected)

        split.add(arch_frame, minsize=200, stretch="never")

        # ---- Resource list
        res_frame = tk.Frame(split)
        tk.Label(res_frame, text="Resources").pack(anchor="w")

        res_tree_frame = tk.Frame(res_frame)
        res_tree_frame.pack(fill="both", expand=True)

        columns = ("ResRef", "Type", "ResID", "BIF", "Index")
        self.res_tree = ttk.Treeview(res_tree_frame, columns=columns, show="headings", height=25)

        for col in columns:
            self.res_tree.heading(col, text=col)

        self.res_tree.column("ResRef", width=260)
        self.res_tree.column("Type", width=80, anchor="center")
        self.res_tree.column("ResID", width=200, anchor="center")
        self.res_tree.column("BIF", width=60, anchor="center")
        self.res_tree.column("Index", width=60, anchor="center")

        yscroll = tk.Scrollbar(res_tree_frame, orient="vertical", command=self.res_tree.yview)
        self.res_tree.config(yscrollcommand=yscroll.set)
        self.res_tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        self.res_tree.bind("<Double-1>", self.extract_selected_resource)

        split.add(res_frame, minsize=400, stretch="always")
        # give the resource pane more space initially
        self.window.after_idle(lambda: self._init_sashes(split))

        # ---- bottom bar
        bottom = tk.Frame(self.window)
        bottom.pack(fill="x", padx=8)

        tk.Button(bottom, text="Extract Selected Resource", command=self.extract_selected_resource).pack(side="left")
        tk.Button(bottom, text="Batch Export (ERF+BIFF)", command=self.batch_export_erf_archives).pack(side="left", padx=6)
        tk.Button(bottom, text="Batch Export Selected Archive", command=self.batch_export_selected_archive).pack(side="left", padx=6)
        tk.Button(bottom, text="Batch MDL Export", command=self.batch_export_mdl).pack(side="left", padx=6)

    def _init_sashes(self, paned: tk.PanedWindow):
        try:
            paned.update_idletasks()
            total = paned.winfo_width()
            if total <= 0:
                total = 1200
            # Allocate ~20% to BIF, ~20% to Archives, rest to Resources
            sash0 = int(total * 0.2)
            sash1 = int(total * 0.4)
            paned.sash_place(0, sash0, 0)
            paned.sash_place(1, sash1, 0)
        except Exception:
            pass

    # ----------------------------------------------------------------------
    def select_game_path(self):
        base_dir = filedialog.askdirectory(title="Select game path (folder containing chitin.key)")
        if not base_dir:
            return
        self.game_path = Path(base_dir)
        key_path = self.game_path / "chitin.key"
        if key_path.exists():
            try:
                self.rm_key = ResourceManager(key_path=str(key_path))
                self.rm = self.rm_key
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load {key_path}:\n{e}")
                return
            self.key_label.config(text=f"{key_path.name} (auto)")
            self.populate_bif_list()
            self.populate_type_filter()
            self.refresh_resource_view()
        else:
            messagebox.showinfo("Not found", "No chitin.key found in the selected path.")
            return

        # Discover archives (ERF/HAK/MOD/NWM/SAV) for batch operations
        try:
            from batch_export_erf import find_archives
            archives = find_archives(self.game_path, include_erf=True, include_mod=True, include_rim=True, include_hak=True)
            self.found_archives = archives
            self.populate_archive_list()
        except Exception:
            self.found_archives = []

    def load_erf_file(self):
        path = filedialog.askopenfilename(title="Select ERF/HAK/MOD/NWM/SAV", filetypes=[("ERF-like", "*.erf *.hak *.mod *.nwm *.sav"), ("All files", "*.*")])
        if not path:
            return

        try:
            self.rm = ResourceManager(erf_path=path)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        self.key_label.config(text=os.path.basename(path))
        # No BIF list in ERF mode
        self.bif_list.delete(0, tk.END)
        self.current_bif_index = None
        self.populate_type_filter()
        self.refresh_resource_view()

    # ----------------------------------------------------------------------
    def populate_bif_list(self):
        self.bif_list.delete(0, tk.END)
        if self.rm_key:
            for i, entry in enumerate(self.rm_key.key.file_table):
                self.bif_list.insert(tk.END, f"[{i}] {entry.Filename}")

    def populate_type_filter(self):
        if self.rm and self.rm.erf:
            types = sorted({e.ResType for e in self.rm.erf.entries})
        elif self.rm and self.rm.key:
            types = sorted({e.ResourceType for e in self.rm.key.key_table})
        else:
            types = []
        self.type_combo["values"] = ["All"] + [str(t) for t in types]
        self.type_var.set("All")

    def populate_archive_list(self):
        self.archive_list.delete(0, tk.END)
        for p in getattr(self, "found_archives", []):
            tag = Path(p).suffix.upper()
            self.archive_list.insert(tk.END, f"[{tag}] {p}")
        # include BIFs
        if self.rm_key:
            for i, entry in enumerate(self.rm_key.key.file_table):
                self.archive_list.insert(tk.END, f"[BIF {i}] {entry.Filename}")

    # ----------------------------------------------------------------------
    def refresh_resource_view(self):
        self.res_tree.delete(*self.res_tree.get_children())

        bif_filter = self.current_bif_index
        type_filter = None if self.type_var.get() == "All" else int(self.type_var.get())

        if self.rm and self.rm.erf:
            # ERF mode: no BIF filter; entries contain ResType/ResID but no BIF/EntryIndex
            for idx, e in enumerate(self.rm.erf.entries):
                if type_filter is not None and e.ResType != type_filter:
                    continue
                self.res_tree.insert(
                    "",
                    tk.END,
                    values=(
                        e.ResRef,
                        e.ResType,
                        e.ResID,
                        "-",  # no BIF
                        idx,  # use list index
                    ),
                )
        elif self.rm and self.rm.key:
            for e in self.rm.key.key_table:
                if bif_filter is not None and e.BIFIndex != bif_filter:
                    continue
                if type_filter is not None and e.ResourceType != type_filter:
                    continue

                self.res_tree.insert("", tk.END, values=(
                    e.ResRef,
                    e.ResourceType,
                    e.ResID,
                    e.BIFIndex,
                    e.EntryIndex
                ))

    # ----------------------------------------------------------------------
    def on_bif_selected(self, _event=None):
        sel = self.bif_list.curselection()
        self.current_bif_index = sel[0] if sel else None
        # ensure we're using KEY manager
        if self.rm_key:
            self.rm = self.rm_key
            self.populate_type_filter()
            self.refresh_resource_view()

    def on_type_filter_changed(self, _event=None):
        self.refresh_resource_view()

    def on_archive_selected(self, _event=None):
        sel = self.archive_list.curselection()
        if not sel:
            return
        item = self.archive_list.get(sel[0])
        # parse tag and path
        if "] " in item:
            tag_part, path_part = item.split("] ", 1)
            tag_part = tag_part.strip("[")
        else:
            tag_part, path_part = "", item
        if tag_part.upper().startswith("BIF"):
            # select BIF by index
            try:
                idx = int(tag_part.split()[-1])
            except Exception:
                idx = None
            if idx is not None and self.rm_key:
                self.rm = self.rm_key
                self.current_bif_index = idx
                self.bif_list.selection_clear(0, tk.END)
                self.populate_type_filter()
                self.refresh_resource_view()
        else:
            path = path_part
            try:
                if path not in self.rm_cache:
                    self.rm_cache[path] = ResourceManager(erf_path=path)
                self.rm = self.rm_cache[path]
                self.current_bif_index = None
                # clear bif selection
                self.bif_list.selection_clear(0, tk.END)
                self.populate_type_filter()
                self.refresh_resource_view()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load archive:\n{e}")

    def search_resref(self):
        q = self.search_entry.get().strip().lower()
        if not q:
            return

        for item in self.res_tree.get_children():
            resref = str(self.res_tree.item(item, "values")[0]).lower()
            if q in resref:
                self.res_tree.selection_set(item)
                self.res_tree.see(item)
                return

    def search_files(self):
        query = self.search_entry.get().strip()
        if not query:
            return messagebox.showinfo("Search Files", "Enter text to search for first.")

        initial_dir = str(self.game_path) if self.game_path else None
        base_dir = filedialog.askdirectory(title="Select folder to search recursively", initialdir=initial_dir)
        if not base_dir:
            return

        old_status = self.key_label.cget("text")
        self.key_label.config(text="Searching files...")

        def worker():
            matches = []
            query_l = query.lower()
            max_matches = 200  # cap to avoid huge dialogs

            try:
                for root, _dirs, files in os.walk(base_dir):
                    if len(matches) >= max_matches:
                        break
                    for fname in files:
                        if len(matches) >= max_matches:
                            break
                        path = Path(root) / fname
                        try:
                            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                                for lineno, line in enumerate(fh, 1):
                                    if query_l in line.lower():
                                        snippet = line.strip()
                                        matches.append((path, lineno, snippet))
                                        break  # one hit per file is enough for the summary
                        except (OSError, UnicodeDecodeError):
                            continue
            finally:
                def done():
                    self.key_label.config(text=old_status)
                    if matches:
                        preview = []
                        preview_limit = 50
                        for path, lineno, snippet in matches[:preview_limit]:
                            text = snippet
                            if len(text) > 120:
                                text = text[:117] + "..."
                            preview.append(f"{path}:{lineno} - {text}")
                        extra = ""
                        if len(matches) > preview_limit:
                            extra = f"\n...and {len(matches) - preview_limit} more matches"
                        messagebox.showinfo("Search Files", "\n".join(preview) + extra)
                    else:
                        messagebox.showinfo("Search Files", f"No matches found for \"{query}\" in {base_dir}.")
                self.window.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    # ----------------------------------------------------------------------
    def extract_selected_resource(self, _event=None):
        sel = self.res_tree.selection()
        if not sel:
            return messagebox.showinfo("No selection", "Select a resource first.")

        # Get table values
        values = self.res_tree.item(sel[0], "values")

        if self.rm.erf:
            idx = int(values[4])
            entry = self.rm.erf.entries[idx]
            res_type = entry.ResType
        else:
            entry_index = int(values[4])
            entry = self.rm.key.key_table[entry_index]
            res_type = entry.ResourceType

        resref = entry.ResRef

        out_dir = filedialog.askdirectory(title=f"Export: {resref}")
        if not out_dir:
            return

        try:
            final_paths = []

            # TPC -> PNG only
            if res_type in (2007, 3007):  # tpc / pc texture
                raw_path = self.rm.export_entry(entry, out_dir)
                raw_suffix = Path(raw_path).suffix.lower()
                if raw_suffix != ".png":
                    png_path = tpc_to_png(Path(raw_path))
                    final_paths.append(f"{raw_path}")
                    final_paths.append(f"{png_path}")
                else:
                    final_paths.append(f"{raw_path}")

            # MDL+MDX export
            elif res_type in (2002, 3008):  # mdl or mdx selected
                mdl_entry = entry if res_type == 2002 else self.rm.get_resource_entry(resref, resource_type=2002)
                mdx_entry = entry if res_type == 3008 else self.rm.get_resource_entry(resref, resource_type=3008)

                if not mdl_entry and not mdx_entry:
                    raise ValueError(f"No MDL/MDX entries found for {resref}")

                safe = sanitize_resref(resref)
                mdl_path = Path(out_dir) / f"{safe}.mdl" if mdl_entry else None
                mdx_path = Path(out_dir) / f"{safe}.mdx" if mdx_entry else None

                # Prompt overwrite if any target already exists
                existing = [p for p in (mdl_path, mdx_path) if p and p.exists()]
                if existing:
                    names = "\n".join(str(p) for p in existing)
                    if not messagebox.askyesno("Overwrite?", f"The following files exist:\n{names}\nOverwrite?"):
                        return

                raw_mdl = None
                raw_mdx = None
                if mdl_entry:
                    raw_mdl = self.rm.export_entry(mdl_entry, out_dir)
                    final_paths.append(f"{raw_mdl}")
                if mdx_entry:
                    raw_mdx = self.rm.export_entry(mdx_entry, out_dir)
                    final_paths.append(f"{raw_mdx}")

                if raw_mdl and not raw_mdx:
                    final_paths.append(f"(MDX missing for {resref})")
                elif raw_mdx and not raw_mdl:
                    final_paths.append(f"(MDL missing for {resref})")

                # Attempt to resolve and export referenced textures next to the model
                try:
                    tex_saved, tex_missing = self._export_model_textures(
                        Path(raw_mdl) if raw_mdl else None,
                        Path(raw_mdx) if raw_mdx else None,
                        Path(out_dir),
                    )
                    final_paths.extend(tex_saved)
                    if tex_missing:
                        final_paths.append(f"(Missing textures: {', '.join(tex_missing)})")
                except Exception as tex_err:
                    final_paths.append(f"(Texture export failed: {tex_err})")

            # All others: just export as-is
            else:
                raw_path = self.rm.export_entry(entry, out_dir)
                final_paths.append(f"{raw_path}")
                # Fallback: if the exported file is a TPC, also convert to PNG
                if Path(raw_path).suffix.lower() == ".tpc":
                    try:
                        png_path = tpc_to_png(Path(raw_path))
                        final_paths.append(f"{png_path}")
                    except Exception as tex_err:
                        final_paths.append(f"(Failed to convert texture {raw_path}: {tex_err})")

            messagebox.showinfo("Exported", "Saved:\n" + "\n".join(final_paths))
        except Exception as e:
            messagebox.showerror("Error", f"Export failed:\n{e}")

    # ----------------------------------------------------------------------
    def batch_export_erf_archives(self):
        if self.game_path:
            base_dir = self.game_path
        else:
            base_dir = filedialog.askdirectory(title="Select game folder (root) to scan for ERF/HAK/MOD/NWM/SAV")
            if not base_dir:
                return
        out_dir = filedialog.askdirectory(title="Select output folder for batch export")
        if not out_dir:
            return
        # Simple toggle dialog for which archive types to include
        opts = {"erf": tk.BooleanVar(value=True), "hak": tk.BooleanVar(value=True), "mod": tk.BooleanVar(value=True), "rim": tk.BooleanVar(value=False), "bif": tk.BooleanVar(value=True)}
        top = tk.Toplevel(self.window)
        top.title("Archive Types")
        tk.Label(top, text="Include:").pack(anchor="w", padx=6, pady=4)
        for label, var in (("ERF", opts["erf"]), ("HAK", opts["hak"]), ("MOD", opts["mod"]), ("RIM", opts["rim"]), ("BIF (via chitin.key)", opts["bif"])):
            tk.Checkbutton(top, text=label, variable=var).pack(anchor="w", padx=12)
        tk.Label(top, text="Select BIF indices (comma-separated, leave empty for all):").pack(anchor="w", padx=6, pady=(4,0))
        bif_entry = tk.Entry(top)
        bif_entry.pack(fill="x", padx=8)
        confirmed = {"ok": False}
        def do_ok():
            confirmed["ok"] = True
            top.destroy()
        def do_cancel():
            top.destroy()
        btns = tk.Frame(top)
        btns.pack(pady=6)
        tk.Button(btns, text="OK", command=do_ok).pack(side="left", padx=4)
        tk.Button(btns, text="Cancel", command=do_cancel).pack(side="left", padx=4)
        top.grab_set()
        self.window.wait_window(top)
        if not confirmed["ok"]:
            return

        # Run heavy work in a background thread to keep UI responsive
        def worker():
            try:
                from batch_export_erf import find_archives, export_archive, export_bif, export_rim
                from ResourceManager import ResourceManager
            except Exception as err:
                self.window.after(0, lambda err=err: messagebox.showerror("Error", f"Failed to import batch exporter:\n{err}"))
                return

            archives = find_archives(
                Path(base_dir),
                include_erf=opts["erf"].get(),
                include_mod=opts["mod"].get(),
                include_rim=opts["rim"].get(),
                include_hak=opts["hak"].get(),
            )

            processed = 0
            if archives:
                # Threaded processing of archives
                max_workers = min(4, len(archives))
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as exe:
                    futures = []
                    for erf_path in archives:
                        if Path(erf_path).suffix.lower() == ".rim":
                            futures.append(exe.submit(export_rim, Path(erf_path), Path(out_dir)))
                        else:
                            futures.append(exe.submit(export_archive, Path(erf_path), Path(out_dir)))
                    for f in concurrent.futures.as_completed(futures):
                        try:
                            f.result()
                        except Exception as e:
                            print(f"Batch export failed: {e}")
                        processed += 1
            else:
                self.window.after(0, lambda: messagebox.showinfo("Batch Export", "No archives found."))
                return

            # Also process BIFFs via chitin.key if requested
            if opts["bif"].get():
                key_path = Path(base_dir) / "chitin.key"
                if key_path.exists():
                    try:
                        rm = ResourceManager(key_path=key_path)
                        # parse selected indices
                        raw = bif_entry.get().strip()
                        if raw:
                            try:
                                indices = [int(x.strip()) for x in raw.split(",") if x.strip()]
                            except ValueError:
                                indices = list(range(len(rm.key.file_table)))
                        else:
                            indices = list(range(len(rm.key.file_table)))
                        for idx in indices:
                            if idx < 0 or idx >= len(rm.key.file_table):
                                print(f"Skipping invalid BIF index {idx}")
                                continue
                            export_bif(rm, idx, Path(out_dir))
                    except Exception as e:
                        print(f"BIF export failed: {e}")
                else:
                    print("No chitin.key found; skipped BIF export.")

            self.window.after(0, lambda: messagebox.showinfo("Batch Export", f"Completed.\nArchives processed: {processed}"))

        threading.Thread(target=worker, daemon=True).start()


    # ----------------------------------------------------------------------
    def batch_export_mdl(self):
        if self.game_path and (self.game_path / "chitin.key").exists():
            key_path = self.game_path / "chitin.key"
        else:
            key_path = filedialog.askopenfilename(title="Select chitin.key", filetypes=[("KEY", "*.key"), ("All files", "*.*")])
            if not key_path:
                return
        out_dir = filedialog.askdirectory(title="Select output folder for MDL export")
        if not out_dir:
            return
        try:
            from batch_export_mdl import export_all
            import threading
        except Exception as e:
            messagebox.showerror("Error", f"Failed to import MDL exporter:\n{e}")
            return

        def worker():
            try:
                export_all(Path(key_path), Path(out_dir))
                self.window.after(0, lambda: messagebox.showinfo("Batch MDL", "Completed MDL/MDX export."))
            except Exception as err:
                self.window.after(0, lambda err=err: messagebox.showerror("Error", f"MDL export failed:\n{err}"))

        threading.Thread(target=worker, daemon=True).start()

    # ----------------------------------------------------------------------
    def batch_export_selected_archive(self):
        sel = self.archive_list.curselection()
        bif_sel = self.bif_list.curselection()
        if not sel and not bif_sel:
            return messagebox.showinfo("No selection", "Select an archive or BIF first.")

        if sel:
            item = self.archive_list.get(sel[0])
            tag = item.split("] ", 1)[0].strip("[")
            path = item.split("] ", 1)[-1]
        else:
            tag = f"BIF {bif_sel[0]}"
            path = None
        out_dir = filedialog.askdirectory(title="Select output folder")
        if not out_dir:
            return
        try:
            from batch_export_erf import export_archive, export_rim, export_bif
            from ResourceManager import ResourceManager
        except Exception as e:
            return messagebox.showerror("Error", f"Failed to import exporter:\n{e}")

        def worker():
            try:
                if tag.upper().startswith("BIF"):
                    if not self.rm_key:
                        self.window.after(0, lambda: messagebox.showinfo("No KEY", "Load game path with chitin.key first."))
                        return
                    try:
                        idx = int(tag.split()[-1])
                    except Exception:
                        idx = None
                    if idx is not None:
                        export_bif(self.rm_key, idx, Path(out_dir))
                elif Path(path).suffix.lower() == ".rim":
                    export_rim(Path(path), Path(out_dir))
                else:
                    export_archive(Path(path), Path(out_dir))
                self.window.after(0, lambda: messagebox.showinfo("Batch Export", f"Completed export of {path if path else tag}"))
            except Exception as err:
                self.window.after(0, lambda err=err: messagebox.showerror("Error", f"Export failed:\n{err}"))

        threading.Thread(target=worker, daemon=True).start()

    # ----------------------------------------------------------------------
    def _export_model_textures(self, mdl_path: Path | None, mdx_path: Path | None, out_dir: Path):
        """
        Parse the MDL to find referenced textures, then export them (prefer PNG).
        Returns (saved_paths, missing_names).
        """
        if not mdl_path or not mdl_path.exists():
            return [], []
        try:
            from pykotor.resource.formats.mdl import mdl_auto
        except Exception as exc:
            return [], [f"pykotor not available: {exc}"]

        try:
            mdl = mdl_auto.read_mdl(str(mdl_path), source_ext=str(mdx_path) if mdx_path and mdx_path.exists() else None)
        except Exception as exc:
            return [], [f"Failed to read MDL: {exc}"]

        tex_names = set()
        for node in mdl.all_nodes():
            mesh = getattr(node, "mesh", None)
            if not mesh:
                continue
            for tn in (getattr(mesh, "texture_1", "") or "", getattr(mesh, "texture_2", "") or ""):
                tn = tn.strip()
                if tn:
                    tex_names.add(Path(tn).stem)

        saved = []
        missing = []
        out_dir.mkdir(parents=True, exist_ok=True)

        for tex in sorted(tex_names):
            data = None
            res_type = None
            for rt in (2007, 3007, 2033):
                try:
                    data = self.rm.extract_resref(tex, resource_type=rt)
                    res_type = rt
                    break
                except Exception:
                    continue
            if data is None:
                missing.append(tex)
                continue

            stem = sanitize_resref(tex)
            try:
                if res_type in (2007, 3007):
                    try:
                        png_bytes = tpc_bytes_to_png_bytes(data)
                        target = out_dir / f"{stem}.png"
                        target.write_bytes(png_bytes)
                        saved.append(str(target))
                        continue
                    except Exception:
                        pass  # fall through to raw save
                ext = "dds" if res_type == 2033 else (ResourceTypeInfo.get_extension(res_type) or "bin")
                target = out_dir / f"{stem}.{ext}"
                target.write_bytes(data)
                saved.append(str(target))
            except Exception as exc:
                missing.append(f"{tex} ({exc})")

        return saved, missing

    # ----------------------------------------------------------------------
    def run(self):
        self.window.mainloop()


if __name__ == "__main__":
    KOTOR_GUI().run()
