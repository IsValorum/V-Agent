fn main() {
    println!("cargo:rerun-if-changed=icons");
    println!("cargo:rerun-if-changed=icons/icon.ico");
    println!("cargo:rerun-if-changed=icons/icon.png");
    println!("cargo:rerun-if-changed=icons/val-app.rgba");
    let attributes = tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "open_sandbox_folder",
            "open_engine_folder",
            "open_guide",
            "open_uninstaller",
            "save_export_file",
            "window_appearance",
            "window_brand_icon",
            "browser_tab_open",
            "browser_tab_bounds",
            "browser_tab_show",
            "browser_tab_hide",
            "browser_tab_close",
            "browser_tab_state",
            "browser_tab_navigate",
            "browser_tab_back",
            "browser_tab_forward",
            "browser_tab_reload",
            "browser_tab_dom",
        ]),
    );
    tauri_build::try_build(attributes).expect("failed to run tauri-build");
}
