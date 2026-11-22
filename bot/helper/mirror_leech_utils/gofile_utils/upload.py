from aiofiles.os import path as aiopath, rename as aiorename
from aiohttp import ClientSession
from aiohttp.client_exceptions import ContentTypeError
from io import BufferedReader
from json import JSONDecodeError
from logging import getLogger
from os import path as ospath, walk as oswalk
from pathlib import Path
from random import choice
from time import time
from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_exception_type,
    RetryError,
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
        data = super().read(size)
        if self.__read_callback:
            # report current position after the read
            self.__read_callback(self.tell())
        return data


class GoFileUpload:
    def __init__(self, listener, path, skip_token_validation=False):
        self.listener = listener
        self._updater = None
        self._path = path
        self._is_errored = False
        self.api_url = "https://api.gofile.io/"
        self.__processed_bytes = 0
        self.last_uploaded = 0
        self.total_time = 0
        self.total_files = 0
        self.total_folders = 0
        self.is_uploading = True
        self.update_interval = 3
        self._start_time = time()
        self.skip_token_validation = skip_token_validation

        # Get user-specific token or fall back to global config
        from .... import user_data

        user_dict = user_data.get(self.listener.user_id, {})
        global_token = getattr(Config, "GOFILE_API", None)
        global_folder = getattr(Config, "GOFILE_FOLDER_ID", "")
        self.token = user_dict.get("GOFILE_TOKEN") or global_token
        # Prefer per-user folder, then global default, otherwise blank
        self.folder_id = user_dict.get("GOFILE_FOLDER_ID") or global_folder or ""

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
    )
    async def upload_aiohttp(self, url, file_path, field_name, extra_fields):
        """
        Low-level helper to POST a file to GoFile with progress reporting.

        Returns the decoded JSON response (dict) or raises on HTTP / parse errors.
        """
        with ProgressFileReader(
            filename=file_path, read_callback=self.__progress_callback
        ) as file_obj:
            data = {field_name: file_obj}
            data.update(extra_fields or {})

            async with ClientSession() as session:
                async with session.post(url, data=data) as resp:
                    try:
                        return await resp.json()
                    except (ContentTypeError, JSONDecodeError):
                        # Fall back to raw text if server didn't send JSON
                        text = await resp.text()
                        raise Exception(
                            f"Unexpected GoFile response ({resp.status}): {text}"
                        )

    @property
    def speed(self):
        """
        Upload speed in bytes/second.

        Computed from processed bytes and elapsed wall time since this
        uploader instance was created. Falls back to 0 if elapsed time
        is too small.
        """
        try:
            elapsed = time() - self._start_time
            if elapsed <= 0:
                return 0
            return self.__processed_bytes / elapsed
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

    @staticmethod
    async def is_goapi(token):
        if token is None:
            return False

        headers = {"Authorization": f"Bearer {token}"}
        async with ClientSession() as session:
            async with session.get(
                "https://api.gofile.io/accounts/website", headers=headers
            ) as resp:
                res = await resp.json()
                return res.get("status") == "ok"

    async def __resp_handler(self, response):
        status = response.get("status", "")
        if status == "ok":
            return response.get("data", {})

        err_msg = (
            response.get("error")
            or response.get("message")
            or status
            or "Unknown GoFile API error"
        )
        if isinstance(err_msg, str) and err_msg.startswith("error-"):
            err_msg = err_msg.split("-", 1)[1] or err_msg

        LOGGER.error(f"GoFile API error response: {response}")
        raise Exception(err_msg)

    async def __getServer(self):
        """
        Fetch an upload server from GoFile in a robust way.

        GoFile may return:
          {"status": "ok", "data": {"servers": [...], "serversAllZone": [...]}}

        or, when the primary pool is exhausted:

          {"status": "noServer", "data": {"servers": [], "serversAllZone": [...]}}
        """
        async with ClientSession() as session:
            async with session.get(f"{self.api_url}servers") as resp:
                raw = await resp.json()

        status = raw.get("status", "")
        data = raw.get("data", {}) or {}

        # Normal, documented case
        if status == "ok":
            servers = data.get("servers") or data.get("serversAllZone") or []
        # Fallback when no primary servers are available
        elif status == "noServer":
            # Prefer any servers list present; if empty, fall back to serversAllZone
            servers = data.get("servers") or data.get("serversAllZone") or []
        else:
            # Use common handler for unexpected errors
            await self.__resp_handler(raw)  # will raise
            servers = []

        if not servers:
            # At this point we have genuinely no server candidates
            raise Exception("No GoFile upload server available (servers list is empty)")

        # Ensure a consistent return shape with a 'servers' list of dicts
        return {"servers": servers}

    async def upload_file(
        self,
        path: str,
        folderId: str = "",
        description: str = "",
        password: str = "",
        tags: str = "",
        expire: str = "",
    ):
        if password and len(password) < 4:
            raise ValueError("Password Length must be greater than 4")

        server = choice((await self.__getServer())["servers"])["name"]
        req_dict = {}

        # GoFile supports passing token/folderId as multipart fields.
        if self.token:
            req_dict["token"] = self.token
        if folderId:
            req_dict["folderId"] = folderId
        if description:
            req_dict["description"] = description
        if password:
            req_dict["password"] = password
        if tags:
            req_dict["tags"] = tags
        if expire:
            req_dict["expire"] = expire

        if self.listener.is_cancelled:
            return None

        original_path = path
        # Replace spaces with dots in filename for upload, then rename back.
        new_path = ospath.join(
            ospath.dirname(path), ospath.basename(path).replace(" ", ".")
        )
        if new_path != original_path:
            await aiorename(original_path, new_path)

        try:
            upload_resp = await self.upload_aiohttp(
                f"https://{server}.gofile.io/contents/uploadfile",
                new_path,
                "file",
                req_dict,
            )
            return await self.__resp_handler(upload_resp)
        finally:
            if new_path != original_path:
                await aiorename(new_path, original_path)

    async def __getAccount(self):
        if self.token is None:
            raise Exception("GoFile API token not found!")

        headers = {"Authorization": f"Bearer {self.token}"}
        async with ClientSession() as session:
            async with session.get(
                f"{self.api_url}accounts/website", headers=headers
            ) as resp:
                return await self.__resp_handler(await resp.json())

    async def __setOptions(self, contentId, option, value):
        if self.token is None:
            raise Exception("GoFile API token not found!")

        if option not in [
            "name",
            "description",
            "tags",
            "public",
            "expiry",
            "password",
        ]:
            raise Exception(f"Invalid GoFile Option Specified: {option}")

        headers = {"Authorization": f"Bearer {self.token}"}
        async with ClientSession() as session:
            async with session.put(
                url=f"{self.api_url}contents/{contentId}/update",
                json={
                    "attribute": option,
                    "attributeValue": value,
                    "token": self.token,
                },
                headers=headers,
            ) as resp:
                return await self.__resp_handler(await resp.json())

    async def create_folder(self, parentFolderId, folderName):
        if self.token is None:
            raise Exception("GoFile API token not found!")

        headers = {"Authorization": f"Bearer {self.token}"}
        async with ClientSession() as session:
            async with session.post(
                url=f"{self.api_url}contents/createFolder",
                json={
                    "parentFolderId": parentFolderId,
                    "folderName": folderName,
                    "token": self.token,
                },
                headers=headers,
            ) as resp:
                data = await self.__resp_handler(await resp.json())

        # API responses have varied over time; normalize to a consistent shape
        folder_id = data.get("folderId") or data.get("id") or data.get("contentId")
        if not folder_id:
            LOGGER.error(f"Unexpected GoFile createFolder response: {data}")
            raise Exception("GoFile createFolder: folder id missing in response")

        data["folderId"] = folder_id
        return data

    async def _upload_dir(
        self, input_directory, parent_folder_id=None, root_folder_id=None
    ):
        if root_folder_id is None:
            account_data = await self.__getAccount()
            root_folder_id = account_data["rootFolder"]

        # Always create a top-level folder for this upload so we can:
        # - preserve structure
        # - return a shareable folder code
        if parent_folder_id is None:
            parent_folder_id = self.folder_id or root_folder_id

        folder_data = await self.create_folder(
            parent_folder_id, ospath.basename(input_directory)
        )
        await self.__setOptions(
            contentId=folder_data["folderId"], option="public", value="true"
        )
        parent_folder_id = folder_data["folderId"]

        # 'code' is not always returned by the API. We'll still upload correctly,
        # but if it's missing we can't construct a /d/<code> share link.
        main_folder_code = folder_data.get("code")

        folder_ids = {".": parent_folder_id}

        for root, dirs, files in await sync_to_async(oswalk, input_directory):
            if self.listener.is_cancelled:
                break

            rel_path = ospath.relpath(root, input_directory)
            current_parent_rel = ospath.dirname(rel_path) or "."
            current_folder_id = folder_ids.get(current_parent_rel, parent_folder_id)

            if rel_path != ".":
                if rel_path in folder_ids:
                    current_folder_id = folder_ids[rel_path]
                else:
                    folder_name = ospath.basename(rel_path)
                    curr_folder_data = await self.create_folder(
                        current_folder_id, folder_name
                    )
                    await self.__setOptions(
                        contentId=curr_folder_data["folderId"],
                        option="public",
                        value="true",
                    )
                    folder_ids[rel_path] = curr_folder_data["folderId"]
                    current_folder_id = curr_folder_data["folderId"]
                    self.total_folders += 1

            # Create empty directories too
            for d in dirs:
                if self.listener.is_cancelled:
                    break

                child_rel = ospath.join(rel_path, d) if rel_path != "." else d
                if child_rel in folder_ids:
                    continue

                child_folder_data = await self.create_folder(current_folder_id, d)
                await self.__setOptions(
                    contentId=child_folder_data["folderId"],
                    option="public",
                    value="true",
                )
                folder_ids[child_rel] = child_folder_data["folderId"]
                self.total_folders += 1

            for file in files:
                if self.listener.is_cancelled:
                    break

                file_path = ospath.join(root, file)
                await self.upload_file(file_path, current_folder_id)
                self.total_files += 1

        return main_folder_code

    async def upload(self):
        try:
            LOGGER.info(f"GoFile Uploading: {self._path}")
            self._updater = SetInterval(self.update_interval, self.progress)

            if not self.token:
                raise ValueError(
                    "GoFile API token not configured! Please set your GoFile token in user settings or configure a global token."
                )

            await self._upload_process()

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
            if not await self.is_goapi(self.token):
                raise Exception("Invalid GoFile API Key, please check your token!")

        account_data = None
        if await aiopath.isdir(self._path):
            account_data = await self.__getAccount()

        if await aiopath.isfile(self._path):
            target_folder = self.folder_id or ""
            file_result = await self.upload_file(
                path=self._path, folderId=target_folder
            )
            if file_result and file_result.get("downloadPage"):
                link = file_result["downloadPage"]
                mime_type = "File"
                self.total_files = 1
            else:
                raise ValueError("Failed to upload file to GoFile")
        elif await aiopath.isdir(self._path):
            folder_code = await self._upload_dir(
                self._path,
                root_folder_id=account_data["rootFolder"],
            )
            if folder_code:
                link = f"https://gofile.io/d/{folder_code}"
            else:
                # Some API responses don't return a folder share code.
                # Upload can still succeed, but we can't construct a /d/<code> link.
                link = "https://gofile.io/"
            mime_type = "Folder"
        else:
            raise ValueError("Invalid file path!")

        if self.listener.is_cancelled:
            return

        LOGGER.info(f"Uploaded To GoFile: {self.listener.name}")
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
            LOGGER.info(f"Cancelling GoFile Upload: {self.listener.name}")
            await self.listener.on_upload_error("GoFile upload has been cancelled!")
