import re
from contextlib import suppress
from PIL import Image
from hashlib import md5
from aiofiles.os import remove, path as aiopath, makedirs, mkdir
import json
from asyncio import (
    create_subprocess_exec,
    gather,
    wait_for,
    sleep,
)
from asyncio.subprocess import PIPE
from os import path as ospath, replace
from re import search as re_search, escape
from time import time
from aioshutil import rmtree
from langcodes import Language
from typing import Tuple, Optional
import difflib
import asyncio
import aiohttp
import urllib
import random
from aiofiles import open as aiopen
from aiohttp import ClientSession as aioClientSession
import hashlib
from secrets import token_hex
from ... import LOGGER, DOWNLOAD_DIR, threads, cores
from ...core.config_manager import BinConfig, Config
from .bot_utils import cmd_exec, sync_to_async
from .files_utils import get_mime_type, is_archive, is_archive_split
from .status_utils import time_to_seconds


async def extract_media_info(
    input_title: str,
) -> Tuple[str, Optional[str], Optional[str]]:
    normalized_title = re.sub(r"\.\w{2,4}$", "", input_title)
    normalized_title = re.sub(r"[.\-_]", " ", normalized_title)
    season_info = None
    year_info = None
    cut_index = len(normalized_title)
    season_episode_pattern = re.search(
        r"(?<!\w)S0*(\d{1,2})E\d{1,2}(?!\w)", input_title, re.IGNORECASE
    )
    if season_episode_pattern:
        season_info = f"Season {int(season_episode_pattern.group(1))}"
        season_start = normalized_title.find(season_episode_pattern.group(0))
        if season_start != -1 and season_start < cut_index:
            cut_index = season_start
    explicit_season_pattern = re.search(
        r"\bSeason\s+(\d{1,2})\b", input_title, re.IGNORECASE
    )
    if explicit_season_pattern and not season_info:
        season_info = f"Season {int(explicit_season_pattern.group(1))}"
        season_start = normalized_title.find(explicit_season_pattern.group(0))
        if season_start != -1 and season_start < cut_index:
            cut_index = season_start
    simple_season_pattern = re.search(
        r"(?<!\w)S0*(\d{1,2})(?!\w)", input_title, re.IGNORECASE
    )
    if simple_season_pattern and not season_info:
        season_info = f"Season {int(simple_season_pattern.group(1))}"
        season_start = normalized_title.find(simple_season_pattern.group(0))
        if season_start != -1 and season_start < cut_index:
            cut_index = season_start
    year_pattern = re.search(r"\b((?:19|20)\d{2})\b", input_title)
    if year_pattern:
        year_info = year_pattern.group(1)
        year_start = normalized_title.find(year_pattern.group(0))
        if year_start != -1 and year_start < cut_index:
            cut_index = year_start
    normalized_title = normalized_title[:cut_index].strip()
    normalized_title = re.sub(r"https?://\S+|@\w+|[^\w\s]", "", normalized_title)
    # Remove common quality, source, group and language tags while preserving title words
    normalized_title = re.sub(
        r"\s*(?:"
        r"\b720p\b|\b1080p\b|\b2160p\b|\b4k\b|\b10bit\b|\b8bit\b|\bNF\b|\bWEBRip\b|\bWEB-DL\b|\bBluRay\b|\bBRRip\b|\bDVDrip\b|"
        r"\bx264\b|\bx265\b|\bHEVC\b|\bH\.264\b|\bH\.265\b|"
        r"\bAAC\b|\bHE-AAC\b|\b5\.1\b|\b2\.0\b|\bDDP\b|\bDD\+\b|\bDTS\b|\bTrueHD\b|\bAtmos\b|\bAC3\b|"
        r"\bOrg\b|\bOriginal\b|\bHindi\b|\bEnglish\b|\bENG\b|\bHIN\b|\bDual\b|\bMulti\b|\bAudio\b|\bESub\b|\bSub\b|\bSubs\b|"
        r"\bCOMBINED\b|\bBongoZone\b|\bPSA\b|\bTGx\b|\bYTS\b|\bEZTV\b|\bRARBG\b|"
        r"\d{1,2}bit|\d{1,3}Kbps|\d{1,3}Mbps|\bE\d{1,2}-E\d{1,2}\b|\bE\d{1,2}\b"
        r")",
        "",
        normalized_title,
        flags=re.IGNORECASE,
    )
    normalized_title = re.sub(r"\s+", " ", normalized_title).strip()
    return sanitize_title(normalized_title), season_info, year_info


