# omega/ui/thumbnails.py
from __future__ import annotations

import hashlib
import queue
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Optional, Tuple


class EpisodeThumbnailer:
    """
    Background thumbnail generator for episode files.

    - Uses FFmpeg to generate cached JPG thumbnails.
    - Runs in a background thread to avoid freezing UI.
    - If FFmpeg isn't available, it quietly does nothing.
    """

    def __init__(
        self,
        cache_dir: Path,
        timestamp_sec: int = 300,
        on_timing: Optional[Callable[[str, float], None]] = None,
        on_result_ready: Optional[Callable[[], None]] = None,
    ):
        self.cache_dir = Path(cache_dir)
        self.thumb_root = self.cache_dir / "thumbnails"
        self.timestamp_sec = int(timestamp_sec)
        self._on_timing = on_timing
        self._on_result_ready = on_result_ready

        self.ffmpeg = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")

        self._done_q: "queue.Queue[tuple[Path, Path, bool]]" = queue.Queue()

        self._enqueued: set[str] = set()
        self._pending_tasks: "deque[tuple[Path, Path, str]]" = deque()
        self._state_lock = threading.Lock()
        self._state_changed = threading.Condition(self._state_lock)
        self._outstanding = 0
        self._paused = False
        self._active_process: Optional[subprocess.Popen] = None
        self._active_episode_key = ""
        self._active_cancel_requested = False

        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def is_available(self) -> bool:
        return bool(self.ffmpeg)

    def done_queue(self) -> "queue.Queue[tuple[Path, Path, bool]]":
        return self._done_q

    def has_outstanding(self) -> bool:
        with self._state_lock:
            return bool(self._outstanding > 0)

    def is_paused(self) -> bool:
        with self._state_lock:
            return bool(self._paused)

    def set_paused(self, paused: bool) -> None:
        with self._state_lock:
            new_value = bool(paused)
            if self._paused == new_value:
                return
            self._paused = new_value
            if self._paused:
                self._drop_pending_tasks_locked()
                if self._active_episode_key:
                    self._active_cancel_requested = True
            self._state_changed.notify_all()

    def pause(self) -> None:
        self.set_paused(True)

    def resume(self) -> None:
        self.set_paused(False)

    @staticmethod
    def _safe_resolve(p: Path) -> str:
        try:
            return str(p.resolve())
        except Exception:
            return str(p.absolute())

    @staticmethod
    def _sha1(s: str) -> str:
        return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()

    def show_key(self, show_dir: Path) -> str:
        return self._sha1(self._safe_resolve(show_dir))

    def episode_key(self, episode_path: Path) -> str:
        p = self._safe_resolve(episode_path)
        try:
            mtime = episode_path.stat().st_mtime
        except Exception:
            mtime = 0.0
        return self._sha1(f"{p}|{mtime}")

    def thumb_path_for(self, show_dir: Path, episode_path: Path) -> Path:
        sk = self.show_key(show_dir)
        ek = self.episode_key(episode_path)
        return self.thumb_root / sk / f"{ek}.jpg"

    def ensure_thumbnail(self, show_dir: Path, episode_path: Path, *, high_priority: bool = False) -> Optional[Path]:
        if not self.is_available():
            return None
        if not episode_path.exists():
            return None

        out_path = self.thumb_path_for(show_dir, episode_path)
        if out_path.exists():
            return out_path

        ek = self.episode_key(episode_path)
        with self._state_lock:
            if self._paused:
                return None
            if ek not in self._enqueued:
                self._enqueued.add(ek)
                self._outstanding += 1
                if bool(high_priority):
                    self._pending_tasks.appendleft((show_dir, episode_path, ek))
                else:
                    self._pending_tasks.append((show_dir, episode_path, ek))
                self._state_changed.notify()

        return None

    def _worker_loop(self):
        while True:
            with self._state_lock:
                while True:
                    while self._paused or not self._pending_tasks:
                        self._state_changed.wait()
                    show_dir, episode_path, ek = self._pending_tasks.popleft()
                    if ek in self._enqueued:
                        self._active_episode_key = str(ek)
                        self._active_cancel_requested = False
                        break
            # Hold the lock only long enough to claim work.
            started = time.perf_counter()
            try:
                out_path = self.thumb_path_for(show_dir, episode_path)
                ok = self._generate_thumb_ffmpeg(
                    episode_path=episode_path,
                    out_path=out_path,
                    primary_sec=self.timestamp_sec,
                    episode_key=ek,
                )
                if ok is not None:
                    self._done_q.put((episode_path, out_path, bool(ok)))
                    if self._on_result_ready is not None:
                        try:
                            self._on_result_ready()
                        except Exception:
                            pass
            except Exception:
                try:
                    out_path = self.thumb_path_for(show_dir, episode_path)
                except Exception:
                    out_path = Path()
                self._done_q.put((episode_path, out_path, False))
                if self._on_result_ready is not None:
                    try:
                        self._on_result_ready()
                    except Exception:
                        pass
            finally:
                elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
                if self._on_timing is not None:
                    try:
                        self._on_timing("thumb_ffmpeg_job", float(elapsed_ms))
                    except Exception:
                        pass
                with self._state_lock:
                    self._enqueued.discard(ek)
                    self._outstanding = max(0, int(self._outstanding) - 1)
                    self._active_process = None
                    self._active_episode_key = ""
                    self._active_cancel_requested = False
                    self._state_changed.notify_all()

    def _drop_pending_tasks_locked(self) -> int:
        dropped = 0
        while self._pending_tasks:
            _show_dir, _episode_path, ek = self._pending_tasks.popleft()
            if ek in self._enqueued:
                self._enqueued.discard(ek)
                dropped += 1
        if dropped > 0:
            self._outstanding = max(0, int(self._outstanding) - dropped)
        return dropped

    def _should_cancel_active_job(self, episode_key: str) -> bool:
        with self._state_lock:
            if not episode_key:
                return False
            if str(self._active_episode_key or "") != str(episode_key):
                return False
            return bool(self._active_cancel_requested)

    @staticmethod
    def _terminate_process(proc: Optional[subprocess.Popen]) -> None:
        if proc is None:
            return
        try:
            if proc.poll() is not None:
                return
        except Exception:
            return
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=0.35)
            return
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=0.35)
        except Exception:
            pass

    @staticmethod
    def _cleanup_partial_output(out_path: Path) -> None:
        try:
            if out_path.exists():
                out_path.unlink()
        except Exception:
            pass

    def _run_ffmpeg_process(self, cmd: list[str], out_path: Path, episode_key: str) -> Optional[bool]:
        if self._should_cancel_active_job(episode_key):
            self._cleanup_partial_output(out_path)
            return None

        creationflags = int(getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
        proc: Optional[subprocess.Popen] = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            with self._state_lock:
                if str(self._active_episode_key or "") == str(episode_key):
                    self._active_process = proc
                    cancel_now = bool(self._active_cancel_requested)
                else:
                    cancel_now = True
            if cancel_now:
                self._terminate_process(proc)
                self._cleanup_partial_output(out_path)
                return None

            while True:
                try:
                    returncode = proc.wait(timeout=0.12)
                    break
                except subprocess.TimeoutExpired:
                    if self._should_cancel_active_job(episode_key):
                        self._terminate_process(proc)
                        self._cleanup_partial_output(out_path)
                        return None
                    continue

            if self._should_cancel_active_job(episode_key):
                self._cleanup_partial_output(out_path)
                return None
            return bool(returncode == 0 and out_path.exists())
        except Exception:
            if proc is not None:
                self._terminate_process(proc)
            self._cleanup_partial_output(out_path)
            return False

    def _generate_thumb_ffmpeg(
        self,
        episode_path: Path,
        out_path: Path,
        primary_sec: int,
        episode_key: str,
    ) -> Optional[bool]:
        if not self.is_available():
            return False

        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            return True

        candidates = [int(primary_sec), 60, 10]

        for sec in candidates:
            if self._should_cancel_active_job(episode_key):
                self._cleanup_partial_output(out_path)
                return None
            cmd = [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-threads", "1",
                "-y",
                "-ss", str(sec),
                "-i", str(episode_path),
                "-frames:v", "1",
                "-q:v", "5",
                "-vf", "scale=480:-2",
                str(out_path),
            ]
            try:
                ok = self._run_ffmpeg_process(cmd, out_path, episode_key)
                if ok is None:
                    return None
                if ok:
                    return True
            except Exception:
                pass

        return False
