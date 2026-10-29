"""Headless checks for in-editor startup and single-window lifecycle."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop.app import MainWindow, configure_application
from desktop.startup import BootAnimation


class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)
        configure_application(cls.application)

    def tearDown(self):
        for widget in self.application.topLevelWidgets():
            widget.close()

    def open_editor(self):
        window = MainWindow()
        window.start_boot_animation()
        window.show()
        self.application.processEvents()
        self.assertIs(window.interface_stack.currentWidget(), window.boot_animation)
        self.assertFalse(window.editor_root.isVisible())
        self.assertFalse(window.statusBar().isVisible())
        self.assertEqual(window.interface_stack.geometry(), window.rect())
        self.assertEqual(window.boot_animation.geometry(), window.interface_stack.rect())
        self.assertFalse(window.boot_animation.isWindow())
        self.assertIs(window.boot_animation.window(), window)
        self.assertFalse(window.choose_button.isEnabled())
        self.assertEqual([w for w in self.application.topLevelWidgets() if w.isVisible()], [window])
        return window

    def drive(self, splash, timeout=8000):
        loop = QEventLoop()
        completed = []
        splash.finished.connect(lambda: (completed.append(True), loop.quit()))
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        deadline.start(timeout)
        loop.exec()
        deadline.stop()
        self.assertEqual(completed, [True], 'Boot did not finish exactly once')
        self.assertFalse(splash.timer.isActive())
        self.assertFalse(splash.isVisible())

    def test_full_animation_stays_in_same_editor_window(self):
        window = self.open_editor()
        handle = window.winId()
        self.drive(window.boot_animation)
        self.assertEqual(window.winId(), handle)
        self.assertTrue(window.isVisible())
        self.assertIs(window.interface_stack.currentWidget(), window.editor_root)
        self.assertTrue(window.editor_root.isVisible())
        self.assertTrue(window.statusBar().isVisible())
        self.assertIs(window.display_stack.currentWidget(), window.scroll)
        self.assertEqual(len(window.boot_animation.logs), 10)
        self.assertTrue(window.choose_button.isEnabled())
        self.assertTrue(window.convert_button.isEnabled())
        self.assertFalse(window.undo_button.isEnabled())
        self.assertTrue(all(not button.isEnabled() for button in window.export_buttons))
        self.assertEqual([w for w in self.application.topLevelWidgets() if w.isVisible()], [window])

    def test_escape_skips_delays_but_checks_modules(self):
        window = self.open_editor()
        splash = window.boot_animation
        QTest.keyClick(splash, Qt.Key.Key_Escape)
        self.drive(splash, 3000)
        self.assertTrue(window.choose_button.isEnabled())
        self.assertEqual(len(splash.logs), 10)
        self.assertLess(splash.clock.elapsed(), 3000)

    def test_click_skips_logo_and_completion_is_idempotent(self):
        window = self.open_editor()
        splash = window.boot_animation
        splash.phase = 'logo'
        splash.reveal_clock.start()
        QTest.mouseClick(splash, Qt.MouseButton.LeftButton)
        self.drive(splash, 1000)
        with patch.object(splash, 'finished') as finished:
            splash._finish()
            finished.emit.assert_not_called()

    def test_resize_and_close_during_animation(self):
        window = self.open_editor()
        window.resize(1500, 960)
        self.application.processEvents()
        self.assertEqual(window.interface_stack.geometry(), window.rect())
        self.assertEqual(window.boot_animation.geometry(), window.interface_stack.rect())
        window.close()
        self.assertFalse(window.boot_animation.timer.isActive())
        self.assertFalse(window.isVisible())

    def test_startup_error_stops_timer_without_success_signal(self):
        window = self.open_editor()
        splash = window.boot_animation
        splash.skip()
        completed = []
        splash.finished.connect(lambda: completed.append(True))
        with patch('desktop.startup.QMessageBox.critical') as message, \
             patch.object(self.application, 'exit') as exit_application, \
             patch('desktop.startup.importlib.import_module', side_effect=ImportError('missing dependency')):
            splash._tick()
        message.assert_called_once()
        exit_application.assert_called_once_with(1)
        self.assertEqual(splash.phase, 'error')
        self.assertFalse(splash.timer.isActive())
        self.assertEqual(completed, [])

    def test_no_animation_opens_editor_directly(self):
        code = '''
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from desktop.startup import run
def check_windows():
    visible = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
    assert len(visible) == 1, visible
    assert visible[0].windowTitle() == 'Fuse Bead Studio'
    assert visible[0].boot_animation is None
    assert visible[0].interface_stack.currentWidget() is visible[0].editor_root
    assert visible[0].display_stack.currentWidget() is visible[0].scroll
    return 0
with patch.object(QApplication, 'exec', side_effect=check_windows):
    assert run(['main.py', '--no-animation']) == 0
'''
        result = subprocess.run([sys.executable, '-B', '-c', code],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
