"""Small reusable desktop surfaces; no image-processing logic or animation."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QToolButton, QFormLayout, QScrollArea,
    QTableWidget, QLabel, QFrame, QSizePolicy,
)


IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}


def image_drop_path(event, enabled=True):
    if not enabled or not event.possibleActions() & Qt.DropAction.CopyAction:
        return ''
    urls = event.mimeData().urls()
    if len(urls) != 1 or not urls[0].isLocalFile():
        return ''
    path = Path(urls[0].toLocalFile())
    return str(path) if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file() else ''


class SettingsSection(QFrame):
    """Instant keyboard-accessible collapse, preserving widget state and slots."""
    def __init__(self, title, expanded=True):
        super().__init__()
        self.setObjectName('settingsSection')
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 12)
        layout.setSpacing(6)
        self.header = QToolButton()
        self.header.setObjectName('sectionHeader')
        self.header.setText(title.replace('&', '&&'))
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.setFixedHeight(30)
        layout.addWidget(self.header)
        self.content = QWidget()
        self.form = QFormLayout(self.content)
        layout.addWidget(self.content)
        self.header.toggled.connect(self.set_expanded)
        self.set_expanded(expanded)

    def set_expanded(self, expanded):
        if self.header.isChecked() != expanded:
            self.header.setChecked(expanded)
            return
        self.content.setVisible(expanded)
        self.header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.header.setAccessibleName(self.header.text().replace('&&', '&'))
        self.header.setToolTip(('Collapse ' if expanded else 'Expand ') + self.header.text().replace('&&', '&'))
        self.layout().setContentsMargins(12, 6, 12, 12 if expanded else 6)
        self.updateGeometry()


class _ScrollShade(QWidget):
    def __init__(self, parent, top):
        super().__init__(parent)
        self.top = top
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, 0, self.height())
        opaque, clear = QColor('#F2EFE8'), QColor(242, 239, 232, 0)
        gradient.setColorAt(0, opaque if self.top else clear)
        gradient.setColorAt(1, clear if self.top else opaque)
        painter.fillRect(self.rect(), gradient)


class SettingsScrollArea(QScrollArea):
    """Inset viewport and static edge shading soften partially scrolled rows."""
    def __init__(self):
        super().__init__()
        self.setViewportMargins(0, 8, 0, 8)
        self.top_shade = _ScrollShade(self.viewport(), True)
        self.bottom_shade = _ScrollShade(self.viewport(), False)
        self.verticalScrollBar().valueChanged.connect(self._update_shades)
        self.verticalScrollBar().rangeChanged.connect(self._update_shades)

    def _update_shades(self, *args):
        width, height = self.viewport().width(), self.viewport().height()
        self.top_shade.setGeometry(0, 0, width, 16)
        self.bottom_shade.setGeometry(0, max(0, height-16), width, 16)
        bar = self.verticalScrollBar()
        self.top_shade.setVisible(bar.value() > bar.minimum())
        self.bottom_shade.setVisible(bar.value() < bar.maximum())
        self.top_shade.raise_()
        self.bottom_shade.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'top_shade'):
            self._update_shades()


class CanvasArea(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setObjectName('canvasArea')
        self.viewport().setObjectName('canvasViewport')
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def setWidget(self, widget):
        super().setWidget(widget)
        widget.setAutoFillBackground(False)

    def sync_empty(self):
        canvas = self.widget()
        if canvas is not None and not canvas.document.pattern:
            canvas.resize_empty(self.viewport().size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_empty()


class MaterialsTable(QTableWidget):
    def __init__(self):
        super().__init__(0, 3)
        self.setObjectName('materialsTable')
        self.empty_label = QLabel('No beads generated yet\nConvert an image to see its colours.', self.viewport())
        self.empty_label.setObjectName('tableEmptyHint')
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(32)
        self.horizontalHeader().setFixedHeight(32)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

    def setRowCount(self, count):
        super().setRowCount(count)
        if hasattr(self, 'empty_label'):
            self.empty_label.setVisible(count == 0)
            self.empty_label.setGeometry(self.viewport().rect().adjusted(16, 8, -16, -8))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'empty_label'):
            self.empty_label.setGeometry(self.viewport().rect().adjusted(16, 8, -16, -8))
