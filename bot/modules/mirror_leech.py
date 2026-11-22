import os
from base64 import b64encode
from re import match as re_match

from aiofiles.os import path as aiopath
from bot.core.config_manager import Config

from .. import DOWNLOAD_DIR, LOGGER, bot_loop, task_dict_lock
from ..helper.ext_utils.bot_utils import (
    COMMAND_USAGE,
    arg_parser,
    get_content_type,
    sync_to_async,
)
from ..helper.ext_utils.exceptions import DirectDownloadLinkException
from ..helper.ext_utils.links_utils import (
    is_gdrive_id,
    is_gdrive_link,
    is_mega_link,
    is_terabox_link,
    is_magnet,
    is_rclone_path,
    is_telegram_link,
    is_url,
)
from ..helper.ext_utils.task_manager import pre_task_check
from ..helper.listeners.task_listener import TaskListener
from ..helper.mirror_leech_utils.download_utils.aria2_download import (
    add_aria2_download,
)
from ..helper.mirror_leech_utils.download_utils.direct_downloader import (
    add_direct_download,
)
from ..helper.mirror_leech_utils.download_utils.direct_link_generator import (
    direct_link_generator,
)
from ..helper.mirror_leech_utils.download_utils.gd_download import add_gd_download
from ..helper.mirror_leech_utils.download_utils.jd_download import add_jd_download
from ..helper.mirror_leech_utils.download_utils.mega_download import add_mega_download
from bot.helper.mirror_leech_utils.download_utils.terabox_download import (
    add_terabox_download,
    add_terabox_account_download,
)
from ..helper.mirror_leech_utils.download_utils.qbit_download import add_qb_torrent
from ..helper.mirror_leech_utils.download_utils.rclone_download import (
    add_rclone_download,
)
from ..helper.mirror_leech_utils.download_utils.telegram_download import (
    TelegramDownloadHelper,
)
from ..helper.telegram_helper.message_utils import (
    auto_delete_message,
    delete_links,
    delete_message,
    get_tg_link_message,
    send_message,
)


