from os.path import basename, splitext
from re import compile as re_compile
from typing import Tuple, List, Iterator
from pycountry import languages
from ..ext_utils.media_utils import get_streams

VALID_PREFIXES = {"all", "v", "a", "s", "g"}

_PLACEHOLDER_PATTERN = re_compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def format_metadata_value(value, variables):
    """
    Substitute {placeholders} in a metadata value using ``variables``.

    Unknown placeholders and stray braces are preserved verbatim, so values
    like "Movie {2023} [x]" never raise and never lose the rest of the text.
    """
    if not isinstance(value, str):
        return str(value)

    def _replace(match):
        name = match.group(1)
        if name in variables:
            return str(variables[name])
        return match.group(0)

    return _PLACEHOLDER_PATTERN.sub(_replace, value)


def _iter_meta_lines(
    raw_meta: str,
) -> Iterator[Tuple[int, str | None, str | None, str]]:
    """Iterator yielding (line_no, prefix, key, value) tuples for metadata lines."""
    if not isinstance(raw_meta, str):
        raise ValueError("Metadata must be a string.")

    raw_meta = raw_meta.lstrip("\ufeff\r\n").strip()
    if not raw_meta:
        return

    for line_no, raw_line in enumerate(raw_meta.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue

        if "=" not in line:
            yield line_no, None, None, f"Line {line_no}: missing '=' separator."
            continue

        left, val = line.split("=", 1)
        left, val = left.strip(), val.strip()

        if not val:
            yield line_no, None, None, f"Line {line_no}: empty value for '{left}'."
            continue

        prefix = None
        key = left

        if ":" in left:
            pre, key = left.split(":", 1)
            pre, key = pre.strip(), key.strip()
            if not pre or not key:
                yield line_no, None, None, f"Line {line_no}: invalid key or prefix."
                continue
            if pre not in VALID_PREFIXES:
                yield (
                    line_no,
                    None,
                    None,
                    f"Line {line_no}: invalid prefix '{pre}'. Allowed: all, v, a, s, g.",
                )
                continue
            prefix = pre

        if any(ord(ch) < 32 for ch in key):
            yield (
                line_no,
                None,
                None,
                f"Line {line_no}: metadata key contains control characters.",
            )
            continue

        yield line_no, prefix, key, val


def metadata_parser(raw_meta: str) -> List[str]:
    """
    Parse metadata string and return FFmpeg command-line arguments.
    Supports stream-targeted metadata only.

    Invalid lines are skipped (with the reason logged) so that one bad entry
    does not discard the whole metadata set.
    """
    try:
        if not isinstance(raw_meta, str) or not raw_meta.strip():
            return []

        args: List[str] = []
        for line_no, prefix, key, val in _iter_meta_lines(raw_meta):
            if key is None or val is None:
                _log_meta_error(f"line {line_no}: {val}")
                continue

            if prefix == "all":
                for s in ["", "s:v", "s:a", "s:s"]:
                    args += ["-metadata" if not s else f"-metadata:{s}", f"{key}={val}"]
            elif prefix == "g":
                args += ["-metadata", f"{key}={val}"]
            elif prefix:
                args += [f"-metadata:s:{prefix}", f"{key}={val}"]
            else:
                args += ["-metadata", f"{key}={val}"]

        return args
    except Exception as e:
        _log_meta_error(f"unexpected error: {e}")
        return []


def _log_meta_error(message: str):
    try:
        from ... import LOGGER

        LOGGER.error(f"Metadata parse error — {message}")
    except Exception:
        pass


class MetadataProcessor:
    _year_pattern = re_compile(r"\b(19|20)\d{2}\b")
    _sanitize_pattern = re_compile(r'[<>:"/\\?*]')

    def __init__(self):
        self.vars = {}
        self.audio_streams = []
        self.subtitle_streams = []

    @staticmethod
    def convert_lang_code(lang_code):
        if not lang_code or lang_code in {"unknown", "und", "none"}:
            return lang_code
        try:
            if len(lang_code) == 2:
                lang = languages.get(alpha_2=lang_code.lower())
            elif len(lang_code) == 3:
                lang = languages.get(alpha_3=lang_code.lower())
            else:
                return lang_code
            return lang.name if lang else lang_code
        except Exception:
            return lang_code

    async def extract_file_vars(self, file_path):
        fname = basename(file_path)
        bname, ext = splitext(fname)
        self.vars = {
            "filename": fname,
            "basename": bname,
            "extension": ext.lstrip("."),
            "audiolang": "unknown",
            "sublang": "none",
        }
        self.audio_streams, self.subtitle_streams = [], []
        try:
            for s in await get_streams(file_path) or []:
                ctype = s.get("codec_type", "").lower()
                slang = s.get("tags", {}).get("language", "unknown")
                full_lang = self.convert_lang_code(slang)
                entry = {
                    "index": s.get("index", 0),
                    "language": slang,
                    "full_language": full_lang,
                }
                if ctype == "audio":
                    self.audio_streams.append(entry)
                    if self.vars["audiolang"] == "unknown" and slang != "und":
                        self.vars["audiolang"] = full_lang
                elif ctype == "subtitle":
                    self.subtitle_streams.append(entry)
                    if self.vars["sublang"] == "none" and slang != "und":
                        self.vars["sublang"] = full_lang
        except Exception:
            pass
        m = self._year_pattern.findall(bname)
        if m:
            self.vars["year"] = m[-1]

    @staticmethod
    def parse_string(metadata_str):
        if not metadata_str or not isinstance(metadata_str, str):
            return {}
        parts, current, i = [], "", 0
        while i < len(metadata_str):
            if (
                metadata_str[i] == "\\"
                and i + 1 < len(metadata_str)
                and metadata_str[i + 1] == "|"
            ):
                current += "|"
                i += 2
            elif metadata_str[i] == "|":
                parts.append(current)
                current = ""
                i += 1
            else:
                current += metadata_str[i]
                i += 1
        if current:
            parts.append(current)
        return dict(p.split("=", 1) if "=" in p else (p, "") for p in parts)

    @staticmethod
    def merge_dicts(default_dict, cmd_dict):
        return {**(default_dict or {}), **(cmd_dict or {})}

    def apply_vars_to_stream(
        self, metadata_dict, stream_lang=None, full_lang=None, stream_type="audio"
    ):
        if not isinstance(metadata_dict, dict):
            return {}
        vars_with_stream = self.vars.copy()
        if stream_lang and stream_lang != "unknown":
            key = "audiolang" if stream_type == "audio" else "sublang"
            vars_with_stream[key] = full_lang or self.convert_lang_code(stream_lang)
        return {
            self.sanitize(k): format_metadata_value(v, vars_with_stream)
            for k, v in metadata_dict.items()
        }

    def apply_vars(self, metadata_dict):
        return self.apply_vars_to_stream(metadata_dict)

    def get_audio_metadata(self, audio_metadata_dict):
        return [
            {
                "index": s["index"],
                "metadata": self.apply_vars_to_stream(
                    audio_metadata_dict, s["language"], s["full_language"], "audio"
                ),
            }
            for s in self.audio_streams
        ]

    def get_subtitle_metadata(self, subtitle_metadata_dict):
        return [
            {
                "index": s["index"],
                "metadata": self.apply_vars_to_stream(
                    subtitle_metadata_dict,
                    s["language"],
                    s["full_language"],
                    "subtitle",
                ),
            }
            for s in self.subtitle_streams
        ]

    def sanitize(self, value):
        return self._sanitize_pattern.sub("_", str(value))[:100]

    async def process_all(
        self,
        video_metadata_dict,
        audio_metadata_dict,
        subtitle_metadata_dict,
        file_path,
    ):
        await self.extract_file_vars(file_path)
        return {
            "video": (
                self.apply_vars(video_metadata_dict) if video_metadata_dict else {}
            ),
            "audio_streams": (
                self.get_audio_metadata(audio_metadata_dict)
                if audio_metadata_dict
                else []
            ),
            "subtitle_streams": (
                self.get_subtitle_metadata(subtitle_metadata_dict)
                if subtitle_metadata_dict
                else []
            ),
            "global": {},
        }

    async def process(self, metadata_dict, file_path):
        await self.extract_file_vars(file_path)
        return self.apply_vars(metadata_dict)