def sanitize_title(title_text: str) -> str:
    cleaned_text = re.sub(r"[^\w\s]", "", title_text)
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()
    return cleaned_text


def select_best_result(results: list, clean_name: str) -> Optional[dict]:
    if not results:
        return None
    max_pop = (
        max((r.get("popularity", 1) for r in results), default=1) or 1
    )  # prevent zero divisor [web:21]
    best_result, best_score = None, -1
    for result in results:
        result_title = (result.get("title", result.get("name", "")) or "").lower()
        similarity = difflib.SequenceMatcher(
            None, clean_name.lower(), result_title
        ).ratio()
        popularity = result.get("popularity", 0) or 0
        score = (0.7 * similarity) + (
            0.3 * (popularity / max_pop)
        )  # safe denom [web:29]
        if score > best_score:
            best_score, best_result = score, result  # one extra indent here [web:21]
    return best_result


async def get_auto_thumbnail_link(
    clean_name: str,
    season: Optional[str],
    year: Optional[str],
    raw_filename: Optional[str] = None,
) -> Optional[str]:
    LOGGER.info(
        f"Starting thumbnail search for {clean_name}, season: {season}, year: {year}"
    )

    # Try ispidy poster API first with raw filename
    if raw_filename:
        try:
            ispidy_url = f"https://poster-api.ispidy.com/v1/fetch?query={urllib.parse.quote(raw_filename)}&api_key=spidy_ppfytejszx"
            LOGGER.debug(f"Trying ispidy API: {ispidy_url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    ispidy_url, timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = data.get("results", [])
                        LOGGER.debug(f"ispidy returned {len(results)} results")

                        # Filter results with landscape URLs
                        landscape_urls = [
                            r.get("landscape") for r in results if r.get("landscape")
                        ]
                        if landscape_urls:
                            selected_url = random.choice(landscape_urls)
                            LOGGER.info(
                                f"Selected landscape URL from ispidy: {selected_url[:50]}..."
                            )
                            return selected_url
                        else:
                            LOGGER.info(
                                "ispidy API returned results but no landscape URLs found"
                            )
                    else:
                        LOGGER.warning(f"ispidy API returned status {response.status}")
        except Exception as e:
            LOGGER.warning(f"ispidy API failed: {e}")

    # Fall back to TMDB
    LOGGER.info("Falling back to TMDB for thumbnail")
    async with aiohttp.ClientSession() as session:
        media_types = ["tv", "movie"] if season else ["movie", "tv"]
        LOGGER.debug(f"Selected media types: {media_types}")

        config_url = (
            f"https://api.themoviedb.org/3/configuration?api_key={Config.TMDB_KEY}"
        )
        LOGGER.debug(f"Fetching configuration from: {config_url}")
        async with session.get(config_url) as config_response:
            if config_response.status != 200:
                LOGGER.error(
                    f"Failed to fetch configuration, status: {config_response.status}"
                )
                return None
            config = await config_response.json()
            base_url = config["images"]["secure_base_url"]
            backdrop_size = config["images"]["backdrop_sizes"][-1]
            LOGGER.debug(
                f"Configuration fetched - base_url: {base_url}, backdrop_size: {backdrop_size}"
            )

        for media_type in media_types:
            search_url = f"https://api.themoviedb.org/3/search/{media_type}?api_key={Config.TMDB_KEY}&query={clean_name}"
            if year and not season:
                search_url += f"&year={year}"
            LOGGER.debug(f"Searching {media_type} with URL: {search_url}")

            async with session.get(search_url) as search_response:
                if search_response.status != 200:
                    LOGGER.warning(
                        f"Search failed for {media_type}, status: {search_response.status}"
                    )
                    continue
                search_results = (await search_response.json()).get("results", [])
                LOGGER.debug(
                    f"Found {len(search_results)} search results for {media_type}"
                )

                if not search_results:
                    LOGGER.info(f"No search results found for {media_type}")
                    continue

                best_result = select_best_result(search_results, clean_name)
                if not best_result:
                    LOGGER.info(f"No suitable result selected for {media_type}")
                    continue

                media_id = best_result["id"]
                LOGGER.debug(f"Selected best result with media_id: {media_id}")

                for language in ["en", None]:
                    image_url = f"https://api.themoviedb.org/3/{media_type}/{media_id}/images?api_key={Config.TMDB_KEY}"
                    if language:
                        image_url += f"&language={language}"
                    LOGGER.debug(f"Fetching images from: {image_url}")

                    async with session.get(image_url) as image_response:
                        if image_response.status != 200:
                            LOGGER.warning(
                                f"Image fetch failed, status: {image_response.status}"
                            )
                            continue
                        data = await image_response.json()
                        LOGGER.debug(
                            f"Received image data with {len(data.get('backdrops', []))} backdrops"
                        )

                        backdrops = [
                            b
                            for b in data.get("backdrops", [])
                            if b.get("iso_639_1")
                            and (
                                language == "en"
                                and b.get("iso_639_1") == "en"
                                or language is None
                                and b.get("iso_639_1") != "null"
                            )
                        ]
                        LOGGER.debug(f"Filtered to {len(backdrops)} valid backdrops")

                        if backdrops:
                            selected_backdrop = max(
                                backdrops,
                                key=lambda x: x.get("vote_average", 0),
                                default=backdrops[0],
                            )
                            LOGGER.info(
                                f"Selected backdrop with vote_average: {selected_backdrop.get('vote_average', 0)}"
                            )
                            return f"{base_url}{backdrop_size}{selected_backdrop['file_path']}"

        LOGGER.info(f"No suitable thumbnail found for {clean_name}")
        return None


async def get_auto_thumbnail(raw_filename: str) -> Optional[str]:
    clean_name, season, year = await extract_media_info(raw_filename)
    LOGGER.info(f"Clean Filename - {clean_name}")
    if season:
        LOGGER.info(f"Season: {season}")
    if year:
        LOGGER.info(f"Year: {year}")
    return await get_auto_thumbnail_link(clean_name, season, year, raw_filename)


def generate_short_filename(url: str, ext: str = ".jpg") -> str:
    short_hash = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"poster_{short_hash}{ext}"


_poster_locks = {}


def _is_readable_image(path: str) -> bool:
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


async def download_auto_thumbnail(url: str) -> str:
    path = "Images/"
    if not await aiopath.isdir(path):
        await mkdir(path)
    filename_part = url.split("/")[-1].split("?")[0]
    ext = "." + filename_part.split(".")[-1] if "." in filename_part else ".jpg"
    filename = generate_short_filename(url, ext)
    des_dir = ospath.join(path, filename)
    lock = _poster_locks.setdefault(des_dir, asyncio.Lock())
    async with lock:
        if await aiopath.isfile(des_dir) and await aiopath.getsize(des_dir) > 0:
            return des_dir
        part_dir = f"{des_dir}.{token_hex(4)}.part"
        for attempt in range(1, 4):
            try:
                async with aioClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            async with aiopen(part_dir, "wb") as file:
                                async for chunk in response.content.iter_chunked(1024):
                                    await file.write(chunk)
                            if not await sync_to_async(_is_readable_image, part_dir):
                                LOGGER.warning(
                                    f"⚠️ Attempt {attempt}: {url} is not a readable image"
                                )
                            else:
                                await sync_to_async(replace, part_dir, des_dir)
                                LOGGER.info(
                                    f"✅ Poster downloaded on attempt {attempt}: {filename}"
                                )
                                return des_dir
                        else:
                            LOGGER.warning(
                                f"⚠️ Attempt {attempt}: Failed to download image from {url} (status {response.status})"
                            )
            except Exception as e:
                LOGGER.warning(
                    f"⚠️ Attempt {attempt}: Exception while downloading image: {e}"
                )
            with suppress(Exception):
                await remove(part_dir)
            await asyncio.sleep(1)
    LOGGER.error(f"❌ All attempts failed to download image from {url}")
    return None


def get_md5_hash(up_path):
    md5_hash = md5()
    with open(up_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)
        return md5_hash.hexdigest()


async def create_thumb(msg, _id=""):
    if not _id:
        _id = time()
        path = f"{DOWNLOAD_DIR}thumbnails"
    else:
        path = "thumbnails"
    await makedirs(path, exist_ok=True)
    photo_dir = await msg.download()
    output = ospath.join(path, f"{_id}.jpg")
    await sync_to_async(Image.open(photo_dir).convert("RGB").save, output, "JPEG")
    await remove(photo_dir)
    return output


async def get_media_info(path, extra_info=False):
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ]
        )
    except Exception as e:
        LOGGER.error(f"Get Media Info: {e}. Mostly File not found! - File: {path}")
        return (0, "", "", "") if extra_info else (0, None, None)
    if result[0] and result[2] == 0:
        ffresult = eval(result[0])
        fields = ffresult.get("format")
        if fields is None:
            LOGGER.error(f"get_media_info: {result}")
            return (0, "", "", "") if extra_info else (0, None, None)
        duration = round(float(fields.get("duration", 0)))
        if extra_info:
            lang, qual, stitles = "", "", ""
            if (streams := ffresult.get("streams")) and streams[0].get(
                "codec_type"
            ) == "video":
                qual = int(streams[0].get("height"))
                qual = f"{480 if qual <= 480 else 540 if qual <= 540 else 720 if qual <= 720 else 1080 if qual <= 1080 else 2160 if qual <= 2160 else 4320 if qual <= 4320 else 8640}p"
                for stream in streams:
                    if stream.get("codec_type") == "audio" and (
                        lc := stream.get("tags", {}).get("language")
                    ):
                        with suppress(Exception):
                            lc = Language.get(lc).display_name()
                        if lc not in lang:
                            lang += f"{lc}, "
                    if stream.get("codec_type") == "subtitle" and (
                        st := stream.get("tags", {}).get("language")
                    ):
                        with suppress(Exception):
                            st = Language.get(st).display_name()
                        if st not in stitles:
                            stitles += f"{st}, "
            return duration, qual, lang[:-2], stitles[:-2]
        tags = fields.get("tags", {})
        artist = tags.get("artist") or tags.get("ARTIST") or tags.get("Artist")
        title = tags.get("title") or tags.get("TITLE") or tags.get("Title")
        return duration, artist, title
    return (0, "", "", "") if extra_info else (0, None, None)


