from contextlib import suppress
from math import isfinite
import os
import signal

from .. import LOGGER
from ..helper.ext_utils.status_utils import (
    MirrorStatus,
    get_readable_file_size,
    get_readable_time,
)

ENGINE_NAME = "DzoneVT V1.0"

_FKEY_STATUS = {
    "encode": MirrorStatus.STATUS_VT_ENCODE,
    "convert": MirrorStatus.STATUS_VT_CONVERT,
    "multi_res": MirrorStatus.STATUS_VT_MULTIRES,
    "merge_video": MirrorStatus.STATUS_VT_MERGE,
    "mux_audio": MirrorStatus.STATUS_VT_MUXAUDIO,
    "softsub": MirrorStatus.STATUS_VT_SOFTSUB,
    "mux_all": MirrorStatus.STATUS_VT_MUX,
    "introsub": MirrorStatus.STATUS_VT_INTROSUB,
    "hardsub": MirrorStatus.STATUS_VT_HARDSUB,
    "rm_sub": MirrorStatus.STATUS_VT_RMSUB,
    "rm_audio": MirrorStatus.STATUS_VT_RMAUDIO,
    "rm_streams": MirrorStatus.STATUS_VT_RMSTREAMS,
    "strip_metadata": MirrorStatus.STATUS_VT_STRIPMETA,
    "extract": MirrorStatus.STATUS_VT_EXTRACT,
    "swap_audio": MirrorStatus.STATUS_VT_SWAPAUDIO,
    "watermark": MirrorStatus.STATUS_VT_WATERMARK,
}


class VTStatus:
    def __init__(self, listener, gid: str, func_key: str, obj=None):
        self.listener = listener
        self._gid = gid
        self._func_key = func_key
        self._obj = obj
        self.engine = ENGINE_NAME
        self._status = _FKEY_STATUS.get(func_key, MirrorStatus.STATUS_FFMPEG)
        self.mode = getattr(self.listener, "mode", ("VT", "Video Tool"))
        self.subname = getattr(self.listener, "subname", "")
        self.subsize = getattr(self.listener, "subsize", 0)
        self.files_to_proceed = getattr(self.listener, "files_to_proceed", [])
        self.proceed_count = getattr(self.listener, "proceed_count", 0)
        self.cancel_reason = None

    def gid(self) -> str:
        return self._gid

    def name(self) -> str:
        return self.listener.name

    def size(self) -> str:
        return get_readable_file_size(self.listener.size)

    def status(self) -> str:
        return self._status

    def processed_bytes(self) -> str:
        if self._obj and hasattr(self._obj, "processed_bytes"):
            return get_readable_file_size(self._obj.processed_bytes)
        return "0B"

    def progress(self) -> str:
        if self._obj and hasattr(self._obj, "progress_raw"):
            progress = self._obj.progress_raw
            try:
                progress = float(progress)
            except (TypeError, ValueError):
                return "0%"
            if not isfinite(progress):
                return "0%"
            progress = max(0.0, min(100.0, progress))
            return f"{round(progress, 2)}%"
        return "0%"

    def speed(self) -> str:
        if self._obj and hasattr(self._obj, "speed_raw"):
            speed = self._obj.speed_raw
            try:
                speed = int(speed or 0)
            except (TypeError, ValueError):
                speed = 0
            speed = max(0, speed)
            return f"{get_readable_file_size(speed)}/s"
        return "0B/s"

    def eta(self) -> str:
        if self._obj and hasattr(self._obj, "eta_raw") and self._obj.eta_raw:
            try:
                eta = int(self._obj.eta_raw)
            except (TypeError, ValueError):
                return "-"
            if eta < 0:
                return "-"
            return get_readable_time(eta)
        return "-"

    def task(self):
        return self

    async def cancel_task(self, reason: str = None):
        if self.listener.is_cancelled:
            return
        LOGGER.info(f"[VT] Cancelling {self._func_key}: {self.listener.name}")
        self.listener.is_cancelled = True
        self.cancel_reason = reason or f"Video Tool ({self._func_key}) stopped by user!"
        proc = getattr(self._obj, "subproc", None)
        if proc is not None and proc.returncode is None:
            try:
                if proc.pid:
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except Exception as e:
                LOGGER.warning(
                    f"[VT] Failed to kill process group for {self.listener.name}: {e}"
                )
                with suppress(Exception):
                    proc.kill()
        await self.listener.on_upload_error(
            self.cancel_reason,
            is_cancelled=True,
        )
