import asyncio
import logging
from threading import Lock
from curl_cffi import requests as curl_requests
from cloudscraper import create_scraper
from bs4 import BeautifulSoup as B
from hashlib import sha256
from json import loads
from lxml.etree import HTML
from os import path as ospath
import os
import re
import time
from re import findall, match, search, compile as re_compile
from niquests import Session, post, get

# cloudscraper builds on requests, so its sessions need a requests-side adapter
from requests.adapters import HTTPAdapter
from time import sleep, time as time_func
from urllib.parse import parse_qs, urlparse, urljoin, quote, unquote, quote_plus
from urllib3.util.retry import Retry
from uuid import uuid4
from base64 import b64decode, b64encode

from ....core.config_manager import Config
from ...ext_utils.exceptions import DirectDownloadLinkException
from ...ext_utils.help_messages import PASSWORD_ERROR_MESSAGE
from ...ext_utils.status_utils import speed_string_to_bytes

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

SCRAPER_PROXIES = Config.SCRAPER_PROXIES
scraper_proxies = {"http": SCRAPER_PROXIES, "https": SCRAPER_PROXIES}
PROXY_PREFIX = Config.PROXY_PREFIX
PROXY_URL = Config.PROXY_URL
proxies = {"http": PROXY_URL, "https": PROXY_URL}

_bypass_api_lock = Lock()

user_agent = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0"
)
TURNSTILE_SOLVER_URL = Config.TURNSTILE_SOLVER_URL

debrid_link_sites = [
    "1fichier.com",
    "anonfiles.com",
    "bayfiles.com",
    "clicknupload.link",
    "clicknupload.org",
    "clicknupload.co",
    "clicknupload.cc",
    "clicknupload.download",
    "clicknupload.club",
    "dailyuploads.net",
    "ddl.to",
    "ddownload.com",
    "ddownload.link",
    "drop.download",
    "dropbox.com",
    "dropboxusercontent.com",
    "easyupload.io",
    "emload.com",
    "file.al",
    "fileaxa.com",
    "filecat.net",
    "filedot.to",
    "filedot.xyz",
    "filextras.com",
    "filer.net",
    "filespace.com",
    "filestore.me",
    "gigapeta.com",
    "gofile.io",
    "hexupload.net",
    "hitfile.net",
    "htfl.net",
    "hulkshare.com",
    "isra.cloud",
    "katfile.com",
    "kshared.com",
    "mediafire.com",
    "mexashare.com",
    "mixdrop.co",
    "mixdrop.to",
    "mixdrop.sx",
    "mixdrop.club",
    "modsbase.com",
    "nelion.me",
    "pixeldrain.com",
    "prefiles.com",
    "racaty.net",
    "rapidgator.net",
    "rapidgator.asia",
    "rg.to",
    "scribd.com",
    "send.cm",
    "sharemods.com",
    "silkfiles.com",
    "soundcloud.com",
    "streamtape.com",
    "tezfiles.com",
    "turb.cc",
    "turb.to",
    "turbobit.net",
    "turbobit.cc",
    "turbobit.pw",
    "turbobit.online",
    "turbobit.ru",
    "turbobit.live",
    "trubobit.com",
    "turboblt.co",
    "uloz.to",
    "ulozto.net",
    "ulozto.sk",
    "ulozto.cz",
    "upload.ee",
    "uploadhaven.com",
    "up-4ever.com",
    "up-4ever.net",
    "uptobox.com",
    "uptobox.fr",
    "uptobox.eu",
    "uptobox.link",
    "uptostream.com",
    "uptostream.fr",
    "uptostream.eu",
    "uptostream.link",
    "upvid.pro",
    "upvid.live",
    "upvid.host",
    "upvid.biz",
    "upvid.cloud",
    "uqload.com",
    "uqload.co",
    "uqload.io",
    "userload.co",
    "uploadgig.com",
    "usersdrive.com",
    "vidoza.net",
    "voe.sx",
    "voe-unblock.com",
    "voeunblock1.com",
    "voeunblock2.com",
    "voeunblock3.com",
    "voeunbl0ck.com",
    "voeunblck.com",
    "voeunblk.com",
    "voe-un-block.com",
    "voeun-block.net",
    "workupload.com",
    "world-bytez.com",
    "worldbytez.com",
    "world-files.com",
    "wupfile.com",
    "zippyshare.com",
]

real_debrid_sites = [
    "1fichier.com",
    "4shared.com",
    "4s.io",
    "4shared-china.com",
    "clicknupload.me",
    "dailymotion.com",
    "dailyuploads.net",
    "drop.download",
    "filenext.com",
    "filespace.com",
    "filextras.com",
    "gigapeta.com",
    "drive.google.com",
    "dropbox.com",
    "hexupload.net",
    "hitfile.net",
    "htfl.net",
    "icloud.com",
    "isra.cloud",
    "katfile.com",
    "mediafire.com",
    "prefiles.com",
    "rapidgator.net",
    "rapidgator.asia",
    "real-debrid.com",
    "rg.to",
    "redtube.com",
    "scribd.com",
    "send.cm",
    "send.now",
    "sendit.cloud",
    "turbobit.net",
    "turbobit.cc",
    "vimeo.com",
    "voe.sx",
]

bypass_sites = [
    "gdflix",
    "gdlink",
    "ziddiflix",
    "gd.vifix.site",
    "vifix",
    "hubcloud",
    "hubdrive",
    "hubcdn",
    "driveseed",
    "driveleech",
    "extralink",
    "dotflix",
    "dtflix.ink",
    "vikingfile",
    "vikingf1le",
    "vik1ngfile",
    "filepress",
    "skymovies",
    "drivehub"
]


def direct_link_generator(link):
    """direct links generator"""
    domain = urlparse(link).hostname
    if not domain:
        raise DirectDownloadLinkException("ERROR: Invalid URL")
    elif Config.REAL_DEBRID_API and any(x in domain for x in real_debrid_sites):
        try:
            return real_debrid(link)
        except Exception:
            if Config.DEBRID_LINK_API and any(x in domain for x in debrid_link_sites):
                return debrid_link(link)
            else:
                raise
    elif Config.DEBRID_LINK_API and any(x in domain for x in debrid_link_sites):
        return debrid_link(link)
    elif "gdflix" in domain:
        return gdflix(link)
    elif "hubcloud" in domain:
        return hubcloud(link)
    elif "vifix.site/hubcloud" in link:
        return hubcloud(link)
    elif "filepress" in domain:
        return filepress(link)
    elif Config.BYPASS_API_URL and Config.BYPASS_API_KEY and any(x in domain for x in bypass_sites):
        return best_direct_link(link)
    elif "vikingfile.com/f" in link:
        return vikingfile(link)
    elif "buzzheavier.com" in domain:
        return buzzheavier(link)
    elif "devuploads.com" in domain:
        return devuploads(link)
    elif "lulacloud.com" in domain:
        return lulacloud(link)
    elif "fuckingfast.co" in domain:
        return fuckingfast_dl(link)
    elif "mediafire.com" in domain:
        return mediafire(link)
    elif "1drv.ms" in domain:
        return onedrive(link)
    elif any(
        x in domain
        for x in ["pixeldrain.com", "pixeldra.in", "pixeldrain.net", "pixeldrain.dev"]
    ):
        return pixeldrain(link)
    elif "racaty" in domain:
        return racaty(link)
    elif "upload.ee" in domain:
        return uploadee(link)
    elif "uploadhaven" in domain:
        return uploadhaven(link)
    elif "gofile.io" in domain:
        return gofile(link)
    elif "send.cm" in domain:
        return send_cm(link)
    elif "mediafile.cc" in domain:
        return mediafile(link)
    elif "streamvid.net" in domain:
        return streamvid(link)
    elif "shrdsk.me" in domain:
        return shrdsk(link)
    elif "u.pcloud.link" in domain:
        return pcloud(link)
    elif "swisstransfer.com" in domain:
        return swisstransfer(link)
    elif "instagram.com" in domain:
        return instagram(link)
    elif any(x in domain for x in ["akmfiles.com", "akmfls.xyz"]):
        return akmfiles(link)
    elif any(
        x in domain
        for x in [
            "streamtape.com",
            "streamtape.co",
            "streamtape.cc",
            "streamtape.to",
            "streamtape.net",
            "streamta.pe",
            "streamtape.xyz",
        ]
    ):
        return streamtape(link)
    elif any(x in domain for x in ["wetransfer.com", "we.tl"]):
        return wetransfer(link)
    elif "transfer.it" in domain:
        return transfer_it(link)
    elif any(x in domain for x in ["streamhub.ink", "streamhub.to"]):
        return streamhub(link)
    elif any(
        x in domain
        for x in [
            "linkbox.to",
            "lbx.to",
            "teltobx.net",
            "telbx.net",
        ]
    ):
        return linkBox(link)
    else:
        raise DirectDownloadLinkException(f"No Direct link function found for {link}")


