# omega/ui_loader.py
from PySide6.QtCore import QFile
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QMainWindow

from omega.paths import UI_PATH


def load_main_window() -> QMainWindow:
    print(f"[DEBUG] Looking for UI at: {UI_PATH}")
    if not UI_PATH.exists():
        raise FileNotFoundError(f"UI not found: {UI_PATH}")

    f = QFile(str(UI_PATH))
    if not f.open(QFile.ReadOnly):
        raise RuntimeError(f"Could not open UI file: {UI_PATH}")

    loader = QUiLoader()
    win = loader.load(f)
    f.close()

    if win is None:
        raise RuntimeError("QUiLoader failed to load the UI (win is None).")

    print("[DEBUG] UI loaded successfully")
    print("[DEBUG] Root widget:", type(win), "objectName:", win.objectName())
    win.resize(1200, 800)
    return win
