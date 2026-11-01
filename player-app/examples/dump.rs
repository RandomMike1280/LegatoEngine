//! Prints what the player makes of a script, for `tests/parity.py check`.

#[path = "../tests/common/mod.rs"]
mod common;

fn main() {
    let path = std::env::args().nth(1).expect("usage: dump FILE.apno");
    let script = autopiano_player::apno::read_script(path.as_ref()).unwrap_or_else(|e| panic!("{e}"));
    println!("{}", common::describe(&script));
}
