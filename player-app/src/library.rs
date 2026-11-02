//! The script library: every .apno in a folder and its subfolders, and finding scripts in it.
//!
//! Searching forgives what people get wrong when they type a song's name: case, accents
//! ("fur elise" finds "Für Elise"), punctuation, spacing ("bwv846" finds "BWV 846") and
//! small typos ("moonlite" finds "Moonlight"). Every word of the search has to match.
//! A port of `src/legatoengine/library.py`.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use crate::apno::{EXTENSION, read_script};

// How much a match counts, by where it was found.
const TITLE: f64 = 1.0;
const FILE_NAME: f64 = 0.9;
const FOLDER: f64 = 0.8;
const DETAILS: f64 = 0.6;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Sort {
    Newest,
    Name,
    Length,
}

impl Sort {
    pub const ALL: [Sort; 3] = [Sort::Newest, Sort::Name, Sort::Length];

    pub fn label(self) -> &'static str {
        match self {
            Sort::Newest => "Newest first",
            Sort::Name => "Name",
            Sort::Length => "Length",
        }
    }

    pub fn id(self) -> &'static str {
        match self {
            Sort::Newest => "newest",
            Sort::Name => "name",
            Sort::Length => "length",
        }
    }

    pub fn from_id(id: &str) -> Sort {
        Sort::ALL.into_iter().find(|s| s.id() == id).unwrap_or(Sort::Newest)
    }
}

/// One script in the library, as the list and the search see it.
#[derive(Clone, Debug, PartialEq)]
pub struct Entry {
    pub path: PathBuf,
    pub title: String,
    pub folder: String, // the subfolder it's in, such as "Classical"; "" at the top of the library
    pub duration: f64,
    pub key_name: String,
    pub source_kind: String,
    pub layout_id: String,
    pub modified: f64,
    pub readable: bool,
}

/// The default library folder: Music/LegatoEngine, the same one the converter saves to on a Mac.
pub fn default_folder() -> PathBuf {
    music_folder().join("LegatoEngine")
}

/// The default library folder from before LegatoEngine was renamed: Music/AutoPiano.
pub fn old_default_folder() -> PathBuf {
    music_folder().join("AutoPiano")
}

fn music_folder() -> PathBuf {
    dirs::audio_dir().or_else(|| dirs::home_dir().map(|h| h.join("Music"))).unwrap_or_else(|| PathBuf::from("."))
}

/// Where `path`, saved inside the folder `old`, is now that `old` has moved to `new`.
/// None if it wasn't in `old`, or `old` is still there.
pub fn moved_path(path: &Path, old: &Path, new: &Path) -> Option<PathBuf> {
    if old.exists() {
        return None;
    }
    path.strip_prefix(old).ok().map(|rest| new.join(rest))
}

/// The words of `text` as the search compares them: lower case, without accents or punctuation.
pub fn words(text: &str) -> Vec<String> {
    let mut spelled = String::with_capacity(text.len());
    for c in text.chars() {
        match c {
            '#' | '♯' => spelled.push_str(" sharp "),
            '♭' => spelled.push_str(" flat "),
            _ => spelled.push(c),
        }
    }
    let plain = deunicode::deunicode(&spelled).to_lowercase();
    let mut found = Vec::new();
    let mut word = String::new();
    let mut last_digit: Option<bool> = None;
    for c in plain.chars() {
        if !c.is_ascii_alphanumeric() {
            if !word.is_empty() {
                found.push(std::mem::take(&mut word));
            }
            last_digit = None;
            continue;
        }
        let digit = c.is_ascii_digit();
        if last_digit.is_some_and(|d| d != digit) && !word.is_empty() {
            found.push(std::mem::take(&mut word)); // "bwv846" is "bwv 846"
        }
        word.push(c);
        last_digit = Some(digit);
    }
    if !word.is_empty() {
        found.push(word);
    }
    found
}

// ---- reading the folder

/// Remembers what each script holds, so a rescan only reads scripts that changed.
#[derive(Default)]
pub struct Library {
    seen: HashMap<PathBuf, ((u128, u64), Entry)>,
    root: PathBuf,
}

