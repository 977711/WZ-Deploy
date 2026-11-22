from asyncio import TimeoutError, create_subprocess_exec, gather, sleep
from contextlib import suppress
from inspect import iscoroutinefunction
from os import getcwd
from pathlib import Path
from time import time

from aioaria2 import Aria2WebsocketClient
from aioaria2.exceptions import Aria2rpcException
from aiohttp import ClientError
from aioqbt.client import create_client
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .. import LOGGER, aria2_options
from ..helper.ext_utils.bot_utils import derive_service_password
from .config_manager import BinConfig, Config


def wrap_with_retry(obj, max_retries=3):
    for attr_name in dir(obj):
        if attr_name.startswith("_"):
            continue

        attr = getattr(obj, attr_name)
        if iscoroutinefunction(attr):
            retry_policy = retry(
                stop=stop_after_attempt(max_retries),
                wait=wait_exponential(multiplier=1, min=1, max=5),
                retry=retry_if_exception_type(
                    (ClientError, TimeoutError, RuntimeError)
                ),
            )
            wrapped = retry_policy(attr)
            setattr(obj, attr_name, wrapped)
    return obj


def _qbit_password():
    return derive_service_password(
        (Config.BOT_TOKEN or "").split(":", 1)[0] or "0",
        "qbit",
    )


