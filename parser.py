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
    "configs.json",
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

# ------------------------------------------------------------
# HPWNR
# ------------------------------------------------------------

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

HPWNR_REPO = (
    "Omegaplexx/hpwnr"
)


# ============================================================
# HTTP SESSION
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
            self.text_parts.append(
                data
            )


class TelegramVisibleTextParser(
    HTMLParser
):

    def __init__(self):

        super().__init__(
            convert_charrefs=True
        )

        self.parts = []
        self.skip_depth = 0

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        tag = tag.lower()

        if tag in (
            "script",
            "style",
            "noscript",
            "svg",
        ):

            self.skip_depth += 1

    def handle_endtag(
        self,
        tag,
    ):

        tag = tag.lower()

        if tag in (
            "script",
            "style",
            "noscript",
            "svg",
        ):

            if self.skip_depth > 0:
                self.skip_depth -= 1

    def handle_data(
        self,
        data,
    ):

        if (
            self.skip_depth == 0
            and data
            and data.strip()
        ):

            self.parts.append(
                data
            )

    def get_text(self):

        return "\n".join(
            x.strip()
            for x in self.parts
            if x.strip()
        )


# ============================================================
# HELPERS
# ============================================================

def normalize_url(
    url: str,
) -> str:

    url = html.unescape(
        url
    ).strip()

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

        parsed = urlsplit(
            url
        )

        return (
            parsed.scheme.lower()
            in (
                "http",
                "https",
            )
            and bool(
                parsed.netloc
            )
        )

    except Exception:

        return False


def unique_preserve_order(
    items,
):

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

    value = html.unescape(
        value
    )

    value = value.replace(
        "\\/",
        "/",
    )

    return value.strip(
        " \t\r\n\"'`<>()[]{} ,;"
    )


# ============================================================
# TELEGRAM
# ============================================================

def normalize_telegram_channel():

    channel = TELEGRAM_CHANNEL.strip()

    channel = re.sub(
        r"^https?://(?:www\.)?"
        r"(?:t\.me|telegram\.me)/",
        "",
        channel,
        flags=re.I,
    )

    channel = channel.lstrip(
        "@"
    ).strip(
        "/"
    )

    if "/" in channel:

        channel = channel.split(
            "/",
            1
        )[0]

    return channel


