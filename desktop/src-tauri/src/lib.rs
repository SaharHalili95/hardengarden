//! HardenGarden desktop shell: starts the Python scanner (the "sidecar"), waits until its
//! local API is healthy, hands the address and token to the UI, and stops it on exit.
//!
//! R35: any startup failure (missing binary, crash, missing library, port problem, no
//! healthy answer within 15 s) becomes a specific `Failed` status with the scanner's last
//! log lines, which the UI shows instead of a blank window.

use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{Manager, RunEvent, State};

pub const STARTUP_TIMEOUT: Duration = Duration::from_secs(15);
const LOG_LINES: usize = 40;
const SIDECAR_NAME: &str = "hardengarden-sidecar";
/// Lets the release smoke tests point the app at a deliberately broken scanner (R35 test).
const SIDECAR_OVERRIDE_ENV: &str = "HARDENGARDEN_SIDECAR";

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum BackendStatus {
    Starting,
    Ready {
        port: u16,
        token: String,
    },
    Failed {
        reason: String,
        log_tail: Vec<String>,
    },
}

#[derive(Debug, Deserialize)]
struct Handshake {
    event: String,
    port: u16,
    token: String,
}

/// Parses the scanner's single stdout handshake line.
pub fn parse_handshake(line: &str) -> Result<(u16, String), String> {
    let handshake: Handshake = serde_json::from_str(line.trim())
        .map_err(|_| "The scanner printed an unexpected start-up message.".to_string())?;
    if handshake.event != "ready" || handshake.port == 0 || handshake.token.len() < 32 {
        return Err("The scanner's start-up message was incomplete.".to_string());
    }
    Ok((handshake.port, handshake.token))
}

/// True when a raw HTTP response is a 200 from HardenGarden's /health endpoint.
pub fn is_healthy_response(raw: &str) -> bool {
    let status_ok = raw
        .lines()
        .next()
        .map(|line| line.starts_with("HTTP/1.1 200") || line.starts_with("HTTP/1.0 200"))
        .unwrap_or(false);
    status_ok && raw.contains("\"status\":\"ok\"")
}

fn health_check(port: u16) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_secs(2)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let request = "GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut raw = String::new();
    let _ = stream.take(16 * 1024).read_to_string(&mut raw);
    is_healthy_response(&raw)
}

pub struct Backend {
    status: Mutex<BackendStatus>,
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
    logs: Arc<Mutex<VecDeque<String>>>,
}

impl Backend {
    fn new() -> Self {
        Self {
            status: Mutex::new(BackendStatus::Starting),
            child: Mutex::new(None),
            stdin: Mutex::new(None),
            logs: Arc::new(Mutex::new(VecDeque::with_capacity(LOG_LINES))),
        }
    }

    fn set(&self, status: BackendStatus) {
        if let Ok(mut current) = self.status.lock() {
            *current = status;
        }
    }

    fn log_tail(&self) -> Vec<String> {
        self.logs
            .lock()
            .map(|l| l.iter().cloned().collect())
            .unwrap_or_default()
    }

    fn fail(&self, reason: impl Into<String>) {
        // Give the stderr reader a moment to collect the scanner's last words.
        thread::sleep(Duration::from_millis(200));
        self.set(BackendStatus::Failed {
            reason: reason.into(),
            log_tail: self.log_tail(),
        });
    }

    /// Closing stdin tells the scanner to exit (it runs with --watch-stdin); kill if it lingers.
    fn stop(&self) {
        if let Ok(mut stdin) = self.stdin.lock() {
            stdin.take();
        }
        if let Ok(mut guard) = self.child.lock() {
            if let Some(child) = guard.as_mut() {
                let deadline = Instant::now() + Duration::from_secs(3);
                while Instant::now() < deadline {
                    if matches!(child.try_wait(), Ok(Some(_))) {
                        return;
                    }
                    thread::sleep(Duration::from_millis(50));
                }
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

fn sidecar_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if let Some(custom) = std::env::var_os(SIDECAR_OVERRIDE_ENV) {
        return Ok(PathBuf::from(custom));
    }
    let resources = app
        .path()
        .resource_dir()
        .map_err(|e| format!("Could not locate the app's files: {e}"))?;
    Ok(resources.join("sidecar").join(SIDECAR_NAME))
}

fn start(app: tauri::AppHandle, backend: &Backend) {
    let path = match sidecar_path(&app) {
        Ok(path) => path,
        Err(reason) => return backend.fail(reason),
    };
    let spawned = Command::new(&path)
        .args(["serve", "--watch-stdin"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn();
    let mut child = match spawned {
        Ok(child) => child,
        Err(err) => {
            return backend.fail(format!(
                "Could not start the scanner at {}: {err}.",
                path.display()
            ))
        }
    };

    if let Some(stderr) = child.stderr.take() {
        let logs = Arc::clone(&backend.logs);
        thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                if let Ok(mut logs) = logs.lock() {
                    if logs.len() == LOG_LINES {
                        logs.pop_front();
                    }
                    logs.push_back(line);
                }
            }
        });
    }
    let (sender, receiver) = mpsc::channel::<String>();
    if let Some(stdout) = child.stdout.take() {
        thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            let mut first = String::new();
            if reader.read_line(&mut first).is_ok() {
                let _ = sender.send(first);
            }
            // Keep draining so the scanner never blocks on a full pipe.
            let mut sink = String::new();
            while reader.read_line(&mut sink).map(|n| n > 0).unwrap_or(false) {
                sink.clear();
            }
        });
    }
    if let Ok(mut guard) = backend.stdin.lock() {
        *guard = child.stdin.take();
    }
    if let Ok(mut guard) = backend.child.lock() {
        *guard = Some(child);
    }

