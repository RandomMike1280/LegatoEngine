"""Moving what LegatoEngine kept under its first name, AutoPiano, to the new names."""

from PySide6.QtCore import QCoreApplication, QSettings

from legatoengine import paths
from legatoengine.gui.settings import copy_old_settings


def test_folders_move_to_the_new_names(tmp_path):
    music, caches, support = tmp_path / "Music", tmp_path / "Library/Caches", tmp_path / "Library/Application Support"
    for folder in (music / "AutoPiano/Classical", caches / "AutoPiano/songs", support / "AutoPiano/models"):
        folder.mkdir(parents=True)
        (folder / "kept").write_text("x")
    assert sorted(paths.move_old_folders("darwin", tmp_path, {})) == sorted(
        [music / "LegatoEngine", support / "LegatoEngine", caches / "LegatoEngine"]
    )
    assert (music / "LegatoEngine/Classical/kept").read_text() == "x"
    assert (caches / "LegatoEngine/songs/kept").is_file()
    assert (support / "LegatoEngine/models/kept").is_file()
    assert not (music / "AutoPiano").exists()
    assert paths.move_old_folders("darwin", tmp_path, {}) == []  # only once


def test_nothing_is_moved_onto_a_folder_in_use(tmp_path):
    (tmp_path / "Music/AutoPiano").mkdir(parents=True)
    (tmp_path / "Music/LegatoEngine").mkdir()
    (tmp_path / "Music/LegatoEngine/New.apno").write_bytes(b"")
    assert paths.move_old_folders("darwin", tmp_path, {}) == []
    assert (tmp_path / "Music/AutoPiano").is_dir()


def test_an_empty_new_folder_is_replaced(tmp_path):
    (tmp_path / "Music/AutoPiano").mkdir(parents=True)
    (tmp_path / "Music/AutoPiano/Old.apno").write_bytes(b"")
    (tmp_path / "Music/LegatoEngine").mkdir()
    assert paths.move_old_folders("darwin", tmp_path, {}) == [tmp_path / "Music/LegatoEngine"]
    assert (tmp_path / "Music/LegatoEngine/Old.apno").is_file()


def test_on_windows_the_app_data_folder_moves(tmp_path):
    local = tmp_path / "AppData/Local"
    (local / "AutoPiano/Cache").mkdir(parents=True)
    (local / "AutoPiano/models").mkdir()
    assert paths.move_old_folders("win32", tmp_path, {"LOCALAPPDATA": str(local)}) == [local / "LegatoEngine"]
    assert (local / "LegatoEngine/Cache").is_dir() and (local / "LegatoEngine/models").is_dir()


def test_remembered_choices_come_along(tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QCoreApplication.setOrganizationName("LegatoEngineTest")
    QCoreApplication.setApplicationName("OldNameTest")
    old = QSettings(str(tmp_path / "old.ini"), QSettings.Format.IniFormat)
    old.setValue("play.speed", 80)
    old.setValue("convert.layout", "vp88")
    copy_old_settings(old)
    assert QSettings().value("convert.layout") == "vp88" and int(QSettings().value("play.speed")) == 80
    old.setValue("convert.layout", "vp61")
    copy_old_settings(old)  # once there are new choices, the old ones are left alone
    assert QSettings().value("convert.layout") == "vp88"
