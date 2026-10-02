#!/usr/bin/env python3

from __future__ import annotations

import base64
import html
import json
import os
import platform
import re
import stat
import subprocess
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import (
    parse_qs,
    quote,
    urlencode,
    unquote,
    urlsplit,
)

import requests


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_CHANNEL = os.getenv(
    "TELEGRAM_CHANNEL",
    "happvpn",
).strip().lstrip("@").rstrip("/")

GIST_TOKEN = os.getenv(
    "GIST_TOKEN",
    "",
).strip()

GIST_ID = os.getenv(
    "GIST_ID",
    "",
).strip()

GIST_FILENAME = os.getenv(
    "GIST_FILENAME",
    "configs.txt",
).strip()

REQUEST_TIMEOUT = int(
    os.getenv(
        "REQUEST_TIMEOUT",
        "30",
    )
)

MAX_SOURCE_SIZE = int(
    os.getenv(
        "MAX_SOURCE_SIZE",
        str(10 * 1024 * 1024),
    )
)

DEBUG_PREVIEW = int(
    os.getenv(
        "DEBUG_PREVIEW",
        "500",
    )
)


# ============================================================
# HPWNR
# ============================================================

HPWNR_BIN = os.getenv(
    "HPWNR_BIN",
    "",
).strip()

HPWNR_DIR = Path(
    os.getenv(
        "HPWNR_DIR",
        ".hpwnr",
    )
)

AUTO_INSTALL_HPWNR = os.getenv(
    "AUTO_INSTALL_HPWNR",
    "1",
).strip().lower() not in (
    "0",
    "false",
    "no",
)

HPWNR_REPO = "Omegaplexx/hpwnr"


# ============================================================
# HTTP
# ============================================================

USER_AGENT = (
    "Mozilla/5.0 "
    "(Linux; Android 14) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/140.0 Mobile Safari/537.36"
)

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
})


# ============================================================
# PROTOCOLS
# ============================================================

PROTOCOLS = (
    "vless://",
    "vmess://",
    "trojan://",
    "ss://",
    "ssconf://",
    "hysteria://",
    "hysteria2://",
    "hy2://",
    "tuic://",
    "wireguard://",
)


# ============================================================
# HAPP
# ============================================================

HAPP_SCHEMES = (
    "happ://crypt/",
    "happ://crypt2/",
    "happ://crypt3/",
    "happ://crypt4/",
    "happ://crypt5/",
)


# ============================================================
# HTML PARSER
# ============================================================

class TelegramHTMLParser(HTMLParser):

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.links = []
        self.text_parts = []

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        if tag.lower() != "a":
            return

        for key, value in attrs:

            if (
                key.lower() == "href"
                and value
            ):

                self.links.append(
                    html.unescape(
                        value.strip()
                    )
                )

    def handle_data(
        self,
        data,
    ):

        if data:
            self.text_parts.append(data)


# ============================================================
# HELPERS
# ============================================================

def normalize_url(
    url: str,
) -> str:

    url = html.unescape(url).strip()

    url = url.replace(
        "\\/",
        "/",
    )

    url = url.strip(
        " \t\r\n<>\"'`()[]{}"
    )

    return url


def is_http_url(
    url: str,
) -> bool:

    try:

        parsed = urlsplit(url)

        return (
            parsed.scheme.lower()
            in ("http", "https")
            and bool(parsed.netloc)
        )

    except Exception:

        return False


def unique_preserve_order(items):

    result = []
    seen = set()

    for item in items:

        if item not in seen:

            seen.add(item)
            result.append(item)

    return result


def clean_config(
    value: str,
) -> str:

    value = html.unescape(value)

    value = value.replace(
        "\\/",
        "/",
    )

    return value.strip(
        " \t\r\n\"'`<>()[]{} ,;"
    )


def first_value(
    obj,
    *keys,
    default=None,
):
    for key in keys:

        value = obj.get(key)

        if value is not None and value != "":
            return value

    return default


# ============================================================
# TELEGRAM
# ============================================================

def get_channel_page():

    url = (
        f"https://t.me/s/"
        f"{TELEGRAM_CHANNEL}"
    )

    print(
        f"[TELEGRAM] Reading channel: {url}"
    )

    response = SESSION.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )

    print(
        f"[TELEGRAM] HTTP "
        f"{response.status_code} "
        f"{len(response.content)} bytes"
    )

    response.raise_for_status()

    return response.text


def get_last_post_url(
    channel_html: str,
):

    pattern = re.compile(
        rf"https?://t\.me/"
        rf"{re.escape(TELEGRAM_CHANNEL)}"
        rf"/(\d+)",
        re.I,
    )

    ids = [
        int(x)
        for x in pattern.findall(channel_html)
    ]

    if not ids:

        pattern = re.compile(
            rf"/(?:s/)?"
            rf"{re.escape(TELEGRAM_CHANNEL)}"
            rf"/(\d+)",
            re.I,
        )

        ids = [
            int(x)
            for x in pattern.findall(channel_html)
        ]

    if not ids:

        raise RuntimeError(
            "Could not find Telegram message IDs"
        )

    last_id = max(ids)

    post_url = (
        f"https://t.me/"
        f"{TELEGRAM_CHANNEL}/"
        f"{last_id}"
    )

    print(
        f"[TELEGRAM] Last post ID: {last_id}"
    )

    print(
        f"[TELEGRAM] Last post: {post_url}"
    )

    return post_url


