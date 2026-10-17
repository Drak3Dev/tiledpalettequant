"""Tkinter front end for the tiled palette quantizer."""

from __future__ import annotations

import base64
import io
import locale
import os
import queue
import sys
import threading
import time
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import numpy as np
from PIL import Image

from . import core
from .core import ColorZero, Dither, DitherPattern, Options

try:
    from PIL import ImageTk
except ImportError:  # some Linux distros ship ImageTk as a separate package
    ImageTk = None

try:
    import tkinterdnd2
except ImportError:
    tkinterdnd2 = None

SAMPLE_IMAGE = Path(__file__).with_name("carina-nebula.png")
MAX_VIEW_SIZE = 16384

STRINGS = {
    "en": {
        "title": "Tiled Palette Quantizer",
        "input": "Input image:",
        "open": "Open...",
        "tile_width": "Tile width:",
        "tile_height": "Tile height:",
        "palettes": "Palettes:",
        "colors": "Colors per palette:",
        "bits": "Bits per channel:",
        "fraction": "Fraction of pixels:",
        "color_zero": "Color index zero behaviour",
        "cz_unique": "unique",
        "cz_shared": "shared color:",
        "cz_tt": "transparent, from transparent pixels",
        "cz_tc": "transparent color:",
        "dither": "Dithering",
        "dither_off": "disabled",
        "dither_fast": "fast",
        "dither_slow": "slow",
        "dither_weight": "Dither weight:",
        "pattern": "Dither pattern",
        "quantize": "Quantize",
        "stop": "Stop",
        "save_image": "Save image...",
        "save_palette": "Save palette...",
        "zoom": "Zoom:",
        "source": "Source",
        "result": "Result",
        "palettes_view": "Palettes",
        "ready": "Ready",
        "loaded": "{name}: {w}×{h}",
        "running": "Quantizing...",
        "done": "Done in {t:.1f} s · MSE {mse:.1f} · {colors} colors",
        "cancelled": "Stopped",
        "error": "Error: {e}",
        "warming": "Preparing (compiling numba kernels, first run only)...",
        "no_numba": "numba is not installed: quantizing will be VERY slow. Run: pip install numba",
        "open_failed": "Can't open the image",
        "save_failed": "Can't save the file",
        "no_result": "Nothing to save yet — press Quantize first.",
        "images": "Images",
        "all_files": "All files",
        "png_indexed": "PNG (indexed when ≤256 colors)",
        "bmp": "BMP (8-bit indexed)",
        "drop_hint": "Tip: drop an image onto the window",
        "pick_color": "Pick a color",
    },
    "ru": {
        "title": "Tiled Palette Quantizer",
        "input": "Изображение:",
        "open": "Открыть...",
        "tile_width": "Ширина тайла:",
        "tile_height": "Высота тайла:",
        "palettes": "Палитр:",
        "colors": "Цветов в палитре:",
        "bits": "Бит на канал:",
        "fraction": "Доля пикселей:",
        "color_zero": "Цвет с индексом 0",
        "cz_unique": "уникальный",
        "cz_shared": "общий цвет:",
        "cz_tt": "прозрачный, из прозрачных пикселей",
        "cz_tc": "прозрачный цвет:",
        "dither": "Дизеринг",
        "dither_off": "выключен",
        "dither_fast": "быстрый",
        "dither_slow": "медленный",
        "dither_weight": "Сила дизеринга:",
        "pattern": "Паттерн дизеринга",
        "quantize": "Квантовать",
        "stop": "Остановить",
        "save_image": "Сохранить картинку...",
        "save_palette": "Сохранить палитру...",
        "zoom": "Масштаб:",
        "source": "Исходник",
        "result": "Результат",
        "palettes_view": "Палитры",
        "ready": "Готово",
        "loaded": "{name}: {w}×{h}",
        "running": "Квантую...",
        "done": "Готово за {t:.1f} с · MSE {mse:.1f} · цветов: {colors}",
        "cancelled": "Остановлено",
        "error": "Ошибка: {e}",
        "warming": "Подготовка (компиляция numba, только при первом запуске)...",
        "no_numba": "numba не установлена: квантование будет ОЧЕНЬ медленным. Выполни: pip install numba",
        "open_failed": "Не получилось открыть изображение",
        "save_failed": "Не получилось сохранить файл",
        "no_result": "Пока нечего сохранять — сначала нажми «Квантовать».",
        "images": "Изображения",
        "all_files": "Все файлы",
        "png_indexed": "PNG (индексированный, если цветов ≤256)",
        "bmp": "BMP (8 бит, индексированный)",
        "drop_hint": "Подсказка: картинку можно перетащить в окно",
        "pick_color": "Выбери цвет",
    },
}


