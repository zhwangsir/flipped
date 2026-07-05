use std::collections::HashMap;
use std::sync::Mutex;

use tauri::{LogicalPosition, LogicalSize, State, WebviewBuilder, WebviewUrl, Window};

/// Manages child webviews used for the embedded interactive browser preview.
///
/// In Tauri desktop mode, the Browser tab renders a ``host`` div and asks Rust to
/// create/position a real Chromium webview on top of that area. The manager keeps
/// track of those webviews so they can be resized, navigated, or closed.
pub struct BrowserWebviewManager {
    pub webviews: Mutex<HashMap<String, tauri::Webview>>,
}

impl BrowserWebviewManager {
    pub fn new() -> Self {
        Self {
            webviews: Mutex::new(HashMap::new()),
        }
    }
}

/// Create a new child webview embedded in the calling window.
#[tauri::command]
pub fn create_browser_webview(
    window: Window,
    state: State<BrowserWebviewManager>,
    label: String,
    url: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    let parsed_url = url::Url::parse(&url).map_err(|e| e.to_string())?;
    let webview_url = WebviewUrl::External(parsed_url);

    // Close any existing webview with the same label before creating a new one.
    {
        let mut map = state.webviews.lock().map_err(|e| e.to_string())?;
        if let Some(old) = map.remove(&label) {
            let _ = old.close();
        }
    }

    let builder = WebviewBuilder::new(&label, webview_url);
    let webview = window
        .add_child(
            builder,
            LogicalPosition::new(x, y),
            LogicalSize::new(width, height),
        )
        .map_err(|e| e.to_string())?;

    let mut map = state.webviews.lock().map_err(|e| e.to_string())?;
    map.insert(label, webview);
    Ok(())
}

/// Move/resize an existing child webview.
#[tauri::command]
pub fn update_browser_webview(
    state: State<BrowserWebviewManager>,
    label: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    let map = state.webviews.lock().map_err(|e| e.to_string())?;
    let webview = map
        .get(&label)
        .ok_or_else(|| "webview not found".to_string())?;
    webview
        .set_position(LogicalPosition::new(x, y))
        .map_err(|e| e.to_string())?;
    webview
        .set_size(LogicalSize::new(width, height))
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Close and remove a child webview.
#[tauri::command]
pub fn close_browser_webview(
    state: State<BrowserWebviewManager>,
    label: String,
) -> Result<(), String> {
    let mut map = state.webviews.lock().map_err(|e| e.to_string())?;
    if let Some(webview) = map.remove(&label) {
        webview.close().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manager_starts_empty() {
        let manager = BrowserWebviewManager::new();
        let map = manager.webviews.lock().unwrap();
        assert!(map.is_empty());
    }

    #[test]
    fn url_parsing_helper_accepts_http() {
        let parsed: url::Url = "http://localhost:5173".parse().unwrap();
        assert_eq!(parsed.host_str(), Some("localhost"));
        assert_eq!(parsed.port(), Some(5173));
    }
}
