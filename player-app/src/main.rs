// No console window behind the player on Windows.
#![cfg_attr(windows, windows_subsystem = "windows")]

use std::path::PathBuf;

use eframe::egui;
use legatoplayer::app::App;
use legatoplayer::library::{default_folder, old_default_folder};

const APP_ID: &str = "legatoplayer";

fn main() -> eframe::Result {
    // "Open with" on Windows passes the script's path.
    let open = std::env::args_os().skip(1).map(PathBuf::from).find(|p| p.extension().is_some_and(|e| e == "apno"));
    move_old_folders();
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("LegatoPlayer")
            .with_inner_size([1080.0, 720.0])
            .with_min_inner_size([780.0, 540.0])
            .with_drag_and_drop(true)
            .with_app_id(APP_ID)
            .with_icon(eframe::icon_data::from_png_bytes(include_bytes!("../packaging/icon.png")).unwrap_or_default()),
        ..Default::default()
    };
    eframe::run_native("LegatoPlayer", options, Box::new(move |cc| Ok(Box::new(App::new(cc, open)))))
}

/// LegatoPlayer was called AutoPiano Player at first. Its settings and the library move to the new
/// names, unless a new folder already has something in it.
fn move_old_folders() {
    let moves = [
        (eframe::storage_dir("autopiano-player"), eframe::storage_dir(APP_ID)),
        (Some(old_default_folder()), Some(default_folder())),
    ];
    for (old, new) in moves {
        if let (Some(old), Some(new)) = (old, new)
            && old.is_dir()
            && std::fs::read_dir(&new).map_or(true, |mut entries| entries.next().is_none())
        {
            let _ = std::fs::remove_dir(&new); // empty: made by something that ran before the move
            if let Some(parent) = new.parent() {
                let _ = std::fs::create_dir_all(parent);
            }
            let _ = std::fs::rename(&old, &new);
        }
    }
}
