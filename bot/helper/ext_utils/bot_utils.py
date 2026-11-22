from asyncio import (
    create_subprocess_exec,
    create_subprocess_shell,
    run_coroutine_threadsafe,
    sleep,
)
from pyrogram.enums import ButtonStyle
from asyncio.subprocess import PIPE
from base64 import urlsafe_b64decode, urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
from hashlib import sha256
from hmac import new as hmac_new
from secrets import token_bytes

from niquests import AsyncSession

from ... import LOGGER, bot_loop, user_data
from ...core.config_manager import Config
from ..telegram_helper.button_build import ButtonMaker
from .help_messages import (
    CLONE_HELP_DICT,
    MIRROR_HELP_DICT,
    YT_HELP_DICT,
)
from .telegraph_helper import telegraph

_SERVICE_PWD_SALT = b"wzmlx_v3_service_pwd_salt"

_cached_secret_bytes = None


def _shared_secret():
    global _cached_secret_bytes
    secret = Config.WEB_ACCESS_PASSWORD
    if not secret:
        if _cached_secret_bytes is None:
            _cached_secret_bytes = token_bytes(32)
        return _cached_secret_bytes
    return secret.encode("utf-8") if isinstance(secret, str) else secret


def derive_service_password(bot_id, service):
    if not bot_id:
        bot_id = "0"
    secret = _shared_secret()
    digest = hmac_new(
        _SERVICE_PWD_SALT,
        f"{bot_id}:{service}".encode("utf-8"),
        sha256,
    )
    digest.update(secret)
    raw = digest.hexdigest()
    return raw[:20] + raw[-4:]


COMMAND_USAGE = {}

THREAD_POOL = ThreadPoolExecutor(max_workers=500)


class SetInterval:
    def __init__(self, interval, action, *args, **kwargs):
        self.interval = interval
        self.action = action
        self.task = bot_loop.create_task(self._set_interval(*args, **kwargs))

    async def _set_interval(self, *args, **kwargs):
        while True:
            await sleep(self.interval)
            await self.action(*args, **kwargs)

    def cancel(self):
        self.task.cancel()


def _build_command_usage(help_dict, command_key):
    buttons = ButtonMaker()
    cmd_list = list(help_dict.keys())[1:]
    cmd_pages = [cmd_list[i : i + 10] for i in range(0, len(cmd_list), 10)]
    temp_store = []

    for i, page in enumerate(cmd_pages):
        for name in page:
            buttons.data_button(name, f"help {command_key} {name} {i}")
        if len(cmd_pages) > 1:
            if i > 0:
                buttons.data_button("⫷", f"help pre {command_key} {i - 1}")
            if i < len(cmd_pages) - 1:
                buttons.data_button("⫸", f"help nex {command_key} {i + 1}")
        buttons.data_button("Close", "help close", "footer", style=ButtonStyle.DANGER)
        temp_store.append(buttons.build_menu(2))
        buttons.reset()

    COMMAND_USAGE[command_key] = [help_dict["main"], *temp_store]


def create_help_buttons():
    _build_command_usage(MIRROR_HELP_DICT, "mirror")
    _build_command_usage(YT_HELP_DICT, "yt")
    _build_command_usage(CLONE_HELP_DICT, "clone")


def bt_selection_buttons(id_, user_id):
    from .selection_pin_store import get_or_create_pin

    gid = id_[:12] if len(id_) > 25 else id_
    pin = get_or_create_pin(id_, user_id)
    buttons = ButtonMaker()
    if Config.WEB_PINCODE:
        buttons.url_button(
            "Select Files",
            f"{Config.BASE_URL}/app/files?gid={id_}",
            style=ButtonStyle.PRIMARY,
        )
        buttons.data_button(
            "Pincode", f"sel pin {gid} {pin}", style=ButtonStyle.PRIMARY
        )
    else:
        buttons.url_button(
            "Select Files",
            f"{Config.BASE_URL}/app/files?gid={id_}&pin={pin}",
            style=ButtonStyle.PRIMARY,
        )
    buttons.data_button(
        "Done Selecting", f"sel done {gid} {id_}", style=ButtonStyle.SUCCESS
    )
    buttons.data_button("Cancel", f"sel cancel {gid}", style=ButtonStyle.DANGER)
    return buttons.build_menu(2)


