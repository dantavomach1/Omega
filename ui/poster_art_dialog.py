# omega/ui/poster_art_dialog.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QMessageBox,
    QLineEdit, QCheckBox, QInputDialog
)

from omega.library.tmdb_client import TMDBClient, TMDBHit


@dataclass
class MissingArtItem:
    """
    One local show/movie group (may be merged from multiple folders).
    """
    display_title: str
    primary_dir: Path
    all_dirs: List[Path]


class PosterArtDialog(QDialog):
    """
    UI behavior:
    - LEFT: Library items (missing-only optional)
      - Rename button (records rename_map for controller)
    - Search button: queries TMDB
    - RIGHT: TMDB suggestions (checkboxes)
    - Apply button: saves backdrop.jpg or poster.jpg into ALL merged dirs
    """

    def __init__(self, items: List[MissingArtItem], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update Poster Art (TMDB)")
        self.setMinimumSize(1180, 650)

        # TMDB client (reads TMDB_READ_TOKEN env var)
        self._tmdb = TMDBClient()

        # Incoming items
        self._all_items: List[MissingArtItem] = list(items)

        # Rename requests:
        # key = str(primary_dir), value = new display title
        self.rename_map: Dict[str, str] = {}

        # Current search hit list
        self._hits: List[TMDBHit] = []

        # -----------------------------
        # Layout
        # -----------------------------
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(18)

        # LEFT column
        left_col = QVBoxLayout()
        left_col.setSpacing(10)

        left_col.addWidget(QLabel("Library Items"))

        self.chk_missing_only = QCheckBox("Show only items missing art", self)
        self.chk_missing_only.setChecked(True)
        left_col.addWidget(self.chk_missing_only)

        self.left_list = QListWidget(self)
        self.left_list.setIconSize(QSize(72, 46))  # wide-ish thumbnail feel
        self.left_list.setSelectionMode(QListWidget.SingleSelection)
        left_col.addWidget(self.left_list, 1)

        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("Optional: override search text (leave blank to use selected title)")
        left_col.addWidget(self.search_box)

        self.btn_rename = QPushButton("Edit show name", self)
        self.btn_rename.setCursor(Qt.PointingHandCursor)
        left_col.addWidget(self.btn_rename)

        self.btn_search = QPushButton("Search for art", self)
        self.btn_search.setCursor(Qt.PointingHandCursor)
        left_col.addWidget(self.btn_search)

        # RIGHT column
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        right_col.addWidget(QLabel("TMDB Suggestions (check one or more)"))

        self.right_list = QListWidget(self)
        self.right_list.setIconSize(QSize(160, 90))  # widescreen preview
        right_col.addWidget(self.right_list, 1)

        self.btn_apply = QPushButton("Apply Selected Art", self)
        self.btn_apply.setCursor(Qt.PointingHandCursor)
        right_col.addWidget(self.btn_apply)

        root.addLayout(left_col, 1)
        root.addLayout(right_col, 1)

        # -----------------------------
        # Populate
        # -----------------------------
        self._rebuild_left_list()

        # -----------------------------
        # Wire
        # -----------------------------
        self.chk_missing_only.stateChanged.connect(lambda _=None: self._rebuild_left_list())
        self.btn_rename.clicked.connect(self._on_rename_clicked)
        self.btn_search.clicked.connect(self._on_search_clicked)
        self.btn_apply.clicked.connect(self._on_apply_clicked)

    # ============================================================
    # Helpers
    # ============================================================
    def _dir_has_any_art(self, d: Path) -> bool:
        """
        Checks whether the folder contains any “poster-like” image
        that your scanner would detect.
        """
        preferred = [
            # prefer wide first
            "backdrop", "Backdrop",
            # then vertical
            "poster", "Poster",
            "folder", "Folder",
            "cover", "Cover",
        ]
        exts = [".jpg", ".jpeg", ".png", ".webp", ".bmp"]

        try:
            for bn in preferred:
                for ext in exts:
                    if (d / f"{bn}{ext}").exists():
                        return True
        except Exception:
            pass

        # also allow “any image at all” to count as art
        try:
            for p in d.iterdir():
                if p.is_file() and p.suffix.lower() in exts:
                    return True
        except Exception:
            pass

        return False

    def _rebuild_left_list(self) -> None:
        """
        Rebuild the left list based on missing-only filter.
        We store:
          UserRole -> primary_dir (str)
          UserRole+1 -> all_dirs (List[str])
        """
        self.left_list.clear()

        missing_only = True
        try:
            missing_only = bool(self.chk_missing_only.isChecked())
        except Exception:
            missing_only = True

        for item in self._all_items:
            primary = Path(item.primary_dir)
            has_art = self._dir_has_any_art(primary)

            if missing_only and has_art:
                continue

            lw = QListWidgetItem(item.display_title)

            lw.setData(Qt.UserRole, str(primary))
            lw.setData(Qt.UserRole + 1, [str(p) for p in item.all_dirs])

            self.left_list.addItem(lw)

        if self.left_list.count() > 0:
            self.left_list.setCurrentRow(0)

        # Reset right side each time filter changes
        self.right_list.clear()
        self._hits = []

    def _selected_left_dirs(self) -> Optional[Dict[str, Any]]:
        """
        Returns dict with:
          primary_dir: Path
          all_dirs: List[Path]
          display_title: str
        """
        row = self.left_list.currentRow()
        if row < 0:
            return None

        it = self.left_list.item(row)
        if it is None:
            return None

        title = (it.text() or "").strip()

        primary_dir = Path(str(it.data(Qt.UserRole)))
        raw_dirs = it.data(Qt.UserRole + 1) or []
        try:
            all_dirs = [Path(str(x)) for x in list(raw_dirs) if x]
        except Exception:
            all_dirs = [primary_dir]

        if not all_dirs:
            all_dirs = [primary_dir]

        return {
            "primary_dir": primary_dir,
            "all_dirs": all_dirs,
            "display_title": title,
        }

    def _hit_is_backdrop(self, h: TMDBHit) -> bool:
        """
        True if we can use a wide backdrop.
        """
        try:
            return bool(getattr(h, "backdrop_path", None))
        except Exception:
            return False

    def _choose_hit_image_path(self, h: TMDBHit) -> Optional[str]:
        """
        For horizontal cards:
          - prefer backdrop (wide)
          - fallback to poster (vertical)
        """
        bd = getattr(h, "backdrop_path", None)
        if bd:
            return bd
        po = getattr(h, "poster_path", None)
        if po:
            return po
        return None

    # ============================================================
    # Rename
    # ============================================================
    def _on_rename_clicked(self) -> None:
        sel = self._selected_left_dirs()
        if not sel:
            QMessageBox.information(self, "Select an item", "Select a show/movie on the left first.")
            return

        current = str(sel["display_title"])
        primary_dir: Path = sel["primary_dir"]

        new_name, ok = QInputDialog.getText(self, "Edit show name", "New display name:", text=current)
        if not ok:
            return

        new_name = (new_name or "").strip()
        if not new_name:
            return

        # Update UI immediately
        row = self.left_list.currentRow()
        it = self.left_list.item(row)
        if it is not None:
            it.setText(new_name)

        # Record rename for controller to apply (MetadataCache)
        self.rename_map[str(primary_dir)] = new_name

    # ============================================================
    # Search
    # ============================================================
    def _on_search_clicked(self) -> None:
        sel = self._selected_left_dirs()
        if not sel:
            QMessageBox.information(self, "Select an item", "Select a show/movie on the left first.")
            return

        title = (sel["display_title"] or "").strip()
        override = (self.search_box.text() or "").strip()
        query = override if override else title

        if not query:
            return

        self.right_list.clear()
        self._hits = []

        try:
            hits = self._tmdb.search_multi(query, limit=16)
        except Exception as e:
            QMessageBox.critical(self, "TMDB Error", f"Search failed:\n{type(e).__name__}: {e}")
            return

        if not hits:
            QMessageBox.information(self, "No results", "TMDB returned no results for that query.")
            return

        self._hits = hits

        # Render suggestions with checkbox + wide thumbnail if possible
        for idx, h in enumerate(hits):
            label = f"{h.title}  ({h.year})  [{h.media_type}]"
            item = QListWidgetItem(label)
            item.setCheckState(Qt.Unchecked)

            # Store index into self._hits
            item.setData(Qt.UserRole, int(idx))

            self.right_list.addItem(item)

            # Preview: prefer backdrop, else poster
            img_path = self._choose_hit_image_path(h)
            if not img_path:
                continue

            try:
                # Backdrops look great as w300/w780 preview.
                # Posters also work; they'll just be “tall” inside the icon box.
                size = "w300" if self._hit_is_backdrop(h) else "w185"
                url = self._tmdb.image_url(img_path, size=size)
                img_bytes = self._tmdb.download_image_bytes(url)

                px = QPixmap()
                px.loadFromData(img_bytes)

                if not px.isNull():
                    item.setIcon(QIcon(px))
            except Exception:
                pass

    # ============================================================
    # Apply
    # ============================================================
    def _on_apply_clicked(self) -> None:
        sel = self._selected_left_dirs()
        if not sel:
            QMessageBox.information(self, "Select an item", "Select a show/movie on the left first.")
            return

        primary_dir: Path = sel["primary_dir"]
        all_dirs: List[Path] = list(sel["all_dirs"])

        # Gather checked suggestions
        checked: List[TMDBHit] = []

        for i in range(self.right_list.count()):
            ri = self.right_list.item(i)
            if ri is None:
                continue
            if ri.checkState() != Qt.Checked:
                continue

            idx = ri.data(Qt.UserRole)
            try:
                hit = self._hits[int(idx)]
                checked.append(hit)
            except Exception:
                pass

        if not checked:
            QMessageBox.information(self, "Nothing checked", "Check at least one suggestion on the right.")
            return

        # Apply FIRST checked (safe baseline; expand later if you want)
        chosen = checked[0]

        chosen_img_path = self._choose_hit_image_path(chosen)
        if not chosen_img_path:
            QMessageBox.warning(self, "No art", "That selection has no backdrop or poster image on TMDB.")
            return

        # Decide output filename by what we used
        out_name = "backdrop.jpg" if self._hit_is_backdrop(chosen) else "poster.jpg"

        # Download bytes (high quality but sane)
        try:
            # Backdrops: w1280 is excellent.
            # Posters: w780 is excellent.
            size = "w1280" if self._hit_is_backdrop(chosen) else "w780"
            url = self._tmdb.image_url(chosen_img_path, size=size)
            img_bytes = self._tmdb.download_image_bytes(url)
        except Exception as e:
            QMessageBox.critical(self, "Download error", f"Could not download art:\n{type(e).__name__}: {e}")
            return

        # Write to ALL merged folders so changes stick no matter which folder wins scan order
        written = 0
        for d in all_dirs:
            try:
                d.mkdir(parents=True, exist_ok=True)
                out_path = d / out_name
                out_path.write_bytes(img_bytes)
                written += 1
            except Exception:
                pass

        if written <= 0:
            QMessageBox.critical(self, "Save error", "Could not write the image into any target folders.")
            return

        QMessageBox.information(
            self,
            "Art Applied",
            f"Wrote {out_name} into {written} folder(s).\n\nSelection:\n{chosen.title} ({chosen.year})",
        )

        # Keep list stable (do NOT auto-remove); user may want to change again
        self.right_list.clear()
        self._hits = []
