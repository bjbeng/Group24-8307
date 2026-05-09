// Tauri v2 最小入口——不注册任何自定义命令，权限由 capabilities 控制
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