def get_channel_page():

    channel = (
        normalize_telegram_channel()
    )

    urls = [
        f"https://t.me/s/{channel}",
        f"https://telegram.me/s/{channel}",
    ]

    last_error = None

    for url in urls:

        print(
            f"[TELEGRAM] Reading channel: "
            f"{url}"
        )

        try:

            response = SESSION.get(
                url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            print(
                f"[TELEGRAM] HTTP "
                f"{response.status_code} "
                f"{len(response.content)} bytes"
            )

            if not response.ok:

                last_error = RuntimeError(
                    f"HTTP {response.status_code}"
                )

                continue

            return response.text

        except Exception as exc:

            last_error = exc

            print(
                f"[TELEGRAM] ERROR: "
                f"{type(exc).__name__}: {exc}"
            )

    raise RuntimeError(
        "Could not load Telegram channel"
    ) from last_error


def extract_telegram_post_ids(
    channel_html: str,
):

    channel = (
        normalize_telegram_channel()
    )

    ids = set()

    patterns = [

        # data-post="happvpn/4241"
        rf'data-post=["\']'
        rf'{re.escape(channel)}/(\d+)'
        rf'["\']',

        # href="/happvpn/4241"
        rf'href=["\']'
        rf'/{re.escape(channel)}/(\d+)'
        rf'["\']',

        # https://t.me/happvpn/4241
        rf'https?://t\.me/'
        rf'{re.escape(channel)}/(\d+)',

        # https://telegram.me/happvpn/4241
        rf'https?://telegram\.me/'
        rf'{re.escape(channel)}/(\d+)',
    ]

    for pattern in patterns:

        for value in re.findall(
            pattern,
            channel_html,
            re.I,
        ):

            try:

                ids.add(
                    int(value)
                )

            except ValueError:

                pass

    return sorted(
        ids,
        reverse=True,
    )


def get_last_post_url(
    channel_html: str,
):

    ids = (
        extract_telegram_post_ids(
            channel_html
        )
    )

    print(
        f"[TELEGRAM] Найдено постов: "
        f"{len(ids)}"
    )

    if not ids:

        raise RuntimeError(
            "Could not find Telegram "
            "message IDs"
        )

    last_id = ids[0]

    channel = (
        normalize_telegram_channel()
    )

    post_url = (
        f"https://t.me/"
        f"{channel}/"
        f"{last_id}"
    )

    print(
        f"[TELEGRAM] Last post ID: "
        f"{last_id}"
    )

    print(
        f"[TELEGRAM] Last post: "
        f"{post_url}"
    )

    return post_url


def extract_post_id(
    post_url: str,
):

    match = re.search(
        r"/(\d+)(?:[/?#]|$)",
        post_url,
    )

    if not match:

        raise RuntimeError(
            f"Could not extract post ID "
            f"from {post_url}"
        )

    return int(
        match.group(1)
    )


def is_generic_telegram_page(
    text: str,
):

    low = text.lower()

    if (
        "telegram: view @" in low
        and
        "tgme_widget_message" not in low
    ):

        return True

    return False


def fetch_post(
    post_url: str,
):

    channel = (
        normalize_telegram_channel()
    )

    post_id = (
        extract_post_id(
            post_url
        )
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # First use /s/channel/id.
    # This is the public Telegram HTML endpoint
    # containing the actual post.
    # --------------------------------------------------------

    urls = [
        f"https://t.me/s/{channel}/{post_id}",
        f"https://telegram.me/s/{channel}/{post_id}",
        f"https://t.me/{channel}/{post_id}",
    ]

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,"
            "application/xhtml+xml,"
            "application/xml;q=0.9,"
            "*/*;q=0.8"
        ),
        "Accept-Language": (
            "en-US,en;q=0.9"
        ),
        "Cache-Control": "no-cache",
    }

    last_error = None

    for url in urls:

        print(
            f"[TELEGRAM] GET {url}"
        )

        try:

            response = SESSION.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            print(
                f"[TELEGRAM] HTTP "
                f"{response.status_code} "
                f"{len(response.content)} bytes"
            )

            if not response.ok:

                last_error = RuntimeError(
                    f"HTTP {response.status_code}"
                )

                continue

            text = response.text

            if is_generic_telegram_page(
                text
            ):

                print(
                    "[TELEGRAM] Generic Telegram "
                    "page detected, trying next URL"
                )

                continue

            if (
                "tgme_widget_message"
                not in text
                and
                "tgme_widget_message_text"
                not in text
            ):

                print(
                    "[TELEGRAM] Post HTML marker "
                    "not found, trying next URL"
                )

                continue

            print(
                "[TELEGRAM] Actual post HTML received"
            )

            return text

        except Exception as exc:

            last_error = exc

            print(
                f"[TELEGRAM] ERROR: "
                f"{type(exc).__name__}: {exc}"
            )

    raise RuntimeError(
        "Could not fetch actual Telegram post"
    ) from last_error


# ============================================================
# URL FILTER
# ============================================================

def is_ignored_url(
    url: str,
) -> bool:

    low = url.lower()

    try:

        parsed = urlsplit(
            url
        )

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
        "web.telegram.org",
        "webk.telegram.org",
        "webz.telegram.org",
        "oauth.tg.dev",
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "www.w3.org",
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

    if path.endswith(
        media
    ):

        return True

    return False


# ============================================================
# HTTPS EXTRACTION
# ============================================================

def extract_https_urls_from_text(
    text: str,
):

    if not text:

        return []

    text = html.unescape(
        text
    )

    text = text.replace(
        "\\/",
        "/",
    )

    found = re.findall(
        r"https?://[^\s\"'<>]+",
        text,
        re.I,
    )

    result = []

    for url in found:

        url = normalize_url(
            url
        )

        url = url.rstrip(
            ".,;!?)]}"
        )

        if not is_http_url(
            url
        ):

            continue

        if is_ignored_url(
            url
        ):

            continue

        result.append(
            url
        )

    return unique_preserve_order(
        result
    )


# ============================================================
# HAPP LINK EXTRACTION
# ============================================================

def extract_happ_links(
    text: str,
):

    if not text:

        return []

    text = html.unescape(
        text
    )

    text = text.replace(
        "\\/",
        "/",
    )

    pattern = re.compile(
        r"(?i)"
        r"happ://crypt(?:2|3|4|5)?/"
        r"[A-Za-z0-9+/=_-]+"
    )

    found = pattern.findall(
        text
    )

    result = []

    for item in found:

        item = normalize_url(
            item
        )

        if item:

            result.append(
                item
            )

    return unique_preserve_order(
        result
    )


