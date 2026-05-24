// Prevents a console window from appearing on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::Command;
use std::thread;
use std::time::{Duration, Instant};

/// Poll until localhost:8000 accepts connections or the timeout expires.
fn wait_for_server(port: u16, timeout_secs: u64) -> bool {
    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    while Instant::now() < deadline {
        if TcpStream::connect(format!("127.0.0.1:{}", port)).is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(200));
    }
    false
}

/// Locate the Python backend binary inside the macOS .app bundle.
/// Tauri bundles resources into Contents/Resources/, not Contents/MacOS/.
fn find_backend() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    // exe is at:  Leads.app/Contents/MacOS/leads
    // resources:  Leads.app/Contents/Resources/
    let macos_dir = exe.parent()?;            // .../Contents/MacOS
    let contents   = macos_dir.parent()?;     // .../Contents

    // Try Resources/leads-bin/leads  (Tauri bundle location)
    let in_resources = contents
        .join("Resources")
        .join("leads-bin")
        .join(if cfg!(target_os = "windows") { "leads.exe" } else { "leads" });
    if in_resources.exists() {
        return Some(in_resources);
    }

    // Fallback: next to the exe (dev / non-bundle layout)
    let next_to_exe = macos_dir
        .join("leads-bin")
        .join(if cfg!(target_os = "windows") { "leads.exe" } else { "leads" });
    if next_to_exe.exists() {
        return Some(next_to_exe);
    }

    None
}

fn main() {
    // Spawn the Python backend in release builds.
    // In dev mode `cargo tauri dev` uses beforeDevCommand instead.
    #[cfg(not(debug_assertions))]
    {
        if let Some(backend) = find_backend() {
            let mut cmd = Command::new(&backend);
            // Tell the Python launcher not to open the browser — Tauri owns the window.
            cmd.env("LEADS_NO_BROWSER", "1");

            match cmd.spawn() {
                Ok(_) => {
                    // Poll until the server is ready (up to 30 s).
                    wait_for_server(8000, 30);
                }
                Err(e) => {
                    eprintln!("Failed to start Python backend at {:?}: {}", backend, e);
                }
            }
        } else {
            eprintln!("Python backend binary not found — tried Resources/leads-bin/leads");
            // Still wait briefly in case backend is already running.
            thread::sleep(Duration::from_secs(2));
        }
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .run(tauri::generate_context!())
        .expect("error running Tauri application");
}
