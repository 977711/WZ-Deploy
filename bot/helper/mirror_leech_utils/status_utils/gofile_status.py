from ....helper.ext_utils.status_utils import (
    MirrorStatus,
    EngineStatus,
    get_readable_file_size,
    get_readable_time,
)


class GoFileStatus:
    def __init__(self, listener, obj, gid, status):
        self.listener = listener
        self._obj = obj
        # Use the listener's resolved size; fall back to 0 if missing
        self._size = int(getattr(self.listener, "size", 0) or 0)
        self._gid = gid
        self._status = status
        self.engine = EngineStatus().STATUS_GOFILE

    def processed_bytes(self):
        return get_readable_file_size(self._obj.processed_bytes)

    def size(self):
        return get_readable_file_size(self._size)

    def status(self):
        if self._status == "up":
            return MirrorStatus.STATUS_UPLOAD
        elif self._status == "dl":
            return MirrorStatus.STATUS_DOWNLOAD
        else:
            return MirrorStatus.STATUS_CLONE

    def name(self):
        return self.listener.name

    def gid(self) -> str:
        return self._gid

    def progress_raw(self):
        """
        Return numeric progress in percent.

        If total size is unknown or zero, treat progress as 0 to avoid
        division errors and misleading values.
        """
        total = float(self._size or 0)
        done = float(getattr(self._obj, "processed_bytes", 0) or 0)
        if total <= 0:
            return 0.0
        return min(max(done / total * 100, 0.0), 100.0)

    def progress(self):
        return f"{round(self.progress_raw(), 2)}%"

    def speed(self):
        return f"{get_readable_file_size(getattr(self._obj, 'speed', 0) or 0)}/s"

    def eta(self):
        """
        Estimate remaining time based on current speed and remaining bytes.

        If speed or total size are unknown, return "-".
        """
        try:
            total = float(self._size or 0)
            done = float(getattr(self._obj, "processed_bytes", 0) or 0)
            speed = float(getattr(self._obj, "speed", 0) or 0)
            if total <= 0 or speed <= 0:
                return "-"
            remaining = max(total - done, 0.0)
            seconds = remaining / speed
            return get_readable_time(int(seconds))
        except Exception:
            return "-"

    def task(self):
        return self._obj