def best_direct_link(url: str):
    api_base = Config.BYPASS_API_URL
    api_key = Config.BYPASS_API_KEY

    headers_auth = {'Authorization': f"Bearer {api_key}"}
    
    bypass_regex = re_compile(r'https?://(?:[^/]*\.)?(filepress|extralink|oxxfile|dotflix|dtflix|gdflix|gdlink|hubcloud|hubdrive|driveseed|driveleech|gdshare|gcloud|gdrex|neodrive|neolink|drivehub|ziddiflix|vifix|ozolinks|skymovies)\.(?:[^/]+)(?:/|$)|https?://(?:[^/]*\.)?(vikingfile|vikingf1le|vik1ngfile)\.(?:[^/]+)/f/|https?://gd\.vifix\.site')

    api_url = f'{api_base}/bypass?url={quote_plus(url)}&dl=True'
    
    with _bypass_api_lock:
        try:
            resp = get(api_url, headers=headers_auth, allow_redirects=False, timeout=240)
        except Exception:
            raise DirectDownloadLinkException('ERROR: Failed to generate direct link. Connection timeout!')

    if not resp.headers.get('Location'):
        if resp.json().get('error'):
            raise DirectDownloadLinkException(f"ERROR: {resp.json().get('error')}")
        raise DirectDownloadLinkException(f'No Bypass found for {url}')

    link = resp.headers.get('Location')

    if bypass_regex.search(link):
        logger.info(f"[BYPASS] {url} -> {link} (recursing)")
        return best_direct_link(link)

    if 'gofile' in link:
        return gofile(link)
    if 'pixeldrain' in link:
        return pixeldrain(url)

    return link


def transfer_it(url):
    resp = post(
        "https://transfer-it-henna.vercel.app/post",
        json={"url": url},
        timeout=30,
    )
    if resp.status_code == 200:
        data = resp.json()
        return data.get("url") or data
    else:
        raise DirectDownloadLinkException("ERROR: File Expired or File Not Found")


def real_debrid(url: str, tor=False):
    def __unrestrict(url, tor=False):
        cget = create_scraper().request
        resp = cget(
            "POST",
            f"https://api.real-debrid.com/rest/1.0/unrestrict/link?auth_token={Config.REAL_DEBRID_API}",
            data={"link": url},
            proxies=proxies,
        )
        if resp.status_code == 200:
            _res = resp.json()
            if tor:
                # Prepend proxy prefix to download link
                return (_res["filename"], PROXY_PREFIX + _res["download"])
            else:
                return PROXY_PREFIX + _res["download"]
        else:
            raise Exception(f"ERROR: {resp.json().get('error', 'Unknown error')}")

    def __addMagnet(magnet):
        cget = create_scraper().request
        hash_ = re.search(r"(?<=xt=urn:btih:)[a-zA-Z0-9]+", magnet).group(0)
        resp = cget(
            "GET",
            f"https://api.real-debrid.com/rest/1.0/torrents/instantAvailability/{hash_}?auth_token={Config.REAL_DEBRID_API}",
            proxies=proxies,
        )
        if resp.status_code != 200 or not resp.json()[hash_.lower()]["rd"]:
            return magnet
        resp = cget(
            "POST",
            f"https://api.real-debrid.com/rest/1.0/torrents/addMagnet?auth_token={Config.REAL_DEBRID_API}",
            data={"magnet": magnet},
            proxies=proxies,
        )
        if resp.status_code == 201:
            _id = resp.json()["id"]
        else:
            raise Exception(f"ERROR: {resp.json().get('error', 'Unknown error')}")
        if _id:
            _file = cget(
                "POST",
                f"https://api.real-debrid.com/rest/1.0/torrents/selectFiles/{_id}?auth_token={Config.REAL_DEBRID_API}",
                data={"files": "all"},
                proxies=proxies,
            )
            if _file.status_code != 204:
                raise Exception(f"ERROR: {resp.json().get('error', 'Unknown error')}")

        contents = {"links": []}
        while not contents["links"]:
            _res = cget(
                "GET",
                f"https://api.real-debrid.com/rest/1.0/torrents/info/{_id}?auth_token={Config.REAL_DEBRID_API}",
                proxies=proxies,
            )
            if _res.status_code == 200:
                contents = _res.json()
            else:
                raise Exception(f"ERROR: {_res.json().get('error', 'Unknown error')}")
            time.sleep(0.5)

        details = {
            "contents": [],
            "title": contents["original_filename"],
            "total_size": contents["bytes"],
        }

        for file_info, link in zip(contents["files"], contents["links"]):
            link_info = __unrestrict(link, tor=True)
            item = {
                "path": os.path.join(
                    details["title"], os.path.dirname(file_info["path"]).lstrip("/")
                ),
                "filename": unquote(link_info[0]),
                "url": link_info[1],
            }
            details["contents"].append(item)
        return details

    try:
        if tor:
            details = __addMagnet(url)
            if isinstance(details, dict) and len(details["contents"]) == 1:
                return details["contents"][0]["url"]
            return details
        else:
            return __unrestrict(url)
    except Exception as e:
        raise Exception(str(e))


def debrid_link(url):
    cget = create_scraper().request
    resp = cget(
        "POST",
        f"https://debrid-link.com/api/v2/downloader/add?access_token={Config.DEBRID_LINK_API}",
        data={"url": url},
        proxies=proxies,
    ).json()

    if not resp["success"]:
        raise DirectDownloadLinkException(
            f"ERROR: {resp['error']} & ERROR ID: {resp['error_id']}"
        )

    if isinstance(resp["value"], dict):
        return PROXY_PREFIX + resp["value"]["downloadUrl"]

    elif isinstance(resp["value"], list):
        details = {
            "contents": [],
            "title": unquote(url.rstrip("/").split("/")[-1]),
            "total_size": 0,
        }
        for dl in resp["value"]:
            if dl.get("expired", False):
                continue
            item = {
                "path": ospath.join(details["title"]),
                "filename": dl["name"],
                "url": PROXY_PREFIX + dl["downloadUrl"],
            }
            if "size" in dl:
                details["total_size"] += dl["size"]
            details["contents"].append(item)
        return details


