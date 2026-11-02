//! The player window, driven offscreen: nothing appears on screen and no hotkeys are taken.
//! Set LEGATOPLAYER_SCREENSHOTS to a folder to save what the window looked like.

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use legatoplayer::app::App;
use egui_kittest::Harness;
use egui_kittest::kittest::Queryable;

/// A library folder of its own for each test, since the tests run side by side.
fn library(test: &str) -> PathBuf {
    let fixtures = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures");
    let folder = std::env::temp_dir().join(format!("legatoplayer-{test}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&folder);
    std::fs::create_dir_all(folder.join("Classical")).unwrap();
    std::fs::copy(fixtures.join("random-1.apno"), folder.join("random-1.apno")).unwrap();
    std::fs::copy(fixtures.join("random-3.apno"), folder.join("Classical/random-3.apno")).unwrap();
    std::fs::copy(fixtures.join("short.apno"), folder.join("short.apno")).unwrap();
    std::fs::write(folder.join("broken.apno"), b"not a script").unwrap();
    folder
}

fn window(folder: PathBuf) -> Harness<'static, App> {
    Harness::builder().with_size([1080.0, 720.0]).build_eframe(move |cc| App::for_tests(cc, folder))
}

fn screenshot(harness: &mut Harness<'_, App>, name: &str) {
    if let Some(folder) = std::env::var_os("LEGATOPLAYER_SCREENSHOTS") {
        harness.render().unwrap().save(Path::new(&folder).join(format!("{name}.png"))).unwrap();
    }
}

/// Steps the window in real time until `done` or the timeout.
fn run_until(harness: &mut Harness<'_, App>, seconds: f64, done: impl Fn(&Harness<'_, App>) -> bool) -> bool {
    let end = Instant::now() + Duration::from_secs_f64(seconds);
    while Instant::now() < end {
        harness.step();
        if done(harness) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(15));
    }
    false
}

#[test]
fn library_lists_scripts_and_a_test_run_reports_its_presses() {
    let folder = library("library");
    let mut harness = window(folder.clone());
    harness.run_steps(3);
    // every script, the one in a subfolder too; the damaged one is listed but can't be opened
    assert_eq!(harness.query_all_by_label_contains("Parity 1").count(), 1);
    assert_eq!(harness.query_all_by_label_contains("Classical").count(), 1);
    harness.get_by_label_contains("can't be read");
    harness.get_by_label_contains("4 scripts");
    harness.get_by_label("Pick a script from your library.");
    screenshot(&mut harness, "1-empty");

    harness.get_by_label_contains("Parity 3").click();
    harness.run_steps(3);
    harness.get_by_label_contains("notes in");
    harness.get_by_label_contains("88"); // the 88-key layout is named in the details
    screenshot(&mut harness, "2-script");

    harness.get_by_label("Keyboard-possible mode").click();
    harness.run_steps(3);
    harness.get_by_label_contains("chords changed");
    screenshot(&mut harness, "3-possible");

    harness.get_by_label_contains("Short test").click();
    harness.run_steps(3);
    harness.get_by_label("▶ Play").click();
    let finished =
        run_until(&mut harness, 5.0, |h| h.query_by_label_contains("Test run finished").is_some());
    assert!(finished, "the test run never finished");
    // 7 notes, every one pressed
    harness.get_by_label("Test run finished: 7 key presses would have been sent.");
    screenshot(&mut harness, "4-test-run");
    let _ = std::fs::remove_dir_all(folder);
}

#[test]
fn search_narrows_the_list_and_stop_ends_a_run() {
    let folder = library("search");
    let mut harness = window(folder.clone());
    harness.run_steps(3);
    harness.get_by_role(eframe::egui::accesskit::Role::TextInput).focus();
    harness.run_steps(1);
    harness.get_by_role(eframe::egui::accesskit::Role::TextInput).type_text("parity 3");
    harness.run_steps(3);
    assert_eq!(harness.query_all_by_label_contains("Parity 1").count(), 0);
    harness.get_by_label_contains("1 of 4");
    screenshot(&mut harness, "5-search");

    harness.get_by_label_contains("Parity 3").click();
    harness.run_steps(3);
    harness.get_by_label("▶ Play").click();
    assert!(run_until(&mut harness, 3.0, |h| h.query_by_label_contains("Playing.").is_some()));
    screenshot(&mut harness, "6-playing");
    harness.get_by_label("Pause").click();
    assert!(run_until(&mut harness, 3.0, |h| h.query_by_label_contains("Paused.").is_some()));
    harness.get_by_label("■ Stop").click();
    // a report if it got as far as the first note, and otherwise ready to play again
    let ended = |h: &Harness<'_, App>| {
        h.query_by_label_contains("Test run finished").is_some() || h.query_by_label_contains("Ready.").is_some()
    };
    assert!(run_until(&mut harness, 3.0, ended));
    let _ = std::fs::remove_dir_all(folder);
}
