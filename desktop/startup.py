"""Whole-window startup animation: spinner, module checks and logo."""
import importlib
import sys

from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget


MODULES = (
    ('numpy', 'numpy'),
    ('Pillow', 'PIL.Image'),
    ('bead palette', 'backend.palette'),
    ('colour science', 'backend.color_science'),
    ('image processing', 'backend.image_processing'),
    ('document model', 'desktop.model'),
    ('pattern canvas', 'desktop.canvas'),
    ('preview display', 'desktop.processing_view'),
    ('desktop controls', 'desktop.ui_components'),
    ('main window', 'desktop.app'),
)
LOGO = (
    '╭──────────────────────────╮',
    '│                          │',
    '│     FUSE BEAD STUDIO     │',
    '│                          │',
    '╰──────────────────────────╯',
)


class BootAnimation(QWidget):
    finished = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setAccessibleName('Fuse Bead Studio startup. Press Escape to skip animation.')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.logs = []
        self.phase = 'loading'
        self.skipped = False
        self.next_module = 320
        self.clock = QElapsedTimer()
        self.reveal_clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)

    def start(self):
        self.show()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.clock.start()
        self.timer.start()

    def skip(self):
        self.skipped = True

    def _finish(self):
        if self.phase == 'done':
            return
        self.phase = 'done'
        self.timer.stop()
        self.finished.emit()

    def _tick(self):
        try:
            if self.phase == 'loading':
                if not self.skipped and self.clock.elapsed() < self.next_module:
                    self.update()
                    return
                if len(self.logs) < len(MODULES):
                    label, module = MODULES[len(self.logs)]
                    importlib.import_module(module)
                    self.logs.append(label)
                    self.next_module = self.clock.elapsed() + 200
                else:
                    self.phase = 'logo'
                    self.reveal_clock.start()
            # Skipping removes presentation delays; required imports still run.
            if self.phase == 'logo' and (self.skipped or self.reveal_clock.elapsed() >= 1880):
                self._finish()
            self.update()
        except Exception as error:
            self.timer.stop()
            self.phase = 'error'
            QMessageBox.critical(self.window(), 'Unable to start Fuse Bead Studio', str(error))
            self.window().close()
            QApplication.instance().exit(1)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.skip()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.skip()
        else:
            super().mousePressEvent(event)

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#080808'))
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont('Consolas', 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        painter.setFont(font)
        centre = Qt.AlignmentFlag.AlignCenter
        if self.phase == 'logo':
            elapsed = self.reveal_clock.elapsed()
            if elapsed < 400:
                shade = int(65 + 190 * elapsed / 400)
            elif elapsed < 1200:
                shade = 255
            else:
                shade = max(0, int(255 * (1880 - elapsed) / 680))
            painter.setPen(QColor(shade, shade, shade))
            line_height = painter.fontMetrics().height()
            top = (self.height() - len(LOGO) * line_height) / 2
            for index, line in enumerate(LOGO):
                painter.drawText(QRectF(0, top + index * line_height, self.width(), line_height), centre, line)
            return
        painter.setPen(QColor(85, 85, 85))
        painter.drawText(QRectF(24, 20, self.width() - 48, 24), 'PYTHON / BOOT')
        painter.setPen(QColor(225, 225, 225))
        painter.setFont(QFont('Segoe UI Symbol', 24))
        spinner = '◐◓◑◒'[(self.clock.elapsed() // 85) % 4] if self.clock.isValid() else '◐'
        painter.drawText(QRectF(0, self.height() * .30, self.width(), 44), centre, spinner)
        painter.setFont(font)
        painter.setPen(QColor(135, 135, 135))
        painter.drawText(QRectF(0, self.height() * .30 + 58, self.width(), 24), centre, 'Initializing environment')
        line_height = painter.fontMetrics().height() + 2
        log_bottom = self.height() - 50
        capacity = max(0, int((log_bottom - (self.height() * .30 + 100)) / line_height))
        visible = self.logs[-capacity:] if capacity else []
        for index, label in enumerate(visible):
            shade = min(180, 65 + index * 15)
            painter.setPen(QColor(shade, shade, shade))
            painter.drawText(QRectF(24, log_bottom - (len(visible) - index) * line_height,
                                   self.width() - 48, line_height), f'[ OK   ]  {label:<18} loaded')
        painter.setPen(QColor(85, 85, 85))
        painter.drawText(QRectF(24, self.height() - 30, self.width() - 48, 20),
                         Qt.AlignmentFlag.AlignRight, 'Esc / click to skip')


def run(argv=None):
    arguments = list(sys.argv if argv is None else argv)
    animate = '--no-animation' not in arguments
    application = QApplication([argument for argument in arguments if argument != '--no-animation'])
    application.setApplicationName('Fuse Bead Studio')
    from .app import MainWindow, configure_application
    configure_application(application)
    window = MainWindow()
    if animate:
        window.start_boot_animation()
    window.show()
    return application.exec()
