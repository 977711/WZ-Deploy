from importlib import import_module
from os import getenv


class Config:
    AS_DOCUMENT = False
    AUTHORIZED_CHATS = ""
    BASE_URL = ""
    BASE_URL_PORT = 80
    BOT_TOKEN = ""
    HELPER_TOKENS = ""
    HELPER_STRINGS = ""
    HELPER_BOT_PROXIES = ""
    HELPER_USER_PROXIES = ""
    BOT_MAX_TASKS = 0
    BOT_PM = False
    CMD_SUFFIX = ""
    CF_TUNNEL = False
    CUSTOM_BOT_HEADER = "Downloader Zone"
    CUSTOM_BOT_HEADER_LINK = "https://t.me/DownloaderZoneGateway"
    DEFAULT_LANG = "en"
    DATABASE_URL = ""
    DEFAULT_UPLOAD = "gd"
    DELETE_LINKS = False
    DISABLE_TORRENTS = False
    DISABLE_SEARCH = False
    DISABLE_MEGA = False
    TERABOX_ENABLED = True
    DISABLE_LEECH = False
    DISABLE_BULK = False
    DISABLE_MULTI = False
    DISABLE_SEED = False
    DISABLE_FF_MODE = False
    STRICT_VIDEO_MODE = False
    STRICT_IMAGE_MODE = False
    EQUAL_SPLITS = False
    EXCLUDED_EXTENSIONS = ""
    FFMPEG_CMDS = {}
    MEDIA_STORE = True
    FORCE_SUB_IDS = ""
    GOFILE_API = ""
    DEVUPLOADS_API_KEY = ""
    VIKINGFILE_USER = ""
    PIXELDRAIN_KEY = ""
    BUZZHEAVIER_API = ""
    BUZZHEAVIER_FOLDER_ID = ""
    GDRIVE_ID = ""
    GD_DESP = "Uploaded by Downloader Zone"
    TERABOX_UPLOAD_PATH = ""
    AUTHOR_NAME = "Downloader Zone"
    AUTHOR_URL = "https://t.me/DownloaderZoneGateway"
    DEBRID_LINK_API = ""
    REAL_DEBRID_API = ""
    PROXY_PREFIX = ""
    PROXY_URL = ""
    SCRAPER_PROXIES = ""
    BYPASS_API_URL = ""
    BYPASS_API_KEY = ""
    TURNSTILE_SOLVER_URL = ""
    INSTADL_API = ""
    INCOMPLETE_TASK_NOTIFIER = False
    INDEX_URL = ""
    IS_TEAM_DRIVE = False
    JD_EMAIL = ""
    JD_PASS = ""
    MEGA_EMAIL = ""
    MEGA_PASSWORD = ""
    DIRECT_LIMIT = 0
    MEGA_LIMIT = 0
    TORRENT_LIMIT = 0
    TERABOX_LIMIT = 0
    GD_DL_LIMIT = 0
    RC_DL_LIMIT = 0
    CLONE_LIMIT = 0
    JD_LIMIT = 0
    YTDLP_LIMIT = 0
    PLAYLIST_LIMIT = 0
    LEECH_LIMIT = 0
    EXTRACT_LIMIT = 0
    ARCHIVE_LIMIT = 0
    STORAGE_LIMIT = 0
    LEECH_DUMP_CHAT = ""
    LINKS_LOG_ID = ""
    MIRROR_LOG_ID = ""
    CLEAN_LOG_MSG = False
    LEECH_PREFIX = ""
    LEECH_CAPTION = ""
    LEECH_SUFFIX = ""
    LEECH_FONT = ""
    LEECH_SPLIT_SIZE = 2097152000
    MEDIA_GROUP = False
    HYBRID_LEECH = True
    USE_HYPER = True
    HYPER_THREADS = 0
    HYPER_PIPELINE = 4
    HYPER_CHUNK = 512 * 1024
    MEM_BUDGET = 0
    NAME_SWAP = ""
    OWNER_ID = 0
    QUEUE_ALL = 0
    QUEUE_DOWNLOAD = 0
    QUEUE_UPLOAD = 0
    RCLONE_FLAGS = ""
    RCLONE_PATH = ""
    RCLONE_SERVE_URL = ""
    RCLONE_SERVE_USER = ""
    RCLONE_SERVE_PASS = ""
    RCLONE_SERVE_PORT = 8080
    RSS_CHAT = ""
    RSS_DELAY = 600
    RSS_SIZE_LIMIT = 0
    SEARCH_API_LINK = ""
    SEARCH_LIMIT = 0
    SEARCH_PLUGINS = [
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/piratebay.py",
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/limetorrents.py",
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torlock.py",
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torrentscsv.py",
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/eztv.py",
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torrentproject.py",
        "https://raw.githubusercontent.com/MaurizioRicci/qBittorrent_search_engines/master/kickass_torrent.py",
        "https://raw.githubusercontent.com/MaurizioRicci/qBittorrent_search_engines/master/yts_am.py",
        "https://raw.githubusercontent.com/MadeOfMagicAndWires/qBit-plugins/master/engines/linuxtracker.py",
        "https://raw.githubusercontent.com/MadeOfMagicAndWires/qBit-plugins/master/engines/nyaasi.py",
        "https://raw.githubusercontent.com/LightDestory/qBittorrent-Search-Plugins/master/src/engines/ettv.py",
        "https://raw.githubusercontent.com/LightDestory/qBittorrent-Search-Plugins/master/src/engines/glotorrents.py",
        "https://raw.githubusercontent.com/LightDestory/qBittorrent-Search-Plugins/master/src/engines/thepiratebay.py",
        "https://raw.githubusercontent.com/v1k45/1337x-qBittorrent-search-plugin/master/leetx.py",
        "https://raw.githubusercontent.com/nindogo/qbtSearchScripts/master/magnetdl.py",
        "https://raw.githubusercontent.com/msagca/qbittorrent_plugins/main/uniondht.py",
        "https://raw.githubusercontent.com/khensolomon/leyts/master/yts.py",
    ]
    SET_COMMANDS = True
    SHOW_CLOUD_LINK = False
    STATUS_LIMIT = 3
    STATUS_UPDATE_INTERVAL = 5
    STOP_DUPLICATE = False
    STREAMWISH_API = ""
    SUDO_USERS = ""
    TELEGRAM_API = 0
    TELEGRAM_HASH = ""
    TG_PROXY = None
    THUMBNAIL_LAYOUT = ""
    VERIFY_TIMEOUT = 0
    LOGIN_PASS = ""
    TORRENT_TIMEOUT = 600
    TIMEZONE = "Asia/Kolkata"
    TMDB_KEY = "6abcb6bb99fb77f33c37016a28866ed2"
    AUTO_THUMBNAIL = True
    USER_MAX_TASKS = 0
    USER_TIME_INTERVAL = 0
    UPLOAD_PATHS = {}
    UPSTREAM_REPO = ""
    UPSTREAM_BRANCH = "main"
    UPDATE_PKGS = True
    USER_SESSION_STRING = ""
    USER_TRANSMISSION = True
    USE_SERVICE_ACCOUNTS = False
    WEB_PINCODE = True
    WEB_ACCESS_PASSWORD = "downloaderzone"
    YT_DLP_OPTIONS = {}
    VT_ENCODE_ENABLED = True
    VT_CONVERT_ENABLED = True
    VT_MULTI_RES_ENABLED = True
    VT_MERGE_VIDEO_ENABLED = True
    VT_MUX_AUDIO_ENABLED = True
    VT_SOFTSUB_ENABLED = True
    VT_MUX_ALL_ENABLED = True
    VT_INTROSUB_ENABLED = True
    VT_HARDSUB_ENABLED = True
    VT_RM_SUB_ENABLED = True
    VT_RM_AUDIO_ENABLED = True
    VT_RM_STREAMS_ENABLED = True
    VT_STRIP_META_ENABLED = True
    VT_EXTRACT_ENABLED = True
    VT_SWAP_AUDIO_ENABLED = True
    VT_WATERMARK_ENABLED = True
    VT_CONVERT_AUDIO_ENABLED = True
    VT_ASPECT_RATIO_ENABLED = True
    @classmethod
    def get(cls, key):
        return getattr(cls, key) if hasattr(cls, key) else None

    @classmethod
    def is_search_enabled(cls):
        return not cls.DISABLE_TORRENTS and not cls.DISABLE_SEARCH

    @classmethod
    def set(cls, key, value):
        if hasattr(cls, key):
            setattr(cls, key, value)
        else:
            raise KeyError(f"{key} is not a valid configuration key.")

    @classmethod
    def get_all(cls):
        return {
            key: getattr(cls, key)
            for key in cls.__dict__.keys()
            if not key.startswith("__") and not callable(getattr(cls, key))
        }

    @classmethod
    def load(cls):
        cls.load_config()
        cls.load_env()

    @classmethod
    def load_config(cls):
        try:
            settings = import_module("config")
        except ModuleNotFoundError:
            return
        for attr in dir(settings):
            if hasattr(cls, attr):
                value = getattr(settings, attr)
                if not value:
                    continue
                if isinstance(value, str):
                    value = value.strip()
                if attr == "DEFAULT_UPLOAD" and value not in [
                    "gd",
                    "gofile",
                    "tb",
                    "tbx",
                ]:
                    value = "rc"
                elif attr in [
                    "BASE_URL",
                    "RCLONE_SERVE_URL",
                    "INDEX_URL",
                    "SEARCH_API_LINK",
                ]:
                    if value:
                        value = value.strip("/")
                setattr(cls, attr, value)
        for key in ["BOT_TOKEN", "OWNER_ID", "TELEGRAM_API", "TELEGRAM_HASH"]:
            value = getattr(cls, key)
            if isinstance(value, str):
                value = value.strip()
            if not value:
                raise ValueError(f"{key} variable is missing!")

    @classmethod
    def load_env(cls):
        config_vars = cls.get_all()
        for key in config_vars:
            env_value = getenv(key)
            if env_value is not None:
                converted_value = cls._convert_env_type(key, env_value)
                cls.set(key, converted_value)

    @classmethod
    def _convert_env_type(cls, key, value):
        original_value = getattr(cls, key, None)
        if original_value is None:
            return value
        elif isinstance(original_value, bool):
            return value.lower() in ("true", "1", "yes")
        elif isinstance(original_value, int):
            try:
                return int(value)
            except ValueError:
                return original_value
        elif isinstance(original_value, float):
            try:
                return float(value)
            except ValueError:
                return original_value
        return value

    @classmethod
    def load_dict(cls, config_dict):
        for key, value in config_dict.items():
            if hasattr(cls, key):
                if key == "DEFAULT_UPLOAD" and value not in [
                    "gd",
                    "gofile",
                    "tb",
                    "tbx",
                ]:
                    value = "rc"
                elif key in [
                    "BASE_URL",
                    "RCLONE_SERVE_URL",
                    "INDEX_URL",
                    "SEARCH_API_LINK",
                ]:
                    if value:
                        value = value.strip("/")
                setattr(cls, key, value)
        for key in ["BOT_TOKEN", "OWNER_ID", "TELEGRAM_API", "TELEGRAM_HASH"]:
            value = getattr(cls, key)
            if isinstance(value, str):
                value = value.strip()
            if not value:
                raise ValueError(f"{key} variable is missing!")


# class BinConfig:
#     ARIA2_NAME = "drift"
#     QBIT_NAME = "titan"
#     FFMPEG_NAME = "apex"
#     RCLONE_NAME = "forge"

class BinConfig:
    ARIA2_NAME = "rushflow"
    QBIT_NAME = "swarmcore"
    FFMPEG_NAME = "framepulse"
    RCLONE_NAME = "cloudsail"
