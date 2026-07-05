use std::env;
use std::fs::OpenOptions;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

/// Handle to the spawned backend process, kept in Tauri app state so it can
/// be killed when the app exits.
pub struct BackendHandle {
    pub child: Mutex<Option<Child>>,
    #[allow(dead_code)]
    pub port: u16,
}

impl BackendHandle {
    pub fn new(port: u16) -> Self {
        Self {
            child: Mutex::new(None),
            port,
        }
    }

    /// Kill and reap the backend child process, if any.
    pub fn kill(&self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(ref mut c) = *child {
                let _ = c.kill();
                let _ = c.wait();
            }
            *child = None;
        }
    }
}

/// Return the project root that contains `.venv/bin/python`.
///
/// Priority:
/// 1. `FLIPPED_ROOT` environment variable.
/// 2. Parent of `CARGO_MANIFEST_DIR` twice (repo root).
/// 3. Walk up from the current executable.
pub fn resolve_backend_root() -> Option<PathBuf> {
    if let Ok(root) = env::var("FLIPPED_ROOT") {
        let p = PathBuf::from(root);
        if p.join(".venv/bin/python").is_file() {
            return Some(p);
        }
    }

    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest.parent()?.parent()?;
    if repo_root.join(".venv/bin/python").is_file() {
        return Some(repo_root.to_path_buf());
    }

    env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().and_then(find_project_root))
}

fn find_project_root(start: &Path) -> Option<PathBuf> {
    let mut cur = start;
    for _ in 0..10 {
        if cur.join(".venv/bin/python").is_file() {
            return Some(cur.to_path_buf());
        }
        cur = cur.parent()?;
    }
    None
}

/// Check whether the backend is already listening on `port`.
///
/// Uses a short HTTP probe via curl (available on macOS) so we confirm the
/// `/api/v1/sessions` endpoint is reachable, not just a bound port.
pub fn is_backend_healthy(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{}/api/v1/sessions", port);
    Command::new("curl")
        .args(["-sf", "-m", "3", "-o", "/dev/null", &url])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Spawn the Python backend as a child process.
///
/// The backend runs `uvicorn api.main:app` inside the project root, with the
/// virtual-env Python interpreter and `PYTHONPATH=src`.
pub fn spawn_backend(root: &Path, port: u16, log_path: &Path) -> std::io::Result<Child> {
    let python = root.join(".venv/bin/python");
    let mut cmd = Command::new(python);
    cmd.arg("-m")
        .arg("uvicorn")
        .arg("api.main:app")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .current_dir(root)
        .env("PYTHONPATH", "src")
        .env(
            "EXO_API_KEY",
            env::var("EXO_API_KEY").unwrap_or_else(|_| "dummy".into()),
        )
        .env("NO_PROXY", "100.64.201.37,localhost,127.0.0.1,::1")
        .env("no_proxy", "100.64.201.37,localhost,127.0.0.1,::1");

    let out = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)?;
    let err = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)?;
    cmd.stdout(Stdio::from(out)).stderr(Stdio::from(err));

    cmd.spawn()
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Cleanup<'a>(&'a Path);
    impl<'a> Drop for Cleanup<'a> {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(self.0);
        }
    }

    #[test]
    fn find_project_root_from_nested_dir() {
        let base = std::env::temp_dir().join(format!("flipped-tauri-test-{}", std::process::id()));
        let _c = Cleanup(&base);
        let root = base.join("repo");
        let venv_bin = root.join(".venv/bin");
        std::fs::create_dir_all(&venv_bin).unwrap();
        std::fs::File::create(venv_bin.join("python")).unwrap();
        let start = root.join("console/src-tauri/target/debug");
        std::fs::create_dir_all(&start).unwrap();
        assert_eq!(find_project_root(&start), Some(root));
    }

    #[test]
    fn is_backend_healthy_false_when_nothing_listens() {
        // 55555 is extremely unlikely to be bound in the test environment.
        assert!(!is_backend_healthy(55555));
    }
}
