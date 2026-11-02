"""MIDI file -> arrangement -> .apno file -> timeline -> player, without Roblox."""

from legatoengine.arrange.pipeline import ArrangeSettings, arrange
from legatoengine.format.apno import read_script, write_script
from legatoengine.ingest.midi import read_midi
from legatoengine.models import Modifier
from legatoengine.player.engine import Player
from legatoengine.player.keyboard import DryRunKeyboard
from legatoengine.player.timeline import Action, PlaySettings, build_timeline, simulate_typing

from .helpers import scale_song, write_midi

SHIFTED = dict(zip("1234567890", "!@#$%^&*()"))


def expected_text(script) -> str:
    out = []
    for chord in sorted({n.chord for n in script.notes}):
        notes = [n for n in script.notes if n.chord == chord]
        for modifier in (Modifier.NONE, Modifier.SHIFT):
            for n in sorted((n for n in notes if n.modifier is modifier), key=lambda n: n.pitch):
                out.append(SHIFTED.get(n.key, n.key.upper()) if modifier is Modifier.SHIFT else n.key)
    return "".join(out)


def test_midi_to_playback(tmp_path):
    song = read_midi(write_midi(tmp_path / "song.mid", scale_song(62), bpm=240))
    script = arrange(song, ArrangeSettings(preset="full", transpose="original"))
    path = write_script(script, tmp_path / "song.apno")
    loaded = read_script(path)
    assert loaded.notes == script.notes

    settings = PlaySettings(speed=2.0)
    actions = build_timeline(loaded.notes, settings)
    assert simulate_typing(actions) == expected_text(loaded)

    kb = DryRunKeyboard()
    player = Player(kb)
    player.load(actions, speed=settings.speed)
    player.play()
    assert player.wait(10)
    assert kb.held() == set()
    replay = [Action(t, down, key) for t, key, down in kb.events]
    assert simulate_typing(replay) == expected_text(loaded)
    first = kb.events[0][0]
    for (t, _, _), a in zip(kb.events, actions):
        assert abs((t - first) - (a.time - actions[0].time)) < 0.003
