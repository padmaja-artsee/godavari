// Prevents a console window from appearing on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::thread;
use std::time::{Duration, Instant};

/// Kill any existing process listening on `port` so we can bind a fresh server.
fn kill_port(port: u16) {
    #[cfg(not(target_os = "windows"))]
    {
        // Run up to 3 rounds: SIGTERM → wait → SIGKILL → wait → verify gone.
        for round in 0..3u8 {
            let Ok(out) = Command::new("lsof")
                .args(["-ti", &format!("tcp:{}", port)])
                .output()
            else { break; };

            let stdout = String::from_utf8_lossy(&out.stdout);
            let pids: Vec<u32> = stdout
                .split_whitespace()
                .filter_map(|s| s.trim().parse::<u32>().ok())
                .filter(|&p| p != std::process::id())
                .collect();

            if pids.is_empty() { break; }

            let sig = if round == 0 { "-TERM" } else { "-9" };
            for pid in &pids {
                let _ = Command::new("kill").args([sig, &pid.to_string()]).status();
            }
            let wait_ms = if round == 0 { 800 } else { 1500 };
            thread::sleep(Duration::from_millis(wait_ms));
        }
    }
}

/// Wait until port is confirmed free (no process listening), up to timeout.
/// This prevents "Address already in use" when the app is relaunched quickly.
fn wait_for_port_free(port: u16, timeout_secs: u64) {
    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    while Instant::now() < deadline {
        // If we can NOT connect, the port is free — good to go.
        if TcpStream::connect(format!("127.0.0.1:{}", port)).is_err() {
            return;
        }
        // Port still occupied — keep killing and waiting.
        kill_port(port);
        thread::sleep(Duration::from_millis(500));
    }
}

/// Poll until localhost:port accepts a TCP connection or the timeout expires.
fn wait_for_server(port: u16, timeout_secs: u64) -> bool {
    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    while Instant::now() < deadline {
        if TcpStream::connect(format!("127.0.0.1:{}", port)).is_ok() {
            // Give uvicorn time to finish init_db and startup handlers
            // before the WebView tries to load a page.
            thread::sleep(Duration::from_millis(2500));
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

    let bin_name = if cfg!(target_os = "windows") { "leads.exe" } else { "leads" };

    // Primary: Resources/leads-bin/leads  (build_app.sh injects it here)
    let in_resources = contents.join("Resources").join("leads-bin").join(bin_name);
    if in_resources.exists() {
        return Some(in_resources);
    }

    // PyInstaller BUNDLE puts the binary at Contents/MacOS/leads
    let in_macos = macos_dir.join(bin_name);
    if in_macos.exists() {
        return Some(in_macos);
    }

    // Fallback: MacOS/leads-bin/leads (dev / alternate layout)
    let next_to_exe = macos_dir.join("leads-bin").join(bin_name);
    if next_to_exe.exists() {
        return Some(next_to_exe);
    }

    None
}

fn server_up(port: u16) -> bool {
    TcpStream::connect(format!("127.0.0.1:{}", port)).is_ok()
}

fn run_tauri() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .run(tauri::generate_context!())
        .expect("error running Tauri application");
}

fn main() {
    const PORT: u16 = 8000;

    // Spawn the Python backend in release builds.
    // In dev mode `cargo tauri dev` uses beforeDevCommand instead.
    #[cfg(not(debug_assertions))]
    {
        let mut backend_child: Option<Child> = None;

        // Another window already started the server — attach UI only.
        if server_up(PORT) {
            run_tauri();
            return;
        }

        kill_port(PORT);
        wait_for_port_free(PORT, 15);

        if server_up(PORT) {
            run_tauri();
            return;
        }

        let Some(backend) = find_backend() else {
            eprintln!(
                "ERROR: Python backend not found in app bundle.\n\
                 Expected Contents/Resources/leads-bin/leads (run ./build_app.sh).\n\
                 Log: ~/Library/Application Support/GodavariLeads/leads.log"
            );
            std::process::exit(1);
        };

        let mut cmd = Command::new(&backend);
        cmd.env("LEADS_NO_BROWSER", "1");

        match cmd.spawn() {
            Ok(child) => {
                backend_child = Some(child);
                if !wait_for_server(PORT, 45) {
                    eprintln!(
                        "ERROR: Python backend did not start on port {} within 45s.\n\
                         See ~/Library/Application Support/GodavariLeads/leads.log",
                        PORT
                    );
                    if let Some(mut c) = backend_child.take() {
                        let _ = c.kill();
                        let _ = c.wait();
                    }
                    std::process::exit(1);
                }
            }
            Err(e) => {
                eprintln!("ERROR: Failed to start Python backend at {:?}: {}", backend, e);
                std::process::exit(1);
            }
        }

        run_tauri();

        if let Some(mut child) = backend_child {
            let _ = child.kill();
            let _ = child.wait();
        }
        return;
    }

    run_tauri();
}
