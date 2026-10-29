"""Desktop controller: widgets -> Python parameters -> worker -> document."""
import sys
from pathlib import Path

from PIL import Image, ImageOps
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QPixmap, QKeySequence, QShortcut, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QSpinBox, QSlider, QCheckBox, QListWidget, QListWidgetItem,
    QFileDialog, QColorDialog, QScrollArea, QSplitter, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QComboBox, QStackedWidget,
    QFrame, QSizePolicy, QMenu,
)
from backend.image_processing import MAX_DIMENSION, Parameters, COLORS, convert_image
from .model import Document
from .canvas import PatternCanvas
from .processing_view import ProcessingView
from .ui_components import SettingsSection, CanvasArea, MaterialsTable, SettingsScrollArea, image_drop_path


class ImageDropZone(QLabel):
    """Accept one local image without moving or modifying the source file."""
    file_dropped = Signal(str)
    extensions = {'.png', '.jpg', '.jpeg', '.webp'}

    def __init__(self):
        super().__init__('Drop an image here\nPNG · JPG · WEBP')
        self.setObjectName('imageDropZone')
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(150)
        self.setAcceptDrops(True)
        self.setToolTip('Drag one PNG, JPG or WEBP file here. Drop another image to replace the preview.')
        self.setProperty('dragActive', False)

    def _path(self, event):
        return image_drop_path(event, self.isEnabled())

    def _highlight(self, active):
        self.setProperty('dragActive', active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def dragEnterEvent(self, event):
        if self._path(event):
            self._highlight(True)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            self._highlight(False)
            event.ignore()

    def dragMoveEvent(self, event):
        if self._path(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            self._highlight(False)
            event.ignore()

    def dragLeaveEvent(self, event):
        self._highlight(False)
        event.accept()

    def dropEvent(self, event):
        self._highlight(False)
        path = self._path(event)
        if path:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.file_dropped.emit(path)
        else:
            event.ignore()


class ConversionWorker(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(int)
    preview = Signal(object)

    def __init__(self, path, params, parent):
        super().__init__(parent)
        self.path, self.params = path, params

    def run(self):
        try:
            pattern = convert_image(self.path, self.params, self.progress.emit,
                                    self.isInterruptionRequested, self.preview.emit)
            self.result.emit(pattern)
        except Exception as error:
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.document = Document()
        self.image_path = ''
        self.background = '#ffffff'
        self.image_ratio = 1
        self.worker = None
        self.boot_animation = None
        self._worker_done = False
        self._preview_done = False
        self._pending_pattern = None
        self.setWindowTitle('Fuse Bead Studio')
        self.resize(1400, 900)
        root = QWidget()
        self.editor_root = root
        self.interface_stack = QStackedWidget()
        self.interface_stack.addWidget(root)
        self.setCentralWidget(self.interface_stack)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 8)
        layout.setSpacing(12)
        title = QLabel('Fuse Bead Studio')
        title.setObjectName('title')
        layout.addWidget(title)
        layout.addWidget(QLabel('Hama Midi · Turn your images into buildable bead patterns'))
        splitter = QSplitter()
        splitter.setHandleWidth(12)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        self.settings = QWidget()
        left = QVBoxLayout(self.settings)
        left.setContentsMargins(12, 4, 14, 8)
        left.setSpacing(12)
        self.choose_button = self.button('Choose image…', self.choose_image)
        self.preview = ImageDropZone()
        self.preview.file_dropped.connect(self.import_image)
        left.addWidget(self.preview)
        self.source_name = QLabel('Drag a file above, or use Choose image…')
        self.source_name.setWordWrap(True)
        self.source_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.source_name)
        dimensions = SettingsSection('Size & Crop')
        self.size_section = dimensions
        form = dimensions.form
        self.width, self.height = QSpinBox(), QSpinBox()
        for spin in (self.width, self.height):
            spin.setRange(1, MAX_DIMENSION)
            spin.setValue(32)
        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        width_label, height_label = QLabel('W'), QLabel('H')
        width_label.setBuddy(self.width)
        height_label.setBuddy(self.height)
        self.width.setAccessibleName('Pattern width')
        self.height.setAccessibleName('Pattern height')
        size_row.addWidget(width_label)
        size_row.addWidget(self.width, 1)
        size_row.addWidget(QLabel('×'))
        size_row.addWidget(height_label)
        size_row.addWidget(self.height, 1)
        form.addRow(size_row)
        self.fit_mode = QComboBox()
        self.fit_mode.addItem('Keep whole image', 'contain')
        self.fit_mode.addItem('Centre crop to fill', 'cover')
        form.addRow('Image fit', self.fit_mode)
        self.lock = QCheckBox('Keep source aspect ratio')
        form.addRow(self.lock)
        self.width.valueChanged.connect(lambda value: self.sync_dimensions(True, value))
        self.height.valueChanged.connect(lambda value: self.sync_dimensions(False, value))
        self.lock.toggled.connect(lambda checked: self.sync_dimensions(True, self.width.value()) if checked else None)
        presets = QComboBox()
        presets.addItem('Square presets…', None)
        for size in (16, 24, 32, 40, 50, 64, 96, 128, 192, MAX_DIMENSION):
            presets.addItem(f'{size} × {size}', size)
        presets.activated.connect(lambda index: self.preset(presets.itemData(index)))
        form.addRow(presets)
        left.addWidget(dimensions)
        adjustments = SettingsSection('Image Adjustments', expanded=False)
        self.adjustments_section = adjustments
        form = adjustments.form
        self.sliders = {}
        for name in ('Brightness', 'Contrast', 'Saturation'):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-100, 100)
            value = QLabel('0')
            value.setFixedWidth(value.fontMetrics().horizontalAdvance('−100') + 4)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            slider.valueChanged.connect(lambda number, label=value: label.setText(str(number)))
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(slider, 1)
            row.addWidget(value)
            form.addRow(name, row)
            self.sliders[name.lower()] = slider
        self.background_button = self.button('Background: #ffffff', self.choose_background)
        form.addRow(self.background_button)
        self.empty = QCheckBox('Transparent pixels become empty')
        self.empty.setChecked(True)
        form.addRow(self.empty)
        left.addWidget(adjustments)
        processing = SettingsSection('Automatic Image Processing')
        self.processing_section = processing
        form = processing.form
        self.auto_background = QCheckBox('Remove plain connected background')
        self.auto_background.setChecked(True)
        self.auto_background.setToolTip('Detects a plain colour shared by at least three corners and removes only border-connected areas. Disable for busy photos or subjects matching the background.')
        form.addRow(self.auto_background)
        self.background_tolerance = QSpinBox()
        self.background_tolerance.setRange(0, 50)
        self.background_tolerance.setValue(12)
        self.background_tolerance.setToolTip('Higher values remove more shades of the detected background.')
        self.auto_background.toggled.connect(self.background_tolerance.setEnabled)
        form.addRow('Background tolerance', self.background_tolerance)
        self.edge_protection = QSpinBox()
        self.edge_protection.setRange(0, 100)
        self.edge_protection.setValue(70)
        self.edge_protection.setSuffix('%')
        self.edge_protection.setSpecialValueText('Off')
        self.edge_protection.setToolTip('Higher values preserve hair and clothing close to the background colour. Lower if background fringes remain. Zero uses colour-only removal.')
        self.auto_background.toggled.connect(self.edge_protection.setEnabled)
        form.addRow('Edge protection', self.edge_protection)
        self.sampling = QComboBox()
        for label, mode in [('Automatic', 'auto'), ('Photo · continuous tones', 'photo'),
                            ('Cartoon · dominant colour', 'cartoon'),
                            ('Logo / line art · thin strokes', 'lineart'),
                            ('Landscape · continuous tones', 'scene'), ('Pixel art · hard edges', 'pixel')]:
            self.sampling.addItem(label, mode)
        form.addRow('Image type', self.sampling)
        self.low_resolution = QCheckBox('Optimise small patterns (≤64)')
        self.low_resolution.setChecked(True)
        self.low_resolution.setToolTip('Preserve contours, align the grid, protect thin strokes and holes, and fit shapes with the bead palette. Pixel art keeps nearest-neighbour sampling. Disable to compare.')
        form.addRow(self.low_resolution)
        self.max_colors = QSpinBox()
        self.max_colors.setRange(0, len(COLORS))
        self.max_colors.setSpecialValueText('All enabled colours')
        self.max_colors.setValue(24)
        form.addRow('Maximum colours', self.max_colors)
        self.cleanup_size = QSpinBox()
        self.cleanup_size.setRange(0, 20)
        self.cleanup_size.setValue(2)
        self.cleanup_size.setSpecialValueText('Off')
        self.cleanup_size.setToolTip('Merge small colour islands into similar neighbours; strong contrast details and empty cells are preserved.')
        form.addRow('Clean islands up to', self.cleanup_size)
        self.alpha_threshold = QSpinBox()
        self.alpha_threshold.setRange(1, 255)
        self.alpha_threshold.setValue(128)
        self.alpha_threshold.setToolTip('Minimum foreground coverage for a subject bead. Higher values tighten the outline. Also controls filled edges after automatic background removal.')
        update_coverage_control = lambda: self.alpha_threshold.setEnabled(
            self.empty.isChecked() or self.auto_background.isChecked())
        update_coverage_control()
        self.empty.toggled.connect(update_coverage_control)
        self.auto_background.toggled.connect(update_coverage_control)
        form.addRow('Foreground coverage', self.alpha_threshold)
        self.denoise = QCheckBox('Light photo noise reduction')
        self.denoise.setChecked(True)
        form.addRow(self.denoise)
        self.dither_strength = QSpinBox()
        self.dither_strength.setRange(0, 100)
        self.dither_strength.setSpecialValueText('Off')
        self.dither_strength.setToolTip('Blend colours using small dots to reproduce gradients. This increases pattern texture.')
        form.addRow('Gradient dithering %', self.dither_strength)
        left.addWidget(processing)
        left.addWidget(QLabel(f'Available colours · {len(COLORS)}'))
        self.palette = QListWidget()
        self.palette.setFixedHeight(170)
        for code, color in COLORS.items():
            item = QListWidgetItem(f"{code}   {color['name']}")
            item.setData(Qt.ItemDataRole.UserRole, code)
            item.setCheckState(Qt.CheckState.Checked)
            swatch = QPixmap(18, 18)
            swatch.fill(QColor(color['displayHex']))
            item.setIcon(QIcon(swatch))
            self.palette.addItem(item)
        left.addWidget(self.palette)
        row = QHBoxLayout()
        row.addWidget(self.button('Select all', lambda: self.select_all(True)))
        row.addWidget(self.button('Clear selection', lambda: self.select_all(False)))
        left.addLayout(row)
        left.addStretch(1)
        self._align_settings_forms()
        self.convert_button = self.button('Convert to beads', self.start_conversion)
        self.convert_button.setObjectName('primary')
        self.progress = QProgressBar()
        self.progress.hide()
        settings_scroll = SettingsScrollArea()
        self.settings_scroll = settings_scroll
        settings_scroll.setObjectName('settingsScroll')
        settings_scroll.viewport().setObjectName('settingsViewport')
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(self.settings)
        settings_scroll.setMinimumWidth(392)
        settings_column = QWidget()
        settings_layout = QVBoxLayout(settings_column)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(12)
        settings_header = QHBoxLayout()
        settings_header.setContentsMargins(12, 0, 20, 0)
        settings_header.addWidget(self.choose_button)
        settings_layout.addLayout(settings_header)
        settings_layout.addWidget(settings_scroll, 1)
        # Reserve the scrollbar gutter in the footer too: button and form edges align.
        settings_footer = QVBoxLayout()
        settings_footer.setContentsMargins(12, 0, 20, 0)
        settings_footer.setSpacing(8)
        settings_footer.addWidget(self.convert_button)
        settings_footer.addWidget(self.progress)
        settings_layout.addLayout(settings_footer)
        splitter.addWidget(settings_column)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)
        toolbar_widget = QWidget()
        toolbar_widget.setObjectName('canvasToolbar')
        toolbar_widget.setFixedHeight(34)
        toolbar = QHBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(3, 1, 3, 1)
        toolbar.setSpacing(10)
        zoom_group = QWidget()
        zoom_group.setObjectName('zoomGroup')
        zoom_layout = QHBoxLayout(zoom_group)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(0)
        for text, callback, width in [('−', lambda: self.zoom(-4), 36),
                                      ('Fit', self.fit_canvas, 52), ('+', lambda: self.zoom(4), 36)]:
            button = self.button(text, callback)
            button.setFixedWidth(width)
            button.setFixedHeight(30)
            button.setObjectName('zoomButton')
            zoom_layout.addWidget(button)
        toolbar.addWidget(zoom_group)
        self.grid = QCheckBox('Grid')
        self.grid.setChecked(True)
        self.codes = QCheckBox('Codes')
        self.grid.toggled.connect(self.display_options)
        self.codes.toggled.connect(self.display_options)
        toolbar.addWidget(self.grid)
        toolbar.addWidget(self.codes)
        toolbar.addStretch(1)
        compare_button = self.button('Compare source', self.compare_source)
        compare_button.setFixedHeight(30)
        compare_button.setObjectName('toolbarButton')
        toolbar.addWidget(compare_button)
        center_layout.addWidget(toolbar_widget)
        self.canvas = PatternCanvas(self.document)
        self.canvas.cell_clicked.connect(self.edit_cell)
        self.canvas.image_requested.connect(self.choose_image)
        self.canvas.file_dropped.connect(self.import_image)
        self.scroll = CanvasArea()
        self.scroll.setWidget(self.canvas)
        self.processing_view = ProcessingView()
        self.processing_view.completed.connect(self.processing_preview_finished)
        self.display_stack = QStackedWidget()
        self.display_stack.addWidget(self.scroll)
        self.display_stack.addWidget(self.processing_view)
        center_layout.addWidget(self.display_stack, 1)
        paint_footer = QFrame()
        paint_footer.setObjectName('paintFooter')
        footer_layout = QVBoxLayout(paint_footer)
        footer_layout.setContentsMargins(10, 8, 10, 8)
        footer_layout.setSpacing(6)
        editing = QHBoxLayout()
        editing.setSpacing(6)
        self.undo_button = self.button('Undo', lambda: self.history(False))
        self.redo_button = self.button('Redo', lambda: self.history(True))
        editing.addWidget(self.undo_button)
        editing.addWidget(self.redo_button)
        self.eraser = QCheckBox('Eraser')
        editing.addWidget(self.eraser)
        self.brush = QComboBox()
        for code, color in COLORS.items():
            self.brush.addItem(f"{code} · {color['name']}", code)
        editing.addWidget(self.brush, 1)
        footer_layout.addLayout(editing)
        hint = QLabel('Click to paint · Shift-click to pick colour · Scrollbars to pan')
        hint.setObjectName('helperText')
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        footer_layout.addWidget(hint)
        center_layout.addWidget(paint_footer)
        splitter.addWidget(center)
        right = QWidget()
        right.setMinimumWidth(280)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.sort = QComboBox()
        self.sort.addItems(['Sort by quantity', 'Sort by code'])
        self.sort.currentIndexChanged.connect(self.refresh)
        right_layout.addWidget(self.sort)
        self.materials = MaterialsTable()
        self.materials.setHorizontalHeaderLabels(['Code', 'Colour', 'Qty'])
        self.materials.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.materials.setColumnWidth(0, 54)
        self.materials.setColumnWidth(2, 58)
        self.materials.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.materials.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        right_layout.addWidget(self.materials, 1)
        stats = QFrame()
        stats.setObjectName('statsCard')
        stats_layout = QVBoxLayout(stats)
        stats_layout.setContentsMargins(12, 10, 12, 10)
        stats_layout.setSpacing(4)
        stats_title = QLabel('PATTERN SUMMARY')
        stats_title.setObjectName('eyebrow')
        stats_layout.addWidget(stats_title)
        stats_layout.addWidget(self.summary)
        right_layout.addWidget(stats)
        exports = QHBoxLayout()
        exports.setSpacing(8)
        self.export_buttons = []
        self.export_actions = {}
        for label, variants in [('Export PNG', [('Pattern', 'plain'), ('With Grid', 'grid'), ('With Codes', 'codes')]),
                                ('Export CSV', [('Bead List', 'list'), ('Matrix', 'matrix')])]:
            button = QPushButton(label)
            button.setObjectName('exportMenuButton')
            button.setFixedHeight(34)
            menu = QMenu(button)
            for caption, kind in variants:
                action = menu.addAction(caption)
                action.triggered.connect(lambda checked=False, k=kind: self.export(k))
                self.export_actions[kind] = action
            button.setMenu(menu)
            self.export_buttons.append(button)
            exports.addWidget(button, 1)
        right_layout.addLayout(exports)
        note = QLabel('Screen colours are approximate references, not physical bead measurements.')
        note.setWordWrap(True)
        note.setObjectName('helperText')
        right_layout.addWidget(note)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([408, 700, 300])
        for control in self.findChildren(QSpinBox) + self.findChildren(QComboBox):
            control.setFixedHeight(34)
            control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.choose_button.setFixedHeight(34)
        self.sort.setFixedHeight(34)
        self.brush.setFixedHeight(32)
        self.undo_button.setFixedHeight(32)
        self.redo_button.setFixedHeight(32)
        self.convert_button.setFixedHeight(36)
        for keys, callback in [('Ctrl+Z', lambda: self.history(False)),
                               ('Ctrl+Shift+Z', lambda: self.history(True))]:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(callback)
        self.refresh()
        self.statusBar().showMessage('Choose an image to begin.')

    def start_boot_animation(self):
        """Use the whole main-window content area as the startup screen."""
        from .startup import BootAnimation
        if self.boot_animation is not None:
            return
        self.boot_animation = BootAnimation(self.interface_stack)
        self.interface_stack.addWidget(self.boot_animation)
        self.interface_stack.setCurrentWidget(self.boot_animation)
        self.editor_root.setEnabled(False)
        self._startup_status_visible = not self.statusBar().isHidden()
        self.statusBar().hide()
        self._startup_shortcuts = [(shortcut, shortcut.isEnabled())
                                   for shortcut in self.findChildren(QShortcut)]
        for shortcut, _ in self._startup_shortcuts:
            shortcut.setEnabled(False)
        self.boot_animation.finished.connect(self.finish_boot_animation)
        self.boot_animation.start()

    def finish_boot_animation(self):
        self.interface_stack.setCurrentWidget(self.editor_root)
        self.editor_root.setEnabled(True)
        self.statusBar().setVisible(self._startup_status_visible)
        for shortcut, enabled in self._startup_shortcuts:
            shortcut.setEnabled(enabled)
        self.statusBar().showMessage('Choose an image to begin.')
        self.choose_button.setFocus()

    @staticmethod
    def button(text, callback):
        button = QPushButton(text)
        button.setFixedHeight(34)
        button.clicked.connect(callback)
        return button

    def _align_settings_forms(self):
        """Share one label column across the independent settings groups."""
        forms = self.settings.findChildren(QFormLayout)
        labels = [form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget()
                  for form in forms for row in range(form.rowCount())
                  if form.itemAt(row, QFormLayout.ItemRole.LabelRole) is not None]
        label_width = max(label.fontMetrics().horizontalAdvance(label.text()) for label in labels) + 4
        for form in forms:
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(8)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        for label in labels:
            label.setFixedWidth(label_width)

    def sync_dimensions(self, from_width, value):
        if self.lock.isChecked():
            target = self.height if from_width else self.width
            target.blockSignals(True)
            target.setValue(max(1, min(MAX_DIMENSION, round(value / self.image_ratio if from_width else value * self.image_ratio))))
            target.blockSignals(False)

    def preset(self, size):
        if size:
            self.lock.setChecked(False)
            self.width.setValue(size)
            self.height.setValue(size)

    def load_image(self, path):
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image).convert('RGBA')
            self.image_ratio = image.width / image.height
            image.thumbnail((230, 130))
            pixmap = QPixmap.fromImage(ImageQt(image))
        self.image_path = path
        self.preview.setPixmap(pixmap)
        self.source_name.setText(Path(path).name)
        self.preview.setToolTip(f'{path}\nDrop another image here to replace it.')
        self.sync_dimensions(True, self.width.value())
        self.statusBar().showMessage(f'Source: {Path(path).name}. Convert to apply changes.')

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose image', '', 'Images (*.png *.jpg *.jpeg *.webp)')
        if path:
            self.import_image(path)

    @Slot(str)
    def import_image(self, path):
        if self.worker is not None:
            return
        try:
            self.load_image(path)
        except Exception as error:
            self.show_error(str(error))

    def choose_background(self):
        color = QColorDialog.getColor(QColor(self.background), self)
        if color.isValid():
            self.background = color.name()
            self.background_button.setText(f'Background: {self.background}')

    def select_all(self, selected):
        for index in range(self.palette.count()):
            self.palette.item(index).setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)

    @Slot()
    def start_conversion(self):
        if self.worker is not None:
            return
        if not self.image_path:
            self.show_error('Choose an image first.')
            return
        enabled = tuple(self.palette.item(i).data(Qt.ItemDataRole.UserRole)
                        for i in range(self.palette.count())
                        if self.palette.item(i).checkState() == Qt.CheckState.Checked)
        if not enabled:
            self.show_error('Enable at least one bead colour.')
            return
        params = Parameters(width=self.width.value(), height=self.height.value(),
                            background=self.background, empty_transparent=self.empty.isChecked(),
                            fit=self.fit_mode.currentData(), sampling=self.sampling.currentData(),
                            auto_background=self.auto_background.isChecked(),
                            background_tolerance=self.background_tolerance.value(),
                            edge_protection=self.edge_protection.value(),
                            alpha_threshold=self.alpha_threshold.value(), max_colors=self.max_colors.value(),
                            cleanup_size=self.cleanup_size.value(), denoise=self.denoise.isChecked(),
                            dither_strength=self.dither_strength.value(),
                            low_resolution=self.low_resolution.isChecked(),
                            enabled=enabled, **{key: slider.value() for key, slider in self.sliders.items()})
        self.worker = ConversionWorker(self.image_path, params, self)
        self._worker_done = self._preview_done = False
        self._pending_pattern = None
        self.processing_view.begin()
        self.display_stack.setCurrentWidget(self.processing_view)
        self.worker.result.connect(self.receive_pattern)
        self.worker.failed.connect(self.processing_failed)
        self.worker.preview.connect(self.processing_view.add_frame)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.progress.connect(self.processing_view.set_progress)
        self.worker.finished.connect(self.conversion_finished)
        self.settings.setEnabled(False)
        self.canvas.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.statusBar().showMessage('Processing background, sampling colours and cleaning pattern…')
        self.refresh()
        self.worker.start()

    @Slot(object)
    def receive_pattern(self, pattern):
        self._pending_pattern = pattern
        self.processing_view.finish()
        self.statusBar().showMessage('Conversion complete.')

    @Slot()
    def processing_preview_finished(self):
        self._preview_done = True
        self._finish_conversion()

    @Slot(str)
    def processing_failed(self, message):
        self.processing_view.abort()
        self._preview_done = True
        self.display_stack.setCurrentWidget(self.scroll)
        self.show_error(message)

    @Slot(object)
    def accept_pattern(self, pattern):
        self.document.replace(pattern)
        self.refresh()
        self.fit_canvas()
        self.statusBar().showMessage('Pattern ready. Click a cell to edit.')

    @Slot()
    def conversion_finished(self):
        self._worker_done = True
        self._finish_conversion()

    def _finish_conversion(self):
        if self.worker is None or not (self._worker_done and self._preview_done):
            return
        self.display_stack.setCurrentWidget(self.scroll)
        if self._pending_pattern is not None:
            self.accept_pattern(self._pending_pattern)
            self._pending_pattern = None
        self.worker.deleteLater()
        self.worker = None
        self.settings.setEnabled(True)
        self.canvas.setEnabled(True)
        self.progress.hide()
        self.refresh()

    @Slot(str)
    def show_error(self, message):
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, 'Fuse Bead Studio', message)

    def edit_cell(self, x, y, pick):
        if self.worker is not None:
            return
        cell = self.document.pattern[y][x]
        if pick:
            if cell.code:
                self.brush.setCurrentIndex(self.brush.findData(cell.code))
                self.eraser.setChecked(False)
            return
        self.document.edit(x, y, None if self.eraser.isChecked() else self.brush.currentData())
        self.refresh()

    def history(self, redo):
        if self.worker is None:
            self.document.history(redo)
            self.refresh()

    def display_options(self):
        self.canvas.grid, self.canvas.codes = self.grid.isChecked(), self.codes.isChecked()
        self.canvas.update()

    def zoom(self, change):
        self.canvas.cell_size = min(88, max(4, self.canvas.cell_size + change))
        self.canvas.refresh()

    def fit_canvas(self):
        if self.document.pattern:
            viewport = self.scroll.viewport().size()
            self.canvas.cell_size = max(4, min(88, (viewport.width() - 8) // len(self.document.pattern[0]),
                                               (viewport.height() - 8) // len(self.document.pattern)))
            self.canvas.refresh()

    def compare_source(self):
        if not self.image_path:
            return
        try:
            with Image.open(self.image_path) as image:
                image = ImageOps.exif_transpose(image).convert('RGBA')
                image.thumbnail((900, 650))
                pixmap = QPixmap.fromImage(ImageQt(image))
            self.comparison = QLabel(self, Qt.WindowType.Window)
            self.comparison.setWindowTitle('Source image')
            self.comparison.setPixmap(pixmap)
            self.comparison.resize(pixmap.size())
            self.comparison.show()
        except Exception as error:
            self.show_error(str(error))

    def refresh(self):
        self.convert_button.setEnabled(self.worker is None)
        self.choose_button.setEnabled(self.worker is None)
        self.canvas.refresh()
        self.scroll.sync_empty()
        counts, empty, average, maximum = self.document.statistics()
        self.summary.setText(f'<b>{sum(counts.values()):,}</b> beads · <b>{len(counts)}</b> colours · {empty:,} empty<br>'
                             f'<span style="font-size:11px;color:#7A7267">Average ΔE: {average:.1f} &nbsp; Maximum ΔE: {maximum:.1f}</span>')
        items = counts.most_common() if self.sort.currentIndex() == 0 else sorted(counts.items(), key=lambda item: int(item[0]))
        self.materials.setRowCount(len(items))
        for row, (code, count) in enumerate(items):
            for column, text in enumerate((code, COLORS[code]['name'], str(count))):
                item = QTableWidgetItem(text)
                item.setTextAlignment((Qt.AlignmentFlag.AlignRight if column == 2 else
                                       Qt.AlignmentFlag.AlignHCenter if column == 0 else
                                       Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
                if column == 1:
                    swatch = QPixmap(14, 14)
                    swatch.fill(QColor(COLORS[code]['displayHex']))
                    item.setIcon(QIcon(swatch))
                self.materials.setItem(row, column, item)
        self.undo_button.setEnabled(bool(self.document.undo_stack) and self.worker is None)
        self.redo_button.setEnabled(bool(self.document.redo_stack) and self.worker is None)
        for control in self.export_buttons + list(self.export_actions.values()):
            control.setEnabled(bool(self.document.pattern) and self.worker is None)

    def export(self, kind):
        extension = 'csv' if kind in ('list', 'matrix') else 'png'
        path, _ = QFileDialog.getSaveFileName(self, 'Export pattern', f'hama-{kind}.{extension}',
                                             f'{extension.upper()} (*.{extension})')
        if path:
            if not path.lower().endswith(f'.{extension}'):
                path += f'.{extension}'
            try:
                self.document.export(path, kind)
                self.statusBar().showMessage(f'Saved: {path}')
            except Exception as error:
                self.show_error(str(error))

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.statusBar().showMessage('Stopping conversion. Close again when it has finished.')
            event.ignore()
        else:
            if self.boot_animation is not None:
                self.boot_animation.timer.stop()
            self.processing_view.abort()
            event.accept()


def configure_application(application):
    application.setStyle('Fusion')
    # Set every palette group explicitly: native dark mode must not leak into
    # scroll-area viewports, popup lists, disabled controls or indicator glyphs.
    palette = QPalette()
    colors = {
        'Window': '#f2efe8', 'WindowText': '#282820',
        'Base': '#ffffff', 'AlternateBase': '#f6f3ee',
        'Text': '#282820', 'Button': '#fbfaf6', 'ButtonText': '#282820',
        'Highlight': '#C05A38', 'HighlightedText': '#ffffff',
        'ToolTipBase': '#ffffff', 'ToolTipText': '#282820',
        'Light': '#ffffff', 'Midlight': '#eee9df', 'Mid': '#c7c0b4',
        'Dark': '#81796b', 'Shadow': '#665f54',
        'Link': '#ad3e20', 'LinkVisited': '#86462e', 'PlaceholderText': '#756d60',
        'Accent': '#C05A38',
    }
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                  QPalette.ColorGroup.Disabled):
        for role, color in colors.items():
            palette.setColor(group, getattr(QPalette.ColorRole, role), QColor(color))
    for role in ('Text', 'WindowText', 'ButtonText'):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role), QColor('#8b8478'))
    application.setPalette(palette)
    assets = (Path(__file__).parent / 'assets').resolve().as_posix()
    stylesheet = (Path(__file__).parent / 'theme.qss').read_text(encoding='utf-8')
    application.setStyleSheet(stylesheet.replace('__ASSETS__', assets))


def run():
    from .startup import run as start
    sys.exit(start())
