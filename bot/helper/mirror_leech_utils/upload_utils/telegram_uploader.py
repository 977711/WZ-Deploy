from asyncio import Semaphore, ensure_future, gather, sleep
from logging import getLogger
from os import path as ospath, walk
from re import match as re_match, sub as re_sub
from time import time

from aioshutil import rmtree
from natsort import natsorted
from PIL import Image
from pyrogram import StopTransmission
from pyrogram.errors import BadRequest, FloodWait, RPCError

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:
    FloodPremiumWait = FloodWait
from aiofiles.os import (
    path as aiopath,
    remove,
    rename,
)
from pyrogram.types import (
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
)
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ....core.config_manager import Config
from ....core.tg_client import TgClient
from ...ext_utils.bot_utils import sync_to_async
from ...ext_utils.files_utils import (
    filter_for_strict_upload_modes,
    get_base_name,
    is_archive,
)
from ...ext_utils.status_utils import get_readable_file_size, get_readable_time
from ...telegram_helper.message_utils import send_message
from ...ext_utils.media_utils import (
    get_audio_thumbnail,
    get_document_type,
    get_media_info,
    get_multiple_frames_thumbnail,
    get_video_thumbnail,
    get_md5_hash,
    get_auto_thumbnail,
    download_auto_thumbnail,
)
from ...telegram_helper.message_utils import delete_message
from ...ext_utils.links_utils import is_telegram_link, is_url
from ...ext_utils.hyperul_utils import HypertgUpload


LOGGER = getLogger(__name__)


