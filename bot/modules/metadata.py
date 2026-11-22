from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE
from os import path as ospath, walk
from time import time

from aiofiles.os import path as aiopath, remove
from aioshutil import move

from .. import LOGGER, cpu_eater_lock, task_dict, task_dict_lock
from ..core.config_manager import BinConfig
from ..helper.ext_utils.bot_utils import sync_to_async
from ..helper.ext_utils.files_utils import get_path_size
from ..helper.ext_utils.media_utils import (
    FFMpeg,
    get_document_type,
    get_media_info,
    get_streams,
)
from ..helper.ext_utils.metadata_utils import (
    metadata_parser,
    MetadataProcessor,
    _iter_meta_lines,
    format_metadata_value,
)
from ..helper.mirror_leech_utils.status_utils.metadata_status import MetadataStatus


async def _build_metadata_args(file_path, metadata_str, processor):
    """Substitute per-file variables into metadata lines and build FFmpeg args."""
    processed_meta_lines = []
    for line_no, prefix, key, val in _iter_meta_lines(metadata_str):
        if key is None or val is None:
            LOGGER.error(
                f"Invalid metadata for {ospath.basename(file_path)}: {val} Skipping line."
            )
            continue
        substituted_val = format_metadata_value(val, processor.vars)
        if prefix:
            processed_meta_lines.append(f"{prefix}:{key}={substituted_val}")
        else:
            processed_meta_lines.append(f"{key}={substituted_val}")
    processed_meta_str = "\n".join(processed_meta_lines)
    return metadata_parser(processed_meta_str) if processed_meta_str else []


async def apply_metadata_title(self, dl_path, gid, metadata_dict):
    if not metadata_dict:
        return dl_path

    if isinstance(metadata_dict, dict):
        lines = []
        stream_keys = {"all", "v", "a", "s"}
        if all(k in stream_keys for k in metadata_dict.keys()):
            for prefix in ("all", "v", "a", "s"):
                values = metadata_dict.get(prefix, {})
                if isinstance(values, dict):
                    for key, val in values.items():
                        lines.append(f"{prefix}:{key}={val}")
        else:
            for key, val in metadata_dict.items():
                lines.append(f"{key}={val}")
        metadata_dict = "\n".join(lines)

    if not isinstance(metadata_dict, str) or not metadata_dict.strip():
        return dl_path

    LOGGER.info(f"Applying metadata to {self.name}")
    ffmpeg = FFMpeg(self)
    is_file = await aiopath.isfile(dl_path)
    files = (
        [(dl_path, *await get_document_type(dl_path))]
        if is_file
        else [
            (ospath.join(d, f), *await get_document_type(ospath.join(d, f)))
            for d, _, fs in await sync_to_async(walk, dl_path, topdown=False)
            for f in fs
        ]
    )
    files = [(f, v, a) for f, v, a, _ in files if v or a]
    if not files:
        LOGGER.info(f"No audio/video files found in {dl_path} to apply metadata.")
        return dl_path

    self.files_to_proceed = files
    self.proceed_count = 0
    self.metadata_started_at = time()
    processor = MetadataProcessor()

    async with task_dict_lock:
        task_dict[self.mid] = MetadataStatus(self, ffmpeg, gid, "up")
    self.progress = False
    await cpu_eater_lock.acquire()
    self.progress = True

    try:
        for file_path, is_video, is_audio in files:
            if self.is_cancelled:
                break
            attempted = False
            try:
                self.subname = ospath.basename(file_path)
                self.subsize = await get_path_size(file_path)
                ext = ospath.splitext(file_path)[1]
                temp_out = f"{ospath.splitext(file_path)[0]}.meta_temp{ext}"
                attempted = True
                met_cmd = [
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-progress",
                    "pipe:1",
                    "-i",
                    file_path,
                ]
                streams = await get_streams(file_path)
                if not streams:
                    LOGGER.error(f"Error getting streams for {file_path}. Skipping.")
                    continue

                maps, meta_args = [], []
                v, a, s = 0, 0, 0
                for stream in streams:
                    idx, typ = stream["index"], stream["codec_type"]

                    # Skip attachment streams - they cause FFmpeg errors during metadata remuxing
                    if typ == "attachment":
                        continue

                    maps += ["-map", f"0:{idx}"]
                    if typ == "video":
                        maps += [f"-c:v:{v}", "copy"]
                        if "tags" in stream and "language" in stream["tags"]:
                            meta_args += [
                                f"-metadata:s:v:{v}",
                                f"language={stream['tags']['language']}",
                            ]
                        v += 1
                    elif typ == "audio":
                        maps += [f"-c:a:{a}", "copy"]
                        if "tags" in stream and "language" in stream["tags"]:
                            meta_args += [
                                f"-metadata:s:a:{a}",
                                f"language={stream['tags']['language']}",
                            ]
                        a += 1
                    elif typ == "subtitle":
                        maps += [f"-c:s:{s}", "copy"]
                        if "tags" in stream and "language" in stream["tags"]:
                            meta_args += [
                                f"-metadata:s:s:{s}",
                                f"language={stream['tags']['language']}",
                            ]
                        s += 1
                    else:
                        maps += [f"-c:{idx}", "copy"]

                met_cmd += maps + ["-map_metadata", "0"] + meta_args

                # Process variables in metadata
                if metadata_dict:
                    try:
                        await processor.extract_file_vars(file_path)
                        parsed_meta = await _build_metadata_args(
                            file_path, metadata_dict, processor
                        )
                        if parsed_meta:
                            met_cmd += parsed_meta
                    except Exception as e:
                        LOGGER.error(f"Error processing metadata for {file_path}: {e}")

                # Keep the original streams while only changing metadata
                met_cmd += ["-c", "copy", "-y", temp_out]

                ffmpeg.clear()
                media_info = await get_media_info(file_path)
                if media_info:
                    ffmpeg._total_time = media_info[0]
                self.subproc = await create_subprocess_exec(
                    *met_cmd, stdout=PIPE, stderr=PIPE
                )
                await ffmpeg._ffmpeg_progress()
                _, stderr = await self.subproc.communicate()
                if self.is_cancelled:
                    if await aiopath.exists(temp_out):
                        await remove(temp_out)
                    break
                if self.subproc.returncode == 0:
                    LOGGER.info(f"Successfully applied metadata to {file_path}")
                    await remove(file_path)
                    await move(temp_out, file_path)
                else:
                    LOGGER.error(
                        f"Error applying metadata to {file_path}: {stderr.decode().strip()}"
                    )
                    if await aiopath.exists(temp_out):
                        await remove(temp_out)
            finally:
                if attempted and not self.is_cancelled:
                    self.proceed_count += 1
    finally:
        cpu_eater_lock.release()
    return dl_path
