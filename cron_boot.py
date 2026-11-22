from time import sleep, monotonic
from os import getenv, path
from logging import error as logerror
from urllib.parse import urlparse

from niquests import get as rget

import http.client
import json
import socket
import ssl


def _load_url():
    try:
        with open("tunnel_url.txt") as f:
            url = f.read().strip().rstrip("/")
        if url:
            return url
    except OSError:
        pass
    base = getenv("BASE_URL", None)
    return base.rstrip("/") if isinstance(base, str) else None


DOH_SERVERS = [
    ("cloudflare-dns.com", "1.1.1.1"),
    ("dns.google", "8.8.8.8"),
    ("dns.quad9.net", "9.9.9.9"),
]


def _get_ip(host, timeout=10):
    try:
        return socket.gethostbyname(host)
    except Exception:
        pass
    for hostname, ip in DOH_SERVERS:
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((ip, 443), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=hostname) as tls:
                    tls.sendall(
                        f"GET /dns-query?name={host}&type=A HTTP/1.1\r\n"
                        f"Host: {hostname}\r\n"
                        "Accept: application/dns-json\r\n"
                        "Connection: close\r\n\r\n".encode()
                    )
                    data = b""
                    while chunk := tls.recv(65536):
                        data += chunk
            body = data.split(b"\r\n\r\n", 1)[1]
            for answer in json.loads(body).get("Answer", []):
                if answer.get("type") == 1:
                    return answer["data"]
        except Exception:
            continue
    return None


def _ping_ip(host, ip, path, timeout=10):
    real_create = socket.create_connection

    def create_connection(address, *args, **kwargs):
        return real_create((ip, address[1]), *args, **kwargs)

    socket.create_connection = create_connection
    try:
        conn = http.client.HTTPSConnection(host, timeout=timeout)
        conn.request("GET", path or "/")
        conn.getresponse().status
        conn.close()
        return True
    finally:
        socket.create_connection = real_create


def ping(url, timeout=10):
    try:
        rget(url, timeout=timeout).status_code
        return True
    except Exception:
        pass
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    ip = _get_ip(parsed.hostname, timeout)
    if not ip:
        return False
    return _ping_ip(parsed.hostname, ip, parsed.path, timeout)


PORT = getenv("PORT", None)
BASE_URL = _load_url()
if PORT is not None and BASE_URL is not None:
    failures = 0
    last_log = 0.0
    while True:
        BASE_URL = _load_url()
        try:
            if ping(BASE_URL):
                failures = 0
                sleep(600)
                continue
        except Exception:
            pass
        failures += 1
        now = monotonic()
        if failures == 30 or (failures > 30 and now - last_log > 900):
            last_log = now
            logerror(f"cron_boot.py: {BASE_URL} is unreachable (attempt {failures})")
        sleep(2)
        continue