def fetch_post(
    post_url: str,
):

    url = post_url + "?embed=1"

    print(
        f"[TELEGRAM] GET {url}"
    )

    response = SESSION.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )

    print(
        f"[TELEGRAM] HTTP "
        f"{response.status_code} "
        f"{len(response.content)} bytes"
    )

    response.raise_for_status()

    return response.text


# ============================================================
# URL FILTER
# ============================================================

def is_ignored_url(
    url: str,
) -> bool:

    low = url.lower()

    try:

        parsed = urlsplit(url)

        host = (
            parsed.hostname
            or ""
        ).lower()

        path = (
            parsed.path
            or ""
        ).lower()

    except Exception:

        return True

    ignored_hosts = (
        "t.me",
        "telegram.me",
        "telegram.org",
        "oauth.tg.dev",
    )

    if host in ignored_hosts:
        return True

    ignored_fragments = (
        "telegram-widget.js",
        "/js/telegram-widget",
    )

    if any(
        x in low
        for x in ignored_fragments
    ):
        return True

    media = (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".bmp",
        ".svg",
        ".ico",
        ".mp4",
        ".webm",
        ".mov",
        ".mp3",
        ".ogg",
        ".wav",
        ".js",
        ".css",
        ".woff",
        ".woff2",
    )

    if path.endswith(media):
        return True

    return False


# ============================================================
# HAPP
# ============================================================

def extract_happ_links(
    text: str,
):

    if not text:
        return []

    text = html.unescape(text)

    text = text.replace(
        "\\/",
        "/",
    )

    pattern = re.compile(
        r"(?i)"
        r"happ://crypt(?:2|3|4|5)?/"
        r"[A-Za-z0-9+/=_-]+"
    )

    found = pattern.findall(text)

    result = []

    for item in found:

        item = normalize_url(item)

        if item:
            result.append(item)

    return unique_preserve_order(result)


def get_hpwrr_platform():

    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":

        if machine in ("x86_64", "amd64"):
            return "hpwnr-linux-x86_64"

        if machine in ("aarch64", "arm64"):
            return "hpwnr-linux-arm64"

        if machine in ("armv7l", "armv7"):
            return "hpwnr-linux-armv7"

        if machine in ("i386", "i686", "x86"):
            return "hpwnr-linux-x86"

        if machine == "riscv64":
            return "hpwnr-linux-riscv64"

    if system == "android":

        if machine in ("aarch64", "arm64"):
            return "hpwnr-android-arm64"

        if machine in ("armv7l", "armv7"):
            return "hpwnr-android-armv7"

        if machine in ("x86_64", "amd64"):
            return "hpwnr-android-x86_64"

        if machine in ("i386", "i686", "x86"):
            return "hpwnr-android-x86"

    if system == "darwin":

        if machine in ("arm64", "aarch64"):
            return "hpwnr-macos-arm64"

        if machine in ("x86_64", "amd64"):
            return "hpwnr-macos-x86_64"

    if system == "windows":

        if machine in ("x86_64", "amd64"):
            return "hpwnr-windows-x64.exe"

        if machine in ("i386", "i686", "x86"):
            return "hpwnr-windows-x86.exe"

    raise RuntimeError(
        "Unsupported hpwnr platform: "
        f"system={system}, architecture={machine}"
    )


