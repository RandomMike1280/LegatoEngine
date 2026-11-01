import time

from autopiano.player.engine import Player, State
from autopiano.player.keyboard import DryRunKeyboard
from autopiano.player.timeline import Action, simulate_typing


def test_events_land_on_time():
    actions = [Action(t, i % 2 == 0, "t") for i, t in enumerate([0.0, 0.05, 0.10, 0.15, 0.20, 0.25])]
    kb = DryRunKeyboard()
    player = Player(kb)
    player.load(actions)
    player.play()
    assert player.wait(2)
    got = [t for t, _, _ in kb.events]
    assert len(got) == 6
    for expected, actual in zip([0.0, 0.05, 0.10, 0.15, 0.20, 0.25], got):
        assert abs(actual - expected) < 0.004, (expected, actual)


def test_stop_lets_go_of_every_key():
    actions = [Action(0.0, True, "shift"), Action(0.001, True, "t"), Action(5.0, False, "t"), Action(5.0, False, "shift")]
    kb = DryRunKeyboard()
    player = Player(kb)
    player.load(actions)
    player.play()
    time.sleep(0.1)
    assert kb.held() == {"shift", "t"}
    player.stop()
    assert kb.held() == set()
    assert player.state is State.STOPPED


def test_pause_releases_keys_and_resume_continues():
    actions = [Action(0.0, True, "a"), Action(0.3, False, "a"), Action(0.4, True, "b"), Action(0.5, False, "b")]
    kb = DryRunKeyboard()
    player = Player(kb)
    player.load(actions)
    player.play()
    time.sleep(0.15)
    player.pause()
    time.sleep(0.1)
    assert player.state is State.PAUSED
    assert kb.held() == set()  # "a" was let go on pause
    time.sleep(0.2)
    player.resume()
    assert player.wait(2)
    keys = [(k, d) for _, k, d in kb.events]
    assert keys == [("a", True), ("a", False), ("b", True), ("b", False)]
    b_down = kb.events[2][0]
    assert 0.65 < b_down < 0.75  # 0.4 s of song plus about 0.3 s paused


def test_seek_into_a_shift_group_presses_shift_again():
    actions = [Action(0.1, True, "shift"), Action(0.2, True, "2"), Action(0.3, False, "shift"), Action(0.4, False, "2")]
    kb = DryRunKeyboard()
    player = Player(kb)
    player.load(actions)
    player.play(start=0.15)
    assert player.wait(2)
    replay = [Action(t, d, k) for t, k, d in kb.events]
    assert simulate_typing(replay) == "@"


def test_countdown_then_play():
    states = []
    kb = DryRunKeyboard()
    player = Player(kb, on_state=states.append)
    player.load([Action(0.0, True, "t"), Action(0.05, False, "t")])
    started = time.perf_counter()
    player.play(countdown=0.2)
    assert player.wait(2)
    first_event = kb._t0 - started
    assert first_event >= 0.19
    assert states == [State.COUNTDOWN, State.PLAYING, State.STOPPED]


def test_toggle_during_countdown_cancels():
    kb = DryRunKeyboard()
    player = Player(kb)
    player.load([Action(0.0, True, "t"), Action(0.05, False, "t")])
    player.play(countdown=5)
    time.sleep(0.05)
    player.toggle_pause()
    assert player.wait(1)
    assert kb.events == []


def test_position_reaches_the_end():
    positions = []
    player = Player(DryRunKeyboard(), on_position=positions.append)
    player.load([Action(0.0, True, "t"), Action(0.2, False, "t")], speed=2.0)
    player.play()
    assert player.wait(2)
    assert positions[-1] == player.duration == 0.4
