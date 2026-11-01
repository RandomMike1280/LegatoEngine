// No console window behind the player on Windows.
#![cfg_attr(windows, windows_subsystem = "windows")]

use std::path::PathBuf;

use autopiano_player::app::App;
use eframe::egui;

fn main() -> eframe::Result {
    // "Open with" on Windows passes the script's path.
    let open = std::env::args_os().skip(1).map(PathBuf::from).find(|p| p.extension().is_some_and(|e| e == "apno"));
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("AutoPiano Player")
            .with_inner_size([1080.0, 720.0])
            .with_min_inner_size([780.0, 540.0])
            .with_drag_and_drop(true)
            .with_app_id("autopiano-player")
            .with_icon(eframe::icon_data::from_png_bytes(include_bytes!("../packaging/icon.png")).unwrap_or_default()),
        ..Default::default()
    };
    eframe::run_native("AutoPiano Player", options, Box::new(move |cc| Ok(Box::new(App::new(cc, open)))))
}