async def get_document_type(path):
    is_video, is_audio, is_image = False, False, False
    if (
        is_archive(path)
        or is_archive_split(path)
        or re_search(r".+(\.|_)(rar|7z|zip|bin)(\.0*\d+)?$", path)
    ):
        return is_video, is_audio, is_image
    mime_type = await sync_to_async(get_mime_type, path)
    if mime_type.startswith("image"):
        return False, False, True
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                path,
            ]
        )
        if result[1] and mime_type.startswith("video"):
            is_video = True
    except Exception as e:
        LOGGER.error(f"Get Document Type: {e}. Mostly File not found! - File: {path}")
        if mime_type.startswith("audio"):
            return False, True, False
        if not mime_type.startswith("video") and not mime_type.endswith("octet-stream"):
            return is_video, is_audio, is_image
        if mime_type.startswith("video"):
            is_video = True
        return is_video, is_audio, is_image
    if result[0] and result[2] == 0:
        fields = eval(result[0]).get("streams")
        if fields is None:
            LOGGER.error(f"get_document_type: {result}")
            return is_video, is_audio, is_image
        is_video = False
        for stream in fields:
            if stream.get("codec_type") == "video":
                codec_name = stream.get("codec_name", "").lower()
                if codec_name not in {"mjpeg", "png", "bmp"}:
                    is_video = True
            elif stream.get("codec_type") == "audio":
                is_audio = True
    return is_video, is_audio, is_image


