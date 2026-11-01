//! The player presses exactly what the converter's own player would: the fixtures hold
//! random scripts and the Python player's output for them (made by `parity.py fixtures`).

mod common;

use std::path::Path;

use serde_json::Value;

/// Equal, allowing for floating-point noise in times.
fn first_difference(path: &str, want: &Value, got: &Value) -> Option<String> {
    match (want, got) {
        (Value::Number(a), Value::Number(b)) => {
            let (a, b) = (a.as_f64().unwrap(), b.as_f64().unwrap());
            ((a - b).abs() > 1e-9).then(|| format!("{path}: Python {a} vs Rust {b}"))
        }
        (Value::Array(a), Value::Array(b)) => {
            if a.len() != b.len() {
                return Some(format!("{path}: {} items vs {}", a.len(), b.len()));
            }
            a.iter().zip(b).enumerate().find_map(|(i, (x, y))| first_difference(&format!("{path}[{i}]"), x, y))
        }
        (Value::Object(a), Value::Object(b)) => a
            .iter()
            .find_map(|(k, x)| first_difference(&format!("{path}.{k}"), x, b.get(k).unwrap_or(&Value::Null))),
        _ => (want != got).then(|| format!("{path}: Python {want} vs Rust {got}")),
    }
}

#[test]
fn matches_the_python_player() {
    let fixtures = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures");
    let mut checked = 0;
    for item in std::fs::read_dir(&fixtures).expect("run parity.py fixtures first") {
        let path = item.unwrap().path();
        if path.extension().is_none_or(|e| e != "apno") {
            continue;
        }
        let script = autopiano_player::apno::read_script(&path).unwrap();
        let want: Value = serde_json::from_str(&std::fs::read_to_string(path.with_extension("json")).unwrap()).unwrap();
        let got = common::describe(&script);
        if let Some(difference) = first_difference("", &want, &got) {
            panic!("{}: {difference}", path.display());
        }
        checked += 1;
    }
    assert!(checked >= 6, "only {checked} fixtures");
}