def _detect_language():
    lang = os.environ.get("TPQ_LANG")
    if not lang:
        try:
            lang = locale.getlocale()[0] or ""
        except ValueError:
            lang = ""
        lang = lang or os.environ.get("LANG", "") or os.environ.get("LC_ALL", "")
    lang = lang.lower()
    return "ru" if lang.startswith("ru") or lang.startswith("russian") else "en"


T = STRINGS[_detect_language()]

IMAGE_EXTENSIONS = "*.png *.bmp *.gif *.jpg *.jpeg *.webp *.tga *.tif *.tiff *.ppm *.pcx *.ico"


def _checkerboard(width, height, cell=8):
    yy, xx = np.mgrid[0:height, 0:width]
    board = ((xx // cell) + (yy // cell)) % 2
    gray = np.where(board == 1, 204, 153).astype(np.uint8)
    return np.repeat(gray[:, :, None], 3, axis=2)


def _to_photo(img: Image.Image):
    if img.mode == "RGBA":
        rgba = np.asarray(img)
        if (rgba[:, :, 3] < 255).any():
            bg = _checkerboard(img.width, img.height)
            a = rgba[:, :, 3:4].astype(np.float32) / 255.0
            rgb = (rgba[:, :, :3] * a + bg * (1.0 - a)).astype(np.uint8)
            img = Image.fromarray(rgb, "RGB")
        else:
            img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")
    if ImageTk is not None:
        return ImageTk.PhotoImage(img)
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=0)
    return tk.PhotoImage(data=base64.b64encode(buf.getvalue()), format="png")


class LabeledSpinbox:
    def __init__(self, parent, row, label, lo, hi, step, default, is_float=False):
        self.lo, self.hi, self.default, self.is_float = lo, hi, default, is_float
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=1)
        self.var = tk.StringVar(value=f"{default:.2f}" if is_float else str(default))
        extra = {"format": "%.2f"} if is_float else {}
        self.widget = ttk.Spinbox(
            parent, from_=lo, to=hi, increment=step, textvariable=self.var, width=8, **extra
        )
        self.widget.grid(row=row, column=1, sticky="ew", pady=1)

    def get(self):
        """Parse and clamp the value, writing the cleaned value back like the web UI."""
        try:
            value = float(self.var.get().replace(",", ".")) if self.is_float else int(float(self.var.get()))
        except ValueError:
            value = self.default
        value = max(self.lo, min(self.hi, value))
        self.var.set(f"{value:.2f}" if self.is_float else str(value))
        return value


class ColorButton:
    def __init__(self, parent, color, on_change=None):
        self.color = color
        self.on_change = on_change
        self.widget = tk.Label(parent, width=4, relief="sunken", borderwidth=2, cursor="hand2")
        self.widget.bind("<Button-1>", self._pick)
        self._update()

    def _update(self):
        self.widget.configure(background="#%02x%02x%02x" % self.color)

    def _pick(self, _event=None):
        result = colorchooser.askcolor(color="#%02x%02x%02x" % self.color, title=T["pick_color"])
        if result and result[1]:
            hex_color = result[1].lstrip("#")
            self.color = tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
            self._update()
            if self.on_change:
                self.on_change()


