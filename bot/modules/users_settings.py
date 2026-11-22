from asyncio import sleep
from functools import partial
from html import escape
from io import BytesIO
from os import getcwd
from re import sub
from time import time
from pyrogram.enums import ButtonStyle
from aiofiles.os import makedirs, remove
from aiofiles.os import path as aiopath
from langcodes import Language
from pyrogram.filters import create
from pyrogram.handlers import MessageHandler

from bot.helper.ext_utils.status_utils import get_readable_file_size

from .. import auth_chats, excluded_extensions, sudo_users, user_data
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import (
    new_task,
    update_user_ldata,
)
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.media_utils import create_thumb
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_file,
    send_message,
)

handler_dict = {}

leech_options = [
    "THUMBNAIL",
    "LEECH_DUMP_CHAT",
    "LEECH_PREFIX",
    "LEECH_SUFFIX",
    "LEECH_CAPTION",
    "THUMBNAIL_LAYOUT",
    "AUTO_THUMBNAIL",
    "SHOW_MEDIAINFO_BUTTON",
]
rclone_options = ["RCLONE_CONFIG", "RCLONE_PATH", "RCLONE_FLAGS"]
gdrive_options = ["TOKEN_PICKLE", "GDRIVE_ID", "INDEX_URL"]
gofile_options = ["GOFILE_TOKEN", "GOFILE_FOLDER_ID"]
pixeldrain_options = ["PIXELDRAIN_KEY"]
buzzheavier_options = ["BUZZHEAVIER_TOKEN", "BUZZHEAVIER_FOLDER_ID"]
devuploads_options = ["DEVUPLOADS_API_KEY"]
vikingfile_options = ["VIKINGFILE_USER"]
terabox_options = ["TERABOX_COOKIE"]
ffset_options = ["FFMPEG_CMDS", "METADATA"]
advanced_options = [
    "EXCLUDED_EXTENSIONS",
    "NAME_SWAP",
    "YT_DLP_OPTIONS",
    "UPLOAD_PATHS",
    "USER_COOKIE_FILE",
]