def find_hpwrr_local():

    if HPWNR_BIN:

        path = Path(HPWNR_BIN)

        if path.exists():
            return str(path)

        return HPWNR_BIN

    try:

        result = subprocess.run(
            ["hpwnr", "h"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode in (0, 1):
            return "hpwnr"

    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
        OSError,
    ):

        pass

    local = (
        HPWNR_DIR
        / (
            "hpwnr.exe"
            if platform.system().lower() == "windows"
            else "hpwnr"
        )
    )

    if local.exists():
        return str(local)

    return None


def install_hpwrr():

    if not AUTO_INSTALL_HPWNR:

        raise RuntimeError(
            "hpwnr is not installed and "
            "AUTO_INSTALL_HPWNR=0"
        )

    asset_name = get_hpwrr_platform()

    print()
    print("[HPWNR] hpwnr not found")
    print(f"[HPWNR] Asset: {asset_name}")

    api_url = (
        "https://api.github.com/repos/"
        f"{HPWNR_REPO}/releases/latest"
    )

    headers = {
        "Accept":
            "application/vnd.github+json",
        "X-GitHub-Api-Version":
            "2022-11-28",
        "User-Agent":
            "telegram-v2ray-parser",
    }

    print(
        "[HPWNR] Getting latest release..."
    )

    response = SESSION.get(
        api_url,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    release = response.json()

    release_tag = release.get(
        "tag_name",
        "unknown",
    )

    print(
        f"[HPWNR] Release: {release_tag}"
    )

    assets = release.get(
        "assets",
        [],
    )

    asset = None

    for candidate in assets:

        if candidate.get("name") == asset_name:

            asset = candidate
            break

    if asset is None:

        available = [
            x.get("name")
            for x in assets
        ]

        raise RuntimeError(
            "Could not find hpwnr asset "
            f"{asset_name}. Available: {available}"
        )

    download_url = asset.get(
        "browser_download_url"
    )

    if not download_url:

        raise RuntimeError(
            "hpwnr release asset has no download URL"
        )

    HPWNR_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    binary_name = (
        "hpwnr.exe"
        if platform.system().lower() == "windows"
        else "hpwnr"
    )

    binary_path = (
        HPWNR_DIR / binary_name
    )

    print("[HPWNR] Downloading:")
    print(download_url)

    response = SESSION.get(
        download_url,
        headers={
            "User-Agent":
                "telegram-v2ray-parser",
        },
        timeout=REQUEST_TIMEOUT,
        stream=True,
    )

    response.raise_for_status()

    downloaded = 0

    with open(binary_path, "wb") as file:

        for chunk in response.iter_content(
            chunk_size=65536
        ):

            if not chunk:
                continue

            file.write(chunk)
            downloaded += len(chunk)

    if (
        platform.system().lower()
        != "windows"
    ):

        current_mode = binary_path.stat().st_mode

        binary_path.chmod(
            current_mode
            | stat.S_IXUSR
            | stat.S_IXGRP
            | stat.S_IXOTH
        )

    if not binary_path.exists():

        raise RuntimeError(
            "hpwnr download finished "
            "but binary does not exist"
        )

    if binary_path.stat().st_size == 0:

        raise RuntimeError(
            "Downloaded hpwnr binary is empty"
        )

    print(
        f"[HPWNR] Downloaded: {downloaded} bytes"
    )

    print("[HPWNR] Installed:")
    print(binary_path)

    return str(binary_path)


def get_hpwnr():

    existing = find_hpwrr_local()

    if existing:

        print(
            f"[HPWNR] Using: {existing}"
        )

        return existing

    return install_hpwrr()


def decrypt_happ_link(
    hpwnr_path: str,
    happ_link: str,
):

    print()
    print("[HAPP] Decrypting:")

    print(
        happ_link[:120]
        + (
            "..."
            if len(happ_link) > 120
            else ""
        )
    )

    try:

        result = subprocess.run(
            [
                hpwnr_path,
                happ_link,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=REQUEST_TIMEOUT,
        )

    except FileNotFoundError as exc:

        raise RuntimeError(
            "hpwnr executable could not "
            f"be started: {exc}"
        )

    except subprocess.TimeoutExpired:

        print("[HAPP] ERROR: timeout")
        return None

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0:

        print("[HAPP] ERROR:")

        if stderr:
            print(stderr[:3000])
        else:
            print(
                f"[HAPP] hpwnr exit code: "
                f"{result.returncode}"
            )

        return None

    if not stdout:

        print("[HAPP] Empty result")

        if stderr:
            print(stderr[:1000])

        return None

    if is_http_url(stdout):

        decrypted = stdout

    else:

        urls = re.findall(
            r"https?://[^\s\"'<>]+",
            stdout,
            re.I,
        )

        if not urls:

            print(
                "[HAPP] No HTTP URL "
                "in decrypted result"
            )

            print(stdout[:1000])

            return None

        decrypted = normalize_url(
            urls[0]
        )

    decrypted = normalize_url(
        decrypted
    )

    print("[HAPP] Decrypted:")
    print(decrypted)

    return decrypted


def process_happ_links(
    post_html: str,
):

    happ_links = extract_happ_links(
        post_html
    )

    print()
    print("=" * 70)
    print(
        f"[HAPP] Encrypted links: "
        f"{len(happ_links)}"
    )
    print("=" * 70)

    if not happ_links:
        return []

    hpwnr_path = get_hpwnr()

    decrypted_urls = []

    for index, happ_link in enumerate(
        happ_links,
        1,
    ):

        print()
        print(
            f"[HAPP] "
            f"{index}/{len(happ_links)}"
        )

        try:

            decrypted = decrypt_happ_link(
                hpwnr_path,
                happ_link,
            )

        except Exception as exc:

            print("[HAPP] Exception:")
            print(repr(exc))
            continue

        if not decrypted:
            continue

        if is_http_url(decrypted):

            decrypted_urls.append(
                decrypted
            )

    decrypted_urls = unique_preserve_order(
        decrypted_urls
    )

    print()
    print(
        f"[HAPP] Decrypted HTTP(S) sources: "
        f"{len(decrypted_urls)}"
    )

    for url in decrypted_urls:
        print(f"  {url}")

    return decrypted_urls


# ============================================================
# NORMAL TELEGRAM HTTPS URLS
# ============================================================

def extract_post_urls(
    post_html: str,
):

    parser = TelegramHTMLParser()

    parser.feed(post_html)

    urls = []

    for url in parser.links:

        url = normalize_url(url)

        if (
            is_http_url(url)
            and not is_ignored_url(url)
        ):

            urls.append(url)

    text = "\n".join(
        parser.text_parts
    )

    text = html.unescape(text)

    for url in re.findall(
        r"https?://[^\s\"'<>]+",
        text,
        re.I,
    ):

        url = normalize_url(url)

        if (
            is_http_url(url)
            and not is_ignored_url(url)
        ):

            urls.append(url)

    return unique_preserve_order(urls)


# ============================================================
# WRAPPER URL
# ============================================================

def extract_wrapped_urls(
    url: str,
):

    result = [url]

    try:

        parsed = urlsplit(url)

        query = parse_qs(
            parsed.query,
            keep_blank_values=True,
        )

        keys = (
            "url",
            "target",
            "src",
            "source",
            "link",
            "sub",
            "subscription",
        )

        for key in keys:

            for value in query.get(
                key,
                [],
            ):

                value = unquote(value)
                value = normalize_url(value)

                if is_http_url(value):
                    result.append(value)

    except Exception as exc:

        print(f"[WRAPPER] {exc}")

    return unique_preserve_order(result)


# ============================================================
# JSON CONFIG DETECTION
# ============================================================

def looks_like_xray_config(
    obj,
) -> bool:

    if not isinstance(obj, dict):
        return False

    keys = set(obj.keys())

    if (
        "inbounds" in keys
        and "outbounds" in keys
    ):
        return True

    if "outbounds" in keys:
        return True

    # Singe outbound-style config
    if (
        "protocol" in keys
        and (
            "settings" in keys
            or "streamSettings" in keys
        )
    ):
        return True

    return False


def extract_json_configs(
    obj,
):

    configs = []

    if isinstance(obj, dict):

        if looks_like_xray_config(obj):

            configs.append(obj)

        for value in obj.values():

            configs.extend(
                extract_json_configs(value)
            )

    elif isinstance(obj, list):

        for item in obj:

            configs.extend(
                extract_json_configs(item)
            )

    return configs


def parse_json_configs(
    text: str,
):

    stripped = text.strip()

    if not (
        stripped.startswith("[")
        or stripped.startswith("{")
    ):
        return []

    try:

        obj = json.loads(stripped)

    except Exception:

        return []

    return extract_json_configs(obj)


# ============================================================
# JSON STRINGS
# ============================================================

def extract_strings_from_json(
    value,
):

    result = []

    if isinstance(value, str):

        result.append(value)

    elif isinstance(value, dict):

        for key, val in value.items():

            result.append(str(key))

            result.extend(
                extract_strings_from_json(val)
            )

    elif isinstance(value, list):

        for item in value:

            result.extend(
                extract_strings_from_json(item)
            )

    return result


# ============================================================
# BASE64
# ============================================================

def decode_base64_variants(
    value: str,
):

    results = []

    if not value:
        return results

    compact = re.sub(
        r"\s+",
        "",
        value.strip(),
    )

    if compact.lower().startswith(
        "data:text/plain;base64,"
    ):

        compact = compact.split(
            ",",
            1
        )[1]

    candidates = [
        compact,
        compact.replace(
            "-",
            "+"
        ).replace(
            "_",
            "/",
        ),
    ]

    for candidate in candidates:

        candidate += "=" * (
            (4 - len(candidate) % 4)
            % 4
        )

        try:

            raw = base64.b64decode(
                candidate,
                validate=False,
            )

            if not raw:
                continue

            decoded = raw.decode(
                "utf-8",
                errors="ignore",
            )

            if decoded.strip():
                results.append(decoded)

        except Exception:

            pass

    return unique_preserve_order(results)


def looks_like_base64(
    value: str,
):

    value = value.strip()

    if len(value) < 16:
        return False

    compact = re.sub(
        r"\s+",
        "",
        value,
    )

    if not re.fullmatch(
        r"[A-Za-z0-9+/=_-]+",
        compact,
    ):
        return False

    for decoded in decode_base64_variants(
        compact
    ):

        if (
            extract_protocol_links(decoded)
            or parse_json_configs(decoded)
        ):
            return True

    return False


# ============================================================
# PROTOCOL LINKS
# ============================================================

def extract_protocol_links(
    text: str,
):

    if not text:
        return []

    text = html.unescape(text)

    text = text.replace(
        "\\/",
        "/",
    )

    protocols = "|".join(
        re.escape(x)
        for x in PROTOCOLS
    )

    pattern = re.compile(
        rf"(?i)"
        rf"(?:{protocols})"
        rf"[^\s\"'<>]+"
    )

    found = pattern.findall(text)

    result = []

    for item in found:

        item = clean_config(item)

        item = item.rstrip(
            ".,;!?"
        )

        if item:
            result.append(item)

    return unique_preserve_order(result)


# ============================================================
# JSON -> URI CONVERTERS
# ============================================================

def get_outbounds(
    config,
):
    """
    Return outbound objects from an Xray/V2Ray JSON config.
    """

    if not isinstance(config, dict):
        return []

    outbounds = config.get(
        "outbounds"
    )

    if isinstance(outbounds, list):
        return [
            x for x in outbounds
            if isinstance(x, dict)
        ]

    # Also support a direct outbound object.
    if (
        "protocol" in config
        and "settings" in config
    ):
        return [config]

    return []


def get_primary_outbound(
    config,
):
    """
    Select a real proxy outbound.
    Ignore common direct/block/DNS outbounds.
    """

    ignored = {
        "freedom",
        "blackhole",
        "dns",
        "loopback",
    }

    outbounds = get_outbounds(config)

    for outbound in outbounds:

        protocol = str(
            outbound.get(
                "protocol",
                ""
            )
        ).lower()

        if protocol not in ignored:
            return outbound

    return None


def get_stream_settings(
    outbound,
):

    settings = outbound.get(
        "streamSettings",
        {}
    )

    if not isinstance(settings, dict):
        return {}

    return settings


def get_server_from_settings(
    outbound,
):

    settings = outbound.get(
        "settings",
        {}
    )

    if not isinstance(settings, dict):
        return None, None

    vnext = settings.get(
        "vnext"
    )

    if isinstance(vnext, list) and vnext:

        first = vnext[0]

        if isinstance(first, dict):

            address = first.get(
                "address"
            )

            port = first.get(
                "port"
            )

            return address, port

    servers = settings.get(
        "servers"
    )

    if isinstance(servers, list) and servers:

        first = servers[0]

        if isinstance(first, dict):

            address = first.get(
                "address"
            )

            port = first.get(
                "port"
            )

            return address, port

    return None, None


def json_vless_to_uri(
    config,
    outbound,
):

    settings = outbound.get(
        "settings",
        {}
    )

    if not isinstance(settings, dict):
        return None

    stream = get_stream_settings(
        outbound
    )

    address, port = get_server_from_settings(
        outbound
    )

    vnext = settings.get(
        "vnext",
        []
    )

    if (
        isinstance(vnext, list)
        and vnext
        and isinstance(vnext[0], dict)
    ):

        user_list = vnext[0].get(
            "users",
            []
        )

        if not user_list:
            return None

        user = user_list[0]

    else:

        return None

    uuid = user.get("id")

    if not uuid or not address or not port:
        return None

    params = {}

    encryption = user.get(
        "encryption"
    )

    if encryption:
        params["encryption"] = encryption

    flow = user.get("flow")

    if flow:
        params["flow"] = flow

    network = stream.get(
        "network",
        "tcp"
    )

    params["type"] = network

    security = stream.get(
        "security",
        "none"
    )

    params["security"] = security

    # --------------------------------------------------------
    # TCP / HTTP
    # --------------------------------------------------------

    tcp_settings = stream.get(
        "tcpSettings",
        {}
    )

    if isinstance(tcp_settings, dict):

        header = tcp_settings.get(
            "header",
            {}
        )

        if isinstance(header, dict):

            header_type = header.get(
                "type"
            )

            if header_type and header_type != "none":

                params["headerType"] = (
                    header_type
                )

                request = header.get(
                    "request",
                    {}
                )

                if isinstance(request, dict):

                    headers = request.get(
                        "headers",
                        {}
                    )

                    if isinstance(
                        headers,
                        dict
                    ):

                        host = headers.get(
                            "Host"
                        )

                        if isinstance(
                            host,
                            list
                        ):
                            host = (
                                host[0]
                                if host
                                else None
                            )

                        if host:
                            params["host"] = host

    # --------------------------------------------------------
    # WebSocket
    # --------------------------------------------------------

    ws = stream.get(
        "wsSettings",
        {}
    )

    if isinstance(ws, dict):

        path = ws.get("path")

        if path:
            params["path"] = path

        headers = ws.get(
            "headers",
            {}
        )

        if isinstance(headers, dict):

            host = headers.get(
                "Host"
            )

            if host:
                params["host"] = host

    # --------------------------------------------------------
    # gRPC
    # --------------------------------------------------------

    grpc = stream.get(
        "grpcSettings",
        {}
    )

    if isinstance(grpc, dict):

        service_name = grpc.get(
            "serviceName"
        )

        if service_name:
            params["serviceName"] = service_name

        mode = grpc.get(
            "multiMode"
        )

        if mode:
            params["mode"] = "multi"

    # --------------------------------------------------------
    # HTTP/2
    # --------------------------------------------------------

    http = stream.get(
        "httpSettings",
        {}
    )

    if isinstance(http, dict):

        path = http.get("path")

        if path:
            params["path"] = path

        host = http.get("host")

        if isinstance(host, list):
            if host:
                params["host"] = host[0]

        elif host:
            params["host"] = host

    # --------------------------------------------------------
    # TLS
    # --------------------------------------------------------

    tls = stream.get(
        "tlsSettings",
        {}
    )

    if isinstance(tls, dict):

        sni = tls.get("serverName")

        if sni:
            params["sni"] = sni

        fp = tls.get(
            "fingerprint"
        )

        if fp:
            params["fp"] = fp

        alpn = tls.get("alpn")

        if isinstance(alpn, list):
            if alpn:
                params["alpn"] = ",".join(
                    str(x) for x in alpn
                )

        elif alpn:
            params["alpn"] = str(alpn)

    # --------------------------------------------------------
    # Reality
    # --------------------------------------------------------

    reality = stream.get(
        "realitySettings",
        {}
    )

    if isinstance(reality, dict):

        sni = reality.get(
            "serverName"
        )

        if sni:
            params["sni"] = sni

        fp = reality.get(
            "fingerprint"
        )

        if fp:
            params["fp"] = fp

        pbk = reality.get(
            "publicKey"
        )

        if pbk:
            params["pbk"] = pbk

        sid = reality.get(
            "shortId"
        )

        if sid:
            params["sid"] = sid

        spx = reality.get(
            "spiderX"
        )

        if spx:
            params["spx"] = spx

    # --------------------------------------------------------
    # Build URI
    # --------------------------------------------------------

    query = urlencode(
        params,
        doseq=False,
        safe="/,",
    )

    name = (
        first_value(
            config,
            "name",
            "remarks",
            "remark",
            default="VLESS",
        )
    )

    uri = (
        "vless://"
        f"{quote(str(uuid), safe='')}"
        "@"
        f"{address}:{port}"
    )

    if query:
        uri += "?" + query

    uri += "#" + quote(
        str(name),
        safe="",
    )

    return uri


def json_vmess_to_uri(
    config,
    outbound,
):

    settings = outbound.get(
        "settings",
        {}
    )

    if not isinstance(settings, dict):
        return None

    vnext = settings.get(
        "vnext",
        []
    )

    if (
        not isinstance(vnext, list)
        or not vnext
        or not isinstance(vnext[0], dict)
    ):
        return None

    server = vnext[0]

    address = server.get(
        "address"
    )

    port = server.get(
        "port"
    )

    users = server.get(
        "users",
        []
    )

    if (
        not address
        or not port
        or not users
    ):
        return None

    user = users[0]

    uuid = user.get("id")

    if not uuid:
        return None

    stream = get_stream_settings(
        outbound
    )

    network = stream.get(
        "network",
        "tcp"
    )

    tls = stream.get(
        "security",
        ""
    )

    tls_settings = stream.get(
        "tlsSettings",
        {}
    )

    ws = stream.get(
        "wsSettings",
        {}
    )

    host = ""
    path = ""

    if isinstance(
        ws,
        dict
    ):

        path = ws.get(
            "path",
            ""
        )

        headers = ws.get(
            "headers",
            {}
        )

        if isinstance(
            headers,
            dict
        ):
            host = headers.get(
                "Host",
                ""
            )

    vmess_obj = {
        "v": "2",
        "ps": first_value(
            config,
            "name",
            "remarks",
            "remark",
            default="VMess",
        ),
        "add": address,
        "port": str(port),
        "id": uuid,
        "aid": str(
            user.get(
                "alterId",
                0
            )
        ),
        "scy": user.get(
            "security",
            "auto",
        ),
        "net": network,
        "type": "none",
        "host": host,
        "path": path,
        "tls": tls,
    }

    if isinstance(
        tls_settings,
        dict
    ):

        sni = tls_settings.get(
            "serverName"
        )

        if sni:
            vmess_obj["sni"] = sni

    raw = json.dumps(
        vmess_obj,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()

    encoded = base64.b64encode(
        raw
    ).decode()

    return (
        "vmess://"
        + encoded
    )


def json_trojan_to_uri(
    config,
    outbound,
):

    settings = outbound.get(
        "settings",
        {}
    )

    if not isinstance(settings, dict):
        return None

    servers = settings.get(
        "servers",
        []
    )

    if (
        not isinstance(servers, list)
        or not servers
        or not isinstance(servers[0], dict)
    ):
        return None

    server = servers[0]

    address = server.get(
        "address"
    )

    port = server.get(
        "port"
    )

    password = server.get(
        "password"
    )

    if (
        not address
        or not port
        or not password
    ):
        return None

    stream = get_stream_settings(
        outbound
    )

    params = {}

    network = stream.get(
        "network"
    )

    if network:
        params["type"] = network

    security = stream.get(
        "security"
    )

    if security:
        params["security"] = security

    tls = stream.get(
        "tlsSettings",
        {}
    )

    if isinstance(tls, dict):

        sni = tls.get(
            "serverName"
        )

        if sni:
            params["sni"] = sni

        fp = tls.get(
            "fingerprint"
        )

        if fp:
            params["fp"] = fp

    name = first_value(
        config,
        "name",
        "remarks",
        "remark",
        default="Trojan",
    )

    query = urlencode(
        params,
        safe="/,",
    )

    uri = (
        "trojan://"
        f"{quote(str(password), safe='')}"
        "@"
        f"{address}:{port}"
    )

    if query:
        uri += "?" + query

    uri += "#" + quote(
        str(name),
        safe="",
    )

    return uri


def json_ss_to_uri(
    config,
    outbound,
):

    settings = outbound.get(
        "settings",
        {}
    )

    if not isinstance(settings, dict):
        return None

    servers = settings.get(
        "servers",
        []
    )

    if (
        not isinstance(servers, list)
        or not servers
        or not isinstance(servers[0], dict)
    ):
        return None

    server = servers[0]

    address = server.get(
        "address"
    )

    port = server.get(
        "port"
    )

    password = server.get(
        "password"
    )

    method = server.get(
        "method"
    )

    if not all(
        [
            address,
            port,
            password,
            method,
        ]
    ):
        return None

    userinfo = (
        f"{method}:{password}"
    )

    encoded = base64.urlsafe_b64encode(
        userinfo.encode()
    ).decode().rstrip("=")

    name = first_value(
        config,
        "name",
        "remarks",
        "remark",
        default="SS",
    )

    return (
        "ss://"
        f"{encoded}"
        f"@{address}:{port}"
        "#"
        f"{quote(str(name), safe='')}"
    )


def json_config_to_uri(
    config,
):
    """
    Convert one Xray/V2Ray JSON config
    into a clean URI.

    Returns None if protocol is unsupported.
    """

    outbound = get_primary_outbound(
        config
    )

    if outbound is None:
        return None

    protocol = str(
        outbound.get(
            "protocol",
            ""
        )
    ).lower()

    try:

        if protocol == "vless":

            return json_vless_to_uri(
                config,
                outbound,
            )

        if protocol == "vmess":

            return json_vmess_to_uri(
                config,
                outbound,
            )

        if protocol == "trojan":

            return json_trojan_to_uri(
                config,
                outbound,
            )

        if protocol in (
            "shadowsocks",
            "ss",
        ):

            return json_ss_to_uri(
                config,
                outbound,
            )

    except Exception as exc:

        print(
            "[CONVERTER] ERROR "
            f"{protocol}: {exc}"
        )

    return None


def convert_json_configs_to_uris(
    configs,
):

    result = []

    converted = 0
    failed = 0

    for config in configs:

        uri = json_config_to_uri(
            config
        )

        if uri:

            result.append(uri)
            converted += 1

        else:

            failed += 1

    result = unique_preserve_order(
        result
    )

    print(
        f"[CONVERTER] JSON configs: "
        f"{len(configs)}"
    )

    print(
        f"[CONVERTER] Converted to URI: "
        f"{converted}"
    )

    print(
        f"[CONVERTER] Unsupported/failed: "
        f"{failed}"
    )

    return result


# ============================================================
# GENERIC CONTENT PARSER
# ============================================================

def parse_content(
    text: str,
):

    uri_configs = []
    json_configs = []

    # --------------------------------------------------------
    # 1. Direct URI links
    # --------------------------------------------------------

    uri_configs.extend(
        extract_protocol_links(text)
    )

    # --------------------------------------------------------
    # 2. JSON Xray/V2Ray configs
    # --------------------------------------------------------

    json_configs.extend(
        parse_json_configs(text)
    )

    # --------------------------------------------------------
    # 3. JSON string values
    # --------------------------------------------------------

    stripped = text.strip()

    if (
        stripped.startswith("[")
        or stripped.startswith("{")
    ):

        try:

            obj = json.loads(stripped)

            for value in (
                extract_strings_from_json(obj)
            ):

                uri_configs.extend(
                    extract_protocol_links(value)
                )

        except Exception:
            pass

    # --------------------------------------------------------
    # 4. Base64
    # --------------------------------------------------------

    if looks_like_base64(text):

        for decoded in (
            decode_base64_variants(text)
        ):

            sub_uri, sub_json = parse_content(
                decoded
            )

            uri_configs.extend(sub_uri)
            json_configs.extend(sub_json)

    return (
        unique_preserve_order(uri_configs),
        json_configs,
    )


# ============================================================
# DOWNLOAD
# ============================================================

def download_source(
    url: str,
):

    print()
    print(
        f"[SOURCE] GET {url}"
    )

    try:

        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )

        print(
            f"[SOURCE] HTTP "
            f"{response.status_code} "
            f"{response.url}"
        )

        print(
            "[SOURCE] Content-Type: "
            + response.headers.get(
                "content-type",
                "",
            )
        )

        if not response.ok:

            print("[SOURCE] skipped")
            return None

        chunks = []
        total = 0

        for chunk in response.iter_content(
            chunk_size=65536
        ):

            if not chunk:
                continue

            total += len(chunk)

            if total > MAX_SOURCE_SIZE:

                print("[SOURCE] too large")
                return None

            chunks.append(chunk)

        raw = b"".join(chunks)

        text = raw.decode(
            "utf-8-sig",
            errors="ignore",
        )

        print(
            f"[SOURCE] received "
            f"{len(raw)} bytes"
        )

        return text

    except Exception as exc:

        print(
            f"[SOURCE] ERROR "
            f"{type(exc).__name__}: {exc}"
        )

        return None


# ============================================================
# DEBUG
# ============================================================

def debug_preview(
    text: str,
):

    preview = (
        text[:DEBUG_PREVIEW]
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )

    print("[DEBUG] Response preview:")
    print(preview)


# ============================================================
# PARSE SOURCE
# ============================================================

def parse_source(
    original_url: str,
):

    uri_configs = []
    json_configs = []

    candidates = extract_wrapped_urls(
        original_url
    )

    print(
        f"[SOURCE] URL candidates: "
        f"{len(candidates)}"
    )

    for candidate in candidates:

        text = download_source(
            candidate
        )

        if not text:
            continue

        uris, jsons = parse_content(
            text
        )

        if uris:

            print(
                f"[SOURCE] URI configs: "
                f"{len(uris)}"
            )

            uri_configs.extend(uris)

        if jsons:

            print(
                f"[SOURCE] JSON configs: "
                f"{len(jsons)}"
            )

            json_configs.extend(jsons)

        if not uris and not jsons:

            print(
                "[SOURCE] "
                "No recognized config format"
            )

            debug_preview(text)

    return (
        unique_preserve_order(uri_configs),
        json_configs,
    )


# ============================================================
# GIST
# ============================================================

def update_gist(
    output_filename: str,
    output: str,
):

    url = (
        "https://api.github.com/gists/"
        f"{GIST_ID}"
    )

    headers = {
        "Authorization":
            f"Bearer {GIST_TOKEN}",

        "Accept":
            "application/vnd.github+json",

        "X-GitHub-Api-Version":
            "2022-11-28",

        "User-Agent":
            "telegram-v2ray-parser",
    }

    payload = {
        "files": {
            output_filename: {
                "content": output
            }
        }
    }

    print()
    print(
        f"[GIST] Updating "
        f"{output_filename}"
    )

    response = requests.patch(
        url,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    print(
        f"[GIST] HTTP "
        f"{response.status_code}"
    )

    if not response.ok:

        print(
            response.text[:2000]
        )

        raise RuntimeError(
            "Gist update failed"
        )

    print(
        "[GIST] Updated successfully"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)

    print(
        "Telegram latest post -> "
        "Happ crypt5 -> "
        "subscription -> "
        "JSON -> URI -> Gist"
    )

    print("=" * 70)

    if not GIST_TOKEN:

        raise RuntimeError(
            "GIST_TOKEN is missing"
        )

    if not GIST_ID:

        raise RuntimeError(
            "GIST_ID is missing"
        )

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

    channel_html = get_channel_page()

    post_url = get_last_post_url(
        channel_html
    )

    post_html = fetch_post(
        post_url
    )

    # --------------------------------------------------------
    # NORMAL HTTPS SOURCES
    # --------------------------------------------------------

    source_urls = extract_post_urls(
        post_html
    )

    print()
    print(
        f"[TELEGRAM] Normal external "
        f"HTTPS sources: "
        f"{len(source_urls)}"
    )

    for index, url in enumerate(
        source_urls,
        1,
    ):

        print(
            f"  {index}. {url}"
        )

    # --------------------------------------------------------
    # HAPP ENCRYPTED SOURCES
    # --------------------------------------------------------

    happ_source_urls = process_happ_links(
        post_html
    )

    source_urls.extend(
        happ_source_urls
    )

    source_urls = unique_preserve_order(
        source_urls
    )

    print()
    print("=" * 70)

    print(
        f"[TELEGRAM] Total external "
        f"sources: {len(source_urls)}"
    )

    for index, url in enumerate(
        source_urls,
        1,
    ):

        print(
            f"  {index}. {url}"
        )

    print("=" * 70)

    if not source_urls:

        raise RuntimeError(
            "No external HTTPS sources "
            "and no decrypted Happ sources"
        )

    # --------------------------------------------------------
    # PARSE ALL SOURCES
    # --------------------------------------------------------

    all_uri_configs = []
    all_json_configs = []

    for index, source_url in enumerate(
        source_urls,
        1,
    ):

        print()
        print("=" * 70)

        print(
            f"[{index}/{len(source_urls)}] "
            f"Processing source"
        )

        print(source_url)

        uris, jsons = parse_source(
            source_url
        )

        all_uri_configs.extend(uris)
        all_json_configs.extend(jsons)

        time.sleep(0.5)

    # --------------------------------------------------------
    # JSON -> URI
    # --------------------------------------------------------

    converted_json_uris = (
        convert_json_configs_to_uris(
            all_json_configs
        )
    )

    # --------------------------------------------------------
    # MERGE ALL URI CONFIGS
    # --------------------------------------------------------

    all_uri_configs.extend(
        converted_json_uris
    )

    all_uri_configs = (
        unique_preserve_order(
            x.strip()
            for x in all_uri_configs
            if x.strip()
        )
    )

    # --------------------------------------------------------
    # STATISTICS
    # --------------------------------------------------------

    print()
    print("=" * 70)

    print(
        f"[RESULT] Direct URI configs: "
        f"{len(all_uri_configs) - len(converted_json_uris)}"
    )

    print(
        f"[RESULT] JSON configs converted: "
        f"{len(converted_json_uris)}"
    )

    print(
        f"[RESULT] TOTAL URI configs: "
        f"{len(all_uri_configs)}"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # DO NOT OVERWRITE WITH EMPTY RESULT
    # --------------------------------------------------------

    if not all_uri_configs:

        raise RuntimeError(
            "No supported URI configs found. "
            "Gist was NOT modified."
        )

    # --------------------------------------------------------
    # OUTPUT
    #
    # IMPORTANT:
    #
    # Gist now receives ONLY clean URI links.
    # NO JSON is written to Gist.
    # --------------------------------------------------------

    output = (
        "\n".join(all_uri_configs)
        + "\n"
    )

    print(
        "[RESULT] Output format: "
        "plain URI subscription"
    )

    print(
        f"[RESULT] Output size: "
        f"{len(output.encode('utf-8'))} bytes"
    )

    # --------------------------------------------------------
    # GIST UPDATE
    # --------------------------------------------------------

    update_gist(
        GIST_FILENAME,
        output,
    )

    # --------------------------------------------------------
    # DONE
    # --------------------------------------------------------

    print()
    print("=" * 70)

    print(
        "[DONE] Successfully completed"
    )

    print(
        f"[DONE] URI configs: "
        f"{len(all_uri_configs)}"
    )

    print(
        f"[DONE] JSON configs converted: "
        f"{len(converted_json_uris)}"
    )

    print("=" * 70)


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\n[FATAL] Interrupted"
        )

        sys.exit(130)

    except Exception as exc:

        print(
            "[FATAL] "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        sys.exit(1)
