"""Qt canvas displays a Python document and emits cell coordinates."""
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QPainter, QFont, QPen
from PySide6.QtWidgets import QWidget
from .model import COLORS
from .ui_components import image_drop_path


class PatternCanvas(QWidget):
    cell_clicked = Signal(int, int, bool)
    image_requested = Signal()
    file_dropped = Signal(str)

    def __init__(self, document):
        super().__init__()
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.drag_active = False
        self.document = document
        self.cell_size = 22
        self.grid = True
        self.codes = False
        self.refresh()

    def refresh(self):
        pattern = self.document.pattern
        self.setFixedSize(len(pattern[0]) * self.cell_size if pattern else 440,
                          len(pattern) * self.cell_size if pattern else 440)
        self.setCursor(Qt.CursorShape.ArrowCursor if pattern else Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName('Bead pattern' if pattern else 'Choose or drop an image')
        self.update()

    def resize_empty(self, viewport):
        self.setFixedSize(max(260, min(440, viewport.width()-40)),
                          max(240, min(340, viewport.height()-40)))

    def _paint_empty(self, painter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        painter.setBrush(QColor('#FBFAF7' if not self.drag_active else '#F8E9DF'))
        painter.setPen(QPen(QColor('#C8C0B4' if not self.drag_active else '#C05A38'), 2, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(box, 12, 12)
        cx, cy = self.width()/2, self.height()/2-44
        pattern = ('00100', '01110', '11211', '01110', '00100')
        colors = {'0': '#E9DFD0', '1': '#C05A38', '2': '#718C80'}
        painter.setPen(Qt.PenStyle.NoPen)
        for y, row in enumerate(pattern):
            for x, value in enumerate(row):
                painter.setBrush(QColor(colors[value]))
                painter.drawRoundedRect(QRectF(cx-43+x*18, cy-43+y*18, 14, 14), 4, 4)
        title_font = QFont('Segoe UI')
        title_font.setPixelSize(14)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor('#3A352F'))
        painter.drawText(QRectF(20, cy+62, self.width()-40, 46),
                         Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                         'Your bead pattern will appear here')
        hint_font = QFont('Segoe UI')
        hint_font.setPixelSize(11)
        painter.setFont(hint_font)
        painter.setPen(QColor('#7A7267'))
        painter.drawText(QRectF(20, cy+112, self.width()-40, 42),
                         Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                         'Click or drop an image to begin, then convert')
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor('#C05A38'), 1))
            painter.drawRoundedRect(box.adjusted(5, 5, -5, -5), 8, 8)

    def dragEnterEvent(self, event):
        if image_drop_path(event, self.isEnabled() and not self.document.pattern):
            self.drag_active = True
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.update()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self.drag_active = False
        self.update()
        event.accept()

    def dropEvent(self, event):
        path = image_drop_path(event, self.isEnabled() and not self.document.pattern)
        self.drag_active = False
        self.update()
        if path:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.file_dropped.emit(path)
        else:
            event.ignore()

    def keyPressEvent(self, event):
        if not self.document.pattern and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.image_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        if not self.document.pattern:
            self._paint_empty(painter)
            return
        painter.fillRect(self.rect(), QColor('#ffffff'))
        size = self.cell_size
        painter.setFont(QFont('Segoe UI', max(6, int(size / 3))))
        for y, row in enumerate(self.document.pattern):
            for x, cell in enumerate(row):
                rect = QRectF(x * size, y * size, size, size)
                if not rect.intersects(QRectF(event.rect())):
                    continue
                color = COLORS[cell.code] if cell.code else None
                painter.fillRect(rect, QColor(color['displayHex'] if color else '#eeeeea'))
                if self.grid:
                    painter.setPen(QColor('#b9b5ad'))
                    painter.drawRect(rect)
                if self.codes and color and size >= 18:
                    painter.setPen(QColor('white' if sum(color['rgb'].values()) < 360 else '#222222'))
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, cell.code)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self.document.pattern:
            self.image_requested.emit()
            return
        x, y = int(event.position().x() // self.cell_size), int(event.position().y() // self.cell_size)
        if 0 <= y < len(self.document.pattern) and 0 <= x < len(self.document.pattern[0]):
            self.cell_clicked.emit(x, y, bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