user_settings_text = {
    "THUMBNAIL": (
        "Photo or Doc",
        "Custom Thumbnail is used as the thumbnail for the files you upload to telegram in media or document mode.",
        "<i>Send a photo to save it as custom thumbnail.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "RCLONE_CONFIG": (
        "",
        "",
        "<i>Send your <code>rclone.conf</code> file to use as your Upload Dest to RClone.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "TOKEN_PICKLE": (
        "",
        "",
        "<i>Send your <code>token.pickle</code> to use as your Upload Dest to GDrive</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "TERABOX_COOKIE": (
        "File",
        "Your TeraBox session cookie. Lets you upload finished tasks to your own TeraBox account with `-up tbx`.",
        """<i>Send your <code>terabox.txt</code> cookie export (a browser \u201cGet cookies.txt\u201d export of your logged-in TeraBox session) to upload to your personal TeraBox account.</i>

Then mirror with <code>-up tbx</code>, or set TeraBox as your default upload.""",
    ),
    "LEECH_DUMP_CHAT": (
        "",
        "",
        """Send leech destination ID/USERNAME/PM. 
* b:id/@username/pm (b: means leech by bot) (id or username of the chat or write pm means private message so bot will send the files in private to you) when you should use b:(leech by bot)? When your default settings is leech by user and you want to leech by bot for specific task.
* u:id/@username(u: means leech by user) This incase OWNER added USER_STRING_SESSION.
* h:id/@username(hybrid leech) h: to upload files by bot and user based on file size.
* id/@username┊topic_id(leech in specific chat and topic) add ┊ without space and write topic id after chat id or username.
You can set up to 3 destinations by separating them with commas.
Example: -100111, -100222, -100333
Bot will forward uploaded files to all destinations.
⚠️ Make sure to add the Bot as Admin in all the destinations.
╰ <b>Time Left :</b> <code>60 sec</code>""",
    ),
    "LEECH_PREFIX": (
        "",
        "",
        "Send Leech Filename Prefix. You can add HTML tags. Example: <code>@mychannel</code>.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_SUFFIX": (
        "",
        "",
        "Send Leech Filename Suffix. You can add HTML tags. Example: <code>@mychannel</code>.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "LEECH_CAPTION": (
        "",
        "",
        "Send Leech Caption. You can add HTML tags. Example: <code>@mychannel</code>.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "THUMBNAIL_LAYOUT": (
        "",
        "",
        "Send thumbnail layout (widthxheight, 2x2, 3x3, 2x4, 4x4, ...). Example: 3x3.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "RCLONE_PATH": (
        "",
        "",
        "Send Rclone Path. If you want to use your rclone config edit using owner/user config from usetting or add mrcc: before rclone path. Example mrcc:remote:folder. </i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "RCLONE_FLAGS": (
        "",
        "",
        "key:value┊key┊key┊key:value . Check here all <a href='https://rclone.org/flags/'>RcloneFlags</a>\nEx: --buffer-size:8M┊--drive-starred-only",
    ),
    "GDRIVE_ID": (
        "",
        "",
        "Send Gdrive ID. If you want to use your token.pickle edit using owner/user token from usetting or add mtp: before the id. Example: mtp:F435RGGRDXXXXXX . </i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "INDEX_URL": (
        "",
        "",
        "Send Index URL for your gdrive option. </i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "GOFILE_TOKEN": (
        "String",
        "GoFile API Token",
        "<i>Send your GoFile Account Token (API Token).</i> Get it from <a href='https://gofile.io/myprofile'>GoFile Profile</a>.\n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "PIXELDRAIN_KEY": (
        "String",
        "PixelDrain API Key",
        "<i>Send your PixelDrain API Key.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "GOFILE_FOLDER_ID": (
        "String",
        "GoFile Folder ID",
        "<i>Send your GoFile Folder ID.</i> (Optional, leave empty to upload to root folder.)\n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "BUZZHEAVIER_TOKEN": (
        "String",
        "BuzzHeavier API Token",
        "<i>Send your BuzzHeavier Account Token (API Token / Account ID).</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "BUZZHEAVIER_FOLDER_ID": (
        "String",
        "BuzzHeavier Folder ID",
        "<i>Send your BuzzHeavier Folder ID.</i> \n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "DEVUPLOADS_API_KEY": (
        "String",
        "DevUploads API Key",
        "<i>Send your DevUploads API Key.</i>\n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "VIKINGFILE_USER": (
        "String",
        "VikingFile User Hash",
        "<i>Send your VikingFile user hash.</i> (Optional: leave empty for anonymous uploads)\n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "UPLOAD_PATHS": (
        "",
        "",
        "Send Dict of keys that have path values. Example: {'path 1': 'remote:rclonefolder', 'path 2': 'gdrive1 id', 'path 3': 'tg chat id', 'path 4': 'mrcc:remote:', 'path 5': b:@username} . </i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "EXCLUDED_EXTENSIONS": (
        "",
        "",
        "Send exluded extenions seperated by space without dot at beginning. </i> \n╰ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "NAME_SWAP": (
        "",
        "",
        """<i>Send your Name Swap. You can add pattern instead of normal text according to the format.</i>
<b>Full Documentation Guide</b> <a href="https://t.me/WZML_X/77">Click Here</a>
╰ <b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "YT_DLP_OPTIONS": (
        "",
        "",
        """Format: {key: value, key: value, key: value}.
Example: {"format": "bv*+mergeall[vcodec=none]", "nocheckcertificate": True, "playliststart": 10, "fragment_retries": float("inf"), "matchtitle": "S13", "writesubtitles": True, "live_from_start": True, "postprocessor_args": {"ffmpeg": ["-threads", "4"]}, "wait_for_video": (5, 100), "download_ranges": [{"start_time": 0, "end_time": 10}]}
Check all yt-dlp api options from this <a href='https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py#L184'>FILE</a> or use this <a href='https://t.me/mltb_official_channel/177'>script</a> to convert cli arguments to api options.

<i>Send dict of YT-DLP Options according to format.</i> \n╰ <b>Time Left :</b> <code>60 sec</code>""",
    ),
    "FFMPEG_CMDS": (
        "",
        "",
        """Dict of list values of ffmpeg commands. You can set multiple ffmpeg commands for all files before upload. Don't write ffmpeg at beginning, start directly with the arguments.
Examples: {"subtitle": ["-i mltb.mkv -c copy -c:s srt mltb.mkv", "-i mltb.video -c copy -c:s srt mltb"], "convert": ["-i mltb.m4a -c:a libmp3lame -q:a 2 mltb.mp3", "-i mltb.audio -c:a libmp3lame -q:a 2 mltb.mp3"], extract: ["-i mltb -map 0:a -c copy mltb.mka -map 0:s -c copy mltb.srt"]}
Notes:
- Add `-del` to the list which you want from the bot to delete the original files after command run complete!
- To execute one of those lists in bot for example, you must use -ff subtitle (list key) or -ff convert (list key)
Here I will explain how to use mltb.* which is reference to files you want to work on.
1. First cmd: the input is mltb.mkv so this cmd will work only on mkv videos and the output is mltb.mkv also so all outputs is mkv. -del will delete the original media after complete run of the cmd.
2. Second cmd: the input is mltb.video so this cmd will work on all videos and the output is only mltb so the extenstion is same as input files.
3. Third cmd: the input in mltb.m4a so this cmd will work only on m4a audios and the output is mltb.mp3 so the output extension is mp3.
4. Fourth cmd: the input is mltb.audio so this cmd will work on all audios and the output is mltb.mp3 so the output extension is mp3.

<i>Send dict of FFMPEG_CMDS Options according to format.</i> \n⏱ <b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "METADATA_CMDS": (
        "",
        "",
        """<i>Send your Meta data. You can according to the format title="Join @WZML_X".</i>
<b>Full Documentation Guide</b> <a href="https://t.me/WZML_X/">Click Here</a>
⏱ <b>Time Left :</b> <code>60 sec</code>
""",
    ),
    "METADATA": (
        "🏷 Stream-Targeted Metadata (all:/v:/a:/s: prefixes)",
        "Apply metadata to all media files with stream targeting support.",
        """<i>📝 Send metadata with stream prefixes (newline-separated):</i>

<b>Format:</b>
<code>all:key=value
g:key=value
v:key=value
a:key=value
s:key=value</code>

<b>Stream Prefixes:</b>
• <code>all:</code> - Apply to all streams (General metadata)
• <code>g:</code> - General (global) metadata
• <code>v:</code> - Video stream only
• <code>a:</code> - Audio stream only
• <code>s:</code> - Subtitle stream only
• No prefix → General metadata

<b>🔧 Dynamic Variables:</b>
• <code>{filename}</code> - Original filename
• <code>{basename}</code> - Name without extension
• <code>{extension}</code> - File extension
• <code>{audiolang}</code> - Audio language
• <code>{sublang}</code> - Subtitle language
• <code>{year}</code> - Year from filename

<b>📋 Examples:</b>
<code>all:title={basename}
all:year={year}
all:comment=Uploaded via Bot
v:title=HD Version
a:language={audiolang}</code>

<i>Or single line with pipe separators (legacy):</i>
<code>title={basename}|artist={audiolang}|year={year}</code>

⏱ <b>Time Left :</b> <code>60 sec</code>""",
    ),
    "USER_COOKIE_FILE": (
        "File",
        "User's YT-DLP Cookie File to authenticate access to websites and youtube.",
        "<i>Send your cookie file (e.g., cookies.txt).</i> \n⏱ <b>Time Left :</b> <code>60 sec</code>",
    ),
    "SHOW_MEDIAINFO_BUTTON": (
        "Boolean",
        "Show or hide the 'Media Info' button under every uploaded file.",
        "<i>Send true/false to enable or disable the Media Info button under uploaded files.</i>\n┖ <b>Time Left :</b> <code>60 sec</code>",
    ),
}


async def get_user_settings(from_user, stype="main"):
    user_id = from_user.id
    user_name = from_user.mention(style="html")
    buttons = ButtonMaker()
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"
    user_dict = user_data.get(user_id, {})

    if stype == "main":
        buttons.data_button(
            "General Settings", f"userset {user_id} general", position="header"
        )
        buttons.data_button("Mirror Settings", f"userset {user_id} mirror")
        buttons.data_button("Leech Settings", f"userset {user_id} leech")
        buttons.data_button("Metadata Settings", f"userset {user_id} ffset")
        buttons.data_button(
            "Misc Settings", f"userset {user_id} advanced", position="l_body"
        )

        if user_dict and any(
            key in user_dict
            for key in list(user_settings_text.keys())
            + [
                "USER_TOKENS",
                "AS_DOCUMENT",
                "EQUAL_SPLITS",
                "MEDIA_GROUP",
                "STOP_DUPLICATE",
                "DEFAULT_UPLOAD",
            ]
        ):
            buttons.data_button(
                "Reset All",
                f"userset {user_id} reset all",
                position="footer",
                style=ButtonStyle.DANGER,
            )
        buttons.data_button("Close", f"userset {user_id} close", position="footer")

        text = f"""⌬ <b>User Settings :</b>

╭ <b>Name</b> → {user_name}
┊ <b>UserID</b> → #ID{user_id}
┊ <b>Username</b> → @{from_user.username}
┊ <b>Telegram DC</b> → {from_user.dc_id}
╰ <b>Telegram Lang</b> → {Language.get(lc).display_name() if (lc := from_user.language_code) else "N/A"}"""

        btns = buttons.build_menu(2)

    elif stype == "general":
        if user_dict.get("DEFAULT_UPLOAD", ""):
            default_upload = user_dict["DEFAULT_UPLOAD"]
        elif "DEFAULT_UPLOAD" not in user_dict:
            default_upload = Config.DEFAULT_UPLOAD

        # Normalize unexpected values to supported ones
        if default_upload not in [
            "gd",
            "rc",
            "gofile",
            "pixeldrain",
            "buzzheavier",
            "devuploads",
            "vikingfile",
            "tb",
        ]:
            default_upload = "gd"

        # Human-readable label for current default
        if default_upload == "gd":
            du = "GDRIVE API"
        elif default_upload == "rc":
            du = "RCLONE"
        elif default_upload == "gofile":
            du = "GOFILE"
        elif default_upload == "pixeldrain":
            du = "PIXELDRAIN"
        elif default_upload == "buzzheavier":
            du = "BUZZHEAVIER"
        elif default_upload == "devuploads":
            du = "DEVUPLOADS"
        elif default_upload == "tb":
            du = "TERABOX"
        else:
            du = "VIKINGFILE"

        # Build swap buttons: cycle through primary upload modes
        # First button toggles between GD and RC
        if default_upload == "gd":
            buttons.data_button(
                "Swap to RCLONE Mode",
                f"userset {user_id} gd_rc general",
            )
        elif default_upload == "rc":
            buttons.data_button(
                "Swap to GDRIVE API Mode",
                f"userset {user_id} rc_gd general",
            )
        else:
            # From any non-gd/rc mode, offer swap to GD
            buttons.data_button(
                "Swap to GDRIVE API Mode",
                f"userset {user_id} {default_upload}_gd general",
            )

        # Second button cycles between gofile, pixeldrain, buzzheavier, devuploads, vikingfile, tb
        if default_upload in [
            "gofile",
            "pixeldrain",
            "buzzheavier",
            "devuploads",
            "vikingfile",
            "tb",
        ]:
            next_map = {
                "gofile": "pixeldrain",
                "pixeldrain": "buzzheavier",
                "buzzheavier": "devuploads",
                "devuploads": "vikingfile",
                "vikingfile": "tb",
                "tb": "gofile",
            }
            target = next_map[default_upload]
            label_map = {
                "gofile": "GOFILE",
                "pixeldrain": "PIXELDRAIN",
                "buzzheavier": "BUZZHEAVIER",
                "devuploads": "DEVUPLOADS",
                "vikingfile": "VIKINGFILE",
                "tb": "TERABOX",
            }
            buttons.data_button(
                f"Swap to {label_map[target]} Mode",
                f"userset {user_id} {default_upload}_{target} general",
            )
        else:
            # When not currently in one of these, offer swap to GOFILE (first in cycle)
            buttons.data_button(
                "Swap to GOFILE Mode",
                f"userset {user_id} {default_upload}_gofile general",
            )

        user_tokens = user_dict.get("USER_TOKENS", False)
        tr = "USER" if user_tokens else "OWNER"
        trr = "OWNER" if user_tokens else "USER"
        buttons.data_button(
            f"Swap to {trr} token/config",
            f"userset {user_id} tog USER_TOKENS {'f' if user_tokens else 't'}",
        )

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        def_cookies = user_dict.get("USE_DEFAULT_COOKIE", False)
        cookie_mode = "Owner's Cookie" if def_cookies else "User's Cookie"
        buttons.data_button(
            f"Swap to {'OWNER' if not def_cookies else 'USER'}'s Cookie File",
            f"userset {user_id} tog USE_DEFAULT_COOKIE {'f' if def_cookies else 't'}",
        )
        btns = buttons.build_menu(1)

        text = f"""⌬ <b>General Settings :</b>
╭ <b>Name</b> → {user_name}
┊ <b>Default Upload Package</b> → <b>{du}</b>
┊ <b>Default Usage Mode</b> → <b>{tr}'s</b> token/config
╰ <b>YT Cookie Mode</b> → <b>{cookie_mode}</b>
"""

    elif stype == "leech":
        thumbpath = f"thumbnails/{user_id}.jpg"
        buttons.data_button("Thumbnail", f"userset {user_id} menu THUMBNAIL")
        thumbmsg = "Exists" if await aiopath.exists(thumbpath) else "Not Exists"
        buttons.data_button(
            "Leech Destination", f"userset {user_id} menu LEECH_DUMP_CHAT"
        )
        if user_dict.get("LEECH_DUMP_CHAT", False):
            leech_dest = user_dict["LEECH_DUMP_CHAT"]
        elif "LEECH_DUMP_CHAT" not in user_dict and Config.LEECH_DUMP_CHAT:
            leech_dest = Config.LEECH_DUMP_CHAT
        else:
            leech_dest = "None"
        buttons.data_button("Leech Prefix", f"userset {user_id} menu LEECH_PREFIX")
        if user_dict.get("LEECH_PREFIX", False):
            lprefix = user_dict["LEECH_PREFIX"]
        elif "LEECH_PREFIX" not in user_dict and Config.LEECH_PREFIX:
            lprefix = Config.LEECH_PREFIX
        else:
            lprefix = "Not Exists"
        buttons.data_button("Leech Suffix", f"userset {user_id} menu LEECH_SUFFIX")
        if user_dict.get("LEECH_SUFFIX", False):
            lsuffix = user_dict["LEECH_SUFFIX"]
        elif "LEECH_SUFFIX" not in user_dict and Config.LEECH_SUFFIX:
            lsuffix = Config.LEECH_SUFFIX
        else:
            lsuffix = "Not Exists"

        buttons.data_button("Leech Caption", f"userset {user_id} menu LEECH_CAPTION")
        if user_dict.get("LEECH_CAPTION", False):
            lcap = user_dict["LEECH_CAPTION"]
        elif "LEECH_CAPTION" not in user_dict and Config.LEECH_CAPTION:
            lcap = Config.LEECH_CAPTION
        else:
            lcap = "Not Exists"

        if (
            user_dict.get("AS_DOCUMENT", False)
            or "AS_DOCUMENT" not in user_dict
            and Config.AS_DOCUMENT
        ):
            ltype = "DOCUMENT"
            buttons.data_button("Send As Media", f"userset {user_id} tog AS_DOCUMENT f")
        else:
            ltype = "MEDIA"
            buttons.data_button(
                "Send As Document", f"userset {user_id} tog AS_DOCUMENT t"
            )
        if (
            user_dict.get("EQUAL_SPLITS", False)
            or "EQUAL_SPLITS" not in user_dict
            and Config.EQUAL_SPLITS
        ):
            buttons.data_button(
                "Disable Equal Splits", f"userset {user_id} tog EQUAL_SPLITS f"
            )
            equal_splits = "Enabled"
        else:
            buttons.data_button(
                "Enable Equal Splits", f"userset {user_id} tog EQUAL_SPLITS t"
            )
            equal_splits = "Disabled"

        if Config.AUTO_THUMBNAIL:
            if user_dict.get("AUTO_THUMBNAIL", True):
                buttons.data_button(
                    "Disable Auto-Thumb", f"userset {user_id} tog AUTO_THUMBNAIL f"
                )
                auto_thumbnail = "Enabled"
            else:
                buttons.data_button(
                    "Enable Auto-Thumb", f"userset {user_id} tog AUTO_THUMBNAIL t"
                )
                auto_thumbnail = "Disabled"
        else:
            auto_thumbnail = "Force Disabled"

        if user_dict.get("SHOW_MEDIAINFO_BUTTON", True):
            buttons.data_button(
                "Hide Media Info Button",
                f"userset {user_id} tog SHOW_MEDIAINFO_BUTTON f",
            )
            mediainfo_msg = "Shown"
        else:
            buttons.data_button(
                "Show Media Info Button",
                f"userset {user_id} tog SHOW_MEDIAINFO_BUTTON t",
            )
            mediainfo_msg = "Hidden"

        if (
            user_dict.get("MEDIA_GROUP", False)
            or "MEDIA_GROUP" not in user_dict
            and Config.MEDIA_GROUP
        ):
            buttons.data_button(
                "Disable Media Group", f"userset {user_id} tog MEDIA_GROUP f"
            )
            media_group = "Enabled"
        else:
            buttons.data_button(
                "Enable Media Group", f"userset {user_id} tog MEDIA_GROUP t"
            )
            media_group = "Disabled"
        buttons.data_button(
            "Thumbnail Layout", f"userset {user_id} menu THUMBNAIL_LAYOUT"
        )
        if user_dict.get("THUMBNAIL_LAYOUT", False):
            thumb_layout = user_dict["THUMBNAIL_LAYOUT"]
        elif "THUMBNAIL_LAYOUT" not in user_dict and Config.THUMBNAIL_LAYOUT:
            thumb_layout = Config.THUMBNAIL_LAYOUT
        else:
            thumb_layout = "None"

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""⌬ <b>Leech Settings :</b>
╭ <b>Name</b> → {user_name}
┊ Leech Type → <b>{ltype}</b>
┊ Custom Thumbnail → <b>{thumbmsg}</b>
┊ Leech Split Size → <b>{get_readable_file_size(Config.LEECH_SPLIT_SIZE)}</b>
┊ Equal Splits → <b>{equal_splits}</b>
┊ Media Group → <b>{media_group}</b>
┊ Leech Prefix → <code>{escape(lprefix)}</code>
┊ Leech Suffix → <code>{escape(lsuffix)}</code>
┊ Leech Caption → <code>{escape(lcap)}</code>
┊ Leech Destination → <code>{leech_dest}</code>
┊ Auto Thumbnail : <b> {auto_thumbnail}</b>
┊ Thumbnail Layout → <b>{thumb_layout}</b>
╰ Media Info Button → <b>{mediainfo_msg}</b>
"""

    elif stype == "rclone":
        buttons.data_button("Rclone Config", f"userset {user_id} menu RCLONE_CONFIG")
        buttons.data_button(
            "Default Rclone Path", f"userset {user_id} menu RCLONE_PATH"
        )
        buttons.data_button("Rclone Flags", f"userset {user_id} menu RCLONE_FLAGS")

        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        rccmsg = "Exists" if await aiopath.exists(rclone_conf) else "Not Exists"
        if user_dict.get("RCLONE_PATH", False):
            rccpath = user_dict["RCLONE_PATH"]
        elif Config.RCLONE_PATH:
            rccpath = Config.RCLONE_PATH
        else:
            rccpath = "None"
        btns = buttons.build_menu(1)

        if user_dict.get("RCLONE_FLAGS", False):
            rcflags = user_dict["RCLONE_FLAGS"]
        elif "RCLONE_FLAGS" not in user_dict and Config.RCLONE_FLAGS:
            rcflags = Config.RCLONE_FLAGS
        else:
            rcflags = "None"

        text = f"""⌬ <b>RClone Settings :</b>
╭ <b>Name</b> → {user_name}
┊ <b>Rclone Config</b> → <b>{rccmsg}</b>
┊ <b>Rclone Flags</b> → <code>{rcflags}</code>
╰ <b>Rclone Path</b> → <code>{rccpath}</code>"""

    elif stype == "gdrive":
        buttons.data_button("token.pickle", f"userset {user_id} menu TOKEN_PICKLE")
        buttons.data_button("Default Gdrive ID", f"userset {user_id} menu GDRIVE_ID")
        buttons.data_button("Index URL", f"userset {user_id} menu INDEX_URL")
        if (
            user_dict.get("STOP_DUPLICATE", False)
            or "STOP_DUPLICATE" not in user_dict
            and Config.STOP_DUPLICATE
        ):
            buttons.data_button(
                "Disable Stop Duplicate", f"userset {user_id} tog STOP_DUPLICATE f"
            )
            sd_msg = "Enabled"
        else:
            buttons.data_button(
                "Enable Stop Duplicate",
                f"userset {user_id} tog STOP_DUPLICATE t",
                "l_body",
            )
            sd_msg = "Disabled"
        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        tokenmsg = "Exists" if await aiopath.exists(token_pickle) else "Not Exists"
        if user_dict.get("GDRIVE_ID", False):
            gdrive_id = user_dict["GDRIVE_ID"]
        elif GDID := Config.GDRIVE_ID:
            gdrive_id = GDID
        else:
            gdrive_id = "None"
        index = user_dict["INDEX_URL"] if user_dict.get("INDEX_URL", False) else "None"
        btns = buttons.build_menu(2)

        text = f"""⌬ <b>GDrive Tools Settings :</b>
╭ <b>Name</b> → {user_name}
┊ <b>Gdrive Token</b> → <b>{tokenmsg}</b>
┊ <b>Gdrive ID</b> → <code>{gdrive_id}</code>
┊ <b>Index URL</b> → <code>{index}</code>
╰ <b>Stop Duplicate</b> → <b>{sd_msg}</b>"""
    elif stype == "gofile":
        buttons.data_button("GoFile Token", f"userset {user_id} menu GOFILE_TOKEN")
        buttons.data_button(
            "GoFile Folder ID", f"userset {user_id} menu GOFILE_FOLDER_ID"
        )
        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        gofile_token_status = (
            "Exists" if user_dict.get("GOFILE_TOKEN") else "Not Exists"
        )
        if user_dict.get("GOFILE_FOLDER_ID", False):
            gofile_folder = user_dict["GOFILE_FOLDER_ID"]
        else:
            gofile_folder = "Root Folder"

        btns = buttons.build_menu(2)

        text = f"""⌬ <b>GoFile Tools Settings :</b>
╭<b>Name</b> → {user_name}
┊<b>GoFile Token</b> → <b>{gofile_token_status}</b>
╰<b>GoFile Folder</b> → <code>{gofile_folder}</code>"""
    elif stype == "pixeldrain":
        buttons.data_button(
            "PixelDrain API Key", f"userset {user_id} menu PIXELDRAIN_KEY"
        )
        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        pixeldrain_status = (
            "Exists" if user_dict.get("PIXELDRAIN_KEY") else "Not Exists"
        )
        btns = buttons.build_menu(1)

        text = f"""⌬ <b>PixelDrain Tools Settings :</b>
╭<b>Name</b> → {user_name}
╰<b>PixelDrain API Key</b> → <b>{pixeldrain_status}</b>"""
    elif stype == "buzzheavier":
        buttons.data_button(
            "BuzzHeavier Token", f"userset {user_id} menu BUZZHEAVIER_TOKEN"
        )
        buttons.data_button(
            "BuzzHeavier Folder ID", f"userset {user_id} menu BUZZHEAVIER_FOLDER_ID"
        )
        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        buzz_token_status = (
            "Exists" if user_dict.get("BUZZHEAVIER_TOKEN") else "Not Exists"
        )
        if user_dict.get("BUZZHEAVIER_FOLDER_ID", False):
            buzz_folder = user_dict["BUZZHEAVIER_FOLDER_ID"]
        else:
            buzz_folder = "Root Directory"

        btns = buttons.build_menu(2)

        text = f"""⌬ <b>BuzzHeavier Tools Settings :</b>
╭<b>Name</b> → {user_name}
┊<b>BuzzHeavier Token</b> → <b>{buzz_token_status}</b>
╰<b>BuzzHeavier Folder</b> → <code>{buzz_folder}</code>"""
    elif stype == "devuploads":
        buttons.data_button(
            "DevUploads API Key", f"userset {user_id} menu DEVUPLOADS_API_KEY"
        )
        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        devuploads_status = (
            "Exists" if user_dict.get("DEVUPLOADS_API_KEY") else "Not Exists"
        )
        btns = buttons.build_menu(1)

        text = f"""⌬ <b>DevUploads Tools Settings :</b>
╭<b>Name</b> → {user_name}
╰<b>DevUploads API Key</b> → <b>{devuploads_status}</b>"""
    elif stype == "vikingfile":
        buttons.data_button(
            "VikingFile User Hash", f"userset {user_id} menu VIKINGFILE_USER"
        )
        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")

        vk_status = "Exists" if user_dict.get("VIKINGFILE_USER") else "Not Exists"
        btns = buttons.build_menu(1)

        text = f"""⌬ <b>VikingFile Tools Settings :</b>
╭<b>Name</b> → {user_name}
╰<b>VikingFile User Hash</b> → <b>{vk_status}</b>"""
    elif stype == "terabox":
        tb_cookie_path = f"terabox_cookies/{user_id}.txt"
        tb_cookie_status = (
            "Exists" if await aiopath.exists(tb_cookie_path) else "Not Exists"
        )
        buttons.data_button("TeraBox Cookie", f"userset {user_id} menu TERABOX_COOKIE")
        buttons.data_button("Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""⌬ <b>TeraBox Tools Settings :</b>
╭ <b>Name</b> → {user_name}
┊ <b>TeraBox Cookie</b> → <b>{tb_cookie_status}</b>
╰ <b>Upload Path</b> → <code>{user_dict.get("TERABOX_UPLOAD_PATH", "") or Config.TERABOX_UPLOAD_PATH or "/"}</code>

<i>Upload your <code>terabox.txt</code> cookie to mirror from your own TeraBox account or use <code>-up tb</code> to upload finished tasks.</i>"""
    elif stype == "mirror":
        buttons.data_button("RClone Tools", f"userset {user_id} rclone")
        rccmsg = "Exists" if await aiopath.exists(rclone_conf) else "Not Exists"
        if user_dict.get("RCLONE_PATH", False):
            rccpath = user_dict["RCLONE_PATH"]
        elif RP := Config.RCLONE_PATH:
            rccpath = RP
        else:
            rccpath = "None"

        buttons.data_button("GDrive Tools", f"userset {user_id} gdrive")
        tokenmsg = "Exists" if await aiopath.exists(token_pickle) else "Not Exists"
        if user_dict.get("GDRIVE_ID", False):
            gdrive_id = user_dict["GDRIVE_ID"]
        elif GI := Config.GDRIVE_ID:
            gdrive_id = GI
        else:
            gdrive_id = "None"

        buttons.data_button("GoFile Tools", f"userset {user_id} gofile")
        gofile_token_status = (
            "Exists" if user_dict.get("GOFILE_TOKEN") else "Not Exists"
        )
        if user_dict.get("GOFILE_FOLDER_ID", False):
            gofile_folder = user_dict["GOFILE_FOLDER_ID"]
        else:
            gofile_folder = "Root Folder"

        buttons.data_button("PixelDrain Tools", f"userset {user_id} pixeldrain")
        pixeldrain_status = (
            "Exists" if user_dict.get("PIXELDRAIN_KEY") else "Not Exists"
        )
        buttons.data_button("BuzzHeavier Tools", f"userset {user_id} buzzheavier")
        buttons.data_button("DevUploads Tools", f"userset {user_id} devuploads")
        buttons.data_button("VikingFile Tools", f"userset {user_id} vikingfile")
        buttons.data_button("TeraBox Tools", f"userset {user_id} terabox")
        buzz_token_status = (
            "Exists" if user_dict.get("BUZZHEAVIER_TOKEN") else "Not Exists"
        )
        devuploads_status = (
            "Exists" if user_dict.get("DEVUPLOADS_API_KEY") else "Not Exists"
        )
        if user_dict.get("BUZZHEAVIER_FOLDER_ID", False):
            buzz_folder = user_dict["BUZZHEAVIER_FOLDER_ID"]
        else:
            buzz_folder = "Root Directory"

        index = user_dict["INDEX_URL"] if user_dict.get("INDEX_URL", False) else "None"
        if (
            user_dict.get("STOP_DUPLICATE", False)
            or "STOP_DUPLICATE" not in user_dict
            and Config.STOP_DUPLICATE
        ):
            sd_msg = "Enabled"
        else:
            sd_msg = "Disabled"

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        tb_cookie_path = f"terabox_cookies/{user_id}.txt"
        tb_cookie_status = (
            "Exists" if await aiopath.exists(tb_cookie_path) else "Not Exists"
        )

        text = f"""⌬ <b>Mirror Settings :</b>
╭ <b>Name</b> → {user_name}
┊ <b>Rclone Config</b> → <b>{rccmsg}</b>
┊ <b>Rclone Path</b> → <code>{rccpath}</code>
┊ <b>Gdrive Token</b> → <b>{tokenmsg}</b>
┊ <b>Gdrive ID</b> → <code>{gdrive_id}</code>
┊ <b>Index Link</b> → <code>{index}</code>
┊ <b>GoFile Token</b> → <b>{gofile_token_status}</b>
┊ <b>GoFile Folder</b> → <code>{gofile_folder}</code>
┊ <b>PixelDrain API Key</b> → <b>{pixeldrain_status}</b>
┊ <b>BuzzHeavier Token</b> → <b>{buzz_token_status}</b>
┊ <b>BuzzHeavier Folder</b> → <code>{buzz_folder}</code>
┊ <b>DevUploads API Key</b> → <b>{devuploads_status}</b>
┊ <b>VikingFile User Hash</b> → <b>{"Exists" if user_dict.get("VIKINGFILE_USER") else "Not Exists"}</b>
┊ <b>TeraBox Cookie</b> → <b>{tb_cookie_status}</b>
╰ <b>Stop Duplicate</b> → <b>{sd_msg}</b>
"""

    elif stype == "ffset":
        if not Config.DISABLE_FF_MODE:
            buttons.data_button(
                "FFmpeg CLI Commands", f"userset {user_id} menu FFMPEG_CMDS", "header"
            )
            if user_dict.get("FFMPEG_CMDS", False):
                ffc = user_dict["FFMPEG_CMDS"]
            elif "FFMPEG_CMDS" not in user_dict and Config.FFMPEG_CMDS:
                ffc = Config.FFMPEG_CMDS
            else:
                ffc = "<b>Not Exists</b>"

            if isinstance(ffc, dict):
                ffc = "\n" + "\n".join(
                    [
                        f"{no}. <b>{key}</b>: <code>{escape(str(value[0]))}</code>"
                        for no, (key, value) in enumerate(ffc.items(), start=1)
                    ]
                )
            ffc_text = f"┊ <b>FFmpeg CLI Commands</b> → {ffc}\n"
        else:
            ffc_text = ""

        buttons.data_button("Metadata", f"userset {user_id} menu METADATA")
        metadata_setting = user_dict.get("METADATA")
        display_meta_val = "<b>Not Set</b>"
        if isinstance(metadata_setting, dict) and metadata_setting:
            display_meta_val = ", ".join(
                f"{k}={escape(str(v))}" for k, v in metadata_setting.items()
            )
            display_meta_val = f"<code>{display_meta_val}</code>"
        elif isinstance(metadata_setting, str) and metadata_setting:
            display_meta_val = f"<code>{escape(metadata_setting)}</code>"

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(2)

        text = f"""⌬ <b>FF Settings :</b>
╭ <b>Name</b> → {user_name}
{ffc_text}╰ <b>Metadata</b> → {display_meta_val}"""

    elif stype == "advanced":
        buttons.data_button(
            "Excluded Extensions", f"userset {user_id} menu EXCLUDED_EXTENSIONS"
        )
        if user_dict.get("EXCLUDED_EXTENSIONS", False):
            ex_ex = user_dict["EXCLUDED_EXTENSIONS"]
        elif "EXCLUDED_EXTENSIONS" not in user_dict:
            ex_ex = excluded_extensions
        else:
            ex_ex = "None"

        if ex_ex != "None":
            ex_ex = ", ".join(ex_ex)

        ns_msg = (
            f"<code>{swap}</code>"
            if (swap := user_dict.get("NAME_SWAP", False))
            else "<b>Not Exists</b>"
        )
        buttons.data_button("Name Swap", f"userset {user_id} menu NAME_SWAP")

        buttons.data_button("YT-DLP Options", f"userset {user_id} menu YT_DLP_OPTIONS")
        if user_dict.get("YT_DLP_OPTIONS", False):
            ytopt = user_dict["YT_DLP_OPTIONS"]
        elif "YT_DLP_OPTIONS" not in user_dict and Config.YT_DLP_OPTIONS:
            ytopt = Config.YT_DLP_OPTIONS
        else:
            ytopt = "None"

        upload_paths = user_dict.get("UPLOAD_PATHS", {})
        if not upload_paths and "UPLOAD_PATHS" not in user_dict and Config.UPLOAD_PATHS:
            upload_paths = Config.UPLOAD_PATHS
        else:
            upload_paths = "None"
        buttons.data_button("Upload Paths", f"userset {user_id} menu UPLOAD_PATHS")

        yt_cookie_path = f"cookies/{user_id}/cookies.txt"
        user_cookie_msg = (
            "Exists" if await aiopath.exists(yt_cookie_path) else "Not Exists"
        )
        buttons.data_button(
            "YT Cookie File", f"userset {user_id} menu USER_COOKIE_FILE"
        )

        buttons.data_button("Back", f"userset {user_id} back", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        btns = buttons.build_menu(1)

        text = f"""⌬ <b>Advanced Settings :</b>
╭ <b>Name</b> → {user_name}
┊ <b>Name Swaps</b> → {ns_msg}
┊ <b>Excluded Extensions</b> → <code>{ex_ex}</code>
┊ <b>Upload Paths</b> → <b>{upload_paths}</b>
┊ <b>YT-DLP Options</b> → <code>{ytopt}</code>
╰ <b>YT User Cookie File</b> → <b>{user_cookie_msg}</b>"""

    return text, btns


async def update_user_settings(query, stype="main"):
    handler_dict[query.from_user.id] = False
    msg, button = await get_user_settings(query.from_user, stype)
    await edit_message(query.message, msg, button)


@new_task
async def send_user_settings(_, message):
    from_user = message.from_user
    handler_dict[from_user.id] = False
    msg, button = await get_user_settings(from_user)
    await send_message(message, msg, button)


@new_task
async def add_file(_, message, ftype, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    if ftype == "THUMBNAIL":
        des_dir = await create_thumb(message, user_id)
    elif ftype == "RCLONE_CONFIG":
        rpath = f"{getcwd()}/rclone/"
        await makedirs(rpath, exist_ok=True)
        des_dir = f"{rpath}{user_id}.conf"
        await message.download(file_name=des_dir)
    elif ftype == "TOKEN_PICKLE":
        tpath = f"{getcwd()}/tokens/"
        await makedirs(tpath, exist_ok=True)
        des_dir = f"{tpath}{user_id}.pickle"
        await message.download(file_name=des_dir)
    elif ftype == "USER_COOKIE_FILE":
        cpath = f"{getcwd()}/cookies/{user_id}"
        await makedirs(cpath, exist_ok=True)
        des_dir = f"{cpath}/cookies.txt"
        await message.download(file_name=des_dir)
    elif ftype == "TERABOX_COOKIE":
        tbpath = f"{getcwd()}/terabox_cookies/"
        await makedirs(tbpath, exist_ok=True)
        des_dir = f"{tbpath}{user_id}.txt"
        await message.download(file_name=des_dir)
    await delete_message(message)
    update_user_ldata(user_id, ftype, des_dir)
    await rfunc()
    await database.update_user_doc(user_id, ftype, des_dir)


@new_task
async def add_one(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    value = message.text
    if value.startswith("{") and value.endswith("}"):
        try:
            value = eval(value)
            if user_dict[option]:
                user_dict[option].update(value)
            else:
                update_user_ldata(user_id, option, value)
        except Exception as e:
            await send_message(message, str(e))
            return
    else:
        await send_message(message, "It must be Dict!")
        return
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


@new_task
async def remove_one(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    names = message.text.split("/")
    for name in names:
        if name in user_dict[option]:
            del user_dict[option][name]
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


@new_task
async def set_option(_, message, option, rfunc):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    value = message.text
    # elif option == "LEECH_DUMP_CHAT": # TODO: Add
    if option == "EXCLUDED_EXTENSIONS":
        fx = value.split()
        value = ["aria2", "!qB"]
        for x in fx:
            x = x.lstrip(".")
            value.append(x.strip().lower())
    elif option in ["METADATA"]:
        value = value.strip() if isinstance(value, str) else ""
    elif option in ["UPLOAD_PATHS", "FFMPEG_CMDS", "YT_DLP_OPTIONS"]:
        if value.startswith("{") and value.endswith("}"):
            try:
                value = eval(sub(r"\s+", " ", value))
            except Exception as e:
                await send_message(message, str(e))
                return
        else:
            await send_message(message, "It must be dict!")
            return
    update_user_ldata(user_id, option, value)
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


async def get_menu(option, message, user_id):
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})

    file_dict = {
        "THUMBNAIL": f"thumbnails/{user_id}.jpg",
        "RCLONE_CONFIG": f"rclone/{user_id}.conf",
        "TOKEN_PICKLE": f"tokens/{user_id}.pickle",
        "USER_COOKIE_FILE": f"cookies/{user_id}/cookies.txt",
        "TERABOX_COOKIE": f"terabox_cookies/{user_id}.txt",
    }

    buttons = ButtonMaker()
    if option in [
        "THUMBNAIL",
        "RCLONE_CONFIG",
        "TOKEN_PICKLE",
        "USER_COOKIE_FILE",
        "TERABOX_COOKIE",
    ]:
        key = "file"
    else:
        key = "set"
    buttons.data_button(
        "Change" if user_dict.get(option, False) else "Set",
        f"userset {user_id} {key} {option}",
    )
    if user_dict.get(option, False):
        if option == "THUMBNAIL":
            buttons.data_button(
                "View Thumb", f"userset {user_id} view THUMBNAIL", "header"
            )
        elif option in ["YT_DLP_OPTIONS", "FFMPEG_CMDS", "UPLOAD_PATHS"]:
            buttons.data_button(
                "Add One", f"userset {user_id} addone {option}", "header"
            )
            buttons.data_button(
                "Remove One", f"userset {user_id} rmone {option}", "header"
            )

        if key != "file":  # TODO: option default val check
            buttons.data_button("Reset", f"userset {user_id} reset {option}")
        elif await aiopath.exists(file_dict[option]):
            buttons.data_button("Remove", f"userset {user_id} remove {option}")
    if option in leech_options:
        back_to = "leech"
    elif option in rclone_options:
        back_to = "rclone"
    elif option in gdrive_options:
        back_to = "gdrive"
    elif option in gofile_options:
        back_to = "gofile"
    elif option in pixeldrain_options:
        back_to = "pixeldrain"
    elif option in buzzheavier_options:
        back_to = "buzzheavier"
    elif option in devuploads_options:
        back_to = "devuploads"
    elif option in vikingfile_options:
        back_to = "vikingfile"
    elif option in terabox_options:
        back_to = "terabox"
    elif option in ffset_options:
        back_to = "ffset"
    elif option in advanced_options:
        back_to = "advanced"
    else:
        back_to = "back"
    buttons.data_button("Back", f"userset {user_id} {back_to}", "footer")
    buttons.data_button("Close", f"userset {user_id} close", "footer")
    val = user_dict.get(option)
    if option in file_dict and await aiopath.exists(file_dict[option]):
        val = "<b>Exists</b>"
    elif option == "METADATA":
        current_meta_val = user_dict.get(option)
        if isinstance(current_meta_val, dict) and current_meta_val:
            val = ", ".join(
                f"{k}={escape(str(v))}" for k, v in current_meta_val.items()
            )
            val = f"<code>{val}</code>"
        elif isinstance(current_meta_val, str) and current_meta_val:
            val = f"<code>{escape(current_meta_val)}</code>"
        elif not current_meta_val:
            val = "<b>Not Set</b>"

        if val is None:
            val = "<b>Not Exists</b>"

    if option == "METADATA":
        text = f"""⌬ <b><u>Menu Settings :</u></b>

╭ <b>Option</b> → {option}
┊
┊ <b>Option's Value</b> → {val if val else "<b>Not Exists</b>"}
┊
┊ <b>Default Input Type</b> → {user_settings_text[option][0]}
┊ <b>Description</b> → {user_settings_text[option][1]}
┊
┊ <b>Dynamic Variables:</b>
┊ • <code>{{filename}}</code> - Full filename
┊ • <code>{{basename}}</code> - Filename without extension  
┊ • <code>{{extension}}</code> - File extension
┊
┊ • <code>{{audiolang}}</code> - Audio language
╰ • <code>{{sublang}}</code> - Subtitle language
"""
    else:
        text = f"""⌬ <b><u>Menu Settings :</u></b>

╭ <b>Option</b> → {option}
┊ <b>Option's Value</b> → {val if val else "<b>Not Exists</b>"}
┊ <b>Default Input Type</b> → {user_settings_text[option][0]}
╰ <b>Description</b> → {user_settings_text[option][1]}
"""
    await edit_message(message, text, buttons.build_menu(2))


async def event_handler(client, query, pfunc, rfunc, photo=False, document=False):
    user_id = query.from_user.id
    handler_dict[user_id] = True
    start_time = update_time = time()

    async def event_filter(_, __, event):
        if photo:
            mtype = event.photo or event.document
        elif document:
            mtype = event.document
        else:
            mtype = event.text
        user = event.from_user or event.sender_chat
        return bool(
            user.id == user_id and event.chat.id == query.message.chat.id and mtype
        )

    handler = client.add_handler(
        MessageHandler(pfunc, filters=create(event_filter)), group=-1
    )

    while handler_dict[user_id]:
        await sleep(0.5)
        if time() - start_time > 60:
            handler_dict[user_id] = False
            await rfunc()
        elif time() - update_time > 8 and handler_dict[user_id]:
            update_time = time()
            msg = await client.get_messages(query.message.chat.id, query.message.id)
            text = msg.text.split("\n")
            text[-1] = (
                f"╰ <b>Time Left :</b> <code>{round(60 - (time() - start_time), 2)} sec</code>"
            )
            await edit_message(msg, "\n".join(text), msg.reply_markup)
    client.remove_handler(*handler)


@new_task
async def edit_user_settings(client, query):
    from_user = query.from_user
    user_id = from_user.id
    name = from_user.mention
    message = query.message
    data = query.data.split()

    handler_dict[user_id] = False
    thumb_path = f"thumbnails/{user_id}.jpg"
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"
    yt_cookie_path = f"cookies/{user_id}/cookies.txt"

    user_dict = user_data.get(user_id, {})
    if user_id != int(data[1]):
        return await query.answer("Not Yours!", show_alert=True)
    elif len(data) > 3 and data[3] in {
        "LEECH_SPLIT_SIZE",
        "USER_TRANSMISSION",
        "HYBRID_LEECH",
    }:
        await query.answer(
            "This option is now controlled from bot settings.",
            show_alert=True,
        )
        await update_user_settings(query, "leech")
        return
    elif data[2] == "setevent":
        await query.answer()
    elif data[2] in [
        "general",
        "mirror",
        "leech",
        "ffset",
        "advanced",
        "gdrive",
        "gofile",
        "rclone",
        "pixeldrain",
        "buzzheavier",
        "devuploads",
        "vikingfile",
        "terabox",
    ]:
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] == "menu":
        await query.answer()
        await get_menu(data[3], message, user_id)
    elif data[2] == "tog":
        await query.answer()
        update_user_ldata(user_id, data[3], data[4] == "t")
        if data[3] == "STOP_DUPLICATE":
            back_to = "gdrive"
        elif data[3] in ["USER_TOKENS", "USE_DEFAULT_COOKIE"]:
            back_to = "general"
        else:
            back_to = "leech"
        await update_user_settings(query, stype=back_to)
        await database.update_user_data(user_id)
    elif data[2] == "file":
        await query.answer()
        buttons = ButtonMaker()
        text = user_settings_text[data[3]][2]
        buttons.data_button("Stop", f"userset {user_id} menu {data[3]} stop")
        buttons.data_button("Back", f"userset {user_id} menu {data[3]}", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        await edit_message(
            message, message.text.html + "\n\n" + text, buttons.build_menu(1)
        )
        rfunc = partial(get_menu, data[3], message, user_id)
        pfunc = partial(add_file, ftype=data[3], rfunc=rfunc)
        await event_handler(
            client,
            query,
            pfunc,
            rfunc,
            photo=data[3] == "THUMBNAIL",
            document=data[3] != "THUMBNAIL",
        )
    elif data[2] in ["set", "addone", "rmone"]:
        await query.answer()
        buttons = ButtonMaker()
        if data[2] == "set":
            text = user_settings_text[data[3]][2]
            func = set_option
        elif data[2] == "addone":
            text = f"Add one or more string key and value to {data[3]}. Example: {{'key 1': 62625261, 'key 2': 'value 2'}}. Timeout: 60 sec"
            func = add_one
        elif data[2] == "rmone":
            text = f"Remove one or more key from {data[3]}. Example: key 1/key2/key 3. Timeout: 60 sec"
            func = remove_one
        buttons.data_button("Stop", f"userset {user_id} menu {data[3]} stop")
        buttons.data_button("Back", f"userset {user_id} menu {data[3]}", "footer")
        buttons.data_button("Close", f"userset {user_id} close", "footer")
        await edit_message(
            message, message.text.html + "\n\n" + text, buttons.build_menu(1)
        )
        rfunc = partial(get_menu, data[3], message, user_id)
        pfunc = partial(func, option=data[3], rfunc=rfunc)
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == "remove":
        await query.answer("Removed!", show_alert=True)
        if data[3] in [
            "THUMBNAIL",
            "RCLONE_CONFIG",
            "TOKEN_PICKLE",
            "USER_COOKIE_FILE",
            "TERABOX_COOKIE",
        ]:
            if data[3] == "THUMBNAIL":
                fpath = thumb_path
            elif data[3] == "RCLONE_CONFIG":
                fpath = rclone_conf
            elif data[3] == "USER_COOKIE_FILE":
                fpath = yt_cookie_path
            elif data[3] == "TERABOX_COOKIE":
                fpath = f"terabox_cookies/{user_id}.txt"
            else:
                fpath = token_pickle
            if await aiopath.exists(fpath):
                await remove(fpath)
            del user_dict[data[3]]
            await database.update_user_doc(user_id, data[3])
        else:
            update_user_ldata(user_id, data[3], "")
            await database.update_user_data(user_id)
        await get_menu(data[3], message, user_id)
    elif data[2] == "reset":
        await query.answer("Reset Done!", show_alert=True)
        if data[3] in user_dict:
            del user_dict[data[3]]
            await get_menu(data[3], message, user_id)
        else:
            for k in list(user_dict.keys()):
                if k not in ("SUDO", "AUTH", "VERIFY_TOKEN", "VERIFY_TIME"):
                    del user_dict[k]
            for fpath in [
                thumb_path,
                rclone_conf,
                token_pickle,
                yt_cookie_path,
                f"terabox_cookies/{user_id}.txt",
            ]:
                if await aiopath.exists(fpath):
                    await remove(fpath)
            await update_user_settings(query)
        await database.update_user_data(user_id)
    elif data[2] == "view":
        await query.answer()
        await send_file(message, thumb_path, name)
    elif (
        data[2] in ["gd", "rc", "gofile", "pixeldrain", "buzzheavier", "tb"]
        or "_" in data[2]
    ):
        await query.answer()
        context = "general"

        if "_" in data[2]:
            current_mode, target_mode = data[2].split("_")
            du = target_mode
            if len(data) > 3:
                context = data[3]
        else:
            # Simple toggles when only a short code is passed (rare; mainly used for gd/rc)
            if data[2] == "gd":
                du = "rc"
            elif data[2] == "rc":
                du = "gd"
            else:
                du = data[2]
            if len(data) > 3:
                context = data[3]

        update_user_ldata(user_id, "DEFAULT_UPLOAD", du)
        await update_user_settings(query, stype=context)
        await database.update_user_data(user_id)
    elif data[2] == "back":
        await query.answer()
        stype = data[3] if len(data) == 4 else "main"
        await update_user_settings(query, stype)
    else:
        await query.answer()
        await delete_message(message, message.reply_to_message)


@new_task
async def get_users_settings(_, message):
    msg = ""
    if auth_chats:
        msg += f"AUTHORIZED_CHATS: {auth_chats}\n"
    if sudo_users:
        msg += f"SUDO_USERS: {sudo_users}\n\n"
    if user_data:
        for u, d in user_data.items():
            kmsg = f"\n<b>{u}:</b>\n"
            if vmsg := "".join(
                f"{k}: <code>{v or None}</code>\n" for k, v in d.items()
            ):
                msg += kmsg + vmsg
        if not msg:
            await send_message(message, "No users data!")
            return
        msg_ecd = msg.encode()
        if len(msg_ecd) > 4000:
            with BytesIO(msg_ecd) as ofile:
                ofile.name = "users_settings.txt"
                await send_file(message, ofile)
        else:
            await send_message(message, msg)
    else:
        await send_message(message, "No users data!")
