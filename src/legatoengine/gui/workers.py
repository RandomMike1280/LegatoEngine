"""Runs conversions in a separate process, so the window stays responsive and Cancel
can stop a download, the separation model or the transcription model immediately."""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import traceback

from PySide6.QtCore import QObject, QTimer, Signal

from ..models import Song

_FRIENDLY_ERRORS = ("AudioError", "LinkError", "ModelDownloadError", "ValueError")
DOWNLOAD_SHARE = 0.1  # of the progress bar, when converting a link


def _convert_main(path: str, kind: str, out) -> None:
    import os
    import warnings

    os.environ.setdefault("MPLBACKEND", "Agg")
    warnings.simplefilter("ignore")
    try:
        from autopiano.ingest.convert import load_song
        from autopiano.ingest.download import download, is_link

        def report(label: str, fraction: float, begin: float = 0.0, width: float = 1.0) -> None:
            out.put(("progress", label, begin + width * fraction))

        title = None
        begin = 0.0
        if is_link(path):
            got = download(path, progress=lambda label, fraction: report(label, fraction, 0.0, DOWNLOAD_SHARE))
            out.put(("downloaded", str(got.path), got.title))
            path, title, begin = str(got.path), got.title, DOWNLOAD_SHARE
        song = load_song(path, kind, progress=lambda label, fraction: report(label, fraction, begin, 1 - begin))
        song.title = title or song.title
        out.put(("done", song.to_dict()))
    except Exception as e:
        message = str(e) if type(e).__name__ in _FRIENDLY_ERRORS else f"Something went wrong while converting: {e}"
        out.put(("error", message, traceback.format_exc()))


class ConvertJob(QObject):
    progress = Signal(str, float)  # stage label, overall fraction
    finished = Signal(object)  # Song
    failed = Signal(str, str)  # message for the user, technical details
    downloaded = Signal(str, str)  # a link's song was saved: file, title

    def __init__(self, path: str, kind: str, parent: QObject | None = None):
        super().__init__(parent)
        ctx = mp.get_context("spawn")
        self._queue = ctx.Queue()
        self._process = ctx.Process(target=_convert_main, args=(str(path), kind, self._queue), daemon=True)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        self._done = False

    def start(self) -> None:
        # Read by macOS when the conversion process starts: it hands the memory of freed audio and
        # model buffers straight back, instead of keeping up to about 1 GB of it on hand for reuse
        os.environ["MallocLargeCache"] = "0"
        self._process.start()
        self._timer.start()

    def cancel(self) -> None:
        self._done = True
        self._timer.stop()
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(2)

    @property
    def running(self) -> bool:
        return not self._done

    def _poll(self) -> None:
        alive = self._process.is_alive()
        try:
            while True:
                if self._handle(self._queue.get(timeout=0.5) if not alive else self._queue.get_nowait()):
                    return
        except queue.Empty:
            pass
        if not alive and not self._done:
            self._finish()
            self.failed.emit("The converter stopped unexpectedly.", f"exit code {self._process.exitcode}")

    def _handle(self, message: tuple) -> bool:
        kind = message[0]
        if kind == "progress":
            self.progress.emit(message[1], message[2])
            return False
        if kind == "downloaded":
            self.downloaded.emit(message[1], message[2])
            return False
        self._finish()
        if kind == "done":
            self.finished.emit(Song.from_dict(message[1]))
        else:
            self.failed.emit(message[1], message[2])
        return True

    def _finish(self) -> None:
        self._done = True
        self._timer.stop()
        self._process.join(1)
