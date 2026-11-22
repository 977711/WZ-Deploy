from asyncio import Condition

from ...core.config_manager import Config

MB = 1024 * 1024
_MIN_BUDGET = 48 * MB
_MAX_BUDGET = 512 * MB


def available_bytes():
    try:
        from psutil import virtual_memory

        return virtual_memory().available
    except Exception:
        return 0


def limit_bytes():
    try:
        from psutil import virtual_memory

        return virtual_memory().total
    except Exception:
        return 2048 * MB


class Budget:
    def __init__(self):
        self._used = 0
        self._peak = 0
        self._waits = 0
        self._cond = Condition()
        self._limit = None

    @property
    def limit(self):
        if self._limit is None:
            configured = (getattr(Config, "MEM_BUDGET", 0) or 0) * MB
            if configured > 0:
                self._limit = configured
            else:
                share = int(limit_bytes() * 0.15)
                self._limit = max(_MIN_BUDGET, min(_MAX_BUDGET, share))
        return self._limit

    @property
    def used(self):
        return self._used

    @property
    def peak(self):
        return self._peak

    @property
    def waits(self):
        return self._waits

    def resize(self, value):
        self._limit = max(1, int(value))

    async def reserve(self, size):
        size = max(0, int(size))
        if size <= 0:
            return 0
        cap = max(self.limit, size)
        async with self._cond:
            waited = False
            while self._used + size > cap:
                waited = True
                await self._cond.wait()
            if waited:
                self._waits += 1
            self._used += size
            self._peak = max(self._peak, self._used)
        return size

    async def release(self, size):
        size = max(0, int(size))
        if size <= 0:
            return
        async with self._cond:
            self._used = max(0, self._used - size)
            self._cond.notify_all()

    def stats(self):
        return {
            "limit": self.limit,
            "used": self._used,
            "peak": self._peak,
            "waits": self._waits,
        }


budget = Budget()
