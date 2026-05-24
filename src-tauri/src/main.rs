// Prevents a console window from appearing on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::Command;
use std::thread;
use std::time::Duration;

fn main() {
    // Spawn the Python backend (the PyInstaller binary sitting next to this exe).
    // In dev mode `cargo tauri dev` handles this via beforeDevCommand instead.
    #[cfg(not(debug_assertions))]
    {
        let exe_dir = std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|d| d.to_path_buf()))
            .unwrap_or_default();

        let backend = if cfg!(target_os = "windows") {
            exe_dir.join("leads.exe")
        } else {
            exe_dir.join("leads")
        };

        if backend.exists() {
            let mut cmd = Command::new(&backend);
            // Tell the Python launcher not to open the browser — Tauri owns the window.
            cmd.env("LEADS_NO_BROWSER", "1");
            cmd.spawn().expect("Failed to start Python backend");
            // Give the server a moment to start before Tauri loads the URL.
            thread::sleep(Duration::from_millis(1500));
        }
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .run(tauri::generate_context!())
        .expect("error running Tauri application");
}