def gdflix(link):
    scraper = create_scraper()
    scraper.proxies = scraper_proxies
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}
    link = link.rstrip("/")
    if "pack" in link:
        return gdflix_pack(link, scraper)
    parsed = urlparse(link)
    id = parsed.path.split("/")[-1]
    link = f"https://gdflix.dev/file/{id}"

    def normalize_url(url):
        if url.startswith("http"):
            return url
        elif url.startswith("/"):
            base = "{uri.scheme}://{uri.netloc}".format(uri=urlparse(link))
            return base + url
        else:
            base = "{uri.scheme}://{uri.netloc}/".format(uri=urlparse(link))
            return base + url

    def decode_fastcdn_url(url):
        parsed = urlparse(url)
        if "fastcdn-dl.pages.dev" in parsed.netloc and parsed.query:
            params = parse_qs(parsed.query)
            if "url" in params:
                return unquote(params["url"][0])
        return url

    try:
        response = scraper.get(link, headers=headers, timeout=15)
        if response.status_code != 200:
            return f"HTTP {response.status_code} fetching main page"
    except Exception as e:
        return f"Request failed: {e}"

    soup = B(response.text, "html.parser")

    candidates = {
        "r2": None,
        "fsl_r2": None,
        "instantdl": None,
        "MGT": None,
        "pixeldrain": None,
        "gofile": None,
    }
    fastcloud_href = None

    for a in soup.find_all("a", href=True):
        href = a["href"]
        href_norm = normalize_url(href)
        label = (a.get_text(strip=True) or "").lower()

        if "start=" in href:
            continue

        if "r2.dev" in href_norm:
            if "fsl" in label:
                if not candidates["fsl_r2"]:
                    candidates["fsl_r2"] = href_norm
            else:
                if not candidates["r2"]:
                    candidates["r2"] = href_norm
        elif "instant" in href or "busycdn" in href_norm:
            if not candidates["instantdl"]:
                try:
                    r = scraper.get(
                        href_norm, headers=headers, allow_redirects=True, timeout=15
                    )
                    if r.status_code == 200 and "?url=" in str(r.url):
                        candidates["instantdl"] = str(r.url).split("?url=")[-1]
                    else:
                        candidates["instantdl"] = str(r.url)
                except:
                    candidates["instantdl"] = href_norm
        elif "pixeldrain" in href_norm:
            if not candidates["pixeldrain"]:
                if "/u/" in href_norm:
                    m = re.search(r"/u/([A-Za-z0-9]+)", href_norm)
                    if m:
                        candidates["pixeldrain"] = (
                            f"https://pixeldrain.dev/api/file/{m.group(1)}?download"
                        )
                else:
                    candidates["pixeldrain"] = href_norm
        elif "zfile" in href:
            if not fastcloud_href:
                try:
                    zl = normalize_url(href)
                    r = scraper.get(zl, headers=headers, timeout=15)
                    if r.status_code == 200:
                        zsoup = B(r.text, "html.parser")
                        for za in zsoup.find_all("a", href=True):
                            zlabel = (za.get_text(strip=True) or "").lower()
                            if "cloud resume download" in zlabel:
                                fastcloud_href = normalize_url(za["href"])
                                break
                            elif "quick download" in zlabel and not fastcloud_href:
                                fastcloud_href = normalize_url(za["href"])
                except:
                    pass
        elif "mgt" in label:
            if not candidates["MGT"]:
                candidates["MGT"] = href_norm
        elif "goflix" in href_norm:
            if not candidates["gofile"]:
                try:
                    r = scraper.get(href_norm, headers=headers, timeout=12)
                    if r.status_code == 200:
                        gsoup = B(r.text, "html.parser")
                        for ga in gsoup.find_all("a", href=True):
                            ghref = ga["href"]
                            if "gofile.io" in ghref:
                                candidates["gofile"] = ghref
                                break
                except:
                    pass

    if not candidates["pixeldrain"]:
        iframe = soup.find("iframe", src=True)
        if iframe and "pixeldrain" in iframe["src"].lower():
            m = re.search(r"/u/([A-Za-z0-9]+)", iframe["src"])
            if m:
                candidates["pixeldrain"] = (
                    f"https://pixeldrain.dev/api/file/{m.group(1)}?download"
                )

    priority_order = ["r2", "fsl_r2", "instantdl", "MGT", "pixeldrain", "gofile"]

    if fastcloud_href:
        priority_order.insert(3, "fastcloud")

    for key in priority_order:
        if key == "fastcloud":
            value = fastcloud_href
        else:
            value = candidates.get(key)
        if value:
            if "fastcdn-dl.pages.dev" in value:
                value = decode_fastcdn_url(value)
            return value

    return "No Valid Download Links Found"


def decode_fastcdn_url(url):
    parsed = urlparse(url)
    if "fastcdn-dl.pages.dev" in parsed.netloc and parsed.query:
        params = parse_qs(parsed.query)
        if "url" in params:
            return unquote(params["url"][0])
    return url


def size_to_bytes(size_str):
    m = re.match(r"([\d.]+)\s*([KMGTP]?B)", size_str.upper())
    if not m:
        return None
    size = float(m.group(1))
    unit = m.group(2)
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
        "PB": 1024**5,
    }
    return int(size * multipliers[unit])


def gdflix_pack(link, scraper):
    scraper.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    r = scraper.get(link)
    html = r.text
    soup = B(html, "html.parser")
    title = soup.title.string.strip()
    title = title.replace("GDFlix | ", "") if title else "GDFlix pack"
    m = search(r'data-total="(\d+)"', html)
    total_size = int(m.group(1)) if m else 0
    contents = []
    for a in soup.select("li a"):
        text = a.get_text(strip=True)
        m = re.search(r"^(.*?)\s*\[([\d.]+\s*[KMGTP]?B)\]\s*$", text)
        if not m:
            continue
        filename = m.group(1).strip()
        filesize = m.group(2).strip()
        link = f"https://gdflix.dev{a.get('href')}"
        contents.append(
            {
                "path": "",
                "filename": filename,
                "url": gdflix(link),
                "size": size_to_bytes(filesize),
            }
        )
    return {
        "title": title,
        "total_size": total_size or 0,
        "contents": contents,
        "header": "",
    }


def normalize_hubcloud(url):
    if "vcloud" in url:
        return url
    parsed = urlparse(url)
    id = parsed.path.split("/")[-1]
    if "/video/" in url:
        return f"https://hubcloud.foo/video/{id}"
    return f"https://hubcloud.foo/drive/{id}"