    let started = Instant::now();
    let line = match receiver.recv_timeout(STARTUP_TIMEOUT) {
        Ok(line) if !line.trim().is_empty() => line,
        _ => {
            let reason = match exit_code(backend) {
                Some(code) => format!("The scanner stopped during start-up (exit code {code})."),
                None => {
                    "The scanner did not report that it was ready within 15 seconds.".to_string()
                }
            };
            backend.stop();
            return backend.fail(reason);
        }
    };
    let (port, token) = match parse_handshake(&line) {
        Ok(ok) => ok,
        Err(reason) => {
            backend.stop();
            return backend.fail(reason);
        }
    };
    while started.elapsed() < STARTUP_TIMEOUT {
        if health_check(port) {
            backend.set(BackendStatus::Ready { port, token });
            return;
        }
        if exit_code(backend).is_some() {
            break;
        }
        thread::sleep(Duration::from_millis(200));
    }
    backend.stop();
    backend.fail("The scanner started but did not answer its health check within 15 seconds.");
}

fn exit_code(backend: &Backend) -> Option<String> {
    let mut guard = backend.child.lock().ok()?;
    let status = guard.as_mut()?.try_wait().ok()??;
    Some(
        status
            .code()
            .map_or_else(|| "signal".to_string(), |c| c.to_string()),
    )
}

/// Reports a crash after a successful start, so the UI can show it instead of failing silently.
fn watch(app: tauri::AppHandle) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(1));
        let backend = app.state::<Backend>();
        let ready = matches!(
            backend.status.lock().map(|s| s.clone()),
            Ok(BackendStatus::Ready { .. })
        );
        if !ready {
            if matches!(
                backend.status.lock().map(|s| s.clone()),
                Ok(BackendStatus::Failed { .. })
            ) {
                return;
            }
            continue;
        }
        if let Some(code) = exit_code(&backend) {
            backend.fail(format!(
                "The scanner stopped unexpectedly (exit code {code}). Restart HardenGarden."
            ));
            return;
        }
    });
}

#[tauri::command]
fn backend_status(backend: State<'_, Backend>) -> BackendStatus {
    backend
        .status
        .lock()
        .map(|s| s.clone())
        .unwrap_or(BackendStatus::Failed {
            reason: "Internal error while reading the scanner status.".to_string(),
            log_tail: Vec::new(),
        })
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .manage(Backend::new())
        .invoke_handler(tauri::generate_handler![backend_status])
        .setup(|app| {
            let handle = app.handle().clone();
            thread::spawn(move || {
                let backend = handle.state::<Backend>();
                start(handle.clone(), &backend);
                watch(handle.clone());
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the HardenGarden window");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<Backend>().stop();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn handshake_is_parsed() {
        let token = "x".repeat(43);
        let line = format!("{{\"event\": \"ready\", \"port\": 4242, \"token\": \"{token}\"}}\n");
        assert_eq!(parse_handshake(&line), Ok((4242, token)));
    }

    #[test]
    fn bad_handshakes_are_rejected() {
        assert!(parse_handshake("Traceback (most recent call last):").is_err());
        assert!(
            parse_handshake("{\"event\": \"ready\", \"port\": 0, \"token\": \"short\"}").is_err()
        );
        assert!(parse_handshake("{\"event\": \"starting\", \"port\": 5, \"token\": \"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\"}").is_err());
    }

    #[test]
    fn health_response_must_be_200_and_ok() {
        assert!(is_healthy_response("HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n\r\n{\"status\":\"ok\",\"version\":\"1\"}"));
        assert!(!is_healthy_response(
            "HTTP/1.1 500 Internal Server Error\r\n\r\n{\"status\":\"ok\"}"
        ));
        assert!(!is_healthy_response("HTTP/1.1 200 OK\r\n\r\nhello"));
        assert!(!is_healthy_response(""));
    }

    #[test]
    fn status_serializes_for_the_ui() {
        let ready = serde_json::to_value(BackendStatus::Ready {
            port: 5,
            token: "t".into(),
        })
        .unwrap();
        assert_eq!(ready["state"], "ready");
        assert_eq!(ready["port"], 5);
        let failed = serde_json::to_value(BackendStatus::Failed {
            reason: "r".into(),
            log_tail: vec!["l".into()],
        })
        .unwrap();
        assert_eq!(failed["state"], "failed");
        assert_eq!(failed["log_tail"][0], "l");
    }
}
