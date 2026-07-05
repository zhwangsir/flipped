mod backend;
mod browser;
mod terminal;

use backend::{is_backend_healthy, resolve_backend_root, spawn_backend, BackendHandle};
use browser::BrowserWebviewManager;
use tauri::menu::{Menu, MenuItem, Submenu};
use tauri::tray::TrayIconBuilder;
use tauri::{Emitter, Manager, WindowEvent};
use terminal::TerminalManager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            let port = std::env::var("FLIPPED_BACKEND_PORT")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(8011);
            let auto_start =
                std::env::var("FLIPPED_BACKEND_AUTO_START").unwrap_or_else(|_| "1".into());
            let handle = app.handle().clone();

            app.manage(BackendHandle::new(port));
            app.manage(BrowserWebviewManager::new());
            app.manage(TerminalManager::new());

            // 原生菜单栏
            let new_session = MenuItem::with_id(app, "new_session", "New Session", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let file_menu = Submenu::with_items(app, "File", true, &[&new_session, &quit])?;
            let edit_menu = Submenu::new(app, "Edit", true)?;
            let view_menu = Submenu::new(app, "View", true)?;
            let window_menu = Submenu::new(app, "Window", true)?;
            let help_menu = Submenu::new(app, "Help", true)?;
            let menu = Menu::with_items(
                app,
                &[&file_menu, &edit_menu, &view_menu, &window_menu, &help_menu],
            )?;
            app.set_menu(menu)?;

            app.on_menu_event(move |app, event| {
                match event.id().as_ref() {
                    "new_session" => {
                        app.emit("menu-new-session", ()).ok();
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                }
            });

            // 托盘图标
            let tray_show = MenuItem::with_id(app, "tray_show", "Show", true, None::<&str>)?;
            let tray_quit = MenuItem::with_id(app, "tray_quit", "Quit", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&tray_show, &tray_quit])?;
            // 图标在 tauri.conf.json app.trayIcon 中配置，代码里只挂菜单。
            TrayIconBuilder::new()
                .menu(&tray_menu)
                .on_menu_event(move |app, event| {
                    match event.id().as_ref() {
                        "tray_show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        "tray_quit" => {
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .build(app)?;

            if auto_start != "0" {
                std::thread::spawn(move || {
                    if is_backend_healthy(port) {
                        log::info!("[backend] already healthy on port {}", port);
                        handle.emit("backend-ready", port).ok();
                        return;
                    }

                    match resolve_backend_root() {
                        Some(root) => {
                            let log_path = root.join("logs/tauri-backend.log");
                            if let Some(parent) = log_path.parent() {
                                let _ = std::fs::create_dir_all(parent);
                            }

                            match spawn_backend(&root, port, &log_path) {
                                Ok(child) => {
                                    if let Ok(mut state) =
                                        handle.state::<BackendHandle>().child.lock()
                                    {
                                        let _ = state.replace(child);
                                    }
                                    log::info!("[backend] spawned, waiting for health");

                                    for _ in 0..40 {
                                        std::thread::sleep(std::time::Duration::from_secs(1));
                                        if is_backend_healthy(port) {
                                            log::info!("[backend] healthy on port {}", port);
                                            handle.emit("backend-ready", port).ok();
                                            break;
                                        }
                                    }
                                }
                                Err(e) => log::error!("[backend] failed to spawn: {}", e),
                            }
                        }
                        None => {
                            log::warn!("[backend] could not resolve project root; skip auto-start")
                        }
                    }
                });
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            browser::create_browser_webview,
            browser::update_browser_webview,
            browser::close_browser_webview,
            terminal::create_terminal,
            terminal::write_terminal,
            terminal::resize_terminal,
            terminal::close_terminal,
        ])
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                window.app_handle().state::<BackendHandle>().kill();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