# ============================================================
# TELEGRAM SOURCES
# ============================================================

def extract_telegram_sources(
    post_html: str,
):

    sources = []

    # --------------------------------------------------------
    # Visible text
    # --------------------------------------------------------

    visible_parser = (
        TelegramVisibleTextParser()
    )

    visible_parser.feed(
        post_html
    )

    visible_text = (
        visible_parser.get_text()
    )

    sources.extend(
        extract_https_urls_from_text(
            visible_text
        )
    )

    # --------------------------------------------------------
    # HREF
    # --------------------------------------------------------

    parser = TelegramHTMLParser()

    parser.feed(
        post_html
    )

    for href in parser.links:

        href = normalize_url(
            href
        )

        if (
            is_http_url(href)
            and
            not is_ignored_url(href)
        ):

            sources.append(
                href
            )

    # --------------------------------------------------------
    # Telegram message text blocks
    # --------------------------------------------------------

    blocks = re.findall(
        r'class=["\'][^"\']*'
        r'tgme_widget_message_text'
        r'[^"\']*["\'][^>]*>'
        r'(.*?)'
        r'</div>',
        post_html,
        re.I | re.S,
    )

    for block in blocks:

        block_text = re.sub(
            r"<[^>]+>",
            " ",
            block,
        )

        block_text = html.unescape(
            block_text
        )

        sources.extend(
            extract_https_urls_from_text(
                block_text
            )
        )

    return unique_preserve_order(
        sources
    )


# ============================================================
# TELEGRAM POST URLs
# ============================================================

def extract_post_urls(
    post_html: str,
):

    return extract_telegram_sources(
        post_html
    )


# ============================================================
# HPWNR
# ============================================================

def get_hpwrr_platform():
    """
    Return exact hpwnr GitHub release asset name.
    """

    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":

        if machine in (
            "x86_64",
            "amd64",
        ):
            return "hpwnr-linux-x86_64"

        if machine in (
            "aarch64",
            "arm64",
        ):
            return "hpwnr-linux-arm64"

        if machine in (
            "armv7l",
            "armv7",
        ):
            return "hpwnr-linux-armv7"

        if machine in (
            "i386",
            "i686",
            "x86",
        ):
            return "hpwnr-linux-x86"

        if machine == "riscv64":
            return "hpwnr-linux-riscv64"

    if system == "android":

        if machine in (
            "aarch64",
            "arm64",
        ):
            return "hpwnr-android-arm64"

        if machine in (
            "armv7l",
            "armv7",
        ):
            return "hpwnr-android-armv7"

        if machine in (
            "x86_64",
            "amd64",
        ):
            return "hpwnr-android-x86_64"

        if machine in (
            "i386",
            "i686",
            "x86",
        ):
            return "hpwnr-android-x86"

    if system == "darwin":

        if machine in (
            "arm64",
            "aarch64",
        ):
            return "hpwnr-macos-arm64"

        if machine in (
            "x86_64",
            "amd64",
        ):
            return "hpwnr-macos-x86_64"

    if system == "windows":

        if machine in (
            "x86_64",
            "amd64",
        ):
            return "hpwnr-windows-x64.exe"

        if machine in (
            "i386",
            "i686",
            "x86",
        ):
            return "hpwnr-windows-x86.exe"

    raise RuntimeError(
        "Unsupported hpwnr platform: "
        f"system={system}, "
        f"architecture={machine}"
    )


def find_hpwrr_local():

    if HPWNR_BIN:

        path = Path(
            HPWNR_BIN
        )

        if path.exists():

            return str(
                path
            )

        return HPWNR_BIN

    try:

        result = subprocess.run(
            [
                "hpwnr",
                "h",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode in (
            0,
            1,
        ):

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
            if platform.system().lower()
            == "windows"
            else "hpwnr"
        )
    )

    if local.exists():

        return str(
            local
        )

    return None


