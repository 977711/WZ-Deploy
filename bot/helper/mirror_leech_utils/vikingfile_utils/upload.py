from asyncio import create_task
from io import BufferedReader
from logging import getLogger
from os import path as ospath
from os import walk as oswalk
from pathlib import Path

from aiofiles.os import path as aiopath
from aiohttp import ClientSession, FormData
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ....core.config_manager import Config
from ...ext_utils.bot_utils import SetInterval, sync_to_async

LOGGER = getLogger(__name__)


class ProgressFileReader(BufferedReader):
    def __init__(self, filename, read_callback=None):
        super().__init__(open(filename, "rb"))
        self.__read_callback = read_callback
        self.length = Path(filename).stat().st_size

    def read(self, size=None):
        size = size or (self.length - self.tell())
        if self.__read_callback:
            self.__read_callback(self.tell())
        return super().read(size)


class LimitedFileReader(BufferedReader):
    def __init__(self, filename, offset, length, read_callback=None):
        self._file = open(filename, "rb")
        self._file.seek(offset)
        super().__init__(self._file)
        self._remaining = length
        self.__read_callback = read_callback

    def read(self, size=-1):
        if self._remaining <= 0:
            return b""
        if size is None or size < 0:
            size = self._remaining
        else:
            size = min(size, self._remaining)

        data = super().read(size)
        if data:
            self._remaining -= len(data)
            if self.__read_callback:
                self.__read_callback(len(data))
        return data

    def close(self):
        try:
            super().close()
        finally:
            self._file.close()

    def __len__(self):
        return self._remaining


class VikingFileUpload:
    def __init__(self, listener, path):
        self.listener = listener
        self._updater = None
        self._path = path
        self._is_errored = False
        self._upload_task = None

        self.__processed_bytes = 0
        self.last_uploaded = 0
        self.total_time = 0
        self.total_files = 0
        self.total_folders = 0
        self.is_uploading = True
        self.update_interval = 3

        from .... import user_data

        user_dict = user_data.get(self.listener.user_id, {})
        self.user_hash = user_dict.get("VIKINGFILE_USER") or getattr(
            Config, "VIKINGFILE_USER", ""
        )

    @property
    def speed(self):
        try:
            return self.__processed_bytes / self.total_time
        except Exception:
            return 0

    @property
    def processed_bytes(self):
        return self.__processed_bytes

    def __progress_callback(self, current):
        chunk_size = current - self.last_uploaded
        self.last_uploaded = current
        self.__processed_bytes += chunk_size

    async def progress(self):
        self.total_time += self.update_interval

    async def _get_upload_urls(self, size: int):
        async with ClientSession() as session:
            async with session.post(
                "https://vikingfile.com/api/get-upload-url",
                data={"size": str(size)},
            ) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}: {await resp.text()}")
                return await resp.json()

    async def _complete_upload(self, key, upload_id, parts, name):
        data = FormData()
        data.add_field("key", key)
        data.add_field("uploadId", upload_id)
        data.add_field("name", name)
        data.add_field("user", self.user_hash or "")
        for idx, part in enumerate(parts):
            data.add_field(f"parts[{idx}][PartNumber]", str(part["PartNumber"]))
            data.add_field(f"parts[{idx}][ETag]", str(part["ETag"]))

        async with ClientSession() as session:
            async with session.post(
                "https://vikingfile.com/api/complete-upload",
                data=data,
            ) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}: {await resp.text()}")
                return await resp.json()

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def upload_file(self, file_path: str):
        if self.listener.is_cancelled:
            return None

        file_size = Path(file_path).stat().st_size
        name = ospath.basename(file_path).replace(" ", ".")

        meta = await self._get_upload_urls(file_size)
        upload_id = meta.get("uploadId")
        key = meta.get("key")
        part_size = int(meta.get("partSize") or 0)
        urls = meta.get("urls") or []
        if not upload_id or not key or not part_size or not urls:
            raise Exception(f"Invalid VikingFile upload-url response: {meta}")

        parts = []

        async with ClientSession() as session:
            for part_number, url in enumerate(urls, start=1):
                if self.listener.is_cancelled:
                    return None

                start = (part_number - 1) * part_size
                part_len = min(part_size, file_size - start)
                if part_len <= 0:
                    break

                def on_read(delta):
                    self.__processed_bytes += delta

                reader = LimitedFileReader(
                    filename=file_path,
                    offset=start,
                    length=part_len,
                    read_callback=on_read,
                )
                try:
                    async with session.put(
                        url,
                        data=reader,
                        headers={"Content-Length": str(part_len)},
                    ) as resp:
                        if resp.status not in [200, 201, 204]:
                            raise Exception(
                                f"Part {part_number} upload failed: HTTP {resp.status}: {await resp.text()}"
                            )
                        etag = resp.headers.get("ETag") or resp.headers.get("Etag")
                        if not etag:
                            raise Exception(f"Missing ETag for part {part_number}")
                        parts.append(
                            {"PartNumber": part_number, "ETag": etag.strip('"')}
                        )
                finally:
                    reader.close()

        result = await self._complete_upload(
            key=key, upload_id=upload_id, parts=parts, name=name
        )
        link = result.get("url")
        if not link:
            raise Exception(f"Invalid VikingFile complete-upload response: {result}")
        return link

    async def upload(self):
        try:
            LOGGER.info(f"VikingFile Uploading: {self._path}")
            self._updater = SetInterval(self.update_interval, self.progress)

            self._upload_task = create_task(self._upload_process())
            await self._upload_task

        except Exception as err:
            if isinstance(err, RetryError):
                LOGGER.info(f"Total Attempts: {err.last_attempt.attempt_number}")
                err = err.last_attempt.exception()
            err = str(err).replace(">", "").replace("<", "")
            LOGGER.error(err)
            await self.listener.on_upload_error(err)
            self._is_errored = True
        finally:
            if self._updater:
                self._updater.cancel()

    async def _upload_process(self):
        if await aiopath.isfile(self._path):
            link = await self.upload_file(self._path)
            if not link:
                raise ValueError("Failed to upload file to VikingFile")
            mime_type = "File"
            self.total_files = 1
        elif await aiopath.isdir(self._path):
            # Match PixelDrain behavior: allow only a single file within a folder.
            files = []
            for root, _, fs in await sync_to_async(oswalk, self._path):
                for f in fs:
                    files.append(ospath.join(root, f))

            if len(files) == 1:
                link = await self.upload_file(files[0])
                if not link:
                    raise ValueError("Failed to upload file to VikingFile")
                mime_type = "File"
                self.total_files = 1
            else:
                raise ValueError(
                    "VikingFile folder uploads are not supported. "
                    "Please upload a single file or use another upload destination."
                )
        else:
            raise ValueError("Invalid file path!")

        if self.listener.is_cancelled:
            return

        LOGGER.info(f"Uploaded To VikingFile: {self.listener.name}")
        await self.listener.on_upload_complete(
            link,
            self.total_files,
            self.total_folders,
            mime_type,
            dir_id="",
        )

    async def cancel_task(self):
        self.listener.is_cancelled = True
        if self.is_uploading:
            LOGGER.info(f"Cancelling VikingFile Upload: {self.listener.name}")
            if self._upload_task and not self._upload_task.done():
                self._upload_task.cancel()
            await self.listener.on_upload_error("VikingFile upload has been cancelled!")