def hubcloud(link: str) -> str:
    if "pack" in link:
        if "hubcloud.bz" in link:
            link = link.replace("hubcloud.bz", "hubcloud.foo")
        elif "hubcloud.one" in link:
            link = link.replace("hubcloud.one", "hubcloud.foo")
        elif "vifix.site" in link:
            link = link.replace("vifix.site/hubcloud", "hubcloud.foo")
        return hubcloud_pack(link)

    link = normalize_hubcloud(link)
    scraper = create_scraper(
        browser={
            "browser": "chrome",
            "platform": "windows",
            "mobile": False,
        }
    )
    scraper.proxies = scraper_proxies

    headers = {
        "User-Agent": "curl/8.5.0",
        "Accept": "*/*",
    }

    def get(url, allow_redirects=True):
        return scraper.get(
            url, headers=headers, timeout=10, allow_redirects=allow_redirects
        )

    try:
        r = get(link)
        if r.status_code != 200:
            return f"Error: HTTP {r.status_code}"
    except Exception as e:
        return f"Request failed: {e}"

    html = r.text
    final_url = str(r.url)

    token_match = re.search(
        r'href=[\'"]*([^\'\"]+token=[^\'\"]+)[\'"]*', html
    ) or re.search(r'url\s*=\s*[\'"]*([^\'\"]+token=[^\'\"]+)[\'"]*', html)
    if token_match and "token=" not in final_url:
        turl = token_match.group(1)
        if not turl.startswith("http"):
            turl = urljoin(link, turl)
        try:
            r2 = get(turl)
            if r2.status_code == 200:
                html = r2.text
        except:
            pass

    soup = B(html, "html.parser")

    mirrors = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            href = urljoin(link, href)
        text = (a.get_text(strip=True) or "").lower()

        link_info = None

        if "10gbps" in text:
            try:
                r_temp = get(href, allow_redirects=False)
                loc = r_temp.headers.get("Location", "")
                if m := re.search(
                    r"https://video-downloads.googleusercontent.com/[^\"']+", loc
                ):
                    link_info = {"label": "10Gbps Server", "url": m.group()}
                elif loc:
                    r_temp = get(loc, allow_redirects=False)
                    loc2 = r_temp.headers.get("Location", "")
                    if m := re.search(
                        r"https://video-downloads.googleusercontent.com/[^\"']+", loc2
                    ):
                        link_info = {"label": "10Gbps Server", "url": m.group()}
            except:
                pass
        elif "pixel" in text:
            if "negn6f" in href:
                pxl = re.search(r'var\s*pxl\s*=\s*"([^"]+)"', html)
                if pxl:
                    href = pxl.group(1)
            if "/u/" in href:
                m = re.search(r"/u/([A-Za-z0-9]+)", href)
                if m:
                    href = f"https://pixeldrain.dev/api/file/{m.group(1)}?download"
            link_info = {"label": "Pixeldrain", "url": href}
        elif "fslv2" in text:
            link_info = {"label": "FSLv2 Server", "url": href}
        elif "fsl" in text and "fslv2" not in text:
            link_info = {"label": "FSL Server", "url": href}
        elif "zipdisk" in text:
            link_info = {"label": "ZipDisk Server", "url": href}
        elif "download file" in text:
            link_info = {"label": "DL Server", "url": href}
        elif "buzz server" in text:
            link_info = {"label": "Buzz Server", "url": href}

        if link_info:
            if not any(m["url"] == link_info["url"] for m in mirrors):
                mirrors.append(link_info)

    if mirrors:
        return mirrors[0]["url"]

    return "No Valid Download Links Found"


def hubcloud_pack(link):
    scraper = create_scraper(
        browser={
            "browser": "chrome",
            "platform": "windows",
            "mobile": False,
        }
    )
    scraper.proxies = scraper_proxies
    scraper.headers.update(
        {
            "User-Agent": "curl/8.5.0",
            "Accept": "*/*",
        }
    )

    r = scraper.get(link)
    html = r.text

    title = search(r'pack_name["\']*\s*:\s*["\']*([^"\']+)', html)
    title = title.group(1) if title else "HubCloud pack"

    match = search(r"const packData = JSON\.parse\(`(.*?)`\);", html, re.DOTALL)
    if match:
        json_data = match.group(1)
        data = loads(json_data)
        total_size = sum(int(file["file_size"]) for file in data["files"])

        files = []
        for f in data["files"]:
            files.append(
                {
                    "id": f["share_id"],
                    "file_name": f["file_name"],
                    "size": int(f["file_size"]),
                }
            )
    else:
        raise DirectDownloadLinkException("ERROR: No Data found for HubCloud pack")

    contents = []
    for file in files:
        if "drive" in link:
            url = f"https://hubcloud.foo/drive/{file['id']}"
        elif "video" in link:
            url = f"https://hubcloud.foo/video/{file['id']}"

        fl = hubcloud(url)

        contents.append(
            {"path": "", "filename": file["file_name"], "url": fl, "size": file["size"]}
        )

    return {
        "title": title,
        "total_size": total_size or 0,
        "contents": contents,
        "header": "",
    }


def buzzheavier(link):
    """
    Generate a direct download link for buzzheavier URLs.
    @param link: URL from buzzheavier
    @return: Direct download link
    """
    link = link if link.endswith("/") else link + "/"
    client = create_scraper()
    try:
        res = client.get(
            link + "download", headers={"hx-current-url": link, "referer": link}
        )
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e

    domain = urlparse(link).netloc
    redirect_url = res.headers.get("Hx-Redirect", "None")

    if redirect_url == "None":
        raise DirectDownloadLinkException("ERROR: Direct link not found")

    if not redirect_url.startswith("http"):
        return f"https://{domain}{redirect_url}"
    return redirect_url


def fuckingfast_dl(url):
    session = Session()
    url = url.strip()

    try:
        response = session.get(url)
        content = response.text
        pattern = r'window\.open\((["\'])(https://fuckingfast\.co/dl/[^"\']+)\1'
        match = search(pattern, content)

        if not match:
            raise DirectDownloadLinkException(
                "ERROR: Could not find download link in page"
            )

        direct_url = match.group(2)
        return direct_url

    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: {str(e)}") from e
    finally:
        session.close()


def devuploads(url):
    file_id = url.rstrip("/").split("/")[-1]
    return f"https://devuploads.dzhq.workers.dev/{file_id}"