/// Each folder under `root` with its file names, skipping hidden folders.
fn walk(root: &Path, out: &mut Vec<(PathBuf, Vec<String>)>) {
    let Ok(read) = std::fs::read_dir(root) else { return };
    let mut files = Vec::new();
    let mut dirs = Vec::new();
    for item in read.flatten() {
        let name = item.file_name().to_string_lossy().into_owned();
        match item.file_type() {
            Ok(t) if t.is_dir() => {
                if !name.starts_with('.') {
                    dirs.push(name);
                }
            }
            Ok(_) => files.push(name),
            Err(_) => {}
        }
    }
    dirs.sort();
    out.push((root.to_path_buf(), files));
    for d in dirs {
        walk(&root.join(d), out);
    }
}

fn read_entry(path: &Path, root: &Path, modified: f64) -> Entry {
    let folder = match path.parent() {
        Some(parent) if parent != root => parent
            .strip_prefix(root)
            .map(|p| p.components().map(|c| c.as_os_str().to_string_lossy()).collect::<Vec<_>>().join("/"))
            .unwrap_or_default(),
        _ => String::new(),
    };
    let stem = path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
    match read_script(path) {
        Ok(script) => {
            let meta = script.meta;
            Entry {
                path: path.to_path_buf(),
                title: if meta.title.is_empty() { stem } else { meta.title },
                folder,
                duration: meta.duration,
                key_name: meta.key_name,
                source_kind: meta.source_kind,
                layout_id: meta.layout_id,
                modified,
                readable: true,
            }
        }
        Err(_) => Entry {
            path: path.to_path_buf(),
            title: stem,
            folder,
            duration: 0.0,
            key_name: String::new(),
            source_kind: String::new(),
            layout_id: String::new(),
            modified,
            readable: false,
        },
    }
}

impl Library {
    /// Every script in `root` and its subfolders, newest first.
    pub fn scan(&mut self, root: &Path) -> Vec<Entry> {
        if root != self.root {
            self.seen.clear();
            self.root = root.to_path_buf();
        }
        if !root.is_dir() {
            self.seen.clear();
            return Vec::new();
        }
        let mut folders = Vec::new();
        walk(root, &mut folders);
        let mut seen = HashMap::new();
        for (folder, files) in folders {
            for name in files {
                if name.starts_with('.') || !name.ends_with(EXTENSION) {
                    continue;
                }
                let path = folder.join(&name);
                let Ok(stat) = std::fs::metadata(&path) else { continue };
                let modified = stat.modified().ok().and_then(|m| m.duration_since(UNIX_EPOCH).ok()).unwrap_or_default();
                let stamp = (modified.as_nanos(), stat.len());
                let entry = match self.seen.remove(&path) {
                    Some((old, entry)) if old == stamp => entry,
                    _ => read_entry(&path, root, modified.as_secs_f64()),
                };
                seen.insert(path, (stamp, entry));
            }
        }
        self.seen = seen;
        let entries: Vec<Entry> = self.seen.values().map(|(_, e)| e.clone()).collect();
        sort_entries(entries, Sort::Newest)
    }
}

/// Names sort the way people count: "Idea 9" comes before "Idea 10".
pub fn sort_entries(mut entries: Vec<Entry>, by: Sort) -> Vec<Entry> {
    match by {
        Sort::Name => entries.sort_by_cached_key(|e| natural(&e.title)),
        Sort::Length => {
            entries.sort_by(|a, b| a.duration.total_cmp(&b.duration).then_with(|| natural(&a.title).cmp(&natural(&b.title))))
        }
        Sort::Newest => entries.sort_by(|a, b| b.modified.total_cmp(&a.modified)),
    }
    entries
}

fn natural(text: &str) -> Vec<(u8, u128, String)> {
    words(text)
        .into_iter()
        .map(|w| match w.parse::<u128>() {
            Ok(n) if w.bytes().all(|b| b.is_ascii_digit()) => (0, n, String::new()),
            _ => (1, 0, w),
        })
        .collect()
}

// ---- searching