class Mirror(TaskListener):
    def __init__(
        self,
        client,
        message,
        is_qbit=False,
        is_leech=False,
        is_jd=False,
        same_dir=None,
        bulk=None,
        multi_tag=None,
        options="",
        **kwargs,
    ):
        if same_dir is None:
            same_dir = {}
        if bulk is None:
            bulk = []
        self.message = message
        self.client = client
        self.multi_tag = multi_tag
        self.options = options
        self.same_dir = same_dir
        self.bulk = bulk
        super().__init__()
        self.is_qbit = is_qbit
        self.is_leech = is_leech
        self.is_jd = is_jd

    async def new_event(self):
        text = self.message.text.split("\n")
        input_list = text[0].split(" ")

        check_msg, check_button = await pre_task_check(self.message)
        if check_msg:
            await delete_links(self.message)
            await auto_delete_message(
                await send_message(self.message, check_msg, check_button)
            )
            return

        args = {
            "-doc": False,
            "-med": False,
            "-d": False,
            "-j": False,
            "-s": False,
            "-b": False,
            "-e": False,
            "-z": False,
            "-sv": False,
            "-ss": False,
            "-f": False,
            "-fd": False,
            "-fu": False,
            "-hl": False,
            "-bt": False,
            "-ut": False,
            "-i": 0,
            "-sp": 0,
            "link": "",
            "-n": "",
            "-m": "",
            "-meta": "",
            "-up": "",
            "-rcf": "",
            "-au": "",
            "-ap": "",
            "-h": "",
            "-t": "",
            "-ca": "",
            "-cv": "",
            "-ns": "",
            "-tl": "",
            "-ff": set(),
            "-vt": False,
        }

        arg_parser(input_list[1:], args)

        if Config.DISABLE_BULK and args.get("-b", False):
            await send_message(self.message, "Bulk downloads are currently disabled.")
            return

        if Config.DISABLE_MULTI and int(args.get("-i", 1)) > 1:
            await send_message(
                self.message,
                "Multi-downloads are currently disabled. Please try without the -i flag.",
            )
            return

        if Config.DISABLE_SEED and args.get("-d", False):
            await send_message(
                self.message,
                "Seeding is currently disabled. Please try without the -d flag.",
            )
            return

        if Config.DISABLE_FF_MODE and args.get("-ff"):
            await send_message(self.message, "FFmpeg commands are currently disabled.")
            return

        self.select = args["-s"]
        self.seed = args["-d"]
        self.name = args["-n"]
        self.requested_name = args["-n"]
        self.up_dest = args["-up"]
        self.rc_flags = args["-rcf"]
        self.link = args["link"]
        self.compress = args["-z"]
        self.extract = args["-e"]
        self.join = args["-j"]
        if not getattr(self, "returning_from_thumbnail", False):
            self.thumb = args["-t"]
        if "-t" in input_list and self.thumb == "":
            await self.request_thumbnail()
            return
        self.split_size = args["-sp"]
        self.sample_video = args["-sv"]
        self.screen_shots = args["-ss"]
        self.force_run = args["-f"]
        self.force_download = args["-fd"]
        self.force_upload = args["-fu"]
        self.convert_audio = args["-ca"]
        self.convert_video = args["-cv"]
        self.name_swap = args["-ns"]
        self.hybrid_leech = args["-hl"]
        self.thumbnail_layout = args["-tl"]
        self.video_tool = args["-vt"]
        self.as_doc = args["-doc"]
        self.as_med = args["-med"]
        self.folder_name = f"/{args['-m']}".rstrip("/") if len(args["-m"]) > 0 else ""
        self.bot_trans = args["-bt"]
        self.user_trans = args["-ut"]
        self.metadata_dict = args["-meta"] or getattr(self, "metadata_dict", "") or ""

        headers = args["-h"]
        is_bulk = args["-b"]

        bulk_start = 0
        bulk_end = 0
        ratio = None
        seed_time = None
        reply_to = None
        file_ = None
        session = ""

        try:
            self.multi = int(args["-i"])
        except Exception:
            self.multi = 0

        try:
            if args["-ff"]:
                if isinstance(args["-ff"], set):
                    self.ffmpeg_cmds = args["-ff"]
                else:
                    self.ffmpeg_cmds = eval(args["-ff"])
        except Exception as e:
            self.ffmpeg_cmds = None
            LOGGER.error(e)

        if not isinstance(self.seed, bool):
            dargs = self.seed.split(":")
            ratio = dargs[0] or None
            if len(dargs) == 2:
                seed_time = dargs[1] or None
            self.seed = True

        if not isinstance(is_bulk, bool):
            dargs = is_bulk.split(":")
            bulk_start = dargs[0] or 0
            if len(dargs) == 2:
                bulk_end = dargs[1] or 0
            is_bulk = True

        if not is_bulk:
            if self.multi > 0:
                if self.folder_name:
                    async with task_dict_lock:
                        if self.folder_name in self.same_dir:
                            self.same_dir[self.folder_name]["tasks"].add(self.mid)
                            for fd_name in self.same_dir:
                                if fd_name != self.folder_name:
                                    self.same_dir[fd_name]["total"] -= 1
                        elif self.same_dir:
                            self.same_dir[self.folder_name] = {
                                "total": self.multi,
                                "tasks": {self.mid},
                            }
                            for fd_name in self.same_dir:
                                if fd_name != self.folder_name:
                                    self.same_dir[fd_name]["total"] -= 1
                        else:
                            self.same_dir = {
                                self.folder_name: {
                                    "total": self.multi,
                                    "tasks": {self.mid},
                                }
                            }
                elif self.same_dir:
                    async with task_dict_lock:
                        for fd_name in self.same_dir:
                            self.same_dir[fd_name]["total"] -= 1
        else:
            await self.init_bulk(input_list, bulk_start, bulk_end, Mirror)
            return

        if len(self.bulk) != 0:
            del self.bulk[0]

        if self.video_tool:
            _sd_entry = (
                self.same_dir.get(self.folder_name, {}) if self.folder_name else {}
            )
            _stored_key = _sd_entry.get("vt_func_key")
            if _stored_key:
                self.vt_func_key = _stored_key
                confirmed = True
            else:
                from .video_tools import video_tool_pre_config

                confirmed = await video_tool_pre_config(self)
                if (
                    confirmed
                    and self.folder_name
                    and self.same_dir
                    and self.folder_name in self.same_dir
                ):
                    self.same_dir[self.folder_name]["vt_func_key"] = self.vt_func_key
            if not confirmed:
                await self.remove_from_same_dir()
                return

        await self.run_multi(input_list, Mirror)

        await self.get_tag(text)

        path = f"{DOWNLOAD_DIR}{self.mid}{self.folder_name}"

        if not self.link and (reply_to := self.message.reply_to_message):
            if reply_to.text:
                self.link = reply_to.text.split("\n", 1)[0].strip()
        if is_telegram_link(self.link):
            try:
                reply_to, session = await get_tg_link_message(self.link)
            except Exception as e:
                await send_message(self.message, f"ERROR: {e}")
                await self.remove_from_same_dir()
                await delete_links(self.message)
                return

        if isinstance(reply_to, list):
            self.bulk = reply_to
            b_msg = input_list[:1]
            self.options = " ".join(input_list[1:])
            b_msg.append(f"{self.bulk[0]} -i {len(self.bulk)} {self.options}")
            nextmsg = await send_message(self.message, " ".join(b_msg))
            nextmsg = await self.client.get_messages(
                chat_id=self.message.chat.id, message_ids=nextmsg.id
            )
            if self.message.from_user:
                nextmsg.from_user = self.user
            else:
                nextmsg.sender_chat = self.user
            await Mirror(
                self.client,
                nextmsg,
                self.is_qbit,
                self.is_leech,
                self.is_jd,
                self.same_dir,
                self.bulk,
                self.multi_tag,
                self.options,
            ).new_event()
            return

        if reply_to:
            file_ = (
                reply_to.document
                or reply_to.photo
                or reply_to.video
                or reply_to.audio
                or reply_to.voice
                or reply_to.video_note
                or reply_to.sticker
                or reply_to.animation
                or None
            )
            self.file_details = {"caption": reply_to.caption}

            if file_ is None:
                if reply_text := reply_to.text:
                    self.link = reply_text.split("\n", 1)[0].strip()
                else:
                    reply_to = None
            elif reply_to.document and (
                file_.mime_type == "application/x-bittorrent"
                or file_.file_name.endswith((".torrent", ".dlc"))
            ):
                self.link = await reply_to.download()
                file_ = None

        if (
            not self.link
            and file_ is None
            or is_telegram_link(self.link)
            and reply_to is None
            or file_ is None
            and not is_url(self.link)
            and not is_magnet(self.link)
            and not await aiopath.exists(self.link)
            and not is_rclone_path(self.link)
            and not is_gdrive_id(self.link)
            and not is_gdrive_link(self.link)
            and not is_mega_link(self.link)
            and self.link != "tbx"
        ):
            await send_message(
                self.message, COMMAND_USAGE["mirror"][0], COMMAND_USAGE["mirror"][1]
            )
            await self.remove_from_same_dir()
            await delete_links(self.message)
            return

        if len(self.link) > 0 and not is_terabox_link(self.link):
            LOGGER.info(self.link)

        if isinstance(self.link, str) and is_mega_link(self.link):
            blocked = False
            blocked_message = "Mega Downloads Are Currently Disabled."
            if Config.DISABLE_MEGA:
                blocked = True
                await send_message(self.message, blocked_message)
            elif self.is_jd:
                blocked = True
                await send_message(self.message, blocked_message)
            if blocked:
                await self.remove_from_same_dir()
                await delete_links(self.message)
                return

        try:
            await self.before_start()
        except Exception as e:
            await send_message(self.message, e)
            await self.remove_from_same_dir()
            await delete_links(self.message)
            return

        self._set_mode_engine()

        if (
            not self.is_jd
            and not self.is_qbit
            and not is_magnet(self.link)
            and not is_rclone_path(self.link)
            and not is_gdrive_link(self.link)
            and not self.link.endswith(".torrent")
            and file_ is None
            and not is_gdrive_id(self.link)
            and not is_mega_link(self.link)
            and not is_terabox_link(self.link)
            and not self.is_terabox_account
        ):
            content_type = await get_content_type(self.link)
            if content_type is None or re_match(r"text/html|text/plain", content_type):
                try:
                    self.link = await sync_to_async(direct_link_generator, self.link)
                    if isinstance(self.link, tuple):
                        self.link, headers = self.link
                    elif isinstance(self.link, str):
                        LOGGER.info(f"Generated link: {self.link}")
                except DirectDownloadLinkException as e:
                    e = str(e)
                    if "This link requires a password!" not in e:
                        LOGGER.info(e)
                    if e.startswith("ERROR:"):
                        await send_message(self.message, e)
                        await self.remove_from_same_dir()
                        await delete_links(self.message)
                        return
                except Exception as e:
                    await send_message(self.message, e)
                    await self.remove_from_same_dir()
                    await delete_links(self.message)
                    return

        await self.send_processing()
        try:
            await delete_links(self.message)
            if file_ is not None:
                await TelegramDownloadHelper(self).add_download(
                    reply_to, f"{path}/", session
                )
            elif isinstance(self.link, dict):
                await add_direct_download(self, path)
            elif self.is_jd:
                await add_jd_download(self, path)
            elif self.is_qbit:
                await add_qb_torrent(self, path, ratio, seed_time)
            elif is_rclone_path(self.link):
                await add_rclone_download(self, f"{path}/")
            elif is_gdrive_link(self.link) or is_gdrive_id(self.link):
                await add_gd_download(self, path)
            elif is_mega_link(self.link):
                await add_mega_download(self, f"{path}/")
            elif self.is_terabox_account:
                await add_terabox_account_download(self, f"{path}/")
            elif is_terabox_link(self.link):
                await add_terabox_download(self, f"{path}/")
            else:
                ussr = args["-au"]
                pssw = args["-ap"]
                if ussr or pssw:
                    auth = f"{ussr}:{pssw}"
                    headers += f" authorization: Basic {b64encode(auth.encode()).decode('ascii')}"
                await add_aria2_download(self, path, headers, ratio, seed_time)
        finally:
            await self.remove_processing()