def mediafile(url):
    try:
        res = get(url, allow_redirects=True)
        match = search(r"href='([^']+)'", res.text)
        if not match:
            raise DirectDownloadLinkException("ERROR: Unable to find link data")
        download_url = match.group(1)
        sleep(60)
        res = get(download_url, headers={"Referer": url}, cookies=res.cookies)
        postvalue = search(r"showFileInformation(.*);", res.text)
        if not postvalue:
            raise DirectDownloadLinkException("ERROR: Unable to find post value")
        postid = postvalue.group(1).replace("(", "").replace(")", "")
        response = post(
            "https://mediafile.cc/account/ajax/file_details",
            data={"u": postid},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        html = response.json()["html"]
        return [
            i for i in findall(r'https://[^\s"\']+', html) if "download_token" in i
        ][1]
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: {str(e)}") from e


def lulacloud(url):
    """
    Generate a direct download link for www.lulacloud.com URLs.
    @param url: URL from www.lulacloud.com
    @return: Direct download link
    """
    session = Session()
    try:
        res = session.post(url, headers={"Referer": url}, allow_redirects=False)
        return res.headers["location"]
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: {str(e)}") from e
    finally:
        session.close()


def mediafire(url, session=None):
    if "/folder/" in url:
        return mediafireFolder(url)
    if "::" in url:
        _password = url.split("::")[-1]
        url = url.split("::")[-2]
    else:
        _password = ""
    if final_link := findall(
        r"https?:\/\/download\d+\.mediafire\.com\/\S+\/\S+\/\S+", url
    ):
        return final_link[0]

    def _repair_download(url, session):
        try:
            html = HTML(session.get(url).text)
            if new_link := html.xpath('//a[@id="continue-btn"]/@href'):
                return mediafire(f"https://mediafire.com/{new_link[0]}")
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e

    if session is None:
        session = create_scraper()
        parsed_url = urlparse(url)
        url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
    try:
        html = HTML(session.get(url).text)
    except Exception as e:
        session.close()
        raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
    if error := html.xpath('//p[@class="notranslate"]/text()'):
        session.close()
        raise DirectDownloadLinkException(f"ERROR: {error[0]}")
    if html.xpath("//div[@class='passwordPrompt']"):
        if not _password:
            session.close()
            raise DirectDownloadLinkException(
                f"ERROR: {PASSWORD_ERROR_MESSAGE}".format(url)
            )
        try:
            html = HTML(session.post(url, data={"downloadp": _password}).text)
        except Exception as e:
            session.close()
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
        if html.xpath("//div[@class='passwordPrompt']"):
            session.close()
            raise DirectDownloadLinkException("ERROR: Wrong password.")
    if not (final_link := html.xpath('//a[@aria-label="Download file"]/@href')):
        if repair_link := html.xpath("//a[@class='retry']/@href"):
            return _repair_download(repair_link[0], session)
        raise DirectDownloadLinkException(
            "ERROR: No links found in this page Try Again"
        )
    if final_link[0].startswith("//"):
        final_url = f"https://{final_link[0][2:]}"
        if _password:
            final_url += f"::{_password}"
        return mediafire(final_url, session)
    session.close()
    return final_link[0]


def onedrive(link):
    with create_scraper() as session:
        try:
            link = session.get(link).url
            parsed_link = urlparse(link)
            link_data = parse_qs(parsed_link.query)
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
        if not link_data:
            raise DirectDownloadLinkException("ERROR: Unable to find link_data")
        folder_id = link_data.get("resid")
        if not folder_id:
            raise DirectDownloadLinkException("ERROR: folder id not found")
        folder_id = folder_id[0]
        authkey = link_data.get("authkey")
        if not authkey:
            raise DirectDownloadLinkException("ERROR: authkey not found")
        authkey = authkey[0]
        boundary = uuid4()
        headers = {"content-type": f"multipart/form-data;boundary={boundary}"}
        data = f"--{boundary}\r\nContent-Disposition: form-data;name=data\r\nPrefer: Migration=EnableRedirect;FailOnMigratedFiles\r\nX-HTTP-Method-Override: GET\r\nContent-Type: application/json\r\n\r\n--{boundary}--"
        try:
            resp = session.get(
                f"https://api.onedrive.com/v1.0/drives/{folder_id.split('!', 1)[0]}/items/{folder_id}?$select=id,@content.downloadUrl&ump=1&authKey={authkey}",
                headers=headers,
                data=data,
            ).json()
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
    if "@content.downloadUrl" not in resp:
        raise DirectDownloadLinkException("ERROR: Direct link not found")
    return resp["@content.downloadUrl"]


def pixeldrain(url):
    try:
        url = url.rstrip("/")
        parts = url.split("/")
        code = parts[-1].split("?", 1)[0]
        if not code and len(parts) >= 2:
            code = parts[-2].split("?", 1)[0]
        return f"https://cdn.pixeldrain.eu.cc/{code}?download"
    except Exception:
        raise DirectDownloadLinkException("ERROR: Direct link not found")


def streamtape(url):
    splitted_url = url.split("/")
    _id = splitted_url[4] if len(splitted_url) >= 6 else splitted_url[-1]
    try:
        with Session() as session:
            html = HTML(session.get(url).text)
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
    script = html.xpath(
        "//script[contains(text(),'ideoooolink')]/text()"
    ) or html.xpath("//script[contains(text(),'ideoolink')]/text()")
    if not script:
        raise DirectDownloadLinkException("ERROR: requeries script not found")
    if not (link := findall(r"(&expires\S+)'", script[0])):
        raise DirectDownloadLinkException("ERROR: Download link not found")
    return f"https://streamtape.com/get_video?id={_id}{link[-1]}"


def racaty(url):
    with create_scraper() as session:
        try:
            url = session.get(url).url
            json_data = {"op": "download2", "id": url.split("/")[-1]}
            html = HTML(session.post(url, data=json_data).text)
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
    if direct_link := html.xpath("//a[@id='uniqueExpirylink']/@href"):
        return direct_link[0]
    else:
        raise DirectDownloadLinkException("ERROR: Direct link not found")


def uploadhaven(url):
    try:
        res = get(url, headers={"Referer": "http://steamunlocked.net/"})
        html = HTML(res.text)
        if not html.xpath('//form[@method="POST"]//input'):
            raise DirectDownloadLinkException("ERROR: Unable to find link data")
        data = {
            i.get("name"): i.get("value")
            for i in html.xpath('//form[@method="POST"]//input')
        }
        sleep(15)
        res = post(url, data=data, headers={"Referer": url}, cookies=res.cookies)
        html = HTML(res.text)
        if not html.xpath('//div[@class="alert alert-success mb-0"]//a'):
            raise DirectDownloadLinkException("ERROR: Unable to find link data")
        a = html.xpath('//div[@class="alert alert-success mb-0"]//a')[0]
        return a.get("href")
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: {str(e)}") from e


def uploadee(url):
    with create_scraper() as session:
        try:
            html = HTML(session.get(url).text)
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
    if link := html.xpath("//a[@id='d_l']/@href"):
        return link[0]
    else:
        raise DirectDownloadLinkException("ERROR: Direct Link not found")


def filepress(url: str) -> str:
    url = url.rstrip("/")
    scraper = create_scraper()
    scraper.proxies = scraper_proxies

    file_id = url.split("/")[-1]
    url = f"https://filebee.xyz/file/{file_id}"
    raw = urlparse(url)

    try:
        json_data = {"id": file_id, "method": "indexDownlaod"}
        api = f"{raw.scheme}://{raw.hostname}/api/file/downlaod/"
        res2 = scraper.post(
            api,
            headers={"Referer": f"{raw.scheme}://{raw.hostname}"},
            json=json_data,
            timeout=20,
        ).json()

        json_data2 = {
            "id": res2.get("data"),
            "method": "indexDownlaod",
        }
        if json_data2["id"]:
            api2 = f"{raw.scheme}://{raw.hostname}/api/file/downlaod2/"
            res = scraper.post(
                api2,
                headers={"Referer": f"{raw.scheme}://{raw.hostname}"},
                json=json_data2,
                timeout=20,
            ).json()

            data = res.get("data")
            if data:
                if (
                    isinstance(data, list)
                    and len(data) == 1
                    and isinstance(data[0], str)
                ):
                    data = data[0]
                if isinstance(data, str) and data.startswith("http"):
                    data = quote(data, safe=":/?=&%.-_A-Za-z0-9")
                    return data
                elif isinstance(data, str):
                    return f"https://drive.google.com/uc?id={data}&export=download"
    except Exception as e:
        print(f"indexDownlaod debug: {e}")

    try:
        json_data = {
            "id": file_id,
            "method": "publicDownlaod",
        }
        api = f"{raw.scheme}://{raw.hostname}/api/file/downlaod/"
        res2 = scraper.post(
            api,
            headers={"Referer": f"{raw.scheme}://{raw.hostname}"},
            json=json_data,
            timeout=20,
        ).json()

        json_data2 = {
            "id": res2.get("data"),
            "method": "publicUserDownlaod",
        }
        if json_data2["id"]:
            api2 = f"{raw.scheme}://{raw.hostname}/api/file/downlaod2/"
            res = scraper.post(
                api2,
                headers={"Referer": f"{raw.scheme}://{raw.hostname}"},
                json=json_data2,
                timeout=20,
            ).json()

            data = res.get("data")
            if data:
                if (
                    isinstance(data, list)
                    and len(data) == 1
                    and isinstance(data[0], str)
                ):
                    data = data[0]
                if isinstance(data, str) and data.startswith("http"):
                    data = quote(data, safe=":/?=&%.-_A-Za-z0-9")
                    return data
                elif isinstance(data, str):
                    return f"https://drive.google.com/uc?id={data}&export=download"
    except Exception as e:
        print(f"publicDownlaod debug: {e}")

    raise DirectDownloadLinkException("No Valid Download Link Found")


def wetransfer(url):
    with create_scraper() as session:
        try:
            url = session.get(url).url
            splited_url = url.split("/")
            json_data = {"security_hash": splited_url[-1], "intent": "entire_transfer"}
            res = session.post(
                f"https://wetransfer.com/api/v4/transfers/{splited_url[-2]}/download",
                json=json_data,
            ).json()
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
    if "direct_link" in res:
        return res["direct_link"]
    elif "message" in res:
        raise DirectDownloadLinkException(f"ERROR: {res['message']}")
    elif "error" in res:
        raise DirectDownloadLinkException(f"ERROR: {res['error']}")
    else:
        raise DirectDownloadLinkException("ERROR: cannot find direct link")


def akmfiles(url):
    with create_scraper() as session:
        try:
            html = HTML(
                session.post(
                    url,
                    data={"op": "download2", "id": url.split("/")[-1]},
                ).text
            )
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
    if direct_link := html.xpath("//a[contains(@class,'btn btn-dow')]/@href"):
        return direct_link[0]
    else:
        raise DirectDownloadLinkException("ERROR: Direct link not found")


def shrdsk(url):
    with create_scraper() as session:
        try:
            _json = session.get(
                f"https://us-central1-affiliate2apk.cloudfunctions.net/get_data?shortid={url.split('/')[-1]}",
            ).json()
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
        if "download_data" not in _json:
            raise DirectDownloadLinkException("ERROR: Download data not found")
        try:
            _res = session.get(
                f"https://shrdsk.me/download/{_json['download_data']}",
                allow_redirects=False,
            )
            if "Location" in _res.headers:
                return _res.headers["Location"]
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
    raise DirectDownloadLinkException("ERROR: cannot find direct link in headers")


def linkBox(url: str):
    parsed_url = urlparse(url)
    try:
        shareToken = parsed_url.path.split("/")[-1]
    except Exception:
        raise DirectDownloadLinkException("ERROR: invalid URL")

    details = {"contents": [], "title": "", "total_size": 0}

    def __singleItem(session, itemId):
        try:
            _json = session.get(
                "https://www.linkbox.to/api/file/detail",
                params={"itemId": itemId},
            ).json()
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
        data = _json["data"]
        if not data:
            if "msg" in _json:
                raise DirectDownloadLinkException(f"ERROR: {_json['msg']}")
            raise DirectDownloadLinkException("ERROR: data not found")
        itemInfo = data["itemInfo"]
        if not itemInfo:
            raise DirectDownloadLinkException("ERROR: itemInfo not found")
        filename = itemInfo["name"]
        sub_type = itemInfo.get("sub_type")
        if sub_type and not filename.strip().endswith(sub_type):
            filename += f".{sub_type}"
        if not details["title"]:
            details["title"] = filename
        item = {
            "path": "",
            "filename": filename,
            "url": itemInfo["url"],
        }
        if "size" in itemInfo:
            size = itemInfo["size"]
            if isinstance(size, str) and size.isdigit():
                size = float(size)
            details["total_size"] += size
        details["contents"].append(item)

    def __fetch_links(session, _id=0, folderPath=""):
        params = {
            "shareToken": shareToken,
            "pageSize": 1000,
            "pid": _id,
        }
        try:
            _json = session.get(
                "https://www.linkbox.to/api/file/share_out_list",
                params=params,
            ).json()
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
        data = _json["data"]
        if not data:
            if "msg" in _json:
                raise DirectDownloadLinkException(f"ERROR: {_json['msg']}")
            raise DirectDownloadLinkException("ERROR: data not found")
        try:
            if data["shareType"] == "singleItem":
                return __singleItem(session, data["itemId"])
        except Exception:
            pass
        if not details["title"]:
            details["title"] = data["dirName"]
        contents = data["list"]
        if not contents:
            return
        for content in contents:
            if content["type"] == "dir" and "url" not in content:
                if not folderPath:
                    newFolderPath = ospath.join(details["title"], content["name"])
                else:
                    newFolderPath = ospath.join(folderPath, content["name"])
                if not details["title"]:
                    details["title"] = content["name"]
                __fetch_links(session, content["id"], newFolderPath)
            elif "url" in content:
                if not folderPath:
                    folderPath = details["title"]
                filename = content["name"]
                if (
                    sub_type := content.get("sub_type")
                ) and not filename.strip().endswith(sub_type):
                    filename += f".{sub_type}"
                item = {
                    "path": ospath.join(folderPath),
                    "filename": filename,
                    "url": content["url"],
                }
                if "size" in content:
                    size = content["size"]
                    if isinstance(size, str) and size.isdigit():
                        size = float(size)
                    details["total_size"] += size
                details["contents"].append(item)

    try:
        with Session() as session:
            __fetch_links(session)
    except DirectDownloadLinkException as e:
        raise e
    return details


def gofile(url):
    proxy_api_url = f"https://gofile.dzhq.workers.dev/?url={quote(url, safe='')}"
    try:
        resp = get(proxy_api_url, timeout=30)
        resp_json = resp.json()
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}")

    contents = []

    if "contents" in resp_json and resp_json["contents"]:
        for item in resp_json["contents"]:
            size_str = item.get("size", "0")
            size = 0
            try:
                size = float(size_str.replace(" GB", "").replace(" MB", "").replace(" KB", "")) * (
                    1024 * 1024 * 1024
                    if "GB" in size_str
                    else 1024 * 1024
                    if "MB" in size_str
                    else 1024
                    if "KB" in size_str
                    else 1
                )
            except (ValueError, AttributeError):
                pass
            contents.append(
                {
                    "path": item.get("path", ""),
                    "filename": item.get("filename"),
                    "url": item.get("proxy_url") or item.get("url"),
                    "size": size,
                }
            )
        title = resp_json.get("title", "")
        header = resp_json.get("header", "")
    elif resp_json.get("proxy_url") or resp_json.get("url"):
        size_str = resp_json.get("size", "0")
        size = 0
        try:
            size = float(size_str.replace(" GB", "").replace(" MB", "").replace(" KB", "")) * (
                1024 * 1024 * 1024
                if "GB" in size_str
                else 1024 * 1024
                if "MB" in size_str
                else 1024
                if "KB" in size_str
                else 1
            )
        except (ValueError, AttributeError):
            pass
        contents.append(
            {
                "path": "",
                "filename": resp_json.get("filename"),
                "url": resp_json.get("proxy_url") or resp_json.get("url"),
                "size": size,
            }
        )
        title = resp_json.get("filename", "")
        header = resp_json.get("header", "")
    else:
        raise DirectDownloadLinkException("ERROR: No downloadable content found")

    total_size = sum(c.get("size", 0) for c in contents)
    if len(contents) == 1:
        return (contents[0]["url"], header)
    return {
        "contents": contents,
        "title": title,
        "total_size": total_size,
        "header": header,
    }


