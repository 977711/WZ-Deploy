from asyncio import create_task
from html import escape
from io import IOBase
from logging import getLogger
from os import path as ospath
from os import walk as oswalk

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
from ...ext_utils.telegraph_helper import telegraph

LOGGER = getLogger(__name__)


class ProgressFileWrapper(IOBase):
    def __init__(self, file_obj, callback=None):
        self.file_obj = file_obj
        self.callback = callback
        self.total_read = 0

    def read(self, size=-1):
        data = self.file_obj.read(size)
        if data:
            self.total_read += len(data)
            if self.callback:
                self.callback(self.total_read)
        return data

    def seek(self, *args, **kwargs):
        return self.file_obj.seek(*args, **kwargs)

    def tell(self):
        return self.file_obj.tell()

    def close(self):
        return self.file_obj.close()

    @property
    def name(self):
        return getattr(self.file_obj, "name", "")

    def readable(self):
        return True

    def writable(self):
        return False

    def seekable(self):
        return True


class DevUploadsUpload:
    def __init__(self, listener, path, skip_token_validation=False):
        self.listener = listener
        self._updater = None
        self._path = path
        self._is_errored = False
        self._upload_task = None

        self.server_api_url = "https://devuploads.com/api/upload/server"

        self.__processed_bytes = 0
        self.last_uploaded = 0
        self.total_time = 0
        self.total_files = 0
        self.total_folders = 0
        self.is_uploading = True
        self.update_interval = 3
        self.skip_token_validation = skip_token_validation

        self._sess_id = None
        self._server_url = None

        from .... import user_data

        user_dict = user_data.get(self.listener.user_id, {})
        self.api_key = user_dict.get("DEVUPLOADS_API_KEY") or getattr(
            Config, "DEVUPLOADS_API_KEY", None
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

    async def get_upload_server(self):
        if not self.api_key:
            raise ValueError("DevUploads API key not found!")

        async with ClientSession() as session:
            url = f"{self.server_api_url}?key={self.api_key}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status} getting upload server")
                result = await resp.json()

        if result.get("status") != 200:
            raise Exception(f"Failed to get upload server: {result}")

        self._sess_id = result.get("sess_id")
        self._server_url = result.get("result")
        if not self._sess_id or not self._server_url:
            raise Exception(f"Invalid upload server response: {result}")
        return True

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        reraise=True,
    )
    async def upload_file(self, file_path: str):
        if not self.api_key:
            raise ValueError("DevUploads API key not found!")

        if self.listener.is_cancelled:
            return None

        if not self._sess_id or not self._server_url:
            await self.get_upload_server()

        file_name = ospath.basename(file_path).replace(" ", ".")
        file_handle = open(file_path, "rb")
        try:
            wrapped = ProgressFileWrapper(file_handle, self.__progress_callback)

            data = FormData()
            data.add_field("sess_id", self._sess_id)
            data.add_field("utype", "reg")
            data.add_field("file", wrapped, filename=file_name)

            async with ClientSession() as session:
                async with session.post(
                    self._server_url,
                    data=data,
                    timeout=3600,
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f"Upload failed with status {resp.status}")
                    result = await resp.json()

            if isinstance(result, list):
                if result and isinstance(result[0], dict):
                    file_code = result[0].get("file_code")
                else:
                    raise Exception(f"Unexpected list response format: {result}")
            elif isinstance(result, dict):
                file_code = result.get("file_code")
            else:
                raise Exception(f"Unexpected response type: {type(result)}")

            if not file_code:
                msg = (
                    result.get("message", "Unknown error")
                    if isinstance(result, dict)
                    else str(result)
                )
                raise Exception(f"DevUploads upload failed: {msg}")

            return f"https://devuploads.com/{file_code}"
        finally:
            file_handle.close()

    async def _links_to_telegraph(self, title, links):
        chunks = [links[i : i + 50] for i in range(0, len(links), 50)]
        pages = []
        total = len(links)

        for page_no, chunk in enumerate(chunks, start=1):
            start_idx = (page_no - 1) * 50 + 1
            header = (
                f"<h3>{escape(title)}</h3>"
                f"<p><b>Total files:</b> {total}<br>"
                f"<b>Page:</b> {page_no}/{len(chunks)}</p>"
                "<hr>"
            )
            items = "".join(
                f'{start_idx + i}. <a href="{escape(url)}">{escape(name)}</a><br>'
                for i, (name, url) in enumerate(chunk)
            )
            pages.append(header + items)

        paths = [
            (await telegraph.create_page(title=title, content=content))["path"]
            for content in pages
        ]
        if len(paths) > 1:
            await telegraph.edit_telegraph(paths, pages, title=title)
        return f"https://telegra.ph/{paths[0]}"

    async def _upload_dir(self, input_directory):
        folder_name = ospath.basename(input_directory)
        uploaded_links = []

        for root, dirs, files in await sync_to_async(oswalk, input_directory):
            if self.listener.is_cancelled:
                break

            rel_root = ospath.relpath(root, input_directory)
            if rel_root != ".":
                self.total_folders += 1

            for file in files:
                if self.listener.is_cancelled:
                    break

                file_path = ospath.join(root, file)
                link = await self.upload_file(file_path)
                if link:
                    self.total_files += 1
                    rel_name = ospath.relpath(file_path, input_directory)
                    uploaded_links.append((rel_name, link))

        if not uploaded_links:
            raise ValueError("Failed to upload folder to DevUploads")

        if len(uploaded_links) == 1:
            return uploaded_links[0][1]

        return await self._links_to_telegraph(folder_name, uploaded_links)

    async def upload(self):
        try:
            LOGGER.info(f"DevUploads Uploading: {self._path}")
            self._updater = SetInterval(self.update_interval, self.progress)

            if not self.api_key:
                raise ValueError(
                    "DevUploads API key not configured! Please set your DevUploads API key in user settings or configure a global key."
                )

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
        if not self.skip_token_validation:
            await self.get_upload_server()

        if await aiopath.isfile(self._path):
            link = await self.upload_file(self._path)
            if not link:
                raise ValueError("Failed to upload file to DevUploads")
            mime_type = "File"
            self.total_files = 1
        elif await aiopath.isdir(self._path):
            # Behave like PixelDrain: DevUploads folder uploads are not supported by this bot.
            # Allow the common "-m folder" case where the directory contains exactly one file.
            files = []
            for root, _, fs in await sync_to_async(oswalk, self._path):
                for f in fs:
                    files.append(ospath.join(root, f))

            if len(files) == 1:
                link = await self.upload_file(files[0])
                if not link:
                    raise ValueError("Failed to upload file to DevUploads")
                mime_type = "File"
                self.total_files = 1
            else:
                raise ValueError(
                    "DevUploads folder uploads are not supported. "
                    "Please upload a single file or use another upload destination."
                )
        else:
            raise ValueError("Invalid file path!")

        if self.listener.is_cancelled:
            return

        LOGGER.info(f"Uploaded To DevUploads: {self.listener.name}")
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
            LOGGER.info(f"Cancelling DevUploads Upload: {self.listener.name}")
            if self._upload_task and not self._upload_task.done():
                self._upload_task.cancel()
            await self.listener.on_upload_error("DevUploads upload has been cancelled!")