async def get_streams(file):
    cmd = [
        "ffprobe",
        "-hide_banner",
        "-loglevel",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        file,
    ]
    process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        LOGGER.error(f"Error getting stream info: {stderr.decode().strip()}")
        return None

    try:
        return json.loads(stdout)["streams"]
    except KeyError:
        LOGGER.error(
            f"No streams found in the ffprobe output: {stdout.decode().strip()}",
        )
        return None


async def take_ss(video_file, ss_nb) -> bool:
    duration = (await get_media_info(video_file))[0]
    if duration != 0:
        dirpath, name = video_file.rsplit("/", 1)
        name, _ = ospath.splitext(name)
        dirpath = f"{dirpath}/{name}_mltbss"
        await makedirs(dirpath, exist_ok=True)
        interval = duration // (ss_nb + 1)
        cap_time = interval
        cmds = []
        for i in range(ss_nb):
            output = f"{dirpath}/SS.{name}_{i:02}.png"
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{cap_time}",
                "-i",
                video_file,
                "-q:v",
                "1",
                "-frames:v",
                "1",
                "-threads",
                f"{threads}",
                output,
            ]
            cap_time += interval
            cmds.append(cmd_exec(cmd))
        try:
            resutls = await wait_for(gather(*cmds), timeout=60)
            if resutls[0][2] != 0:
                LOGGER.error(
                    f"Error while creating sreenshots from video. Path: {video_file}. stderr: {resutls[0][1]}"
                )
                await rmtree(dirpath, ignore_errors=True)
                return False
        except Exception:
            LOGGER.error(
                f"Error while creating sreenshots from video. Path: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
            )
            await rmtree(dirpath, ignore_errors=True)
            return False
        return dirpath
    else:
        LOGGER.error("take_ss: Can't get the duration of video")
        return False