class TorrentManager:
    aria2 = None
    qbittorrent = None
    _qbit_process = None
    _last_qbit_restart = 0
    _restart_debounce = 60

    @staticmethod
    def _is_connection_error(exc):
        message = str(exc).lower()
        return any(
            token in message
            for token in (
                "cannot connect",
                "connection refused",
                "name or service not known",
                "connect call failed",
                "timed out",
                "connection reset",
                "no route to host",
            )
        )

    @classmethod
    async def _connect_aria2(cls, retries=15, delay=2):
        last_error = None
        for attempt in range(retries):
            try:
                return await Aria2WebsocketClient.new("http://localhost:6800/jsonrpc")
            except Exception as exc:
                last_error = exc
                if not isinstance(exc, Aria2rpcException) and not cls._is_connection_error(exc):
                    raise
                if attempt == retries - 1:
                    raise
                LOGGER.warning(
                    "Aria2 RPC not ready yet (%s). Retrying in %s seconds.",
                    exc,
                    delay,
                )
                await sleep(delay)
        if last_error is not None:
            raise last_error

    @classmethod
    async def _auth_qbit(cls):
        if cls.qbittorrent is None:
            return False
        pwd = _qbit_password()
        try:
            await cls.qbittorrent.auth.login("admin", pwd)
            return True
        except Exception:
            return False

    @classmethod
    async def initiate(cls):
        if cls.aria2 or cls.qbittorrent:
            return
        tasks = [cls._init_aria2()]
        if not Config.DISABLE_TORRENTS:
            tasks.append(cls._init_qbit())
        await gather(*tasks)

    @classmethod
    async def _init_aria2(cls):
        try:
            cls.aria2 = await cls._connect_aria2()
            LOGGER.info("Aria2 initialized successfully.")
        except Exception as e:
            cls.aria2 = None
            if cls._is_connection_error(e):
                LOGGER.warning("Aria2 is unavailable; continuing without it: %s", e)
            else:
                LOGGER.error(f"Error during aria2 initialization: {e}")

    @classmethod
    async def _init_qbit(cls):
        try:
            cls._qbit_process = await create_subprocess_exec(
                BinConfig.QBIT_NAME,
                "-d",
                "--confirm-legal-notice",
                f"--profile={getcwd()}/configs/qbittorrent",
            )
            await sleep(2)
            LOGGER.info("qBittorrent started !")

            cls.qbittorrent = await create_client("http://localhost:8090/api/v2/")
            cls.qbittorrent = wrap_with_retry(cls.qbittorrent)
            await cls._auth_qbit()
            LOGGER.info("qBittorrent initialized successfully.")
        except Exception as e:
            cls.qbittorrent = None
            if cls._is_connection_error(e):
                LOGGER.warning(
                    "qBittorrent is unavailable; continuing without it: %s",
                    e,
                )
            else:
                LOGGER.error(f"Error during qBittorrent initialization: {e}")

    @classmethod
    async def close_all(cls):
        close_tasks = []
        if cls.aria2:
            close_tasks.append(cls.aria2.close())
            cls.aria2 = None
        if cls.qbittorrent:
            close_tasks.append(cls.qbittorrent.close())
            cls.qbittorrent = None
        if close_tasks:
            await gather(*close_tasks)

    @classmethod
    async def ensure_qbit(cls):
        if cls.qbittorrent is None:
            return await cls._start_qbit()
        try:
            await cls.qbittorrent.app.version()
            return True
        except Exception:
            return await cls._start_qbit()

    @classmethod
    async def _start_qbit(cls):
        now = time()
        if now - cls._last_qbit_restart < cls._restart_debounce:
            return False
        cls._last_qbit_restart = now
        LOGGER.info("(Re)starting qBittorrent...")
        try:
            if cls.qbittorrent:
                try:
                    await cls.qbittorrent.close()
                except Exception:
                    pass
                cls.qbittorrent = None
            cls._qbit_process = await create_subprocess_exec(
                BinConfig.QBIT_NAME,
                "-d",
                "--confirm-legal-notice",
                f"--profile={getcwd()}/configs/qbittorrent",
            )
            await sleep(3)
            cls.qbittorrent = await create_client("http://localhost:8090/api/v2/")
            cls.qbittorrent = wrap_with_retry(cls.qbittorrent)
            await cls._auth_qbit()
            LOGGER.info("qBittorrent (re)started successfully")
            return True
        except Exception as e:
            LOGGER.error(f"Failed to (re)start qBittorrent: {e}")
            return False

    @classmethod
    async def aria2_remove(cls, download):
        if not cls.aria2:
            return
        if download.get("status", "") in ["active", "paused", "waiting"]:
            with suppress(Exception):
                await cls.aria2.forceRemove(download.get("gid", ""))
        else:
            with suppress(Exception):
                await cls.aria2.removeDownloadResult(download.get("gid", ""))

    @classmethod
    async def remove_all(cls):
        await cls.pause_all()
        tasks = []
        if cls.aria2:
            tasks.append(cls.aria2.purgeDownloadResult())
        if cls.qbittorrent:
            tasks.append(cls.qbittorrent.torrents.delete("all", True))
        if tasks:
            with suppress(Exception):
                await gather(*tasks)

        if not cls.aria2:
            return

        downloads = []
        results = await gather(cls.aria2.tellActive(), cls.aria2.tellWaiting(0, 1000))
        for res in results:
            downloads.extend(res)
        tasks = []
        tasks.extend(
            cls.aria2.forceRemove(download.get("gid")) for download in downloads
        )
        with suppress(Exception):
            await gather(*tasks)

    @classmethod
    async def overall_speed(cls):
        if not cls.aria2:
            return 0, 0

        aria2_speed = await cls.aria2.getGlobalStat()
        download_speed = int(aria2_speed.get("downloadSpeed", "0"))
        upload_speed = int(aria2_speed.get("uploadSpeed", "0"))

        if cls.qbittorrent:
            with suppress(Exception):
                qb_speed = await cls.qbittorrent.transfer.info()
                download_speed += qb_speed.dl_info_speed
                upload_speed += qb_speed.up_info_speed

        return download_speed, upload_speed

    @classmethod
    async def pause_all(cls):
        pause_tasks = []
        if cls.aria2:
            pause_tasks.append(cls.aria2.forcePauseAll())
        if cls.qbittorrent:
            pause_tasks.append(cls.qbittorrent.torrents.stop("all"))
        if pause_tasks:
            with suppress(Exception):
                await gather(*pause_tasks)

    @classmethod
    async def change_aria2_option(cls, key, value):
        if not cls.aria2:
            return
        downloads = []
        results = await gather(cls.aria2.tellActive(), cls.aria2.tellWaiting(0, 1000))
        for res in results:
            downloads.extend(res)
        tasks = [
            cls.aria2.changeOption(download.get("gid"), {key: value})
            for download in downloads
            if download.get("status", "") != "complete"
        ]
        if tasks:
            try:
                await gather(*tasks)
            except Exception as e:
                LOGGER.error(e)
        if key not in ["checksum", "index-out", "out", "pause", "select-file"]:
            with suppress(Exception):
                await cls.aria2.changeGlobalOption({key: value})
            aria2_options[key] = value


def aria2_name(download_info):
    if "bittorrent" in download_info and download_info["bittorrent"].get("info"):
        return download_info["bittorrent"]["info"]["name"]
    elif download_info.get("files"):
        if download_info["files"][0]["path"].startswith("[METADATA]"):
            return download_info["files"][0]["path"]
        file_path = download_info["files"][0]["path"]
        dir_path = download_info["dir"]
        if file_path.startswith(dir_path):
            return Path(file_path[len(dir_path) + 1 :]).parts[0]
        else:
            return ""
    else:
        return ""


def is_metadata(download_info):
    return any(
        f["path"].startswith("[METADATA]") for f in download_info.get("files", [])
    )