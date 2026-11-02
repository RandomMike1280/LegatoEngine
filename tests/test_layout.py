from legatoengine.layout import is_black, list_layouts, load_layout
from legatoengine.models import Modifier

SHIFTED = {"1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^", "7": "&", "8": "*", "9": "(", "0": ")"}


def test_vp61_range_and_known_keys():
    lay = load_layout("vp61")
    assert (lay.low, lay.high) == (36, 96)
    assert len(lay.keys) == 61
    assert lay.lookup(36) == ("1", Modifier.NONE)
    assert lay.lookup(37) == ("1", Modifier.SHIFT)
    assert lay.lookup(60) == ("t", Modifier.NONE)  # middle C
    assert lay.lookup(61) == ("t", Modifier.SHIFT)
    assert lay.lookup(96) == ("m", Modifier.NONE)
    assert lay.lookup(35) is None
    assert lay.lookup(97) is None


def test_vp61_every_pitch_has_its_own_key():
    lay = load_layout("vp61")
    combos = list(lay.keys.values())
    assert len(set(combos)) == 61
    assert sorted(lay.keys) == list(range(36, 97))


def test_vp61_black_keys_are_shift_plus_the_white_key_below():
    lay = load_layout("vp61")
    for pitch, (key, mod) in lay.keys.items():
        if is_black(pitch):
            assert mod is Modifier.SHIFT
            assert lay.lookup(pitch - 1) == (key, Modifier.NONE)
        else:
            assert mod is Modifier.NONE


def test_vp61_matches_virtual_piano_characters():
    lay = load_layout("vp61")
    white = "".join(k for p, (k, m) in lay.keys.items() if m is Modifier.NONE)
    black = "".join(SHIFTED.get(k, k.upper()) for p, (k, m) in lay.keys.items() if m is Modifier.SHIFT)
    assert white == "1234567890qwertyuiopasdfghjklzxcvbnm"
    assert black == "!@$%^*(QWETYIOPSDGHJLZCVB"


def test_vp88_adds_ctrl_keys():
    lay = load_layout("vp88")
    assert (lay.low, lay.high) == (21, 108)
    assert len(lay.keys) == 88
    assert lay.lookup(21) == ("1", Modifier.CTRL)
    assert lay.lookup(35) == ("t", Modifier.CTRL)
    assert lay.lookup(36) == ("1", Modifier.NONE)
    assert lay.lookup(97) == ("y", Modifier.CTRL)
    assert lay.lookup(108) == ("j", Modifier.CTRL)
    assert len(set(lay.keys.values())) == 88


def test_list_layouts():
    assert [lay.id for lay in list_layouts()] == ["vp61", "vp88"]
