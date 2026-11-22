from time import time

from .... import LOGGER
from ...ext_utils.status_utils import (
    get_readable_file_size,
    EngineStatus,
    MirrorStatus,
    get_readable_time,
)


class MetadataStatus:
    def __init__(self, listener, obj, gid, status=""):
        self.listener = listener
        self._obj = obj
        self._gid = gid
        self._cstatus = status
        self.engine = EngineStatus().STATUS_METADATA

    def speed(self):
        try:
            if hasattr(self._obj, "speed_raw") and self._obj.speed_raw:
                return f"{get_readable_file_size(self._obj.speed_raw)}/s"
            started_at = getattr(self.listener, "metadata_started_at", None)
            processed = getattr(self._obj, "processed_bytes", 0) or 0
            if started_at and processed:
                elapsed = max(time() - started_at, 1)
                return f"{get_readable_file_size(processed / elapsed)}/s"
            subsize = getattr(self.listener, "subsize", None) or 0
            progress = getattr(self._obj, "progress_raw", 0) or 0
            if started_at and subsize and progress:
                elapsed = max(time() - started_at, 1)
                processed_est = subsize * (progress / 100)
                return f"{get_readable_file_size(processed_est / elapsed)}/s"
            return "0 B/s"
        except Exception:
            return "0 B/s"

    def _processed_estimate(self):
        subsize = getattr(self.listener, "subsize", None) or 0
        progress = getattr(self._obj, "progress_raw", 0) or 0
        if subsize and progress:
            return int(subsize * (progress / 100))
        total = getattr(self.listener, "files_to_proceed", None)
        proceed = getattr(self.listener, "proceed_count", 0) or 0
        total_size = getattr(self.listener, "size", 0) or 0
        if total and total_size and proceed > 0:
            return int(total_size * (proceed / len(total)))
        return 0

    def processed_bytes(self):
        try:
            if hasattr(self._obj, "processed_bytes") and self._obj.processed_bytes:
                subsize = getattr(self.listener, "subsize", None) or 0
                processed = self._obj.processed_bytes
                if subsize and processed > subsize:
                    processed = subsize
                return get_readable_file_size(processed)
            subsize = getattr(self.listener, "subsize", None) or 0
            progress = getattr(self._obj, "progress_raw", 0) or 0
            if subsize and progress:
                return get_readable_file_size(subsize * (progress / 100))
            estimate = self._processed_estimate()
            return get_readable_file_size(estimate) if estimate else "0 B"
        except Exception:
            return "0 B"

    def progress(self):
        try:
            if (
                hasattr(self._obj, "progress_raw")
                and self._obj.progress_raw is not None
            ):
                return f"{round(self._obj.progress_raw, 2)}%"
            elif hasattr(self._obj, "_progress") and self._obj._progress is not None:
                return f"{round(self._obj._progress, 2)}%"
            if getattr(self.listener, "subsize", None) and getattr(
                self._obj, "progress_raw", 0
            ):
                return f"{round(self._obj.progress_raw, 2)}%"
            estimate = self._processed_estimate()
            size = getattr(self.listener, "size", 0) or 0
            if size and estimate:
                return f"{round((estimate / size) * 100, 2)}%"
            return "0%"
        except Exception:
            return "0%"

    def gid(self):
        return self._gid

    def name(self):
        try:
            return getattr(self.listener, "subname", None) or self.listener.name
        except Exception:
            return "Processing..."

    def size(self):
        try:
            size = getattr(self.listener, "subsize", None) or self.listener.size
            return get_readable_file_size(size) if size else "Unknown"
        except Exception:
            return "Unknown"

    def eta(self):
        try:
            if (
                hasattr(self._obj, "eta_raw")
                and self._obj.eta_raw is not None
                and self._obj.eta_raw > 0
            ):
                return get_readable_time(self._obj.eta_raw)
            elif hasattr(self._obj, "_eta") and self._obj._eta != "-":
                return self._obj._eta
            speed = getattr(self._obj, "speed_raw", 0) or 0
            size = getattr(self.listener, "subsize", None) or self.listener.size
            processed = getattr(self._obj, "processed_bytes", 0) or 0
            if speed > 0 and size and size > processed:
                return get_readable_time(int((size - processed) / speed))
            progress = getattr(self._obj, "progress_raw", 0) or 0
            if size and progress:
                remaining = size - (size * (progress / 100))
                elapsed = max(
                    time() - getattr(self.listener, "metadata_started_at", time()), 1
                )
                processed_est = size * (progress / 100)
                if processed_est > 0:
                    return get_readable_time(int((remaining / processed_est) * elapsed))
            total = getattr(self.listener, "files_to_proceed", None)
            proceed = getattr(self.listener, "proceed_count", 0) or 0
            started_at = getattr(self.listener, "metadata_started_at", None)
            if total and started_at and proceed > 0:
                remaining = len(total) - proceed
                if remaining > 0:
                    elapsed = time() - started_at
                    avg = elapsed / max(proceed, 1)
                    return get_readable_time(int(avg * remaining))
            return "-"
        except Exception:
            return "-"

    def status(self):
        if self._cstatus == "Convert":
            return MirrorStatus.STATUS_CONVERT
        else:
            return MirrorStatus.STATUS_METADATA

    def task(self):
        return self

    async def cancel_task(self):
        LOGGER.info(f"Cancelling {self._cstatus}: {self.listener.name}")
        self.listener.is_cancelled = True
        if (
            self.listener.subproc is not None
            and self.listener.subproc.returncode is None
        ):
            try:
                self.listener.subproc.kill()
            except Exception:
                pass
        await self.listener.on_upload_error(f"{self._cstatus} stopped by user!")
