"""Plain display of real backend snapshots, replaced as processing advances."""
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget


class ProcessingView(QWidget):
    completed = Signal()
    stages = ('source', 'edges', 'background', 'sampling', 'matching', 'cleanup')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 380)
        self.frame = None
        self.pixmap = QPixmap()
        self.seen_stages = []
        self.progress = 0
        self.running = False

    def begin(self):
        self.frame = None
        self.pixmap = QPixmap()
        self.seen_stages.clear()
        self.progress = 0
        self.running = True
        self.update()

    def add_frame(self, frame):
        if not self.running:
            return
        self.frame = frame
        # Qt image objects belong to the GUI thread; backend snapshots are PIL.
        self.pixmap = QPixmap.fromImage(ImageQt(frame.image).copy())
        if not self.seen_stages or self.seen_stages[-1] != frame.stage:
            self.seen_stages.append(frame.stage)
        self.update()

    def set_progress(self, value):
        self.progress = max(self.progress, min(100, value))

    def finish(self):
        if self.running:
            self.running = False
            self.completed.emit()

    def abort(self):
        self.running = False
        self.frame = None
        self.pixmap = QPixmap()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#ffffff'))
        box = QRectF(12, 12, self.width() - 24, max(100, self.height() - 60))
        if not self.pixmap.isNull():
            size = self.pixmap.size().scaled(box.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(box.center().x() - size.width() / 2,
                            box.center().y() - size.height() / 2, size.width(), size.height())
            # Checkerboard represents transparent pixels in actual mask images.
            painter.save()
            painter.setClipRect(target)
            for y in range(int(target.top()), int(target.bottom()) + 1, 16):
                for x in range(int(target.left()), int(target.right()) + 1, 16):
                    if ((x - int(target.left())) // 16 + (y - int(target.top())) // 16) % 2:
                        painter.fillRect(QRectF(x, y, 16, 16), QColor('#eeeeea'))
            smooth = self.frame.stage in ('source', 'edges', 'background')
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
            painter.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))
            painter.restore()
        painter.setPen(QColor('#756d60'))
        painter.setFont(QFont('Segoe UI', 10))
        title = self.frame.title if self.frame else 'Preparing image…'
        painter.drawText(QRectF(12, self.height() - 34, self.width() - 24, 24),
                         Qt.AlignmentFlag.AlignCenter, title)
