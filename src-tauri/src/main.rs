// Prevents a console window from appearing on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::Command;
use std::thread;
use std::time::{Duration, Instant};

/// Kill any existing process listening on `port` so we can bind a fresh server.
/// Uses lsof on macOS/Linux, netstat on Windows.
fn kill_port(port: u16) {
    #[cfg(not(target_os = "windows"))]
    {
        // lsof -ti tcp:<port> returns pids one per line.
        if let Ok(out) = Command::new("lsof")
            .args(["-ti", &format!("tcp:{}", port)])
            .output()
        {
            let stdout = String::from_utf8_lossy(&out.stdout);
            let mut killed = false;
            for pid_str in stdout.split_whitespace() {
                if let Ok(pid) = pid_str.trim().parse::<u32>() {
                    if pid != std::process::id() {
                        // SIGTERM first for a clean shutdown, then SIGKILL to
                        // guarantee the port is released before we try to bind.
                        let _ = Command::new("kill").args(["-TERM", &pid.to_string()]).status();
                        killed = true;
                    }
                }
            }
            if killed {
                // Give SIGTERM a moment, then SIGKILL any survivors.
                thread::sleep(Duration::from_millis(600));
                if let Ok(out2) = Command::new("lsof")
                    .args(["-ti", &format!("tcp:{}", port)])
                    .output()
                {
                    let stdout2 = String::from_utf8_lossy(&out2.stdout);
                    for pid_str in stdout2.split_whitespace() {
                        if let Ok(pid) = pid_str.trim().parse::<u32>() {
                            if pid != std::process::id() {
                                let _ = Command::new("kill").args(["-9", &pid.to_string()]).status();
                            }
                        }
                    }
                    if !stdout2.trim().is_empty() {
                        // Wait for SIGKILL to take effect.
                        thread::sleep(Duration::from_millis(600));
                    }
                }
            }
        }
    }
}

/// Poll until localhost:port accepts a TCP connection or the timeout expires.
fn wait_for_server(port: u16, timeout_secs: u64) -> bool {
    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    while Instant::now() < deadline {
        if TcpStream::connect(format!("127.0.0.1:{}", port)).is_ok() {
            // Give uvicorn one more moment to finish its startup sequence
            // before the WebView tries to load a page.
            thread::sleep(Duration::from_millis(400));
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
    let macos_dir = exe.parent()?;        // .../Contents/MacOS
    let contents = macos_dir.parent()?;   // .../Contents

    // Primary: Resources/leads-bin/leads  (build_app.sh injects it here)
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
    const PORT: u16 = 8000;

    // Spawn the Python backend in release builds.
    // In dev mode `cargo tauri dev` uses beforeDevCommand instead.
    #[cfg(not(debug_assertions))]
    {
        // Kill any stale instance first so the new one can bind to PORT.
        kill_port(PORT);

        if let Some(backend) = find_backend() {
            let mut cmd = Command::new(&backend);
            // Tell the Python launcher not to open the browser — Tauri owns the window.
            cmd.env("LEADS_NO_BROWSER", "1");

            match cmd.spawn() {
                Ok(_) => {
                    // Poll until the server is ready (up to 30 s).
                    if !wait_for_server(PORT, 30) {
                        eprintln!("Warning: Python backend did not respond within 30s on port {}", PORT);
                    }
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
