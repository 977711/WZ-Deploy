from time import time

from .... import LOGGER
from ...ext_utils.status_utils import (
    get_readable_file_size,
    EngineStatus,
    MirrorStatus,
    get_readable_time,
)


class FFmpegStatus:
    def __init__(self, listener, obj, gid, status=""):
        self.listener = listener
        self._obj = obj
        self._gid = gid
        self._cstatus = status
        self.engine = EngineStatus().STATUS_FFMPEG

    def speed(self):
        if self._obj.speed_raw:
            return f"{get_readable_file_size(self._obj.speed_raw)}/s"
        subsize = getattr(self.listener, "subsize", None) or 0
        progress = getattr(self._obj, "progress_raw", 0) or 0
        start = getattr(self._obj, "_start_time", None)
        if subsize and progress and start:
            processed = subsize * (progress / 100)
            elapsed = max(time() - start, 1)
            return f"{get_readable_file_size(processed / elapsed)}/s"
        return "0 B/s"

    def processed_bytes(self):
        if self._obj.processed_bytes:
            return get_readable_file_size(self._obj.processed_bytes)
        subsize = getattr(self.listener, "subsize", None) or 0
        progress = getattr(self._obj, "progress_raw", 0) or 0
        if subsize and progress:
            return get_readable_file_size(subsize * (progress / 100))
        return "0 B"

    def progress(self):
        return f"{round(self._obj.progress_raw, 2)}%"

    def gid(self):
        return self._gid

    def name(self):
        return self.listener.name

    def size(self):
        if self._cstatus == "Split":
            subsize = getattr(self.listener, "subsize", None) or 0
            if subsize:
                return get_readable_file_size(subsize)
        return get_readable_file_size(self.listener.size)

    def eta(self):
        return get_readable_time(self._obj.eta_raw) if self._obj.eta_raw else "-"

    def status(self):
        if self._cstatus == "Convert":
            return MirrorStatus.STATUS_CONVERT
        elif self._cstatus == "Split":
            return MirrorStatus.STATUS_SPLIT
        elif self._cstatus == "Sample Video":
            return MirrorStatus.STATUS_SAMVID
        else:
            return MirrorStatus.STATUS_FFMPEG

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
