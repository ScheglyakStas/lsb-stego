"""Графический интерфейс LSB-стеганографии для BMP-изображений (PySide6)."""

from __future__ import annotations

import os
import sys

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import lsb_core as core

__version__ = "1.0.1"

# В сборке PyInstaller ресурсы распаковываются в sys._MEIPASS.
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ICON_PATH = os.path.join(BASE_DIR, "assets", "icon.png")

BMP_FILTER = "Изображения BMP (*.bmp);;Все файлы (*)"
IMAGE_FILTER = (
    "Изображения (" + " ".join(f"*.{e}" for e in core.IMAGE_EXTENSIONS) + ");;"
    "Изображения BMP (*.bmp);;Все файлы (*)"
)
TEXT_FILTER = "Текстовые файлы (*.txt);;Все файлы (*)"


def to_pixmap(arr: np.ndarray) -> QPixmap:
    arr = np.ascontiguousarray(arr)
    h, w, _ = arr.shape
    img = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(img.copy())


ZOOM_LEVELS = (("Вписать в окно", 0), ("100%", 1), ("200%", 2), ("400%", 4), ("800%", 8))


class _Canvas(QWidget):
    """Холст: в режиме «вписать» рисует сглаженную уменьшенную копию,
    при увеличении — только видимую часть, пиксели без сглаживания."""

    def __init__(self, view: ImageView):
        super().__init__()
        self._view = view
        self._fit_cache: QPixmap | None = None
        self._drag_from = None

    def paintEvent(self, event):  # noqa: N802
        view = self._view
        painter = QPainter(self)
        if view.pixmap is None:
            painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, view.placeholder)
            return
        if view.zoom == 0:
            self._paint_fit(painter)
            return
        z = view.zoom
        r = event.rect()
        src = QRect(r.left() // z, r.top() // z, r.width() // z + 2, r.height() // z + 2)
        src = src.intersected(view.pixmap.rect())
        painter.drawPixmap(QRect(src.x() * z, src.y() * z, src.width() * z, src.height() * z),
                           view.pixmap, src)

    def _paint_fit(self, painter: QPainter) -> None:
        pixmap = self._view.pixmap
        target = pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        if self._fit_cache is None or self._fit_cache.size() != target:
            mode = Qt.TransformationMode.SmoothTransformation
            if target.width() >= pixmap.width():
                mode = Qt.TransformationMode.FastTransformation
            self._fit_cache = pixmap.scaled(target, Qt.AspectRatioMode.IgnoreAspectRatio, mode)
        painter.drawPixmap((self.width() - target.width()) // 2,
                           (self.height() - target.height()) // 2, self._fit_cache)

    def reset_cache(self) -> None:
        self._fit_cache = None

    # Перетаскивание мышью для прокрутки увеличенного изображения.
    def mousePressEvent(self, event):  # noqa: N802
        if self._view.zoom and event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_from is not None:
            pos = event.globalPosition().toPoint()
            delta = pos - self._drag_from
            self._drag_from = pos
            h, v = self._view.horizontalScrollBar(), self._view.verticalScrollBar()
            h.setValue(h.value() - delta.x())
            v.setValue(v.value() - delta.y())

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_from = None
        self.setCursor(Qt.CursorShape.OpenHandCursor if self._view.zoom else Qt.CursorShape.ArrowCursor)


class ImageView(QScrollArea):
    """Просмотр изображения: вписывание в окно или масштаб 100–800% с прокруткой."""

    def __init__(self, placeholder: str):
        super().__init__()
        self.placeholder = placeholder
        self.pixmap: QPixmap | None = None
        self.zoom = 0  # 0 — вписать в окно
        self._canvas = _Canvas(self)
        self.setWidget(self._canvas)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 160)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._apply_zoom()

    def set_array(self, arr: np.ndarray | None) -> None:
        self.pixmap = None if arr is None else to_pixmap(arr)
        self._apply_zoom()

    def center(self) -> tuple[float, float]:
        """Точка изображения (в пикселях), находящаяся в центре окна."""
        if self.pixmap is None:
            return 0.0, 0.0
        if self.zoom == 0:
            return self.pixmap.width() / 2, self.pixmap.height() / 2
        return ((self.horizontalScrollBar().value() + self.viewport().width() / 2) / self.zoom,
                (self.verticalScrollBar().value() + self.viewport().height() / 2) / self.zoom)

    def set_zoom(self, zoom: int, center: tuple[float, float] | None = None) -> None:
        cx, cy = center or self.center()
        self.zoom = zoom
        self._apply_zoom()
        if zoom:
            self.horizontalScrollBar().setValue(int(cx * zoom - self.viewport().width() / 2))
            self.verticalScrollBar().setValue(int(cy * zoom - self.viewport().height() / 2))

    def _apply_zoom(self) -> None:
        self._canvas.reset_cache()
        if self.pixmap is None or self.zoom == 0:
            self.setWidgetResizable(True)
            self._canvas.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setWidgetResizable(False)
            self._canvas.resize(self.pixmap.size() * self.zoom)
            self._canvas.setCursor(Qt.CursorShape.OpenHandCursor)
        self._canvas.update()


def link_scrolling(a: ImageView, b: ImageView) -> None:
    """Синхронная прокрутка двух просмотров одинакового размера."""
    for bar_a, bar_b in ((a.horizontalScrollBar(), b.horizontalScrollBar()),
                         (a.verticalScrollBar(), b.verticalScrollBar())):
        bar_a.valueChanged.connect(bar_b.setValue)
        bar_b.valueChanged.connect(bar_a.setValue)


class TitledImage(QWidget):
    def __init__(self, title: str, placeholder: str):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(f"<b>{title}</b>")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view = ImageView(placeholder)
        layout.addWidget(caption)
        layout.addWidget(self.view, 1)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LSB-стеганография в изображениях BMP")
        self.resize(1200, 760)

        self.container: np.ndarray | None = None  # исходное изображение
        self.container_path = ""
        self.stego: np.ndarray | None = None  # результат встраивания
        self.extract_image: np.ndarray | None = None
        self.extract_path = ""

        splitter = QSplitter()
        splitter.addWidget(self._build_settings_panel())
        splitter.addWidget(self._build_tabs())
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage("Откройте изображение-контейнер для начала работы.")
        self._update_capacity()

    # ------------------------------------------------------------------ панель параметров

    def _build_settings_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        box = QGroupBox("Контейнер")
        box_layout = QVBoxLayout(box)
        open_btn = QPushButton("Открыть изображение…")
        open_btn.setToolTip("BMP или другой формат (PNG, JPEG, GIF, TIFF, WebP…) "
                            "с автоматическим преобразованием в BMP 24 бит")
        open_btn.clicked.connect(self.open_container)
        self.save_container_btn = QPushButton("Сохранить как BMP…")
        self.save_container_btn.setToolTip("Сохранить преобразованный контейнер в файл BMP")
        self.save_container_btn.setEnabled(False)
        self.save_container_btn.clicked.connect(self.save_container)
        self.container_info = QLabel("Изображение не загружено")
        self.container_info.setWordWrap(True)
        box_layout.addWidget(open_btn)
        box_layout.addWidget(self.save_container_btn)
        box_layout.addWidget(self.container_info)
        layout.addWidget(box)

        box = QGroupBox("Цветовые компоненты")
        box_layout = QVBoxLayout(box)
        self.channel_checks = []
        for name in core.CHANNEL_NAMES:
            check = QCheckBox(name)
            check.setChecked(name.endswith("(B)"))
            check.toggled.connect(self._update_capacity)
            box_layout.addWidget(check)
            self.channel_checks.append(check)
        layout.addWidget(box)

        box = QGroupBox("Битовые плоскости")
        box_layout = QVBoxLayout(box)
        self.plane_checks = []
        for plane in range(1, core.MAX_PLANE + 1):
            label = f"{plane}-я плоскость" + (" (младший бит)" if plane == 1 else "")
            check = QCheckBox(label)
            check.setChecked(plane == 1)
            check.toggled.connect(self._update_capacity)
            box_layout.addWidget(check)
            self.plane_checks.append(check)
        layout.addWidget(box)

        box = QGroupBox("Интервал встраивания")
        box_layout = QVBoxLayout(box)
        self.interval_combo = QComboBox()
        for skip, name in core.INTERVALS:
            self.interval_combo.addItem(name, skip)
        self.interval_combo.currentIndexChanged.connect(self._update_capacity)
        box_layout.addWidget(self.interval_combo)
        layout.addWidget(box)

        box = QGroupBox("Ёмкость контейнера")
        box_layout = QVBoxLayout(box)
        self.capacity_label = QLabel()
        self.capacity_label.setWordWrap(True)
        box_layout.addWidget(self.capacity_label)
        layout.addWidget(box)

        hint = QLabel(
            "Параметры (компоненты, плоскости, интервал) при извлечении "
            "должны совпадать с параметрами встраивания."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("font-style: italic;")
        layout.addWidget(hint)
        layout.addStretch(1)
        return panel

    def params(self) -> tuple[list[int], list[int], int]:
        channels = [i for i, c in enumerate(self.channel_checks) if c.isChecked()]
        planes = [i + 1 for i, c in enumerate(self.plane_checks) if c.isChecked()]
        return channels, planes, self.interval_combo.currentData()

    # ------------------------------------------------------------------ вкладки

    def _build_tabs(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(self._build_embed_tab(), "Встраивание")
        tabs.addTab(self._build_extract_tab(), "Извлечение")
        tabs.addTab(self._build_planes_tab(), "Битовые плоскости")
        return tabs

    def _build_embed_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        row = QHBoxLayout()
        row.addWidget(QLabel("<b>Сообщение для встраивания:</b>"))
        row.addStretch(1)
        load_btn = QPushButton("Загрузить из файла…")
        load_btn.clicked.connect(self.load_message)
        row.addWidget(load_btn)
        layout.addLayout(row)

        self.message_edit = QPlainTextEdit()
        self.message_edit.setPlaceholderText("Введите текст сообщения…")
        self.message_edit.textChanged.connect(self._update_message_info)
        self.message_edit.setMaximumHeight(160)
        layout.addWidget(self.message_edit)

        self.message_info = QLabel()
        layout.addWidget(self.message_info)

        row = QHBoxLayout()
        self.embed_btn = QPushButton("Встроить сообщение")
        self.embed_btn.clicked.connect(self.do_embed)
        self.save_btn = QPushButton("Сохранить результат…")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_stego)
        row.addWidget(self.embed_btn)
        row.addWidget(self.save_btn)
        row.addStretch(1)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Масштаб просмотра:"))
        self.embed_zoom = self._zoom_combo()
        row.addWidget(self.embed_zoom)
        row.addWidget(QLabel("(при увеличении изображения прокручиваются синхронно; "
                             "перетаскивайте мышью)"))
        row.addStretch(1)
        layout.addLayout(row)

        images = QHBoxLayout()
        self.original_view = TitledImage("Исходное изображение", "Нет изображения")
        self.stego_view = TitledImage("Стегоконтейнер", "Встраивание не выполнено")
        images.addWidget(self.original_view)
        images.addWidget(self.stego_view)
        layout.addLayout(images, 1)
        link_scrolling(self.original_view.view, self.stego_view.view)
        self.embed_zoom.currentIndexChanged.connect(
            lambda: self._set_zoom(self.embed_zoom, self.original_view.view, self.stego_view.view))

        self.metrics_label = QLabel()
        layout.addWidget(self.metrics_label)
        self._update_message_info()
        return tab

    def _build_extract_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        row = QHBoxLayout()
        open_btn = QPushButton("Открыть стегоконтейнер…")
        open_btn.clicked.connect(self.open_extract_image)
        use_btn = QPushButton("Взять результат встраивания")
        use_btn.clicked.connect(self.use_stego_for_extract)
        row.addWidget(open_btn)
        row.addWidget(use_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self.extract_info = QLabel("Изображение для извлечения не выбрано")
        layout.addWidget(self.extract_info)

        self.extract_view = ImageView("Нет изображения")
        layout.addWidget(self.extract_view, 1)

        row = QHBoxLayout()
        extract_btn = QPushButton("Извлечь сообщение")
        extract_btn.clicked.connect(self.do_extract)
        self.save_text_btn = QPushButton("Сохранить текст…")
        self.save_text_btn.setEnabled(False)
        self.save_text_btn.clicked.connect(self.save_extracted)
        row.addWidget(extract_btn)
        row.addWidget(self.save_text_btn)
        row.addStretch(1)
        layout.addLayout(row)

        layout.addWidget(QLabel("<b>Извлечённое сообщение:</b>"))
        self.extracted_edit = QPlainTextEdit()
        self.extracted_edit.setReadOnly(True)
        self.extracted_edit.setMaximumHeight(180)
        layout.addWidget(self.extracted_edit)
        return tab

    def _build_planes_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QGridLayout()
        self.plane_source = QComboBox()
        self.plane_source.addItems(["Исходное изображение", "Стегоконтейнер", "Изображение для извлечения"])
        self.plane_channel = QComboBox()
        self.plane_channel.addItems(core.CHANNEL_NAMES)
        self.plane_index = QComboBox()
        for plane in range(1, 9):
            self.plane_index.addItem(f"{plane}-я" + (" (младший бит)" if plane == 1 else ""), plane)
        form.addWidget(QLabel("Изображение:"), 0, 0)
        form.addWidget(self.plane_source, 0, 1)
        form.addWidget(QLabel("Компонента:"), 0, 2)
        form.addWidget(self.plane_channel, 0, 3)
        form.addWidget(QLabel("Плоскость:"), 0, 4)
        form.addWidget(self.plane_index, 0, 5)
        self.plane_zoom = self._zoom_combo()
        form.addWidget(QLabel("Масштаб:"), 0, 6)
        form.addWidget(self.plane_zoom, 0, 7)
        form.setColumnStretch(8, 1)
        layout.addLayout(form)

        for combo in (self.plane_source, self.plane_channel, self.plane_index):
            combo.currentIndexChanged.connect(self._update_plane_view)

        self.plane_view = ImageView("Нет изображения")
        self.plane_zoom.currentIndexChanged.connect(lambda: self._set_zoom(self.plane_zoom, self.plane_view))
        layout.addWidget(self.plane_view, 1)
        layout.addWidget(QLabel("Белый цвет — бит равен 1, чёрный — бит равен 0."))
        return tab

    # ------------------------------------------------------------------ обновление состояния

    def _update_capacity(self) -> None:
        channels, planes, skip = self.params()
        if self.container is None:
            self.capacity_label.setText("Загрузите изображение, чтобы рассчитать ёмкость.")
        elif not channels or not planes:
            self.capacity_label.setText("<span style='color:#c0392b'>Выберите хотя бы одну "
                                        "компоненту и одну плоскость.</span>")
        else:
            shape = self.container.shape
            pixels = core.usable_pixels(shape, skip)
            bits = core.capacity_bits(shape, channels, planes, skip)
            nbytes = core.capacity_bytes(shape, channels, planes, skip)
            self.capacity_label.setText(
                f"Используемых пикселей: {pixels}<br>"
                f"Всего бит: {bits}<br>"
                f"Макс. длина сообщения: <b>{nbytes} байт</b><br>"
                f"(32 бита отводятся под длину сообщения)"
            )
        self._update_message_info()

    def _update_message_info(self) -> None:
        if not hasattr(self, "message_info"):
            return
        text = self.message_edit.toPlainText()
        nbytes = len(text.encode("utf-8"))
        info = f"Символов: {len(text)}, байт (UTF-8): {nbytes}"
        if self.container is not None:
            channels, planes, skip = self.params()
            cap = core.capacity_bytes(self.container.shape, channels, planes, skip)
            if nbytes > cap:
                info = f"<span style='color:#c0392b'>{info} — превышает ёмкость ({cap} байт)</span>"
            else:
                info += f" из {cap} доступных"
        self.message_info.setText(info)

    def _update_plane_view(self) -> None:
        sources = (self.container, self.stego, self.extract_image)
        arr = sources[self.plane_source.currentIndex()]
        if arr is None:
            self.plane_view.set_array(None)
            return
        self.plane_view.set_array(
            core.bit_plane(arr, self.plane_channel.currentIndex(), self.plane_index.currentData())
        )

    @staticmethod
    def _zoom_combo() -> QComboBox:
        combo = QComboBox()
        for name, zoom in ZOOM_LEVELS:
            combo.addItem(name, zoom)
        return combo

    @staticmethod
    def _set_zoom(combo: QComboBox, *views: ImageView) -> None:
        center = views[0].center()
        for view in views:
            view.set_zoom(combo.currentData(), center)

    def _error(self, text: str) -> None:
        QMessageBox.warning(self, "Ошибка", text)

    def _start_dir(self) -> str:
        return os.path.dirname(self.container_path) if self.container_path else os.getcwd()

    # ------------------------------------------------------------------ действия

    def open_container(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Открыть изображение", self._start_dir(), IMAGE_FILTER)
        if not path:
            return
        try:
            arr, info, fmt = core.load_image(path)
        except core.StegoError as exc:
            self._error(str(exc))
            return
        self.container, self.container_path = arr, path
        self.save_container_btn.setEnabled(True)
        self.stego = None
        self.container_info.setText(f"{os.path.basename(path)}<br>{info}")
        self.original_view.view.set_array(arr)
        self.stego_view.view.set_array(None)
        self.save_btn.setEnabled(False)
        self.metrics_label.clear()
        self._update_capacity()
        self._update_plane_view()
        if fmt == "BMP":
            self.statusBar().showMessage(f"Загружено: {path}")
        else:
            self.statusBar().showMessage(f"Загружено: {path} — изображение {fmt} преобразовано в BMP 24 бит.")

    def save_container(self) -> None:
        if self.container is None:
            return
        base = os.path.splitext(self.container_path)[0] + ".bmp"
        path = self._ask_bmp_path("Сохранить контейнер как BMP", base)
        if path and self._write_bmp(self.container, path):
            self.statusBar().showMessage(f"Контейнер сохранён в BMP: {path}")

    def _ask_bmp_path(self, title: str, default: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, title, default, BMP_FILTER)
        if path and not path.lower().endswith(".bmp"):
            path += ".bmp"
        return path

    def _write_bmp(self, arr: np.ndarray, path: str) -> bool:
        try:
            core.save_bmp(arr, path)
        except (OSError, ValueError) as exc:
            self._error(f"Не удалось сохранить файл:\n{exc}")
            return False
        return True

    def load_message(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Загрузить текст", self._start_dir(), TEXT_FILTER)
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                self.message_edit.setPlainText(f.read())
        except (OSError, UnicodeDecodeError) as exc:
            self._error(f"Не удалось прочитать файл (ожидается текст в UTF-8):\n{exc}")

    def do_embed(self) -> None:
        if self.container is None:
            self._error("Сначала откройте изображение-контейнер.")
            return
        message = self.message_edit.toPlainText().encode("utf-8")
        if not message:
            self._error("Введите сообщение для встраивания.")
            return
        channels, planes, skip = self.params()
        try:
            self.stego = core.embed(self.container, message, channels, planes, skip)
        except core.StegoError as exc:
            self._error(str(exc))
            return
        self.stego_view.view.set_array(self.stego)
        self.save_btn.setEnabled(True)

        mse, psnr, changed = core.metrics(self.container, self.stego)
        total = self.container.shape[0] * self.container.shape[1]
        psnr_text = "∞" if psnr == float("inf") else f"{psnr:.2f} дБ"
        used_bits = (len(message) + 4) * 8
        cap_bits = core.capacity_bits(self.container.shape, channels, planes, skip)
        self.metrics_label.setText(
            f"Встроено {len(message)} байт ({used_bits} бит с заголовком, "
            f"{100 * used_bits / cap_bits:.1f}% ёмкости). "
            f"Изменено пикселей: {changed} из {total}. MSE = {mse:.4f}, PSNR = {psnr_text}"
        )
        self._update_plane_view()
        self.statusBar().showMessage("Сообщение встроено. Сохраните результат в файл BMP.")

    def save_stego(self) -> None:
        if self.stego is None:
            return
        base = os.path.splitext(self.container_path)[0] + "_stego.bmp"
        path = self._ask_bmp_path("Сохранить стегоконтейнер", base)
        if path and self._write_bmp(self.stego, path):
            self.statusBar().showMessage(f"Сохранено: {path}")

    def open_extract_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Открыть стегоконтейнер", self._start_dir(), IMAGE_FILTER)
        if not path:
            return
        try:
            arr, info, fmt = core.load_image(path, normalize=False)
        except core.StegoError as exc:
            self._error(str(exc))
            return
        self._set_extract_image(arr, f"{os.path.basename(path)} — {info}")
        if fmt in core.LOSSY_FORMATS:
            QMessageBox.information(
                self, "Внимание",
                f"Формат {fmt} может использовать сжатие с потерями, которое разрушает "
                "младшие биты. Сообщение, скорее всего, не удастся извлечь — "
                "используйте стегоконтейнер в формате BMP.",
            )

    def use_stego_for_extract(self) -> None:
        if self.stego is None:
            self._error("Встраивание ещё не выполнено.")
            return
        self._set_extract_image(self.stego.copy(), "Результат встраивания (из памяти)")

    def _set_extract_image(self, arr: np.ndarray, info: str) -> None:
        self.extract_image = arr
        self.extract_info.setText(info)
        self.extract_view.set_array(arr)
        self.extracted_edit.clear()
        self.save_text_btn.setEnabled(False)
        self._update_plane_view()

    def do_extract(self) -> None:
        if self.extract_image is None:
            self._error("Сначала откройте изображение для извлечения.")
            return
        channels, planes, skip = self.params()
        try:
            data = core.extract(self.extract_image, channels, planes, skip)
        except core.StegoError as exc:
            self.extracted_edit.clear()
            self.save_text_btn.setEnabled(False)
            self._error(str(exc))
            return
        try:
            text = data.decode("utf-8")
            self.statusBar().showMessage(f"Извлечено {len(data)} байт.")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
            QMessageBox.information(
                self, "Внимание",
                f"Извлечено {len(data)} байт, но они не являются корректным текстом UTF-8.\n"
                "Возможно, параметры извлечения не совпадают с параметрами встраивания.",
            )
        self.extracted_edit.setPlainText(text)
        self.save_text_btn.setEnabled(True)

    def save_extracted(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить текст", self._start_dir(), TEXT_FILTER)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.extracted_edit.toPlainText())
        except OSError as exc:
            self._error(f"Не удалось сохранить файл:\n{exc}")


def main() -> None:
    app = QApplication(sys.argv)
    # Имя приложения попадает в X11-свойство WM_CLASS (кодировка Latin-1),
    # по нему панель задач подписывает окно — поэтому только ASCII.
    app.setApplicationName("LSB-Stego")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("lsb-stego")
    app.setWindowIcon(QIcon(ICON_PATH))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