class App:
    def __init__(self, root, initial_path=None):
        self.root = root
        self.root.title(T["title"])
        self.queue = queue.Queue()
        self.worker = None
        self.stop_event = threading.Event()
        self.run_id = 0
        self.source_rgba = None
        self.source_name = "image"
        self.source_dir = None
        self.result = None
        self.result_preview = None
        self.palette_preview = None
        self.zoom = 1
        self.photos = {}
        self.last_preview_time = 0.0
        self.pending_preview = None

        self._build_ui()
        self._bind_keys()
        self._setup_dnd()

        if initial_path:
            self.load(initial_path)
        elif SAMPLE_IMAGE.exists():
            self.load(SAMPLE_IMAGE)

        if not core.HAVE_NUMBA:
            self.set_status(T["no_numba"])
        else:
            self._start_warmup()
        self.root.after(50, self._poll)

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        # Native themes may ignore this; in "clam" the default bar color blends with the trough.
        ttk.Style(self.root).configure("Quant.Horizontal.TProgressbar", background="#3d8fd6")
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        side = ttk.Frame(self.root, padding=8)
        side.grid(row=0, column=0, sticky="ns")
        side.columnconfigure(0, weight=1)

        files = ttk.Frame(side)
        files.grid(row=0, column=0, sticky="ew")
        files.columnconfigure(1, weight=1)
        ttk.Label(files, text=T["input"]).grid(row=0, column=0, sticky="w")
        ttk.Button(files, text=T["open"], command=self.open_dialog).grid(row=0, column=1, sticky="e")
        self.file_label = ttk.Label(files, text="", foreground="gray", width=34)
        self.file_label.grid(row=1, column=0, columnspan=2, sticky="w")

        nums = ttk.Frame(side)
        nums.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        nums.columnconfigure(1, weight=1)
        self.tile_w = LabeledSpinbox(nums, 0, T["tile_width"], 1, 32, 1, 8)
        self.tile_h = LabeledSpinbox(nums, 1, T["tile_height"], 1, 32, 1, 8)
        self.num_pal = LabeledSpinbox(nums, 2, T["palettes"], 1, 16, 1, 8)
        self.num_col = LabeledSpinbox(nums, 3, T["colors"], 2, 256, 1, 4)
        self.bits = LabeledSpinbox(nums, 4, T["bits"], 2, 8, 1, 5)
        self.fraction = LabeledSpinbox(nums, 5, T["fraction"], 0.01, 10.0, 0.05, 0.1, is_float=True)

        cz = ttk.LabelFrame(side, text=T["color_zero"], padding=6)
        cz.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.color_zero = tk.IntVar(value=int(ColorZero.UNIQUE))
        ttk.Radiobutton(cz, text=T["cz_unique"], variable=self.color_zero,
                        value=int(ColorZero.UNIQUE)).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(cz, text=T["cz_shared"], variable=self.color_zero,
                        value=int(ColorZero.SHARED)).grid(row=1, column=0, sticky="w")
        select_shared = lambda: self.color_zero.set(int(ColorZero.SHARED))
        self.shared_color = ColorButton(cz, (0, 0, 0), select_shared)
        self.shared_color.widget.grid(row=1, column=1, sticky="w", padx=4)
        ttk.Radiobutton(cz, text=T["cz_tt"], variable=self.color_zero,
                        value=int(ColorZero.TRANSPARENT_FROM_TRANSPARENT)).grid(
            row=2, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(cz, text=T["cz_tc"], variable=self.color_zero,
                        value=int(ColorZero.TRANSPARENT_FROM_COLOR)).grid(row=3, column=0, sticky="w")
        select_tc = lambda: self.color_zero.set(int(ColorZero.TRANSPARENT_FROM_COLOR))
        self.transparent_color = ColorButton(cz, (255, 0, 255), select_tc)
        self.transparent_color.widget.grid(row=3, column=1, sticky="w", padx=4)

        dith = ttk.LabelFrame(side, text=T["dither"], padding=6)
        dith.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        dith.columnconfigure(1, weight=1)
        self.dither = tk.IntVar(value=int(Dither.OFF))
        for i, (key, value) in enumerate(
            (("dither_off", Dither.OFF), ("dither_fast", Dither.FAST), ("dither_slow", Dither.SLOW))
        ):
            ttk.Radiobutton(dith, text=T[key], variable=self.dither, value=int(value)).grid(
                row=0, column=i, sticky="w", padx=(0, 6))
        weight_row = ttk.Frame(dith)
        weight_row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        weight_row.columnconfigure(1, weight=1)
        self.dither_weight = LabeledSpinbox(weight_row, 0, T["dither_weight"], 0.01, 1.0, 0.05, 0.5,
                                            is_float=True)

        ttk.Label(dith, text=T["pattern"]).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.pattern = tk.IntVar(value=int(DitherPattern.DIAGONAL4))
        layout = (
            (DitherPattern.DIAGONAL4, 3, 0), (DitherPattern.DIAGONAL2, 3, 1),
            (DitherPattern.HORIZONTAL4, 4, 0), (DitherPattern.HORIZONTAL2, 4, 1),
            (DitherPattern.VERTICAL4, 5, 0), (DitherPattern.VERTICAL2, 5, 1),
        )
        for value, r, c in layout:
            ttk.Radiobutton(dith, text=value.name.lower(), variable=self.pattern, value=int(value)).grid(
                row=r, column=c, columnspan=2 if c == 1 else 1, sticky="w", padx=(0, 12))

        actions = ttk.Frame(side)
        actions.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        self.quantize_button = ttk.Button(actions, text=T["quantize"], command=self.toggle_run)
        self.quantize_button.grid(row=0, column=0, sticky="ew", ipady=3)
        self.progress = ttk.Progressbar(actions, maximum=100, style="Quant.Horizontal.TProgressbar")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        # ---- right side: toolbar, synced source/result views, palettes
        main = ttk.Frame(self.root, padding=(0, 8, 8, 8))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        bar = ttk.Frame(main)
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(bar, text=T["zoom"]).pack(side="left")
        self.zoom_var = tk.StringVar(value="1×")
        zoom_box = ttk.Combobox(bar, textvariable=self.zoom_var, width=5, state="readonly",
                                values=[f"{z}×" for z in (1, 2, 3, 4, 5, 6, 8, 10, 12, 16)])
        zoom_box.pack(side="left", padx=(4, 0))
        zoom_box.bind("<<ComboboxSelected>>", lambda e: self.set_zoom(int(self.zoom_var.get()[:-1])))
        self.save_palette_button = ttk.Button(bar, text=T["save_palette"], command=self.save_palette,
                                              state="disabled")
        self.save_palette_button.pack(side="right")
        self.save_image_button = ttk.Button(bar, text=T["save_image"], command=self.save_image,
                                            state="disabled")
        self.save_image_button.pack(side="right", padx=(0, 4))

        views = ttk.Frame(main)
        views.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        views.columnconfigure((0, 1), weight=1, uniform="views")
        views.rowconfigure(1, weight=1)
        ttk.Label(views, text=T["source"]).grid(row=0, column=0, sticky="w")
        ttk.Label(views, text=T["result"]).grid(row=0, column=1, sticky="w")
        self.canvases = []
        for col in (0, 1):
            c = tk.Canvas(views, highlightthickness=0, background="#3c3c3c", width=360, height=300)
            c.grid(row=1, column=col, sticky="nsew", padx=(0, 4) if col == 0 else (0, 0))
            self.canvases.append(c)
        self.vbar = ttk.Scrollbar(views, orient="vertical", command=self._yview)
        self.vbar.grid(row=1, column=2, sticky="ns")
        self.hbar = ttk.Scrollbar(views, orient="horizontal", command=self._xview)
        self.hbar.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.canvases[0].configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)
        for c in self.canvases:
            self._bind_view_events(c)

        ttk.Label(main, text=T["palettes_view"]).grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.palette_canvas = tk.Canvas(main, highlightthickness=0, height=40, background="#3c3c3c")
        self.palette_canvas.grid(row=3, column=0, sticky="ew")

        self.status = ttk.Label(self.root, text=T["ready"], anchor="w", padding=(8, 2))
        self.status.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _bind_keys(self):
        self.root.bind_all("<Control-o>", lambda e: self.open_dialog())
        self.root.bind_all("<Control-s>", lambda e: self.save_image())
        self.root.bind_all("<Control-Return>", lambda e: self.toggle_run())
        self.root.bind_all("<F5>", lambda e: self.toggle_run())
        if sys.platform == "darwin":
            self.root.bind_all("<Command-o>", lambda e: self.open_dialog())
            self.root.bind_all("<Command-s>", lambda e: self.save_image())
            self.root.bind_all("<Command-Return>", lambda e: self.toggle_run())

    def _setup_dnd(self):
        if tkinterdnd2 is None or not hasattr(self.root, "drop_target_register"):
            return
        self.root.drop_target_register(tkinterdnd2.DND_FILES)
        self.root.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        if paths:
            self.load(paths[0])

    # ------------------------------------------------------ view handling
    def _xview(self, *args):
        for c in self.canvases:
            c.xview(*args)

    def _yview(self, *args):
        for c in self.canvases:
            c.yview(*args)

    def _sync_from(self, canvas):
        x, y = canvas.xview()[0], canvas.yview()[0]
        for c in self.canvases:
            if c is not canvas:
                c.xview_moveto(x)
                c.yview_moveto(y)

    def _bind_view_events(self, canvas):
        def press(e):
            canvas.scan_mark(e.x, e.y)

        def drag(e):
            canvas.scan_dragto(e.x, e.y, gain=1)
            self._sync_from(canvas)

        def wheel(e, delta=None):
            delta = e.delta if delta is None else delta
            if delta == 0:
                return
            step = -1 if delta > 0 else 1
            if e.state & 0x0004:  # Control
                self.change_zoom(-step)
            elif e.state & 0x0001:  # Shift
                self._xview("scroll", step * 3, "units")
            else:
                self._yview("scroll", step * 3, "units")

        canvas.bind("<ButtonPress-1>", press)
        canvas.bind("<B1-Motion>", drag)
        canvas.bind("<ButtonPress-2>", press)
        canvas.bind("<B2-Motion>", drag)
        canvas.bind("<MouseWheel>", wheel)
        canvas.bind("<Button-4>", lambda e: wheel(e, 1))
        canvas.bind("<Button-5>", lambda e: wheel(e, -1))

    def change_zoom(self, direction):
        levels = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16]
        idx = min(range(len(levels)), key=lambda i: abs(levels[i] - self.zoom))
        idx = max(0, min(len(levels) - 1, idx + direction))
        self.set_zoom(levels[idx])

    def max_zoom(self):
        if self.source_rgba is None:
            return 16
        h, w = self.source_rgba.shape[:2]
        return max(1, MAX_VIEW_SIZE // max(w, h))

    def set_zoom(self, zoom):
        zoom = max(1, min(int(zoom), self.max_zoom()))
        self.zoom = zoom
        self.zoom_var.set(f"{zoom}×")
        self.redraw_views()

    def auto_zoom(self, attempts=20):
        """Pick the largest integer zoom that fits; waits until the window is mapped."""
        if self.source_rgba is None:
            return
        cw = self.canvases[0].winfo_width()
        ch = self.canvases[0].winfo_height()
        if (cw <= 1 or ch <= 1) and attempts > 0:
            self.set_zoom(self.zoom)
            self.root.after(50, lambda: self.auto_zoom(attempts - 1))
            return
        h, w = self.source_rgba.shape[:2]
        self.set_zoom(max(1, min(cw // w, ch // h, 8)))

    def _draw(self, canvas, key, img):
        canvas.delete("all")
        if img is None:
            self.photos.pop(key, None)
            return
        if self.zoom > 1:
            img = img.resize((img.width * self.zoom, img.height * self.zoom), Image.NEAREST)
        photo = _to_photo(img)
        self.photos[key] = photo
        canvas.create_image(0, 0, anchor="nw", image=photo)

    def redraw_views(self):
        src = Image.fromarray(self.source_rgba, "RGBA") if self.source_rgba is not None else None
        self._draw(self.canvases[0], "source", src)
        res = None
        if self.result is not None:
            res = self.result.image()
        elif self.result_preview is not None:
            res = Image.fromarray(self.result_preview, "RGBA")
        self._draw(self.canvases[1], "result", res)
        if src is not None:
            region = (0, 0, src.width * self.zoom, src.height * self.zoom)
            for c in self.canvases:
                c.configure(scrollregion=region)
        self._sync_from(self.canvases[0])

    def redraw_result(self):
        if self.result is not None:
            img = self.result.image()
        elif self.result_preview is not None:
            img = Image.fromarray(self.result_preview, "RGBA")
        else:
            img = None
        self._draw(self.canvases[1], "result", img)

    def redraw_palettes(self, palettes):
        c = self.palette_canvas
        c.delete("all")
        if palettes is None:
            self.photos.pop("palette", None)
            return
        img = core.palette_image(palettes)
        photo = _to_photo(img)
        self.photos["palette"] = photo
        c.configure(height=img.height)
        c.create_image(0, 0, anchor="nw", image=photo)

    # ------------------------------------------------------------- files
    def open_dialog(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            initialdir=self.source_dir or None,
            filetypes=[(T["images"], IMAGE_EXTENSIONS), (T["all_files"], "*")],
        )
        if path:
            self.load(path)

    def load(self, path):
        path = Path(path)
        try:
            rgba = core.load_image(path)
        except Exception as e:  # noqa: BLE001 - show any decoder error to the user
            messagebox.showerror(T["open_failed"], f"{path}\n\n{e}", parent=self.root)
            return
        if self.worker is not None and self.worker.is_alive():
            self.stop_event.set()
            self.run_id += 1  # drop any messages still coming from the abandoned run
            self.worker = None
            self.quantize_button.configure(text=T["quantize"])
            self.progress["value"] = 0
        self.source_rgba = rgba
        self.source_name = path.stem
        self.source_dir = str(path.parent)
        self.result = None
        self.result_preview = None
        self.redraw_palettes(None)
        self.file_label.configure(text=path.name)
        self.save_image_button.configure(state="disabled")
        self.save_palette_button.configure(state="disabled")
        self.set_status(T["loaded"].format(name=path.name, w=rgba.shape[1], h=rgba.shape[0]))
        self.auto_zoom()

    def options(self):
        return Options(
            tile_width=self.tile_w.get(),
            tile_height=self.tile_h.get(),
            num_palettes=self.num_pal.get(),
            colors_per_palette=self.num_col.get(),
            bits_per_channel=self.bits.get(),
            fraction_of_pixels=self.fraction.get(),
            color_zero=ColorZero(self.color_zero.get()),
            color_zero_value=self._color_zero_value(),
            dither=Dither(self.dither.get()),
            dither_weight=self.dither_weight.get(),
            dither_pattern=DitherPattern(self.pattern.get()),
        )

    def _color_zero_value(self):
        cz = ColorZero(self.color_zero.get())
        if cz == ColorZero.SHARED:
            return self.shared_color.color
        if cz in (ColorZero.TRANSPARENT_FROM_TRANSPARENT, ColorZero.TRANSPARENT_FROM_COLOR):
            return self.transparent_color.color
        return (0, 0, 0)

    def _default_name(self, suffix):
        return self.source_name + self.result.options.settings_suffix() + suffix

    def save_image(self):
        if self.result is None:
            messagebox.showinfo(T["title"], T["no_result"], parent=self.root)
            return
        types = [(T["png_indexed"], "*.png")]
        if self.result.can_be_indexed:
            types.append((T["bmp"], "*.bmp"))
        types.append((T["all_files"], "*"))
        path = filedialog.asksaveasfilename(
            parent=self.root, initialdir=self.source_dir or None,
            initialfile=self._default_name(".png"), defaultextension=".png", filetypes=types,
        )
        if path:
            self._save(lambda: self.result.save_image(path))

    def save_palette(self):
        if self.result is None:
            messagebox.showinfo(T["title"], T["no_result"], parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, initialdir=self.source_dir or None,
            initialfile=self._default_name("-palette.png"), defaultextension=".png",
            filetypes=[("PNG", "*.png"), (T["all_files"], "*")],
        )
        if path:
            self._save(lambda: self.result.save_palette(path))

    def _save(self, action):
        try:
            action()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(T["save_failed"], str(e), parent=self.root)

    # ------------------------------------------------------- quantizing
    def toggle_run(self):
        if self.worker is not None and self.worker.is_alive():
            self.stop_event.set()
            return
        if self.source_rgba is None:
            self.open_dialog()
            return
        opts = self.options()
        self.stop_event = threading.Event()
        self.run_id += 1
        run_id = self.run_id
        self.result = None
        self.result_preview = None
        self.pending_preview = None
        self.save_image_button.configure(state="disabled")
        self.save_palette_button.configure(state="disabled")
        self.quantize_button.configure(text=T["stop"])
        self.progress["value"] = 0
        self.set_status(T["running"])
        self.worker = threading.Thread(
            target=self._run, args=(run_id, self.source_rgba, opts, self.stop_event), daemon=True
        )
        self.worker.start()

    def _run(self, run_id, rgba, opts, stop_event):
        put = self.queue.put
        try:
            result = core.quantize(
                rgba, opts,
                progress=lambda p: put((run_id, "progress", p)),
                preview=lambda img, pals: put((run_id, "preview", (img, pals))),
                should_stop=stop_event.is_set,
            )
            put((run_id, "done", result))
        except core.Cancelled:
            put((run_id, "cancelled", None))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            put((run_id, "error", e))

    def _start_warmup(self):
        self.set_status(T["warming"])

        def work():
            try:
                core.warmup()
            except Exception:  # noqa: BLE001 - warmup is best effort
                traceback.print_exc()
            self.queue.put((None, "warm", None))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        latest_preview = None
        try:
            while True:
                run_id, kind, payload = self.queue.get_nowait()
                if kind == "warm":
                    if self.worker is None or not self.worker.is_alive():
                        if self.status.cget("text") == T["warming"]:
                            self.set_status(T["ready"])
                    continue
                if run_id != self.run_id:
                    continue
                if kind == "progress":
                    self.progress["value"] = payload
                elif kind == "preview":
                    latest_preview = payload
                elif kind == "done":
                    latest_preview = None
                    self._finish(payload)
                elif kind == "cancelled":
                    latest_preview = None
                    self._end_run(T["cancelled"])
                elif kind == "error":
                    latest_preview = None
                    self._end_run(T["error"].format(e=payload))
        except queue.Empty:
            pass
        if latest_preview is not None:
            self.pending_preview = latest_preview
        now = time.monotonic()
        if self.pending_preview is not None and now - self.last_preview_time > 0.25:
            img, pals = self.pending_preview
            self.pending_preview = None
            self.last_preview_time = now
            self.result_preview = img
            self.redraw_result()
            self.redraw_palettes(pals)
        self.root.after(50, self._poll)

    def _finish(self, result):
        self.result = result
        self.result_preview = None
        self.pending_preview = None
        self.redraw_result()
        self.redraw_palettes(result.palettes)
        self.save_image_button.configure(state="normal")
        self.save_palette_button.configure(state="normal")
        self._end_run(T["done"].format(t=result.elapsed, mse=result.mse,
                                       colors=result.options.total_colors))

    def _end_run(self, message):
        self.quantize_button.configure(text=T["quantize"])
        self.progress["value"] = 100 if self.result is not None else 0
        self.set_status(message)

    def set_status(self, text):
        self.status.configure(text=text)


def _enable_hidpi():
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    _enable_hidpi()
    if tkinterdnd2 is not None:
        try:
            root = tkinterdnd2.TkinterDnD.Tk()
        except Exception:  # noqa: BLE001 - tkdnd binary missing for this platform
            root = tk.Tk()
    else:
        root = tk.Tk()
    style = ttk.Style(root)
    if sys.platform.startswith("linux") and "clam" in style.theme_names():
        style.theme_use("clam")
    root.geometry("1180x780")
    root.minsize(900, 690)
    App(root, argv[0] if argv else None)
    root.mainloop()


if __name__ == "__main__":
    main()