def mediafireFolder(url):
    if "::" in url:
        _password = url.split("::")[-1]
        url = url.split("::")[-2]
    else:
        _password = ""
    try:
        raw = url.split("/", 4)[-1]
        folderkey = raw.split("/", 1)[0]
        folderkey = folderkey.split(",")
    except:
        raise DirectDownloadLinkException("ERROR: Could not parse ")
    if len(folderkey) == 1:
        folderkey = folderkey[0]
    details = {"contents": [], "title": "", "total_size": 0, "header": ""}

    session = create_scraper()
    adapter = HTTPAdapter(
        max_retries=Retry(total=10, read=10, connect=10, backoff_factor=0.3)
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session = create_scraper(
        browser={"browser": "firefox", "platform": "windows", "mobile": False},
        delay=10,
        sess=session,
    )
    folder_infos = []

    def __get_info(folderkey):
        try:
            if isinstance(folderkey, list):
                folderkey = ",".join(folderkey)
            _json = session.post(
                "https://www.mediafire.com/api/1.5/folder/get_info.php",
                data={
                    "recursive": "yes",
                    "folder_key": folderkey,
                    "response_format": "json",
                },
            ).json()
        except Exception as e:
            raise DirectDownloadLinkException(
                f"ERROR: {e.__class__.__name__} While getting info"
            )
        _res = _json["response"]
        if "folder_infos" in _res:
            folder_infos.extend(_res["folder_infos"])
        elif "folder_info" in _res:
            folder_infos.append(_res["folder_info"])
        elif "message" in _res:
            raise DirectDownloadLinkException(f"ERROR: {_res['message']}")
        else:
            raise DirectDownloadLinkException("ERROR: something went wrong!")

    try:
        __get_info(folderkey)
    except Exception as e:
        raise DirectDownloadLinkException(e)

    details["title"] = folder_infos[0]["name"]

    def __scraper(url):
        session = create_scraper()
        parsed_url = urlparse(url)
        url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"

        try:
            html = HTML(session.get(url).text)
        except:
            return None
        if html.xpath("//div[@class='passwordPrompt']"):
            if not _password:
                raise DirectDownloadLinkException(
                    f"ERROR: {PASSWORD_ERROR_MESSAGE}".format(url)
                )
            try:
                html = HTML(session.post(url, data={"downloadp": _password}).text)
            except:
                return None
            if html.xpath("//div[@class='passwordPrompt']"):
                return None
        try:
            final_link = __decode_url(html)
        except:
            return None
        return final_link

    def __decode_url(html):
        enc_url = html.xpath('//a[@id="downloadButton"]')
        if enc_url:
            final_link = enc_url[0].attrib.get("href")
            scrambled = enc_url[0].attrib.get("data-scrambled-url")
            if final_link and scrambled:
                try:
                    final_link = b64decode(scrambled).decode("utf-8")
                    return final_link
                except:
                    return None
            elif final_link.startswith("http"):
                return final_link
            elif final_link.startswith("//"):
                return __scraper(f"https:{final_link}")
            else:
                return None
        else:
            return None

    def __get_content(folderKey, folderPath="", content_type="folders"):
        try:
            params = {
                "content_type": content_type,
                "folder_key": folderKey,
                "response_format": "json",
            }
            _json = session.get(
                "https://www.mediafire.com/api/1.5/folder/get_content.php",
                params=params,
            ).json()
        except Exception as e:
            raise DirectDownloadLinkException(
                f"ERROR: {e.__class__.__name__} While getting content"
            )
        _res = _json["response"]
        if "message" in _res:
            raise DirectDownloadLinkException(f"ERROR: {_res['message']}")
        _folder_content = _res["folder_content"]
        if content_type == "folders":
            folders = _folder_content["folders"]
            for folder in folders:
                if folderPath:
                    newFolderPath = ospath.join(folderPath, folder["name"])
                else:
                    newFolderPath = ospath.join(folder["name"])
                __get_content(folder["folderkey"], newFolderPath)
            __get_content(folderKey, folderPath, "files")
        else:
            files = _folder_content["files"]
            for file in files:
                item = {}
                if not (_url := __scraper(file["links"]["normal_download"])):
                    continue
                item["filename"] = file["filename"]
                if not folderPath:
                    folderPath = details["title"]
                item["path"] = ospath.join(folderPath)
                item["url"] = _url
                if "size" in file:
                    size = file["size"]
                    if isinstance(size, str) and size.isdigit():
                        size = float(size)
                    details["total_size"] += size
                details["contents"].append(item)

    try:
        for folder in folder_infos:
            __get_content(folder["folderkey"], folder["name"])
    except Exception as e:
        raise DirectDownloadLinkException(e)
    finally:
        session.close()
    if len(details["contents"]) == 1:
        return (details["contents"][0]["url"], [details["header"]])
    return details


def vikingfile(url: str) -> str:
    import aiohttp
    from aiohttp_socks import ProxyConnector

    async def _run(url: str) -> str | None:
        connector = ProxyConnector.from_url(PROXY_URL)

        async with aiohttp.ClientSession(connector=connector) as session:
            # 1) Fetch proxy IPv4 (required by backend)
            async with session.get("https://api.ipify.org") as resp:
                proxy_ip = (await resp.text()).strip()

            # 2) Load VikingFile page
            async with session.get(url) as resp:
                final_url = str(resp.url)
                html = await resp.text()

            key_match = re.search(r"sitekey:\s*'([^']+)", html)
            if not key_match:
                raise RuntimeError("Turnstile sitekey not found on page")

            sitekey = key_match.group(1)

            # 3) Solve Turnstile
            payload = {
                "mode": "turnstile",
                "domain": url,
                "siteKey": sitekey,
            }

            async with session.post(TURNSTILE_SOLVER_URL, json=payload) as resp:
                data = await resp.json()

            token = data.get("token")
            if not token:
                raise RuntimeError("Turnstile solver did not return token")

            # 4) Submit form with token + IPv4
            form_data = {
                "cf-turnstile-response": token,
                "ipv4": proxy_ip,
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
            }

            async with session.post(final_url, headers=headers, data=form_data) as resp:
                result = await resp.json()

            return result.get("link")

    try:
        result = asyncio.run(_run(url))
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: VikingFile bypass failed: {e}")

    if not result:
        raise DirectDownloadLinkException("ERROR: Unable to bypass VikingFile")

    return result


def send_cm_file(url, file_id=None):
    if "::" in url:
        _password = url.split("::")[-1]
        url = url.split("::")[-2]
    else:
        _password = ""
    _passwordNeed = False
    with create_scraper() as session:
        if file_id is None:
            try:
                html = HTML(session.get(url).text)
            except Exception as e:
                raise DirectDownloadLinkException(
                    f"ERROR: {e.__class__.__name__}"
                ) from e
            if html.xpath("//input[@name='password']"):
                _passwordNeed = True
            if not (file_id := html.xpath("//input[@name='id']/@value")):
                raise DirectDownloadLinkException("ERROR: file_id not found")
        try:
            data = {"op": "download2", "id": file_id}
            if _password and _passwordNeed:
                data["password"] = _password
            _res = session.post("https://send.cm/", data=data, allow_redirects=False)
            if "Location" in _res.headers:
                return (_res.headers["Location"], "Referer: https://send.cm/")
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
        if _passwordNeed:
            raise DirectDownloadLinkException(
                f"ERROR:\n{PASSWORD_ERROR_MESSAGE.format(url)}"
            )
        raise DirectDownloadLinkException("ERROR: Direct link not found")


def send_cm(url):
    if "/d/" in url:
        return send_cm_file(url)
    elif "/s/" not in url:
        file_id = url.split("/")[-1]
        return send_cm_file(url, file_id)
    splitted_url = url.split("/")
    details = {
        "contents": [],
        "title": "",
        "total_size": 0,
        "header": "Referer: https://send.cm/",
    }
    if len(splitted_url) == 5:
        url += "/"
        splitted_url = url.split("/")
    if len(splitted_url) >= 7:
        details["title"] = splitted_url[5]
    else:
        details["title"] = splitted_url[-1]
    session = Session()

    def __collectFolders(html):
        folders = []
        folders_urls = html.xpath("//h6/a/@href")
        folders_names = html.xpath("//h6/a/text()")
        for folders_url, folders_name in zip(folders_urls, folders_names):
            folders.append(
                {
                    "folder_link": folders_url.strip(),
                    "folder_name": folders_name.strip(),
                }
            )
        return folders

    def __getFile_link(file_id):
        try:
            _res = session.post(
                "https://send.cm/",
                data={"op": "download2", "id": file_id},
                allow_redirects=False,
            )
            if "Location" in _res.headers:
                return _res.headers["Location"]
        except Exception:
            pass

    def __getFiles(html):
        files = []
        hrefs = html.xpath('//tr[@class="selectable"]//a/@href')
        file_names = html.xpath('//tr[@class="selectable"]//a/text()')
        sizes = html.xpath('//tr[@class="selectable"]//span/text()')
        for href, file_name, size_text in zip(hrefs, file_names, sizes):
            files.append(
                {
                    "file_id": href.split("/")[-1],
                    "file_name": file_name.strip(),
                    "size": speed_string_to_bytes(size_text.strip()),
                }
            )
        return files

    def __writeContents(html_text, folderPath=""):
        folders = __collectFolders(html_text)
        for folder in folders:
            _html = HTML(cf_bypass(folder["folder_link"]))
            __writeContents(_html, ospath.join(folderPath, folder["folder_name"]))
        files = __getFiles(html_text)
        for file in files:
            if not (link := __getFile_link(file["file_id"])):
                continue
            item = {"url": link, "filename": file["filename"], "path": folderPath}
            details["total_size"] += file["size"]
            details["contents"].append(item)

    try:
        mainHtml = HTML(cf_bypass(url))
    except DirectDownloadLinkException as e:
        session.close()
        raise e
    except Exception as e:
        session.close()
        raise DirectDownloadLinkException(
            f"ERROR: {e.__class__.__name__} While getting mainHtml"
        )
    try:
        __writeContents(mainHtml, details["title"])
    except DirectDownloadLinkException as e:
        session.close()
        raise e
    except Exception as e:
        session.close()
        raise DirectDownloadLinkException(
            f"ERROR: {e.__class__.__name__} While writing Contents"
        )
    session.close()
    if len(details["contents"]) == 1:
        return (details["contents"][0]["url"], details["header"])
    return details


def streamvid(url: str):
    file_code = url.split("/")[-1]
    parsed_url = urlparse(url)
    url = f"{parsed_url.scheme}://{parsed_url.hostname}/d/{file_code}"
    quality_defined = bool(url.strip().endswith(("_o", "_h", "_n", "_l")))
    with create_scraper() as session:
        try:
            html = HTML(session.get(url).text)
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
        if quality_defined:
            data = {}
            if not (inputs := html.xpath('//form[@id="F1"]//input')):
                raise DirectDownloadLinkException("ERROR: No inputs found")
            for i in inputs:
                if key := i.get("name"):
                    data[key] = i.get("value")
            try:
                html = HTML(session.post(url, data=data).text)
            except Exception as e:
                raise DirectDownloadLinkException(
                    f"ERROR: {e.__class__.__name__}"
                ) from e
            if not (
                script := html.xpath(
                    '//script[contains(text(),"document.location.href")]/text()'
                )
            ):
                if error := html.xpath(
                    '//div[@class="alert alert-danger"][1]/text()[2]'
                ):
                    raise DirectDownloadLinkException(f"ERROR: {error[0]}")
                raise DirectDownloadLinkException(
                    "ERROR: direct link script not found!"
                )
            if directLink := findall(r'document\.location\.href="(.*)"', script[0]):
                return directLink[0]
            raise DirectDownloadLinkException(
                "ERROR: direct link not found! in the script"
            )
        elif (qualities_urls := html.xpath('//div[@id="dl_versions"]/a/@href')) and (
            qualities := html.xpath('//div[@id="dl_versions"]/a/text()[2]')
        ):
            error = "\nProvide a quality to download the video\nAvailable Quality:"
            for quality_url, quality in zip(qualities_urls, qualities):
                error += f"\n{quality.strip()} <code>{quality_url}</code>"
            raise DirectDownloadLinkException(f"ERROR: {error}")
        elif error := html.xpath('//div[@class="not-found-text"]/text()'):
            raise DirectDownloadLinkException(f"ERROR: {error[0]}")
        raise DirectDownloadLinkException("ERROR: Something went wrong")


def streamhub(url):
    file_code = url.split("/")[-1]
    parsed_url = urlparse(url)
    url = f"{parsed_url.scheme}://{parsed_url.hostname}/d/{file_code}"
    with create_scraper() as session:
        try:
            html = HTML(session.get(url).text)
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
        if not (inputs := html.xpath('//form[@name="F1"]//input')):
            raise DirectDownloadLinkException("ERROR: No inputs found")
        data = {}
        for i in inputs:
            if key := i.get("name"):
                data[key] = i.get("value")
        session.headers.update({"referer": url})
        sleep(1)
        try:
            html = HTML(session.post(url, data=data).text)
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
        if directLink := html.xpath(
            '//a[@class="btn btn-primary btn-go downloadbtn"]/@href'
        ):
            return directLink[0]
        if error := html.xpath('//div[@class="alert alert-danger"]/text()[2]'):
            raise DirectDownloadLinkException(f"ERROR: {error[0]}")
        raise DirectDownloadLinkException("ERROR: direct link not found!")


def pcloud(url):
    with create_scraper() as session:
        try:
            res = session.get(url)
        except Exception as e:
            raise DirectDownloadLinkException(f"ERROR: {e.__class__.__name__}") from e
    if link := findall(r".downloadlink.:..(https:.*)..", res.text):
        return link[0].replace(r"\/", "/")
    raise DirectDownloadLinkException("ERROR: Direct link not found")


def swisstransfer(link):
    matched_link = match(
        r"https://www\.swisstransfer\.com/d/([\w-]+)(?:\:\:(\w+))?", link
    )
    if not matched_link:
        raise DirectDownloadLinkException(
            f"ERROR: Invalid SwissTransfer link format {link}"
        )

    transfer_id, password = matched_link.groups()
    password = password or ""

    def encode_password(password):
        return b64encode(password.encode("utf-8")).decode("utf-8") if password else ""

    def getfile(transfer_id, password):
        url = f"https://www.swisstransfer.com/api/links/{transfer_id}"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Authorization": encode_password(password) if password else "",
            "Content-Type": "application/json" if not password else "",
        }
        response = get(url, headers=headers)

        if response.status_code == 200:
            try:
                return response.json(), headers
            except ValueError:
                raise DirectDownloadLinkException(
                    f"ERROR: Error parsing JSON response {response.text}"
                )
        raise DirectDownloadLinkException(
            f"ERROR: Error fetching file details {response.status_code}, {response.text}"
        )

    def gettoken(password, containerUUID, fileUUID):
        url = "https://www.swisstransfer.com/api/generateDownloadToken"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
        }
        body = {
            "password": password,
            "containerUUID": containerUUID,
            "fileUUID": fileUUID,
        }

        response = post(url, headers=headers, json=body)

        if response.status_code == 200:
            return response.text.strip().replace('"', "")
        raise DirectDownloadLinkException(
            f"ERROR: Error generating download token {response.status_code}, {response.text}"
        )

    data, headers = getfile(transfer_id, password)
    if not data:
        return None

    try:
        container_uuid = data["data"]["containerUUID"]
        download_host = data["data"]["downloadHost"]
        files = data["data"]["container"]["files"]
        folder_name = data["data"]["container"]["message"] or "unknown"
    except (KeyError, IndexError, TypeError) as e:
        raise DirectDownloadLinkException(f"ERROR: Error parsing file details {e}")

    total_size = sum(file["fileSizeInBytes"] for file in files)

    if len(files) == 1:
        file = files[0]
        file_uuid = file["UUID"]
        token = gettoken(password, container_uuid, file_uuid)
        download_url = f"https://{download_host}/api/download/{transfer_id}/{file_uuid}?token={token}"
        return download_url, "User-Agent:Mozilla/5.0"

    contents = []
    for file in files:
        file_uuid = file["UUID"]
        file_name = file["fileName"]
        file["fileSizeInBytes"]

        token = gettoken(password, container_uuid, file_uuid)
        if not token:
            continue

        download_url = f"https://{download_host}/api/download/{transfer_id}/{file_uuid}?token={token}"
        contents.append({"filename": file_name, "path": "", "url": download_url})

    return {
        "contents": contents,
        "title": folder_name,
        "total_size": total_size,
        "header": "User-Agent:Mozilla/5.0",
    }


def instagram(link: str) -> str:
    api_url = Config.INSTADL_API or "https://instagramcdn.vercel.app"
    full_url = f"{api_url}/api/video?postUrl={link}"

    try:
        response = get(full_url)
        response.raise_for_status()
        data = response.json()

        if (
            data.get("status") == "success"
            and "data" in data
            and "videoUrl" in data["data"]
        ):
            return data["data"]["videoUrl"]

        raise DirectDownloadLinkException("ERROR: Failed to retrieve video URL.")

    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: {e}")
