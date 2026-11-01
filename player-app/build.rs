//! Gives the Windows exe its icon, compiled from packaging/app.rc with the MinGW resource compiler.

use std::path::PathBuf;
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=packaging/app.rc");
    println!("cargo:rerun-if-changed=packaging/icon.ico");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows") {
        return;
    }
    let out = PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("app-resources.o");
    let windres = if cfg!(windows) { "windres" } else { "x86_64-w64-mingw32-windres" };
    let status = Command::new(windres)
        .current_dir("packaging")
        .args(["app.rc", "-O", "coff", "-o"])
        .arg(&out)
        .status();
    match status {
        Ok(s) if s.success() => println!("cargo:rustc-link-arg-bins={}", out.display()),
        _ => println!("cargo:warning=couldn't run {windres}; the exe will have no icon"),
    }
}