async def _mirror_request_thumbnail(self, timeout: int = 60):
    """Request user to upload a thumbnail image when -t is provided without URL.

    If the user does not send a valid image within `timeout` seconds,
    the request is cancelled and the task does not proceed.
    """
    self.returning_from_thumbnail = True
    self.original_message = self.message

    msg = await send_message(
        self.message,
        "You've used the `-t` flag without providing an image URL.\n\n"
        f"Please send an image that will be used as thumbnail within {timeout} seconds.\n\n"
        "If you don't respond in time, this task will be cancelled.",
    )

    self.thumb_request_msg_id = msg.id

    from ..helper.ext_utils.task_manager import thumbnail_waiters

    async with task_dict_lock:
        thumbnail_waiters[self.user_id] = self

    async def _timeout_watcher():
        from asyncio import sleep

        await sleep(timeout)
        async with task_dict_lock:
            # If user already replied and we were removed, do nothing
            if thumbnail_waiters.get(self.user_id) is not self:
                return
            # Timed out: clean up waiter entry
            thumbnail_waiters.pop(self.user_id, None)

        # Delete the original thumbnail request message, if it still exists
        try:
            if hasattr(self, "thumb_request_msg_id") and self.thumb_request_msg_id:
                # msg is the thumbnail request we just sent above
                await delete_message(msg)
        except Exception as e:
            LOGGER.error(f"Error deleting thumbnail request message on timeout: {e}")

        # Inform user and do not proceed with the task
        try:
            # Reply to the original command message
            await send_message(
                self.original_message,
                "Thumbnail upload timed out. Task has been cancelled.\n\n"
                "Please send the command again if you still want to run it.",
            )
        except Exception as e:
            LOGGER.error(f"Error sending thumbnail timeout message: {e}")

    # Run timeout watcher in background
    bot_loop.create_task(_timeout_watcher())