class TelegramUploader:
    def __init__(self, listener, path):
        self._last_uploaded = 0
        self._processed_bytes = 0
        self._listener = listener
        self._path = path
        self._client = None
        self._start_time = time()
        self._total_files = 0
        self._thumb = self._listener.thumb or f"thumbnails/{listener.user_id}.jpg"
        self._auto_thumbnail = self._listener.auto_thumbnail
        self._msgs_dict = {}
        self._corrupted = 0
        self._is_corrupted = False
        self._media_dict = {"videos": {}, "documents": {}}
        self._last_msg_in_group = False
        self._lprefix = ""
        self._lsuffix = ""
        self._lcaption = ""
        self._lfont = ""
        self._bot_pm = False
        self._media_group = False
        self._is_private = False
        self._sent_msg = None
        self._log_msg = None
        self._user_session = self._listener.user_transmission
        self._error = ""
        self._hu = None
        self._upload_seq = []
        self._msg_to_seq = {}
        self._sem = Semaphore(1)
        self.hyper_up = bool(
            Config.USE_HYPER
            and (
                len(TgClient.helper_bots) != 0
                or len(TgClient.helper_users) != 0
                or TgClient.user is not None
            )
        )

    async def _upload_progress(self, current, _):
        if self._listener.is_cancelled:
            if self._user_session:
                TgClient.user.stop_transmission()
            else:
                self._listener.client.stop_transmission()
        chunk_size = current - self._last_uploaded
        self._last_uploaded = current
        self._processed_bytes += chunk_size

    async def _user_settings(self):
        settings_map = {
            "MEDIA_GROUP": ("_media_group", False),
            "BOT_PM": ("_bot_pm", False),
            "LEECH_PREFIX": ("_lprefix", ""),
            "LEECH_SUFFIX": ("_lsuffix", ""),
            "LEECH_CAPTION": ("_lcaption", ""),
            "LEECH_FONT": ("_lfont", ""),
        }

        for key, (attr, default) in settings_map.items():
            setattr(
                self,
                attr,
                self._listener.user_dict.get(key) or getattr(Config, key, default),
            )

        # Normalize thumbnail source:
        # - If it's a direct HTTP/HTTPS URL, download it once and use the local file.
        # - If it's a local path and doesn't exist, drop it.
        if self._thumb is not None and self._thumb != "none":
            if is_url(self._thumb) and not is_telegram_link(self._thumb):
                try:
                    downloaded = await download_auto_thumbnail(self._thumb)
                    if downloaded and await aiopath.exists(downloaded):
                        self._thumb = downloaded
                    else:
                        self._thumb = None
                except Exception as e:
                    LOGGER.warning(
                        f"Failed to download custom thumbnail from URL {self._thumb}: {e}"
                    )
                    self._thumb = None
            elif not await aiopath.exists(self._thumb):
                self._thumb = None

    async def _msg_to_reply(self):
        if self._listener.up_dest:
            msg_link = (
                self._listener.message.link if self._listener.is_super_chat else ""
            )
            msg = f"""➲ <b><u>Leech Started :</u></b>
┃
┊ <b>User :</b> {self._listener.user.mention} ( #ID{self._listener.user_id} ){f"\n┊ <b>Message Link :</b> <a href='{msg_link}'>Click Here</a>" if msg_link else ""}
╰ <b>Source :</b> <a href='{self._listener.source_url}'>Click Here</a>"""
            try:
                await TgClient.bot.resolve_peer(self._listener.up_dest)
                self._log_msg = await TgClient.bot.send_message(
                    chat_id=self._listener.up_dest,
                    text=msg,
                    disable_web_page_preview=True,
                    message_thread_id=self._listener.chat_thread_id,
                    disable_notification=True,
                )
                self._sent_msg = self._log_msg
                if self._user_session:
                    self._sent_msg = await TgClient.user.get_messages(
                        chat_id=self._sent_msg.chat.id,
                        message_ids=self._sent_msg.id,
                    )
                else:
                    self._is_private = self._sent_msg.chat.type.name == "PRIVATE"

            except Exception as e:
                await self._listener.on_upload_error(str(e))
                return False

        elif self._user_session:
            self._sent_msg = await TgClient.user.get_messages(
                chat_id=self._listener.message.chat.id, message_ids=self._listener.mid
            )
            if self._sent_msg is None:
                self._sent_msg = await TgClient.user.send_message(
                    chat_id=self._listener.message.chat.id,
                    text="Deleted Cmd Message! Don't delete the cmd message again!",
                    disable_web_page_preview=True,
                    disable_notification=True,
                )
        else:
            self._sent_msg = self._listener.message
        if self._sent_msg is None:
            await self._listener.on_upload_error("Failed to get message for upload")
            return False
        return True

    async def _prepare_file(self, pre_file_, dirpath):
        cap_file_ = file_ = pre_file_
        lprefix = self._lprefix
        lsuffix = self._lsuffix
        lcaption = self._lcaption

        if lprefix:
            cap_file_ = lprefix.replace(r"\s", " ") + file_
            lprefix = re_sub(r"<.*?>", "", lprefix).replace(r"\s", " ")
            if not file_.startswith(lprefix):
                file_ = f"{lprefix}{file_}"

        if lsuffix:
            name, ext = ospath.splitext(cap_file_)
            cap_file_ = name + lsuffix.replace(r"\s", " ") + ext
            lsuffix = re_sub(r"<.*?>", "", lsuffix).replace(r"\s", " ")

        cap_mono = (
            f"<{Config.LEECH_FONT}>{cap_file_}</{Config.LEECH_FONT}>"
            if Config.LEECH_FONT
            else cap_file_
        )
        if lcaption:
            lcaption = re_sub(
                r"(\\\||\\\{|\\\}|\\s)",
                lambda m: {r"\|": "%%", r"\{": "&%&", r"\}": "$%$", r"\s": " "}[
                    m.group(0)
                ],
                lcaption,
            )

            parts = lcaption.split("|")
            parts[0] = re_sub(
                r"\{([^}]+)\}", lambda m: f"{{{m.group(1).lower()}}}", parts[0]
            )
            up_path = ospath.join(dirpath, pre_file_)
            dur, qual, lang, subs = await get_media_info(up_path, True)
            cap_mono = parts[0].format(
                filename=cap_file_,
                size=get_readable_file_size(await aiopath.getsize(up_path)),
                duration=get_readable_time(dur),
                quality=qual,
                languages=lang,
                subtitles=subs,
                md5_hash=await sync_to_async(get_md5_hash, up_path),
                mime_type=self._listener.file_details.get("mime_type", "text/plain"),
                prefilename=self._listener.file_details.get("filename", ""),
                precaption=self._listener.file_details.get("caption", ""),
            )

            for part in parts[1:]:
                args = part.split(":")
                cap_mono = cap_mono.replace(
                    args[0],
                    args[1] if len(args) > 1 else "",
                    int(args[2]) if len(args) == 3 else -1,
                )
            cap_mono = re_sub(
                r"%%|&%&|\$%\$",
                lambda m: {"%%": "|", "&%&": "{", "$%$": "}"}[m.group()],
                cap_mono,
            )

        if len(file_) > 56:
            if is_archive(file_):
                name = get_base_name(file_)
                ext = file_.split(name, 1)[1]
            elif match := re_match(r".+(?=\..+\.0*\d+$)|.+(?=\.part\d+\..+$)", file_):
                name = match.group(0)
                ext = file_.split(name, 1)[1]
            elif len(fsplit := ospath.splitext(file_)) > 1:
                name = fsplit[0]
                ext = fsplit[1]
            else:
                name = file_
                ext = ""
            if lsuffix:
                ext = f"{lsuffix}{ext}"
            name = name[: 56 - len(ext)]
            file_ = f"{name}{ext}"
        elif lsuffix:
            name, ext = ospath.splitext(file_)
            file_ = f"{name}{lsuffix}{ext}"

        old_path = ospath.join(dirpath, pre_file_)
        new_path = ospath.join(dirpath, file_)
        if old_path != new_path:
            await rename(old_path, new_path)

        return new_path, cap_mono

    def _get_input_media(self, subkey, key):
        rlist = []
        for msg in self._media_dict[key][subkey]:
            if key == "videos":
                input_media = InputMediaVideo(
                    media=msg.video.file_id, caption=msg.caption
                )
            else:
                input_media = InputMediaDocument(
                    media=msg.document.file_id, caption=msg.caption
                )
            rlist.append(input_media)
        return rlist

    async def _send_screenshots(self, dirpath, outputs):
        inputs = [
            InputMediaPhoto(ospath.join(dirpath, p), p.rsplit("/", 1)[-1])
            for p in outputs
        ]
        for i in range(0, len(inputs), 10):
            batch = inputs[i : i + 10]
            if Config.BOT_PM:
                await TgClient.bot.send_media_group(
                    chat_id=self._listener.user_id,
                    media=batch,
                    disable_notification=True,
                )
            self._sent_msg = (
                await self._sent_msg.reply_media_group(
                    media=batch,
                    quote=True,
                    disable_notification=True,
                )
            )[-1]

    async def _send_media_group(self, subkey, key, msgs):
        old_ids = [(m[0], m[1]) for m in msgs]
        for index, msg in enumerate(msgs):
            if self._listener.hybrid_leech or not self._user_session:
                msgs[index] = await self._listener.client.get_messages(
                    chat_id=msg[0], message_ids=msg[1]
                )
            else:
                msgs[index] = await TgClient.user.get_messages(
                    chat_id=msg[0], message_ids=msg[1]
                )
        msgs_list = await msgs[0].reply_to_message.reply_media_group(
            media=self._get_input_media(subkey, key),
            quote=True,
            disable_notification=True,
        )
        for msg in msgs:
            if msg.link in self._msgs_dict:
                del self._msgs_dict[msg.link]
            await delete_message(msg)
        self._media_dict[key].pop(subkey, None)
        if self._listener.is_super_chat or self._listener.up_dest:
            for m in msgs_list:
                self._msgs_dict[m.link] = m.caption
        for i, old_key in enumerate(old_ids):
            if old_key not in self._msg_to_seq or i >= len(msgs_list):
                continue
            seq_idx = self._msg_to_seq.pop(old_key)
            new_msg = msgs_list[i]
            self._upload_seq[seq_idx] = {
                "chat_id": new_msg.chat.id,
                "msg_id": new_msg.id,
                "link": new_msg.link,
                "file_": self._upload_seq[seq_idx]["file_"],
            }
            self._msg_to_seq[(new_msg.chat.id, new_msg.id)] = seq_idx
        self._sent_msg = msgs_list[-1]

    async def _attach_mediainfo(self, sent_msg, up_path, seq_idx):
        if not self._listener.user_dict.get("SHOW_MEDIAINFO_BUTTON", True):
            return
        try:
            from ....modules.mediainfo import (
                get_mediainfo_telegraph_link_from_path,
            )
            from ...telegram_helper.button_build import ButtonMaker

            if not await aiopath.exists(up_path):
                return
            file_size = await aiopath.getsize(up_path)
            telegraph_link = await get_mediainfo_telegraph_link_from_path(
                up_path, file_size
            )
            if not telegraph_link:
                return
            entry = self._upload_seq[seq_idx]
            if entry is not None:
                entry["telegraph_link"] = telegraph_link
            buttons = ButtonMaker()
            buttons.url_button("Media Info", telegraph_link)
            await sent_msg.edit_reply_markup(buttons.build_menu(1))
        except Exception as e:
            LOGGER.warning(f"Failed to add Media Info button: {e}")

    async def _upload_file_task(self, file_, f_path, dirpath, user_session, seq_idx):
        async with self._sem:
            up_path = None
            try:
                if self._listener.is_cancelled:
                    return None
                up_path, cap_mono = await self._prepare_file(file_, dirpath)
                self._last_uploaded = 0
                sent_msg = await self._upload_file(
                    cap_mono, up_path, file_, seq_idx, user_session=user_session
                )
                if self._listener.is_cancelled:
                    return None
                if sent_msg is not None:
                    await self._attach_mediainfo(sent_msg, up_path, seq_idx)
                return sent_msg
            except Exception as err:
                if isinstance(err, RetryError):
                    LOGGER.info(f"Total Attempts: {err.last_attempt.attempt_number}")
                    err = err.last_attempt.exception()
                LOGGER.error(f"{err}. Path: {f_path}", exc_info=True)
                self._error = str(err)
                self._corrupted += 1
                return None
            finally:
                path_to_clean = up_path or f_path
                if not self._listener.is_cancelled and await aiopath.exists(
                    path_to_clean
                ):
                    await remove(path_to_clean)

    async def _sequence_copies(self):
        leech_dests = [
            d.strip()
            for d in str(self._listener.leech_dest or "").split(",")
            if d.strip()
        ]
        for entry in self._upload_seq:
            if entry is None:
                continue
            if self._bot_pm:
                try:
                    dm_msg = await TgClient.bot.copy_message(
                        chat_id=self._listener.user_id,
                        from_chat_id=entry["chat_id"],
                        message_id=entry["msg_id"],
                        reply_to_message_id=(
                            self._listener.pm_msg.id if self._listener.pm_msg else None
                        ),
                    )
                    telegraph_link = entry.get("telegraph_link")
                    if dm_msg and telegraph_link:
                        from ...telegram_helper.button_build import ButtonMaker

                        buttons = ButtonMaker()
                        buttons.url_button("Media Info", telegraph_link)
                        await dm_msg.edit_reply_markup(buttons.build_menu(1))
                except Exception as err:
                    if not self._listener.is_cancelled:
                        LOGGER.error(f"Failed To Send in BotPM:\n{err}")
            for leech_dest in leech_dests:
                try:
                    leech_thread = None
                    if "|" in leech_dest:
                        leech_dest, leech_thread = leech_dest.split("|", 1)
                    if leech_dest.lstrip("-").isdigit():
                        leech_dest = int(leech_dest)
                    copy_kwargs = {
                        "chat_id": leech_dest,
                        "from_chat_id": entry["chat_id"],
                        "message_id": entry["msg_id"],
                    }
                    if leech_thread and leech_thread.lstrip("-").isdigit():
                        copy_kwargs["message_thread_id"] = int(leech_thread)
                    await TgClient.bot.copy_message(**copy_kwargs)
                except Exception as e:
                    if not self._listener.is_cancelled:
                        LOGGER.error(f"Failed to forward to {leech_dest}: {e}")
                        await send_message(
                            self._listener.user_id,
                            f"Failed to forward to {leech_dest}\n{e}",
                        )

    async def upload(self):
        await self._user_settings()
        (
            filtered_path,
            valid_count,
            filtered_count,
            skipped,
        ) = await filter_for_strict_upload_modes(self._path)
        if not filtered_path:
            msg = (
                "No File To Upload, All Files did not meet Upload Criteria. "
                f"Filtered files: {filtered_count}."
            )
            LOGGER.info(f"STRICT_UPLOAD_MODES: All files filtered: {self._path}")
            await self._listener.on_upload_error(msg)
            return
        self._path = filtered_path
        res = await self._msg_to_reply()
        if not res:
            return
        if self.hyper_up:
            self._hu = HypertgUpload(self)
            if not self._hu.num_clients:
                self._hu = None
                self.hyper_up = False
        self._sem = Semaphore(self._hu.num_clients if self._hu else 1)
        is_log_del = False
        upload_tasks = []
        seq_idx = 0

        def drop_pending():
            for t in upload_tasks:
                if not t.done():
                    t.cancel()

        for dirpath, _, files in natsorted(await sync_to_async(walk, self._path)):
            if dirpath.strip().endswith("/yt-dlp-thumb"):
                continue
            if dirpath.strip().endswith("_mltbss"):
                await self._send_screenshots(dirpath, files)
                await rmtree(dirpath, ignore_errors=True)
                continue
            for file_ in natsorted(files):
                self._error = ""
                f_path = ospath.join(dirpath, file_)
                if not await aiopath.exists(f_path):
                    LOGGER.error(f"{f_path} not exists! Continue uploading!")
                    continue
                try:
                    f_size = await aiopath.getsize(f_path)
                    self._total_files += 1
                    if f_size == 0:
                        LOGGER.error(
                            f"{f_path} size is zero, telegram don't upload zero size files"
                        )
                        self._corrupted += 1
                        continue
                    if self._listener.is_cancelled:
                        drop_pending()
                        return
                    if self._last_msg_in_group and self._hu is None:
                        group_lists = [
                            x for v in self._media_dict.values() for x in v.keys()
                        ]
                        match = re_match(r".+(?=\.\d+$)|.+(?=\.part\d+\..+$)", f_path)
                        if not match or match and match.group(0) not in group_lists:
                            for key, value in list(self._media_dict.items()):
                                for subkey, msgs in list(value.items()):
                                    if len(msgs) > 1:
                                        await self._send_media_group(subkey, key, msgs)
                    user_session = self._user_session
                    if self._listener.hybrid_leech and self._listener.user_transmission:
                        user_session = f_size > 2097152000
                        if self._hu is None:
                            self._user_session = user_session
                            client = (
                                TgClient.user
                                if user_session
                                else self._listener.client
                            )
                            self._sent_msg = await client.get_messages(
                                chat_id=self._sent_msg.chat.id,
                                message_ids=self._sent_msg.id,
                            )
                    self._last_msg_in_group = False
                    self._upload_seq.append(None)
                    task = ensure_future(
                        self._upload_file_task(
                            file_, f_path, dirpath, user_session, seq_idx
                        )
                    )
                    upload_tasks.append(task)
                    if self._hu is None:
                        await task
                    seq_idx += 1

                    if (
                        self._hu is None
                        and self._log_msg
                        and not is_log_del
                        and Config.CLEAN_LOG_MSG
                    ):
                        await delete_message(self._log_msg)
                        is_log_del = True
                    if self._listener.is_cancelled:
                        drop_pending()
                        return
                except Exception as err:
                    if isinstance(err, RetryError):
                        LOGGER.info(
                            f"Total Attempts: {err.last_attempt.attempt_number}"
                        )
                        err = err.last_attempt.exception()
                    LOGGER.error(f"{err}. Path: {f_path}", exc_info=True)
                    self._error = str(err)
                    self._corrupted += 1
                    if self._listener.is_cancelled:
                        drop_pending()
                        return
        if upload_tasks:
            results = await gather(*upload_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    LOGGER.error(f"Upload task error: {r}")
            await sleep(1)
        if self._log_msg and not is_log_del and Config.CLEAN_LOG_MSG:
            await delete_message(self._log_msg)
            is_log_del = True
        for key, value in list(self._media_dict.items()):
            for subkey, msgs in list(value.items()):
                if len(msgs) > 1:
                    try:
                        await self._send_media_group(subkey, key, msgs)
                    except Exception as e:
                        LOGGER.info(
                            f"While sending media group at the end of task. Error: {e}"
                        )
        if self._listener.is_cancelled:
            return
        await self._sequence_copies()
        if (
            self._listener.is_super_chat or self._listener.up_dest
        ) and not self._is_private:
            for entry in self._upload_seq:
                if entry is None or not entry["link"]:
                    continue
                if entry["link"] not in self._msgs_dict:
                    self._msgs_dict[entry["link"]] = entry["file_"]
        if self._total_files == 0:
            await self._listener.on_upload_error(
                "No files to upload. In case you have filled EXCLUDED_EXTENSIONS, then check if all files have those extensions or not."
            )
            return
        if self._total_files <= self._corrupted:
            await self._listener.on_upload_error(
                f"Files Corrupted or unable to upload. {self._error or 'Check logs!'}"
            )
            return
        LOGGER.info(f"Leech Completed: {self._listener.name}")
        await self._listener.on_upload_complete(
            None, self._msgs_dict, self._total_files, self._corrupted, skipped=skipped
        )
        return

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
    )
    async def _upload_file(
        self,
        cap_mono,
        up_path,
        file,
        seq_idx,
        force_document=False,
        user_session=False,
    ):
        thumb = None
        auto_thumb = None
        o_path = up_path
        self._is_corrupted = False
        sent_msg = None
        try:
            if not await aiopath.exists(up_path):
                LOGGER.error(f"File not found: {up_path}")
                self._is_corrupted = True
                return
            is_video, is_audio, is_image = await get_document_type(up_path)
            doc_mode = (
                self._listener.as_doc
                or force_document
                or (not is_video and not is_audio and not is_image)
            )
            key = (
                "documents"
                if doc_mode
                else "videos"
                if is_video
                else "audios"
                if is_audio
                else "photos"
            )

            # Credit - BeingXAnonymous
            if is_video and self._auto_thumbnail and Config.AUTO_THUMBNAIL:
                poster_url = await get_auto_thumbnail(file)
                if poster_url:
                    thumb = auto_thumb = await download_auto_thumbnail(poster_url)
            if (
                self._thumb is not None
                and not await aiopath.exists(self._thumb)
                and self._thumb != "none"
            ):
                self._thumb = None
            if thumb is None:
                thumb = self._thumb

            if self._hu is not None:
                if self._sent_msg is None:
                    await self._listener.on_upload_error("No message context for upload")
                    return
                sent_msg = await self._hu.upload(
                    up_path,
                    cap_mono,
                    self._sent_msg,
                    self._sent_msg.id,
                    force_document=force_document,
                    user_thumb=thumb,
                    user_session=user_session,
                )
                if self._listener.is_cancelled:
                    return
            else:
                if not doc_mode and not is_image and thumb is None:
                    file_name = ospath.splitext(file)[0]
                    thumb_path = f"{self._path}/yt-dlp-thumb/{file_name}.jpg"
                    if await aiopath.isfile(thumb_path):
                        thumb = thumb_path
                    elif await aiopath.isfile(thumb_path.replace("/yt-dlp-thumb", "")):
                        thumb = thumb_path.replace("/yt-dlp-thumb", "")
                    elif is_audio and not is_video:
                        thumb = await get_audio_thumbnail(up_path)

                if doc_mode:
                    key = "documents"
                    if self._listener.is_cancelled:
                        return
                    if thumb == "none":
                        thumb = None
                    if self._sent_msg is None:
                        await self._listener.on_upload_error("No message context for upload")
                        return
                    self._sent_msg = await self._sent_msg.reply_document(
                        document=up_path,
                        quote=True,
                        thumb=thumb,
                        caption=cap_mono,
                        force_document=True,
                        disable_notification=True,
                        progress=self._upload_progress,
                    )
                elif is_video:
                    key = "videos"
                    duration = (await get_media_info(up_path))[0]
                    if thumb is None and self._listener.thumbnail_layout:
                        thumb = await get_multiple_frames_thumbnail(
                            up_path,
                            self._listener.thumbnail_layout,
                            self._listener.screen_shots,
                        )
                    if thumb is None:
                        thumb = await get_video_thumbnail(up_path, duration)
                    if thumb is not None and thumb != "none":
                        with Image.open(thumb) as img:
                            width, height = img.size
                    else:
                        width = 480
                        height = 320
                    if self._listener.is_cancelled:
                        return
                    if thumb == "none":
                        thumb = None
                    if self._sent_msg is None:
                        await self._listener.on_upload_error("No message context for upload")
                        return
                    self._sent_msg = await self._sent_msg.reply_video(
                        video=up_path,
                        quote=True,
                        caption=cap_mono,
                        duration=duration,
                        width=width,
                        height=height,
                        video_cover=thumb,
                        supports_streaming=True,
                        disable_notification=True,
                        progress=self._upload_progress,
                    )
                elif is_audio:
                    key = "audios"
                    duration, artist, title = await get_media_info(up_path)
                    if self._listener.is_cancelled:
                        return
                    if thumb == "none":
                        thumb = None
                    if self._sent_msg is None:
                        await self._listener.on_upload_error("No message context for upload")
                        return
                    self._sent_msg = await self._sent_msg.reply_audio(
                        audio=up_path,
                        quote=True,
                        caption=cap_mono,
                        duration=duration,
                        performer=artist,
                        title=title,
                        thumb=thumb,
                        disable_notification=True,
                        progress=self._upload_progress,
                    )
                else:
                    key = "photos"
                    if self._listener.is_cancelled:
                        return
                    if self._sent_msg is None:
                        await self._listener.on_upload_error("No message context for upload")
                        return
                    self._sent_msg = await self._sent_msg.reply_photo(
                        photo=up_path,
                        quote=True,
                        caption=cap_mono,
                        disable_notification=True,
                        progress=self._upload_progress,
                    )

            if self._hu is None:
                sent_msg = self._sent_msg

            if sent_msg is not None:
                self._upload_seq[seq_idx] = {
                    "chat_id": sent_msg.chat.id,
                    "msg_id": sent_msg.id,
                    "link": sent_msg.link,
                    "file_": file,
                }
                self._msg_to_seq[(sent_msg.chat.id, sent_msg.id)] = seq_idx

            if (
                not self._listener.is_cancelled
                and self._media_group
                and sent_msg is not None
                and (sent_msg.video or sent_msg.document)
            ):
                key = "documents" if sent_msg.document else "videos"
                if match := re_match(r".+(?=\.0*\d+$)|.+(?=\.part\d+\..+$)", o_path):
                    pname = match.group(0)
                    if pname in self._media_dict[key].keys():
                        self._media_dict[key][pname].append(
                            [sent_msg.chat.id, sent_msg.id]
                        )
                    else:
                        self._media_dict[key][pname] = [
                            [sent_msg.chat.id, sent_msg.id]
                        ]
                    msgs = self._media_dict[key][pname]
                    if len(msgs) == 10:
                        self._media_dict[key].pop(pname, None)
                        await self._send_media_group(pname, key, msgs)
                    else:
                        self._last_msg_in_group = True

            if (
                self._thumb is None
                and thumb is not None
                and thumb != auto_thumb
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
            return sent_msg
        except StopTransmission:
            if (
                self._thumb is None
                and thumb is not None
                and thumb != auto_thumb
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
            LOGGER.info(f"Upload stopped: {up_path}")
            return None
        except (FloodWait, FloodPremiumWait) as f:
            LOGGER.warning(str(f))
            await sleep(f.value * 1.3)
            if (
                self._thumb is None
                and thumb is not None
                and thumb != auto_thumb
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
            return await self._upload_file(
                cap_mono,
                up_path,
                file,
                seq_idx,
                user_session=user_session,
            )
        except Exception as err:
            if (
                self._thumb is None
                and thumb is not None
                and thumb != auto_thumb
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
            err_type = "RPCError: " if isinstance(err, RPCError) else ""
            LOGGER.error(f"{err_type}{err}. Path: {up_path}", exc_info=True)
            if isinstance(err, BadRequest) and key != "documents":
                LOGGER.error(f"Retrying As Document. Path: {up_path}")
                return await self._upload_file(
                    cap_mono,
                    up_path,
                    file,
                    seq_idx,
                    force_document=True,
                    user_session=user_session,
                )
            raise err

    @property
    def speed(self):
        try:
            return self._processed_bytes / (time() - self._start_time)
        except ZeroDivisionError:
            return 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    async def close_hyper(self):
        if self._hu is not None:
            try:
                await self._hu.cancel()
            except Exception:
                pass
            self._hu = None

    async def cancel_task(self):
        self._listener.is_cancelled = True
        LOGGER.info(f"Cancelling Upload: {self._listener.name}")
        await self.close_hyper()
        await self._listener.on_upload_error("your upload has been stopped!")
