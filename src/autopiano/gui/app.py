"""Starts the AutoPiano desktop app."""

from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path


def main() -> int:
    if sys.platform != "darwin":
        print("The AutoPiano window needs macOS so far. On Windows, convert songs with autopiano-cli convert,\n"
              "and play the scripts with AutoPiano Player (player-app in the project folder).", file=sys.stderr)
        return 1
    multiprocessing.freeze_support()  # conversions run in a child process, also in the packaged app
    sys.setswitchinterval(0.001)  # hand the GIL to the player thread quickly while the window redraws

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    class App(QApplication):
        """Also receives files opened from Finder: double-clicked scripts, songs dropped on the Dock icon."""

        def __init__(self, argv: list[str]):
            super().__init__(argv)
            self.window = None
            self.pending: list[str] = []

        def event(self, event) -> bool:
            if event.type() == QEvent.Type.FileOpen:
                if self.window is None:
                    self.pending.append(event.file())  # arrived before the window exists
                else:
                    self.window.open_path(event.file())
                return True
            return super().event(event)

    QCoreApplication.setOrganizationName("AutoPiano")
    QCoreApplication.setOrganizationDomain("autopiano.local")
    QCoreApplication.setApplicationName("AutoPiano")
    app = App(sys.argv)

    from .main_window import MainWindow

    window = MainWindow()
    window.show()
    app.window = window
    for path in app.pending + [arg for arg in sys.argv[1:] if Path(arg).is_file()]:
        window.open_path(path)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