/// The entries that match every word of `query`, best first. Equally good matches keep
/// their order. An empty query keeps every entry.
pub fn search(entries: &[Entry], query: &str) -> Vec<Entry> {
    let tokens = words(query);
    if tokens.is_empty() {
        return entries.to_vec();
    }
    let mut scored: Vec<(f64, usize)> = entries.iter().enumerate().map(|(i, e)| (score(e, &tokens), i)).collect();
    scored.sort_by(|a, b| b.0.total_cmp(&a.0).then(a.1.cmp(&b.1)));
    scored.into_iter().filter(|(s, _)| *s > 0.0).map(|(_, i)| entries[i].clone()).collect()
}

fn score(entry: &Entry, tokens: &[String]) -> f64 {
    let mut total = 0.0;
    let mut tokens = tokens.to_vec();
    let key = words(&entry.key_name);
    if let Some(at) = find(&tokens, &key) {
        // the search names the script's key, such as "a minor"; part of a key isn't enough
        tokens.drain(at..at + key.len());
        total += DETAILS * key.len() as f64;
    }
    let title = words(&entry.title);
    let stem = words(&entry.path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default());
    let fields: [(f64, Vec<String>, bool); 4] = [
        (TITLE, title.clone(), true),
        (FILE_NAME, stem.clone(), true),
        (FOLDER, words(&entry.folder), true),
        (DETAILS, details(entry), false), // whole words only
    ];
    let compact = [title.concat(), stem.concat()];
    for token in &tokens {
        let mut best = fields
            .iter()
            .flat_map(|(weight, found, loose)| found.iter().map(move |word| weight * matches(token, word, *loose)))
            .fold(0.0, f64::max);
        if best == 0.0 && token.chars().count() >= 3 && compact.iter().any(|text| text.contains(token.as_str())) {
            best = 0.45; // "bwv846" in "BWV 846", "lalaland" in "La La Land"
        }
        if best == 0.0 {
            return 0.0;
        }
        total += best;
    }
    total + if tokens.is_empty() { 0.0 } else { phrase_bonus(&title, &tokens) }
}

/// Where `phrase` starts in `tokens`.
fn find(tokens: &[String], phrase: &[String]) -> Option<usize> {
    if phrase.is_empty() || phrase.len() > tokens.len() {
        return None;
    }
    (0..=tokens.len() - phrase.len()).find(|&i| tokens[i..i + phrase.len()] == *phrase)
}

fn details(entry: &Entry) -> Vec<String> {
    let mut found = words(&entry.source_kind);
    if !entry.layout_id.is_empty() {
        // "vp88" -> "88"
        found.extend(words(&entry.layout_id).into_iter().filter(|w| w.bytes().all(|b| b.is_ascii_digit())));
    }
    found
}

fn is_number(text: &str) -> bool {
    !text.is_empty() && text.bytes().all(|b| b.is_ascii_digit())
}

fn matches(token: &str, word: &str, loose: bool) -> f64 {
    if word == token {
        return 1.0;
    }
    if !loose {
        return 0.0;
    }
    let (tl, wl) = (token.chars().count(), word.chars().count());
    if word.starts_with(token) {
        return 0.7 + 0.25 * tl as f64 / wl as f64;
    }
    if tl >= 3 && word.contains(token) {
        return 0.5;
    }
    let allowed = if is_number(token) { 0 } else { typos_allowed(tl) }; // "2023" is not a typo for "2024"
    if allowed > 0 {
        let prefix: String = word.chars().take(tl).collect();
        if distance(token, word, allowed).min(distance(token, &prefix, allowed)) <= allowed {
            return 0.4;
        }
    }
    0.0
}

/// Extra for titles that hold the search as it was typed: more when the title starts with it.
fn phrase_bonus(title: &[String], tokens: &[String]) -> f64 {
    let (last, whole) = tokens.split_last().unwrap();
    if title.len() < tokens.len() {
        return 0.0;
    }
    for i in 0..=title.len() - tokens.len() {
        if title[i..i + whole.len()] == *whole && title[i + whole.len()].starts_with(last.as_str()) {
            return if i == 0 { 0.8 } else { 0.5 };
        }
    }
    0.0
}