def install_hpwrr():

    if not AUTO_INSTALL_HPWNR:

        raise RuntimeError(
            "hpwnr is not installed and "
            "AUTO_INSTALL_HPWNR=0"
        )

    asset_name = (
        get_hpwrr_platform()
    )

    print()
    print(
        "[HPWNR] hpwnr not found"
    )

    print(
        f"[HPWNR] Asset: {asset_name}"
    )

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

    release_tag = (
        release.get(
            "tag_name",
            "unknown",
        )
    )

    print(
        f"[HPWNR] Release: {release_tag}"
    )

    assets = (
        release.get(
            "assets",
            [],
        )
    )

    asset = None

    for candidate in assets:

        if (
            candidate.get("name")
            == asset_name
        ):

            asset = candidate

            break

    if asset is None:

        available = [
            x.get("name")
            for x in assets
        ]

        raise RuntimeError(
            "Could not find hpwnr asset "
            f"{asset_name}. "
            f"Available: {available}"
        )

    download_url = (
        asset.get(
            "browser_download_url"
        )
    )

    if not download_url:

        raise RuntimeError(
            "hpwnr release asset "
            "has no download URL"
        )

    HPWNR_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if (
        platform.system().lower()
        == "windows"
    ):

        binary_name = "hpwnr.exe"

    else:

        binary_name = "hpwnr"

    binary_path = (
        HPWNR_DIR
        / binary_name
    )

    print(
        "[HPWNR] Downloading:"
    )

    print(
        download_url
    )

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

    with open(
        binary_path,
        "wb",
    ) as file:

        for chunk in response.iter_content(
            chunk_size=65536
        ):

            if not chunk:
                continue

            file.write(
                chunk
            )

            downloaded += len(
                chunk
            )

    if (
        platform.system().lower()
        != "windows"
    ):

        current_mode = (
            binary_path.stat().st_mode
        )

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

    if (
        binary_path.stat().st_size
        == 0
    ):

        raise RuntimeError(
            "Downloaded hpwnr binary "
            "is empty"
        )

    print(
        f"[HPWNR] Downloaded: "
        f"{downloaded} bytes"
    )

    print(
        "[HPWNR] Installed:"
    )

    print(
        binary_path
    )

    return str(
        binary_path
    )


def get_hpwnr():

    existing = (
        find_hpwrr_local()
    )

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
    print(
        "[HAPP] Decrypting:"
    )

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

        print(
            "[HAPP] ERROR: timeout"
        )

        return None

    stdout = (
        result.stdout.strip()
    )

    stderr = (
        result.stderr.strip()
    )

    if result.returncode != 0:

        print(
            "[HAPP] ERROR:"
        )

        if stderr:

            print(
                stderr[:3000]
            )

        else:

            print(
                f"[HAPP] hpwnr exit code: "
                f"{result.returncode}"
            )

        return None

    if not stdout:

        print(
            "[HAPP] Empty result"
        )

        if stderr:

            print(
                stderr[:1000]
            )

        return None

    if is_http_url(
        stdout
    ):

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

            print(
                stdout[:1000]
            )

            return None

        decrypted = normalize_url(
            urls[0]
        )

    decrypted = normalize_url(
        decrypted
    )

    print(
        "[HAPP] Decrypted:"
    )

    print(
        decrypted
    )

    return decrypted


def process_happ_links(
    post_html: str,
):

    happ_links = (
        extract_happ_links(
            post_html
        )
    )

    print()
    print(
        "=" * 70
    )

    print(
        f"[HAPP] Encrypted links: "
        f"{len(happ_links)}"
    )

    print(
        "=" * 70
    )

    if not happ_links:

        return []

    hpwnr_path = (
        get_hpwnr()
    )

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

            decrypted = (
                decrypt_happ_link(
                    hpwnr_path,
                    happ_link,
                )
            )

        except Exception as exc:

            print(
                "[HAPP] Exception:"
            )

            print(
                repr(exc)
            )

            continue

        if not decrypted:
            continue

        if is_http_url(
            decrypted
        ):

            decrypted_urls.append(
                decrypted
            )

    decrypted_urls = (
        unique_preserve_order(
            decrypted_urls
        )
    )

    print()
    print(
        f"[HAPP] Decrypted HTTP(S) "
        f"sources: "
        f"{len(decrypted_urls)}"
    )

    for url in decrypted_urls:

        print(
            f"  {url}"
        )

    return decrypted_urls


# ============================================================
# WRAPPER URL
# ============================================================

def extract_wrapped_urls(
    url: str,
):

    result = [
        url
    ]

    try:

        parsed = urlsplit(
            url
        )

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

                value = unquote(
                    value
                )

                value = normalize_url(
                    value
                )

                if is_http_url(
                    value
                ):

                    result.append(
                        value
                    )

    except Exception as exc:

        print(
            f"[WRAPPER] {exc}"
        )

    return unique_preserve_order(
        result
    )