# Attach as a method of Mirror so instances can call `self.request_thumbnail()`
Mirror.request_thumbnail = _mirror_request_thumbnail


async def mirror(client, message):
    bot_loop.create_task(Mirror(client, message).new_event())


async def qb_mirror(client, message):
    bot_loop.create_task(Mirror(client, message, is_qbit=True).new_event())


async def jd_mirror(client, message):
    bot_loop.create_task(Mirror(client, message, is_jd=True).new_event())


async def leech(client, message):
    if Config.DISABLE_LEECH:
        await message.reply("The Leech command is currently disabled.")
        return
    bot_loop.create_task(Mirror(client, message, is_leech=True).new_event())


async def qb_leech(client, message):
    bot_loop.create_task(
        Mirror(client, message, is_qbit=True, is_leech=True).new_event()
    )


async def jd_leech(client, message):
    bot_loop.create_task(Mirror(client, message, is_leech=True, is_jd=True).new_event())


async def handle_thumbnail_upload(client, message):
    """Handle when a user uploads a thumbnail in response to the request"""
    user_id = message.from_user.id

    from ..helper.ext_utils.task_manager import thumbnail_waiters

    async with task_dict_lock:
        if user_id not in thumbnail_waiters:
            return

        mirror_obj = thumbnail_waiters[user_id]

        thumbnail_waiters.pop(user_id)
    if message.photo:
        os.makedirs("thumbnails", exist_ok=True)

        file_id = f"{user_id}.jpg"
        thumb_path = f"thumbnails/{file_id}"

        await message.download(file_name=thumb_path)

        mirror_obj.thumb = thumb_path
        status_msg = await send_message(
            message,
            "✅ Thumbnail set successfully! Continuing with your request...",
        )

        from ..helper.telegram_helper.message_utils import auto_delete_message

        await auto_delete_message(status_msg, stime=5)

        try:
            await client.delete_messages(
                chat_id=message.chat.id, message_ids=message.id
            )
        except Exception as e:
            LOGGER.error(f"Error deleting user's thumbnail image message: {e}")
        if hasattr(mirror_obj, "thumb_request_msg_id"):
            try:
                await client.delete_messages(
                    chat_id=message.chat.id, message_ids=mirror_obj.thumb_request_msg_id
                )
            except Exception as e:
                LOGGER.error(f"Error deleting thumbnail request message: {e}")
        if (
            hasattr(mirror_obj, "original_message")
            and mirror_obj.original_message.chat.id == message.chat.id
        ):
            try:
                pass
            except Exception as e:
                LOGGER.error(f"Error deleting original message: {e}")
        mirror_obj.message = mirror_obj.original_message
        mirror_obj.thumb = thumb_path

        mirror_obj.returning_from_thumbnail = True

        if hasattr(mirror_obj, "yt_obj"):
            mirror_obj.yt_obj.thumb = thumb_path
            mirror_obj.yt_obj.returning_from_thumbnail = True
            mirror_obj.yt_obj.message = mirror_obj.original_message
            await mirror_obj.yt_obj.new_event()
        else:
            await mirror_obj.new_event()
    else:
        await send_message(
            message,
            "❌ That's not a valid image. Please send an image file to use as thumbnail.",
        )
