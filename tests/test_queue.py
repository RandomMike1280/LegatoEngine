"""The Convert tab's queue, driven by a stand-in for the converter process (nothing is downloaded)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QMimeData, QObject, QSettings, Qt, QUrl, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autopiano import paths  # noqa: E402
from autopiano.arrange.pipeline import ArrangeSettings  # noqa: E402
from autopiano.format.apno import read_script  # noqa: E402
from autopiano.gui.queue_box import FAILED, SAVED, WAITING, WORKING, QueueBox, free_path  # noqa: E402
from autopiano.gui.widgets import dropped_songs  # noqa: E402
from autopiano.ingest.convert import load_song  # noqa: E402

from .helpers import write_midi  # noqa: E402

A, B = "https://www.youtube.com/watch?v=aaaaaaaaaaa", "https://www.youtube.com/watch?v=bbbbbbbbbbb"


class FakeJob(QObject):
    progress = Signal(str, float)
    finished = Signal(object)
    failed = Signal(str, str)
    downloaded = Signal(str, str)

    def __init__(self, source, kind, parent=None):
        super().__init__(parent)
        self.source, self.kind = source, kind
        self.started = self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp("settings")))
    QCoreApplication.setOrganizationName("AutoPianoTest")
    QCoreApplication.setApplicationName("AutoPianoTest")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def library(app, tmp_path, monkeypatch):
    QSettings().clear()
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(paths, "LIBRARY_DIR", root)
    monkeypatch.setattr(paths, "DOWNLOADS_DIR", root / "Downloads")
    return root


@pytest.fixture
def jobs():
    return []


def _box(jobs, busy=lambda: False):
    def make(source, kind, parent):
        jobs.append(FakeJob(source, kind, parent))
        return jobs[-1]

    return QueueBox(lambda: ("piano", ArrangeSettings(preset="melody")), busy, job_type=make)


def _song(tmp_path, title):
    path = write_midi(tmp_path / "song.mid", [{"name": "Piano", "notes": [(60 + i, i * 0.5, 0.5, 90) for i in range(8)]}])
    song = load_song(path, "midi")
    song.title = title
    return song


def test_queue_converts_one_after_another_and_never_replaces_a_script(library, tmp_path, jobs):
    (library / "Covers").mkdir()
    (library / "Covers" / "Golden.apno").write_bytes(b"someone else's")
    (library / "Downloads").mkdir()
    box = _box(jobs)
    box.folder.setCurrentIndex(box.folder.findData("Covers"))
    assert box.folder.findData("Downloads") == -1  # downloaded songs aren't a place for scripts

    assert box.add([A, B, A]) == 2
    assert [j.source for j in jobs] == [A] and jobs[0].kind == "piano" and jobs[0].started
    assert [i.state for i in box.items] == [WORKING, WAITING]
    assert box.add([A]) == 0  # already queued

    jobs[0].progress.emit("Downloading", 0.05)
    assert "Downloading… 5%" in box.list.item(0).text()
    jobs[0].downloaded.emit(str(tmp_path / "Golden.m4a"), "Golden")
    jobs[0].finished.emit(_song(tmp_path, "Golden"))
    first = box.items[0]
    assert first.state == SAVED and first.saved == str(library / "Covers" / "Golden (2).apno")
    script = read_script(first.saved)
    assert script.meta.title == "Golden" and script.meta.preset == "melody"
    assert (library / "Covers" / "Golden.apno").read_bytes() == b"someone else's"

    assert [j.source for j in jobs] == [A, B]
    jobs[1].failed.emit("Couldn't download this link: HTTP Error 404", "details")
    assert box.items[1].state == FAILED and not box.running
    assert "Failed: Couldn't download" in box.list.item(1).text()
    assert box.status.text() == "Done: 1 converted · 1 failed"
    assert box.start_button.text() == "Retry Failed"

    box.start_or_stop()
    assert box.items[1].state == WORKING and jobs[2].source == B
    jobs[2].finished.emit(_song(tmp_path, "Second"))
    assert [i.state for i in box.items] == [SAVED, SAVED] and not box.running
    box.clear_converted()
    assert box.items == [] and box.isHidden()


def test_queue_waits_for_the_tabs_own_song_and_stops_cleanly(library, tmp_path, jobs):
    busy = [True]
    box = _box(jobs, busy=lambda: busy[0])
    box.add([A])
    assert jobs == [] and box.running
    assert box.status.text() == "1 waiting until the song above is converted"

    busy[0] = False
    box.resume()
    assert [j.source for j in jobs] == [A]

    box.stop()
    assert jobs[0].cancelled and not box.running
    assert box.items[0].state == WAITING and box.items[0].detail == "Stopped"
    assert box.start_button.text() == "Start"

    box.add([B])  # adding songs starts the queue again, from the top
    assert [j.source for j in jobs] == [A, A]


def test_queue_is_remembered_between_launches(library, tmp_path, jobs):
    song_file = tmp_path / "First song.m4a"
    song_file.write_bytes(b"audio")
    box = _box(jobs)
    box.add([A, B])
    jobs[0].downloaded.emit(str(song_file), "First song")
    box.shutdown()  # the app quits mid-song
    assert jobs[0].cancelled

    again = _box(jobs)
    assert [(i.source, i.name, i.state) for i in again.items] == [(A, "First song", WAITING), (B, B[8:], WAITING)]
    assert len(jobs) == 1 and not again.running and again.status.text() == "2 waiting"

    again.start_or_stop()
    assert jobs[-1].source == str(song_file)  # converts the downloaded song instead of downloading it again
    again.list.item(0).setSelected(True)
    again.remove_selected()
    assert jobs[1].cancelled and jobs[-1].source == B
    assert [i.source for i in again.items] == [B]


def test_free_path_and_dropped_songs(library, tmp_path):
    assert free_path(library, "A/B: c") == library / "A-B- c.apno"
    (library / "Song.apno").touch()
    (library / "Song (2).apno").touch()
    assert free_path(library, "Song") == library / "Song (3).apno"

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/tmp/one.mp3"), QUrl.fromLocalFile("/tmp/old.apno"), QUrl(A)])
    assert dropped_songs(mime) == ["/tmp/one.mp3", A]


def test_pasting_several_links_into_the_convert_tab_queues_them(library, jobs):
    from autopiano.gui.convert_panel import ConvertPanel
    from autopiano.gui.preview import PreviewPlayer

    panel = ConvertPanel(PreviewPlayer())
    made = []
    panel.queue._job_type = lambda source, kind, parent: made.append(FakeJob(source, kind, parent)) or made[-1]
    assert panel.queue.isHidden()
    panel.link.setText(f"| 1 | Golden | {A} |\n| 2 | Soda Pop | {B} |")
    assert panel.link.text() == ""
    assert [i.source for i in panel.queue.items] == [A, B] and not panel.queue.isHidden()
    assert [j.source for j in made] == [A]
    assert panel.queue.list.item(0).data(Qt.ItemDataRole.UserRole).state == WORKING
    panel.shutdown()