def terabox_selection_buttons(gid, user_id):
    from .selection_pin_store import get_or_create_pin

    pin = get_or_create_pin(gid, user_id)
    base_url = get_valid_base_url()
    buttons = ButtonMaker()
    if Config.WEB_PINCODE:
        buttons.url_button(
            "Select Files",
            f"{base_url}/app/files?gid={gid}&type=terabox",
            style=ButtonStyle.PRIMARY,
        )
        buttons.data_button(
            "Pincode", f"tsel pin {gid} {pin}", style=ButtonStyle.PRIMARY
        )
    else:
        buttons.url_button(
            "Select Files",
            f"{base_url}/app/files?gid={gid}&pin={pin}&type=terabox",
            style=ButtonStyle.PRIMARY,
        )
    buttons.data_button("Done Selecting", f"tsel done {gid}", style=ButtonStyle.SUCCESS)
    buttons.data_button("Cancel", f"tsel cancel {gid}", style=ButtonStyle.DANGER)
    return buttons.build_menu(2)


def get_valid_base_url():
    base_url = (Config.BASE_URL or "").strip().rstrip("/")
    if not base_url:
        return ""
    from urllib.parse import urlsplit

    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return base_url


def mega_selection_buttons(gid, user_id):
    from .selection_pin_store import get_or_create_pin

    pin = get_or_create_pin(gid, user_id)
    base_url = get_valid_base_url()
    buttons = ButtonMaker()
    if Config.WEB_PINCODE:
        buttons.url_button(
            "Select Files",
            f"{base_url}/app/files?gid={gid}&type=mega",
            style=ButtonStyle.PRIMARY,
        )
        buttons.data_button(
            "Pincode", f"sel pin {gid} {pin}", style=ButtonStyle.PRIMARY
        )
    else:
        buttons.url_button(
            "Select Files",
            f"{base_url}/app/files?gid={gid}&pin={pin}&type=mega",
            style=ButtonStyle.PRIMARY,
        )
    buttons.data_button(
        "Done Selecting", f"sel done {gid} {gid}", style=ButtonStyle.SUCCESS
    )
    buttons.data_button("Cancel", f"sel cancel {gid}", style=ButtonStyle.DANGER)
    return buttons.build_menu(2)


async def get_telegraph_list(telegraph_content):
    path = [
        (
            await telegraph.create_page(
                title="Downloader Zone Drive Search", content=content
            )
        )["path"]
        for content in telegraph_content
    ]
    if len(path) > 1:
        await telegraph.edit_telegraph(path, telegraph_content)
    buttons = ButtonMaker()
    buttons.url_button(
        "🔎 VIEW", f"https://telegra.ph/{path[0]}", style=ButtonStyle.SUCCESS
    )
    return buttons.build_menu(1)


