# omega/main.py
import sys
import traceback

from PySide6.QtWidgets import QApplication

from omega.paths import ensure_mpv_dll_on_path
from omega.theme import apply_dark_palette
from omega.ui_loader import load_main_window


def main():
    # MUST happen before anything imports python-mpv / mpv_backend
    ensure_mpv_dll_on_path()

    # Import AFTER PATH is fixed
    from omega.player.controller import PlayerController

    app = QApplication(sys.argv)
    apply_dark_palette(app)

    win = load_main_window()
    _controller = PlayerController(win)
    win.show()
    win.raise_()
    win.activateWindow()

    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("\n[ERROR] Omega crashed:\n")
        traceback.print_exc()
        try:
            input("\nPress Enter to close...")
        except Exception:
            pass
