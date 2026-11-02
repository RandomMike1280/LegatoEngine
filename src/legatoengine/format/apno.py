"""The .apno script format.

A file is a 40-byte header followed by a sealed payload:

    magic    4 bytes   b"APNO"
    version  u16       format version
    flags    u16       reserved, 0
    salt     16 bytes  per-file salt for key derivation
    nonce    12 bytes  AES-GCM nonce
    length   u32       length of the sealed payload
    sealed   AES-256-GCM(zlib(msgpack(payload))), 16-byte tag at the end

The header is authenticated as associated data, so changing any byte of the file
makes it unreadable instead of silently wrong.

The key is derived from a secret built into AutoPiano. That keeps scripts unreadable
to other programs, but it is obfuscation rather than real DRM: someone who takes the
program apart can recover the secret.
"""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import asdict, fields
from pathlib import Path

import msgpack
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..models import Modifier, Note, Role, Script, ScriptMeta

MAGIC = b"APNO"
FORMAT_VERSION = 1
EXTENSION = ".apno"
HEADER = struct.Struct("<4sHH16s12sI")

_A = bytes.fromhex("34b1a241acb7ce5f7becc55442f537805e00352cb45bca7217a22b29fe463e65")
_B = bytes.fromhex("2bb0d288d558860d9c495e3570a63bd8fb583dd9d38ee64f15b05ed240854b9c")


class ApnoError(Exception):
    """The file can't be used as a script. The message is safe to show the user."""


def _key(salt: bytes, magic: bytes) -> bytes:
    secret = bytes(a ^ b for a, b in zip(_A, _B))
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"autopiano/" + magic)
    return hkdf.derive(secret)


def seal(payload: dict, magic: bytes = MAGIC, version: int = FORMAT_VERSION) -> bytes:
    body = zlib.compress(msgpack.packb(payload, use_bin_type=True), 9)
    salt, nonce = os.urandom(16), os.urandom(12)
    header = HEADER.pack(magic, version, 0, salt, nonce, len(body) + 16)
    return header + AESGCM(_key(salt, magic)).encrypt(nonce, body, header)


def unseal(data: bytes, magic: bytes = MAGIC, max_version: int = FORMAT_VERSION) -> dict:
    if len(data) < HEADER.size or data[:4] != magic:
        raise ApnoError("This is not an AutoPiano script.")
    _, version, _, salt, nonce, length = HEADER.unpack_from(data)
    if version > max_version:
        raise ApnoError(f"This script needs a newer AutoPiano (format v{version}).")
    if version < 1:
        raise ApnoError("This script is damaged.")
    sealed = data[HEADER.size :]
    if len(sealed) != length:
        raise ApnoError("This script is damaged or incomplete.")
    try:
        body = AESGCM(_key(salt, magic)).decrypt(nonce, sealed, data[: HEADER.size])
        return msgpack.unpackb(zlib.decompress(body), raw=False, strict_map_key=False)
    except (InvalidTag, zlib.error, ValueError, msgpack.ExtraData) as e:
        raise ApnoError("This script is damaged or was modified.") from e


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def _deltas(values: list[int]) -> list[int]:
    out, prev = [], 0
    for v in values:
        out.append(v - prev)
        prev = v
    return out


def _undeltas(values: list[int]) -> list[int]:
    out, total = [], 0
    for v in values:
        total += v
        out.append(total)
    return out


def script_to_payload(script: Script) -> dict:
    notes = sorted(script.notes, key=lambda n: (n.start, n.pitch))
    for n in notes:
        if len(n.key) != 1:
            raise ValueError(f"note {n.pitch} at {n.start:.3f}s has no key assigned")
    return {
        "meta": asdict(script.meta),
        "beats": _deltas([_ms(b) for b in script.beats]),
        "pedals": {
            "t": _deltas([_ms(s) for s, _ in script.pedals]),
            "d": [max(1, _ms(e - s)) for s, e in script.pedals],
        },
        "notes": {
            "t": _deltas([_ms(n.start) for n in notes]),
            "d": [max(1, _ms(n.duration)) for n in notes],
            "p": [n.pitch for n in notes],
            "v": [n.velocity for n in notes],
            "r": [int(n.role) for n in notes],
            "c": _deltas([n.chord for n in notes]),
            "k": "".join(n.key for n in notes),
            "m": [int(n.modifier) for n in notes],
        },
    }


def payload_to_script(payload: dict) -> Script:
    try:
        known = {f.name for f in fields(ScriptMeta)}
        meta = ScriptMeta(**{k: v for k, v in payload["meta"].items() if k in known})
        cols = payload["notes"]
        starts, chords = _undeltas(cols["t"]), _undeltas(cols["c"])
        notes = [
            Note(
                pitch=p,
                start=s / 1000,
                duration=d / 1000,
                velocity=v,
                role=Role(r),
                chord=c,
                key=k,
                modifier=Modifier(m),
            )
            for s, d, p, v, r, c, k, m in zip(
                starts, cols["d"], cols["p"], cols["v"], cols["r"], chords, cols["k"], cols["m"], strict=True
            )
        ]
        pedal_starts = _undeltas(payload["pedals"]["t"])
        pedals = [(s / 1000, (s + d) / 1000) for s, d in zip(pedal_starts, payload["pedals"]["d"], strict=True)]
        beats = [b / 1000 for b in _undeltas(payload["beats"])]
    except (KeyError, TypeError, ValueError) as e:
        raise ApnoError("This script is damaged.") from e
    return Script(meta=meta, notes=notes, beats=beats, pedals=pedals)


def dumps(script: Script) -> bytes:
    return seal(script_to_payload(script))


def loads(data: bytes) -> Script:
    return payload_to_script(unseal(data))


def write_script(script: Script, path: str | os.PathLike) -> Path:
    path = Path(path)
    if path.suffix != EXTENSION:
        path = path.with_suffix(EXTENSION)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(dumps(script))
    tmp.replace(path)
    return path


def read_script(path: str | os.PathLike) -> Script:
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise ApnoError(f"Couldn't open the script: {e.strerror}.") from e
    return loads(data)