def arg_parser(items, arg_base):
    if not items:
        return

    arg_start = -1
    i = 0
    total = len(items)

    bool_arg_set = {
        "-b",
        "-e",
        "-z",
        "-s",
        "-j",
        "-d",
        "-sv",
        "-ss",
        "-f",
        "-fd",
        "-fu",
        "-sync",
        "-hl",
        "-doc",
        "-med",
        "-ut",
        "-bt",
        "-vt",
    }
    disabled_args = set()
    if Config.DISABLE_BULK and "-b" in items:
        arg_base["-b"] = False

    if Config.DISABLE_MULTI and "-i" in items:
        arg_base["-i"] = 0

    if Config.DISABLE_SEED and "-d" in items:
        arg_base["-d"] = False
        disabled_args.add("-d")

    while i < total:
        part = items[i]

        if part in disabled_args:
            i += 1
            continue

        if part in arg_base:
            if arg_start == -1:
                arg_start = i

            if (
                i + 1 == total
                and part in bool_arg_set
                or part
                in [
                    "-s",
                    "-j",
                    "-f",
                    "-fd",
                    "-fu",
                    "-sync",
                    "-hl",
                    "-doc",
                    "-med",
                    "-ut",
                    "-bt",
                ]
            ):
                arg_base[part] = True
            else:
                sub_list = []
                for j in range(i + 1, total):
                    if items[j] in arg_base:
                        if part in bool_arg_set and not sub_list:
                            arg_base[part] = True
                            break
                        if not sub_list:
                            break
                        check = " ".join(sub_list).strip()
                        if check.startswith("[") and check.endswith("]"):
                            break
                        elif not check.startswith("["):
                            break
                    sub_list.append(items[j])
                if sub_list:
                    value = " ".join(sub_list)
                    if part == "-ff" and not value.strip().startswith("["):
                        arg_base[part].add(value)
                    else:
                        arg_base[part] = value
                    i += len(sub_list)

        i += 1

    if "link" in arg_base:
        link_items = items[:arg_start] if arg_start != -1 else items
        if link_items:
            arg_base["link"] = " ".join(link_items)


def get_size_bytes(size):
    size = size.lower()
    if "k" in size:
        size = int(float(size.split("k")[0]) * 1024)
    elif "m" in size:
        size = int(float(size.split("m")[0]) * 1048576)
    elif "g" in size:
        size = int(float(size.split("g")[0]) * 1073741824)
    elif "t" in size:
        size = int(float(size.split("t")[0]) * 1099511627776)
    else:
        size = 0
    return size


async def get_content_type(url):
    try:
        async with AsyncSession() as client:
            response = await client.head(url, allow_redirects=True)
            return response.headers.get("Content-Type")
    except Exception:
        return None


def update_user_ldata(id_, key, value):
    user_data.setdefault(id_, {})
    user_data[id_][key] = value


def encode_slink(string):
    return (urlsafe_b64encode(string.encode("ascii")).decode("ascii")).strip("=")


def decode_slink(b64_str):
    return urlsafe_b64decode(
        (b64_str.strip("=") + "=" * (-len(b64_str.strip("=")) % 4)).encode("ascii")
    ).decode("ascii")


async def cmd_exec(cmd, shell=False):
    if shell:
        proc = await create_subprocess_shell(cmd, stdout=PIPE, stderr=PIPE)
    else:
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await proc.communicate()
    try:
        stdout = stdout.decode().strip()
    except Exception:
        stdout = "Unable to decode the response!"
    try:
        stderr = stderr.decode().strip()
    except Exception:
        stderr = "Unable to decode the error!"
    return stdout, stderr, proc.returncode


def new_task(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        task = bot_loop.create_task(func(*args, **kwargs))
        return task

    return wrapper


async def sync_to_async(func, *args, wait=True, **kwargs):
    pfunc = partial(func, *args, **kwargs)
    future = bot_loop.run_in_executor(THREAD_POOL, pfunc)
    return await future if wait else future


def async_to_sync(func, *args, wait=True, **kwargs):
    future = run_coroutine_threadsafe(func(*args, **kwargs), bot_loop)
    return future.result() if wait else future


def loop_thread(func):
    @wraps(func)
    def wrapper(*args, wait=False, **kwargs):
        future = run_coroutine_threadsafe(func(*args, **kwargs), bot_loop)
        return future.result() if wait else future

    return wrapper


def parse_dest(value):
    if isinstance(value, int) or not value:
        return value, None
    chat, _, thread = str(value).partition("|")
    chat = chat.strip()
    thread = thread.strip()
    if chat.lstrip("-").isdigit():
        chat = int(chat)
    return chat, int(thread) if thread.isdigit() else None