async def get_audio_thumbnail(audio_file):
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        audio_file,
        "-an",
        "-vcodec",
        "copy",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.debug(
                f"No embedded cover in audio file. Name: {audio_file}"
            )
            return None
    except Exception:
        LOGGER.debug(
            f"Could not extract thumbnail from audio. Name: {audio_file}"
        )
        return None
    return output


async def get_video_thumbnail(video_file, duration):
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if duration == 0:
        duration = 3
    duration = duration // 2
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{duration}",
        "-i",
        video_file,
        "-vf",
        "thumbnail",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while extracting thumbnail from video. Name: {video_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.error(
            f"Error while extracting thumbnail from video. Name: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    return output


async def get_multiple_frames_thumbnail(video_file, layout, keep_screenshots):
    layout = re.sub(r"(\d+)\D+(\d+)", r"\1x\2", layout)
    ss_nb = layout.split("x")
    if len(ss_nb) != 2 or not ss_nb[0].isdigit() or not ss_nb[1].isdigit():
        LOGGER.error(f"Invalid layout value: {layout}")
        return None
    ss_nb = int(ss_nb[0]) * int(ss_nb[1])
    if ss_nb == 0:
        LOGGER.error(f"Invalid layout value: {layout}")
        return None
    dirpath = await take_ss(video_file, ss_nb)
    if not dirpath:
        return None
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-pattern_type",
        "glob",
        "-i",
        f"{escape(dirpath)}/*.png",
        "-vf",
        f"tile={layout}, thumbnail",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-f",
        "mjpeg",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while combining thumbnails for video. Name: {video_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.error(
            f"Error while combining thumbnails from video. Name: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    finally:
        if not keep_screenshots:
            await rmtree(dirpath, ignore_errors=True)
    return output


class FFMpeg:
    def __init__(self, listener):
        self._listener = listener
        self.subproc = None
        self.subsize = 0
        self._processed_bytes = 0
        self._last_processed_bytes = 0
        self._processed_time = 0
        self._last_processed_time = 0
        self._speed_raw = 0
        self._progress_raw = 0
        self._total_time = 0
        self._eta_raw = 0
        self._time_rate = 0.1
        self._start_time = 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    @property
    def speed_raw(self):
        return self._speed_raw

    @property
    def progress_raw(self):
        return self._progress_raw

    @property
    def eta_raw(self):
        return self._eta_raw

    def clear(self):
        self._start_time = time()
        self._processed_bytes = 0
        self._processed_time = 0
        self._speed_raw = 0
        self._progress_raw = 0
        self._eta_raw = 0
        self._time_rate = 0.1
        self._last_processed_time = 0
        self._last_processed_bytes = 0

    async def _ffmpeg_progress(self):
        proc = self.subproc or getattr(self._listener, "subproc", None)
        while not (
            proc.returncode is not None
            or self._listener.is_cancelled
            or proc.stdout.at_eof()
        ):
            try:
                line = await wait_for(proc.stdout.readline(), 60)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
            line = line.decode()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                if value != "N/A":
                    if key == "total_size":
                        self._processed_bytes = int(value) + self._last_processed_bytes
                        self._speed_raw = self._processed_bytes / (
                            time() - self._start_time
                        )
                    elif key == "speed":
                        self._time_rate = max(0.1, float(value.strip("x")))
                    elif key == "out_time":
                        self._processed_time = (
                            time_to_seconds(value) + self._last_processed_time
                        )
                        try:
                            self._progress_raw = (
                                self._processed_time * 100
                            ) / self._total_time
                            if self.subsize and self._progress_raw > 0:
                                self._processed_bytes = int(
                                    self.subsize * (self._progress_raw / 100)
                                )
                            if (time() - self._start_time) > 0:
                                self._speed_raw = self._processed_bytes / (
                                    time() - self._start_time
                                )
                            else:
                                self._speed_raw = 0
                            self._eta_raw = (
                                self._total_time - self._processed_time
                            ) / self._time_rate
                        except ZeroDivisionError:
                            self._progress_raw = 0
                            self._eta_raw = 0
            await sleep(0.05)

    async def ffmpeg_cmds(self, ffmpeg, f_path):
        self.clear()
        self._total_time = (await get_media_info(f_path))[0]
        base_name, ext = ospath.splitext(f_path)
        dir, base_name = base_name.rsplit("/", 1)
        indices = [
            index
            for index, item in enumerate(ffmpeg)
            if item.startswith("mltb") or item == "mltb"
        ]
        outputs = []
        for index in indices:
            output_file = ffmpeg[index]
            if output_file != "mltb" and output_file.startswith("mltb"):
                bo, oext = ospath.splitext(output_file)
                if oext:
                    if ext == oext:
                        prefix = f"ffmpeg{index}." if bo == "mltb" else ""
                    else:
                        prefix = ""
                    ext = ""
                else:
                    prefix = ""
            else:
                prefix = f"ffmpeg{index}."
            output = f"{dir}/{prefix}{output_file.replace('mltb', base_name)}{ext}"
            outputs.append(output)
            ffmpeg[index] = output
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *ffmpeg, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return outputs
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while running ffmpeg cmd, mostly file requires different/specific arguments. Path: {f_path}"
            )
            for op in outputs:
                if await aiopath.exists(op):
                    await remove(op)
            return False

    async def convert_video(self, video_file, ext, retry=False):
        self.clear()
        self._total_time = (await get_media_info(video_file))[0]
        base_name = ospath.splitext(video_file)[0]
        output = f"{base_name}.{ext}"
        if retry:
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-i",
                video_file,
                "-map",
                "0",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-threads",
                f"{threads}",
                output,
            ]
            if ext == "mp4":
                cmd[17:17] = ["-c:s", "mov_text"]
            elif ext == "mkv":
                cmd[17:17] = ["-c:s", "ass"]
            else:
                cmd[17:17] = ["-c:s", "copy"]
        else:
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-i",
                video_file,
                "-map",
                "0",
                "-c",
                "copy",
                "-threads",
                f"{threads}",
                output,
            ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            if await aiopath.exists(output):
                await remove(output)
            if not retry:
                return await self.convert_video(video_file, ext, True)
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while converting video, mostly file need specific codec. Path: {video_file}"
            )
        return False

    async def convert_audio(self, audio_file, ext):
        self.clear()
        self._total_time = (await get_media_info(audio_file))[0]
        base_name = ospath.splitext(audio_file)[0]
        output = f"{base_name}.{ext}"
        cmd = [
            "taskset",
            "-c",
            f"{cores}",
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            audio_file,
            "-threads",
            f"{threads}",
            output,
        ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while converting audio, mostly file need specific codec. Path: {audio_file}"
            )
            if await aiopath.exists(output):
                await remove(output)
        return False

    async def sample_video(self, video_file, sample_duration, part_duration):
        self.clear()
        self._total_time = sample_duration
        dir, name = video_file.rsplit("/", 1)
        output_file = f"{dir}/SAMPLE.{name}"
        segments = [(0, part_duration)]
        duration = (await get_media_info(video_file))[0]
        remaining_duration = duration - (part_duration * 2)
        parts = (sample_duration - (part_duration * 2)) // part_duration
        time_interval = remaining_duration // parts
        next_segment = time_interval
        for _ in range(parts):
            segments.append((next_segment, next_segment + part_duration))
            next_segment += time_interval
        segments.append((duration - part_duration, duration))

        filter_complex = ""
        for i, (start, end) in enumerate(segments):
            filter_complex += (
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]; "
            )
            filter_complex += (
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]; "
            )

        for i in range(len(segments)):
            filter_complex += f"[v{i}][a{i}]"

        filter_complex += f"concat=n={len(segments)}:v=1:a=1[vout][aout]"

        cmd = [
            "taskset",
            "-c",
            f"{cores}",
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            video_file,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-threads",
            f"{threads}",
            output_file,
        ]

        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == -9:
            self._listener.is_cancelled = True
            return False
        elif code == 0:
            return output_file
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while creating sample video, mostly file is corrupted. Path: {video_file}"
            )
            if await aiopath.exists(output_file):
                await remove(output_file)
            return False

    async def split(self, f_path, file_, parts, split_size):
        self.clear()
        multi_streams = True
        self._total_time = duration = (await get_media_info(f_path))[0]
        base_name, extension = ospath.splitext(file_)
        split_size -= 3000000
        start_time = 0
        i = 1
        while i <= parts or start_time < duration - 4:
            out_path = f_path.replace(file_, f"{base_name}.part{i:03}{extension}")
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-ss",
                str(start_time),
                "-i",
                f_path,
                "-fs",
                str(split_size),
                "-map",
                "0",
                "-map_chapters",
                "-1",
                "-async",
                "1",
                "-strict",
                "-2",
                "-c",
                "copy",
                "-threads",
                f"{threads}",
                out_path,
            ]
            if not multi_streams:
                del cmd[15]
                del cmd[15]
            if self._listener.is_cancelled:
                return False
            self._listener.subproc = await create_subprocess_exec(
                *cmd, stdout=PIPE, stderr=PIPE
            )
            await self._ffmpeg_progress()
            _, stderr = await self._listener.subproc.communicate()
            code = self._listener.subproc.returncode
            if self._listener.is_cancelled:
                return False
            if code == -9:
                self._listener.is_cancelled = True
                return False
            elif code != 0:
                try:
                    stderr = stderr.decode().strip()
                except Exception:
                    stderr = "Unable to decode the error!"
                with suppress(Exception):
                    await remove(out_path)
                if multi_streams:
                    LOGGER.warning(
                        f"{stderr}. Retrying without map, -map 0 not working in all situations. Path: {f_path}"
                    )
                    multi_streams = False
                    continue
                else:
                    LOGGER.warning(
                        f"{stderr}. Unable to split this video, if it's size less than {self._listener.max_split_size} will be uploaded as it is. Path: {f_path}"
                    )
                return False
            out_size = await aiopath.getsize(out_path)
            if out_size > self._listener.max_split_size:
                split_size -= (out_size - self._listener.max_split_size) + 5000000
                LOGGER.warning(
                    f"Part size is {out_size}. Trying again with lower split size!. Path: {f_path}"
                )
                await remove(out_path)
                continue
            lpd = (await get_media_info(out_path))[0]
            if lpd == 0:
                LOGGER.error(
                    f"Something went wrong while splitting, mostly file is corrupted. Path: {f_path}"
                )
                break
            elif duration == lpd:
                LOGGER.warning(
                    f"This file has been splitted with default stream and audio, so you will only see one part with less size from orginal one because it doesn't have all streams and audios. This happens mostly with MKV videos. Path: {f_path}"
                )
                break
            elif lpd <= 3:
                await remove(out_path)
                break
            self._last_processed_time += lpd
            self._last_processed_bytes += out_size
            start_time += lpd - 3
            i += 1
        return True