# ============================================================
# JSON CONFIG DETECTION
# ============================================================

def looks_like_xray_config(
    obj,
) -> bool:

    if not isinstance(
        obj,
        dict,
    ):

        return False

    keys = set(
        obj.keys()
    )

    if (
        "inbounds" in keys
        and
        "outbounds" in keys
    ):

        return True

    if "outbounds" in keys:

        return True

    return False


def extract_json_configs(
    obj,
):

    configs = []

    if isinstance(
        obj,
        dict,
    ):

        if looks_like_xray_config(
            obj
        ):

            configs.append(
                obj
            )

        for value in obj.values():

            configs.extend(
                extract_json_configs(
                    value
                )
            )

    elif isinstance(
        obj,
        list,
    ):

        for item in obj:

            configs.extend(
                extract_json_configs(
                    item
                )
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

        obj = json.loads(
            stripped
        )

    except Exception:

        return []

    return extract_json_configs(
        obj
    )


# ============================================================
# JSON STRING EXTRACTION
# ============================================================

def extract_strings_from_json(
    value,
):

    result = []

    if isinstance(
        value,
        str,
    ):

        result.append(
            value
        )

    elif isinstance(
        value,
        dict,
    ):

        for key, val in value.items():

            result.append(
                str(key)
            )

            result.extend(
                extract_strings_from_json(
                    val
                )
            )

    elif isinstance(
        value,
        list,
    ):

        for item in value:

            result.extend(
                extract_strings_from_json(
                    item
                )
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

                results.append(
                    decoded
                )

        except Exception:

            pass

    return unique_preserve_order(
        results
    )


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

    for decoded in (
        decode_base64_variants(
            compact
        )
    ):

        if extract_protocol_links(
            decoded
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

    text = html.unescape(
        text
    )

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

    found = pattern.findall(
        text
    )

    result = []

    for item in found:

        item = clean_config(
            item
        )

        item = item.rstrip(
            ".,;!?"
        )

        if item:

            result.append(
                item
            )

    return unique_preserve_order(
        result
    )


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
        extract_protocol_links(
            text
        )
    )

    # --------------------------------------------------------
    # 2. JSON Xray/V2Ray configs
    # --------------------------------------------------------

    json_configs.extend(
        parse_json_configs(
            text
        )
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

            obj = json.loads(
                stripped
            )

            for value in (
                extract_strings_from_json(
                    obj
                )
            ):

                uri_configs.extend(
                    extract_protocol_links(
                        value
                    )
                )

        except Exception:

            pass

    # --------------------------------------------------------
    # 4. Base64
    # --------------------------------------------------------

    if looks_like_base64(
        text
    ):

        for decoded in (
            decode_base64_variants(
                text
            )
        ):

            sub_uri, sub_json = (
                parse_content(
                    decoded
                )
            )

            uri_configs.extend(
                sub_uri
            )

            json_configs.extend(
                sub_json
            )

    return (
        unique_preserve_order(
            uri_configs
        ),
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

            print(
                "[SOURCE] skipped"
            )

            return None

        chunks = []
        total = 0

        for chunk in response.iter_content(
            chunk_size=65536
        ):

            if not chunk:
                continue

            total += len(
                chunk
            )

            if (
                total
                > MAX_SOURCE_SIZE
            ):

                print(
                    "[SOURCE] too large"
                )

                return None

            chunks.append(
                chunk
            )

        raw = b"".join(
            chunks
        )

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
            f"{type(exc).__name__}: "
            f"{exc}"
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
        .replace(
            "\r",
            "\\r",
        )
        .replace(
            "\n",
            "\\n",
        )
    )

    print(
        "[DEBUG] Response preview:"
    )

    print(
        preview
    )


# ============================================================
# PARSE SOURCE
# ============================================================

def parse_source(
    original_url: str,
):

    uri_configs = []
    json_configs = []

    candidates = (
        extract_wrapped_urls(
            original_url
        )
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

        uris, jsons = (
            parse_content(
                text
            )
        )

        if uris:

            print(
                f"[SOURCE] URI configs: "
                f"{len(uris)}"
            )

            uri_configs.extend(
                uris
            )

        if jsons:

            print(
                f"[SOURCE] JSON configs: "
                f"{len(jsons)}"
            )

            json_configs.extend(
                jsons
            )

        if not uris and not jsons:

            print(
                "[SOURCE] "
                "No recognized config format"
            )

            debug_preview(
                text
            )

    return (
        unique_preserve_order(
            uri_configs
        ),
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
        "Happ crypt -> "
        "subscription -> "
        "V2Ray/Xray -> Gist"
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
    # Telegram channel
    # --------------------------------------------------------

    channel_html = (
        get_channel_page()
    )

    post_url = (
        get_last_post_url(
            channel_html
        )
    )

    # --------------------------------------------------------
    # Actual Telegram post
    # --------------------------------------------------------

    post_html = (
        fetch_post(
            post_url
        )
    )

    # --------------------------------------------------------
    # Visible text DEBUG
    # --------------------------------------------------------

    visible_parser = (
        TelegramVisibleTextParser()
    )

    visible_parser.feed(
        post_html
    )

    visible_text = (
        visible_parser.get_text()
    )

    print()
    print(
        "[TELEGRAM] Visible text preview:"
    )

    print(
        visible_text[:DEBUG_PREVIEW]
    )

    # --------------------------------------------------------
    # NORMAL HTTPS SOURCES
    # --------------------------------------------------------

    source_urls = (
        extract_telegram_sources(
            post_html
        )
    )

    print()
    print(
        f"[TELEGRAM] HTTPS sources: "
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

    happ_source_urls = (
        process_happ_links(
            post_html
        )
    )

    # --------------------------------------------------------
    # MERGE
    # --------------------------------------------------------

    source_urls.extend(
        happ_source_urls
    )

    source_urls = (
        unique_preserve_order(
            source_urls
        )
    )

    print()
    print(
        "=" * 70
    )

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

    print(
        "=" * 70
    )

    if not source_urls:

        raise RuntimeError(
            "No external HTTPS sources "
            "and no decrypted Happ sources"
        )

    # --------------------------------------------------------
    # PARSE SOURCES
    # --------------------------------------------------------

    all_uri_configs = []
    all_json_configs = []

    for index, source_url in enumerate(
        source_urls,
        1,
    ):

        print()
        print(
            "=" * 70
        )

        print(
            f"[{index}/{len(source_urls)}] "
            f"Processing source"
        )

        print(
            source_url
        )

        uris, jsons = (
            parse_source(
                source_url
            )
        )

        all_uri_configs.extend(
            uris
        )

        all_json_configs.extend(
            jsons
        )

        time.sleep(
            0.5
        )

    # --------------------------------------------------------
    # DEDUP URI
    # --------------------------------------------------------

    all_uri_configs = (
        unique_preserve_order(
            x.strip()
            for x in all_uri_configs
            if x.strip()
        )
    )

    # --------------------------------------------------------
    # DEDUP JSON
    # --------------------------------------------------------

    unique_json = []
    seen_json = set()

    for config in all_json_configs:

        try:

            normalized = json.dumps(
                config,
                ensure_ascii=False,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
            )

            if normalized in seen_json:
                continue

            seen_json.add(
                normalized
            )

            unique_json.append(
                config
            )

        except Exception:

            continue

    # --------------------------------------------------------
    # STATISTICS
    # --------------------------------------------------------

    print()
    print(
        "=" * 70
    )

    print(
        f"[RESULT] URI configs: "
        f"{len(all_uri_configs)}"
    )

    print(
        f"[RESULT] JSON configs: "
        f"{len(unique_json)}"
    )

    print(
        "=" * 70
    )

    # --------------------------------------------------------
    # NEVER OVERWRITE GIST WITH EMPTY RESULT
    # --------------------------------------------------------

    if (
        not all_uri_configs
        and not unique_json
    ):

        raise RuntimeError(
            "No supported configs found. "
            "Gist was NOT modified."
        )

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    if unique_json:

        output = (
            json.dumps(
                unique_json,
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )

        print(
            "[RESULT] Output format: "
            "Xray/V2Ray JSON"
        )

    else:

        output = (
            "\n".join(
                all_uri_configs
            )
            + "\n"
        )

        print(
            "[RESULT] Output format: "
            "URI subscription"
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
    print(
        "=" * 70
    )

    print(
        "[DONE] Successfully completed"
    )

    print(
        f"[DONE] JSON configs: "
        f"{len(unique_json)}"
    )

    print(
        f"[DONE] URI configs: "
        f"{len(all_uri_configs)}"
    )

    print(
        "=" * 70
    )


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