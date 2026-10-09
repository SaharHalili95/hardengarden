// Prevents an extra console window on Windows release builds; harmless on Linux.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    hardengarden_desktop_lib::run();
}
