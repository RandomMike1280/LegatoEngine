//! Reads .apno scripts, the encrypted format the AutoPiano converter writes.
//!
//! A file is a 40-byte header followed by AES-256-GCM(zlib(msgpack(payload))). The header
//! is authenticated too, so a changed byte anywhere makes the file unreadable rather than
//! silently wrong. See `src/autopiano/format/apno.py` in the converter for the writer.

use std::io::Read;
use std::path::Path;

use aes_gcm::aead::{Aead, KeyInit, Payload};
use aes_gcm::{Aes256Gcm, Nonce};
use hkdf::Hkdf;
use rmpv::Value;
use sha2::Sha256;

use crate::model::{Meta, Modifier, Note, Role, Script};

pub const EXTENSION: &str = "apno";
const MAGIC: &[u8; 4] = b"APNO";
const FORMAT_VERSION: u16 = 1;
const HEADER: usize = 40; // magic 4, version u16, flags u16, salt 16, nonce 12, length u32

const A: &str = "34b1a241acb7ce5f7becc55442f537805e00352cb45bca7217a22b29fe463e65";
const B: &str = "2bb0d288d558860d9c495e3570a63bd8fb583dd9d38ee64f15b05ed240854b9c";

/// Why a file can't be used. The message is safe to show the user.
#[derive(Debug, Clone, PartialEq)]
pub struct ApnoError(pub String);

impl std::fmt::Display for ApnoError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

fn error<T>(message: &str) -> Result<T, ApnoError> {
    Err(ApnoError(message.to_string()))
}

fn unhex(text: &str) -> Vec<u8> {
    (0..text.len()).step_by(2).map(|i| u8::from_str_radix(&text[i..i + 2], 16).unwrap()).collect()
}

fn key(salt: &[u8]) -> [u8; 32] {
    let secret: Vec<u8> = unhex(A).iter().zip(unhex(B)).map(|(a, b)| a ^ b).collect();
    let mut info = b"autopiano/".to_vec();
    info.extend_from_slice(MAGIC);
    let mut okm = [0u8; 32];
    Hkdf::<Sha256>::new(Some(salt), &secret).expand(&info, &mut okm).expect("32 bytes is a valid length");
    okm
}

pub fn read_script(path: &Path) -> Result<Script, ApnoError> {
    let data = std::fs::read(path).map_err(|e| ApnoError(format!("Couldn't open the script: {e}.")))?;
    parse(&data)
}

pub fn parse(data: &[u8]) -> Result<Script, ApnoError> {
    payload_to_script(&unseal(data)?).ok_or_else(|| ApnoError("This script is damaged.".into()))
}

fn unseal(data: &[u8]) -> Result<Value, ApnoError> {
    if data.len() < HEADER || &data[..4] != MAGIC {
        return error("This is not an AutoPiano script.");
    }
    let version = u16::from_le_bytes([data[4], data[5]]);
    if version > FORMAT_VERSION {
        return Err(ApnoError(format!("This script needs a newer AutoPiano (format v{version}).")));
    }
    if version < 1 {
        return error("This script is damaged.");
    }
    let salt = &data[8..24];
    let nonce: [u8; 12] = data[24..36].try_into().unwrap();
    let length = u32::from_le_bytes(data[36..40].try_into().unwrap()) as usize;
    let sealed = &data[HEADER..];
    if sealed.len() != length {
        return error("This script is damaged or incomplete.");
    }
    let cipher = Aes256Gcm::new_from_slice(&key(salt)).expect("32-byte key");
    let body = cipher
        .decrypt(&Nonce::from(nonce), Payload { msg: sealed, aad: &data[..HEADER] })
        .or_else(|_| error("This script is damaged or was modified."))?;
    let mut packed = Vec::new();
    flate2::read::ZlibDecoder::new(&body[..])
        .read_to_end(&mut packed)
        .or_else(|_| error("This script is damaged or was modified."))?;
    rmpv::decode::read_value(&mut &packed[..]).or_else(|_| error("This script is damaged or was modified."))
}

fn get<'a>(map: &'a Value, name: &str) -> Option<&'a Value> {
    map.as_map()?.iter().find(|(k, _)| k.as_str() == Some(name)).map(|(_, v)| v)
}

fn ints(map: &Value, name: &str) -> Option<Vec<i64>> {
    get(map, name)?.as_array()?.iter().map(|v| v.as_i64()).collect()
}

fn running_total(deltas: &[i64]) -> Vec<i64> {
    let mut total = 0;
    deltas
        .iter()
        .map(|d| {
            total += d;
            total
        })
        .collect()
}

fn text(map: &Value, name: &str) -> String {
    get(map, name).and_then(|v| v.as_str()).unwrap_or("").to_string()
}

fn number(map: &Value, name: &str) -> f64 {
    get(map, name).and_then(|v| v.as_f64().or_else(|| v.as_i64().map(|i| i as f64))).unwrap_or(0.0)
}

fn payload_to_script(payload: &Value) -> Option<Script> {
    let m = get(payload, "meta")?;
    let meta = Meta {
        title: text(m, "title"),
        source_name: text(m, "source_name"),
        source_kind: text(m, "source_kind"),
        duration: number(m, "duration"),
        bpm: number(m, "bpm"),
        key_name: text(m, "key_name"),
        transpose: number(m, "transpose") as i64,
        layout_id: get(m, "layout_id").and_then(|v| v.as_str()).unwrap_or("vp61").to_string(),
        preset: text(m, "preset"),
        created: number(m, "created"),
    };
    let cols = get(payload, "notes")?;
    let starts = running_total(&ints(cols, "t")?);
    let chords = running_total(&ints(cols, "c")?);
    let (durations, pitches, velocities) = (ints(cols, "d")?, ints(cols, "p")?, ints(cols, "v")?);
    let (roles, modifiers) = (ints(cols, "r")?, ints(cols, "m")?);
    let keys: Vec<char> = get(cols, "k")?.as_str()?.chars().collect();
    let n = starts.len();
    if [chords.len(), durations.len(), pitches.len(), velocities.len(), roles.len(), modifiers.len(), keys.len()]
        .iter()
        .any(|&len| len != n)
    {
        return None;
    }
    let mut notes = Vec::with_capacity(n);
    for i in 0..n {
        notes.push(Note {
            pitch: pitches[i] as i32,
            start: starts[i] as f64 / 1000.0,
            duration: durations[i] as f64 / 1000.0,
            velocity: velocities[i] as i32,
            role: Role::from_int(roles[i])?,
            chord: chords[i],
            key: keys[i],
            modifier: Modifier::from_int(modifiers[i])?,
        });
    }
    let beats = running_total(&ints(payload, "beats").unwrap_or_default()).iter().map(|&b| b as f64 / 1000.0).collect();
    Some(Script { meta, notes, beats })
}