fn typos_allowed(length: usize) -> usize {
    if length < 4 {
        0
    } else if length < 8 {
        1
    } else {
        2
    }
}

/// Edit distance from `a` to `b`, counting a swap of neighbouring letters as one edit.
/// Stops early and returns `limit + 1` once the distance is past `limit`.
fn distance(a: &str, b: &str, limit: usize) -> usize {
    let (a, b): (Vec<char>, Vec<char>) = (a.chars().collect(), b.chars().collect());
    if a.len().abs_diff(b.len()) > limit {
        return limit + 1;
    }
    let mut before: Option<Vec<usize>> = None;
    let mut previous: Vec<usize> = (0..=b.len()).collect();
    for i in 1..=a.len() {
        let ca = a[i - 1];
        let mut row = vec![0; b.len() + 1];
        row[0] = i;
        for j in 1..=b.len() {
            let cb = b[j - 1];
            row[j] = (previous[j] + 1).min(row[j - 1] + 1).min(previous[j - 1] + usize::from(ca != cb));
            if let Some(before) = &before {
                if j > 1 && i > 1 && ca == b[j - 2] && a[i - 2] == cb {
                    row[j] = row[j].min(before[j - 2] + 1);
                }
            }
        }
        if *row.iter().min().unwrap() > limit {
            return limit + 1;
        }
        before = Some(std::mem::replace(&mut previous, row));
    }
    previous[b.len()]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(title: &str, folder: &str, key: &str) -> Entry {
        Entry {
            path: PathBuf::from(format!("/lib/{title}.apno")),
            title: title.into(),
            folder: folder.into(),
            duration: 60.0,
            key_name: key.into(),
            source_kind: "midi".into(),
            layout_id: "vp61".into(),
            modified: 0.0,
            readable: true,
        }
    }

    #[test]
    fn words_fold_case_accents_and_numbers() {
        assert_eq!(words("Für Elise"), ["fur", "elise"]);
        assert_eq!(words("BWV846_Prelude"), ["bwv", "846", "prelude"]);
        assert_eq!(words("C# minor"), ["c", "sharp", "minor"]);
    }

    #[test]
    fn search_forgives_typos_and_spacing() {
        let all = vec![
            entry("Moonlight Sonata", "Classical", "C# minor"),
            entry("Für Elise", "Classical", "A minor"),
            entry("Prelude in C BWV 846", "Classical", "C major"),
            entry("La La Land", "", "D major"),
        ];
        let titles = |q: &str| search(&all, q).into_iter().map(|e| e.title).collect::<Vec<_>>();
        assert_eq!(titles("moonlite"), ["Moonlight Sonata"]);
        assert_eq!(titles("fur elise"), ["Für Elise"]);
        assert_eq!(titles("bwv846"), ["Prelude in C BWV 846"]);
        assert_eq!(titles("lalaland"), ["La La Land"]);
        assert_eq!(titles("a minor"), ["Für Elise"]);
        assert_eq!(titles("nothing like it").len(), 0);
        assert_eq!(titles("").len(), 4);
    }

    #[test]
    fn names_sort_like_counting() {
        let sorted = sort_entries(vec![entry("Idea 10", "", ""), entry("Idea 9", "", "")], Sort::Name);
        assert_eq!(sorted[0].title, "Idea 9");
    }

    #[test]
    fn saved_paths_follow_the_renamed_folder() {
        let (old, new) = (Path::new("/nowhere/Music/AutoPiano"), Path::new("/nowhere/Music/LegatoEngine"));
        let script = old.join("Classical/Song.apno");
        assert_eq!(moved_path(&script, old, new), Some(new.join("Classical/Song.apno")));
        assert_eq!(moved_path(old, old, new), Some(new.to_path_buf()));
        assert_eq!(moved_path(Path::new("/elsewhere/Song.apno"), old, new), None);
        let here = std::env::temp_dir(); // a folder that's still there keeps its paths
        assert_eq!(moved_path(&here.join("Song.apno"), &here, new), None);
    }
}
