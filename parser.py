#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HappVPN Telegram → URI parser

Что делает:
1. Берёт последний пост Telegram-канала.
2. Извлекает обычные HTTPS subscription URL.
3. Извлекает happ://crypt...crypt5.
4. Расшифровывает Happ через hpwnr.
5. Скачивает subscription.
6. Поддерживает:
   - обычные URI
   - Base64
   - JSON
   - JSON-массивы Xray/V2Ray
7. JSON превращает в чистые URI.
8. Сохраняет tag/remarks как имя после #.
9. Поддерживает:
   - VLESS
   - VMess
   - Trojan
   - Shadowsocks
   - xhttp
   - WebSocket
   - gRPC
   - TCP
   - TLS
   - Reality
10. В Gist публикуются ТОЛЬКО URI.
"""

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
).strip().lstrip("@")

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
    "happ.txt",
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
    "hpwnr",
).strip()

HPWNR_DIR = Path(
    os.getenv(
        "HPWNR_DIR",
        ".hpwnr",
    )
)

AUTO_INSTALL_HPWNR = (
    os.getenv(
        "AUTO_INSTALL_HPWNR",
        "true",
    ).strip().lower()
    in (
        "1",
        "true",
        "yes",
        "on",
    )
)

HPWNR_REPO = os.getenv(
    "HPWNR_REPO",
    "Omegaplexx/hpwnr",
).strip()


# ============================================================
# HTTP
# ============================================================

UA = (
    "Mozilla/5.0 (Linux; Android 13; K)"
    " AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/131.0 Mobile Safari/537.36"
)

HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# SUPPORTED PROTOCOLS
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
# HELPERS
# ============================================================

def first_value(value, default=""):
    if isinstance(value, list):
        return value[0] if value else default

    if value is None:
        return default

    return str(value)


def clean_string(value):
    if value is None:
        return ""

    if not isinstance(value, str):
        value = str(value)

    return (
        value
        .replace("\r", "")
        .replace("\n", "")
        .strip()
    )


def normalize_url(url):
    return html.unescape(
        unquote(
            clean_string(url)
        )
    ).strip()


def dedupe(items):
    result = []
    seen = set()

    for item in items:
        item = clean_string(item)

        if not item:
            continue

        if item in seen:
            continue

        seen.add(item)
        result.append(item)

    return result


def is_http_url(value):
    try:
        p = urlsplit(value)

        return (
            p.scheme.lower()
            in (
                "http",
                "https",
            )
            and bool(p.netloc)
        )

    except Exception:
        return False


def safe_name(value):
    value = clean_string(value)

    if not value:
        return ""

    value = value.replace(
        "#",
        "",
    )

    value = value.replace(
        "\r",
        " ",
    )

    value = value.replace(
        "\n",
        " ",
    )

    return value.strip()


def encode_name(name):
    name = safe_name(name)

    if not name:
        return ""

    return quote(
        name,
        safe="",
    )


def build_uri_with_name(uri, name):
    uri = clean_string(uri)

    if not uri:
        return ""

    name = safe_name(name)

    if not name:
        return uri

    if "#" in uri:
        return uri

    return (
        uri
        + "#"
        + encode_name(name)
    )


# ============================================================
# TELEGRAM HTML PARSER
# ============================================================

class TelegramHTMLParser(HTMLParser):

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.links = []

        self.texts = []

        self.current_href = None
        self.current_text = []

    def handle_starttag(
        self,
        tag,
        attrs,
    ):
        tag = tag.lower()

        attrs = dict(attrs)

        # ----------------------------------------------------
        # A
        # ----------------------------------------------------

        if tag == "a":

            href = attrs.get(
                "href"
            )

            if href:
                self.current_href = (
                    html.unescape(
                        href
                    )
                )

                self.current_text = []

    def handle_data(self, data):

        if not data:
            return

        # Сохраняем видимый текст страницы.
        self.texts.append(data)

        # Текст текущей ссылки.
        if self.current_href is not None:
            self.current_text.append(
                data
            )

    def handle_endtag(self, tag):

        if tag.lower() != "a":
            return

        if self.current_href:

            text = "".join(
                self.current_text
            ).strip()

            self.links.append(
                (
                    self.current_href,
                    text,
                )
            )

        self.current_href = None
        self.current_text = []


# ============================================================
# TELEGRAM
# ============================================================

def get_channel_page():

    channel = (
        TELEGRAM_CHANNEL
        .lstrip("@")
        .strip("/")
    )

    urls = [
        f"https://t.me/s/{channel}",
        f"https://telegram.me/s/{channel}",
    ]

    last_error = None

    for url in urls:

        try:

            print(
                f"[TELEGRAM] GET {url}"
            )

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            print(
                f"[TELEGRAM] HTTP "
                f"{response.status_code}"
            )

            if (
                response.ok
                and response.text
            ):
                return response.text

        except Exception as e:

            last_error = e

            print(
                f"[TELEGRAM] Ошибка: {e}"
            )

    if last_error:

        print(
            "[TELEGRAM] Последняя ошибка: "
            f"{last_error}"
        )

    return ""


def extract_telegram_post_links(page):

    """
    Ищет реальные сообщения канала.

    Поддерживает:

        https://t.me/happvpn/4241
        href="/happvpn/4241"
        href="https://t.me/happvpn/4241"
        data-post="happvpn/4241"
    """

    channel_name = (
        TELEGRAM_CHANNEL
        .lstrip("@")
        .strip("/")
    )

    channel = re.escape(
        channel_name
    )

    patterns = [

        # https://t.me/happvpn/4241
        rf'https?://t\.me/'
        rf'{channel}/(\d+)',

        # /happvpn/4241
        rf'href=["\']/'
        rf'{channel}/(\d+)["\']',

        # https://t.me/happvpn/4241
        rf'href=["\']https://t\.me/'
        rf'{channel}/(\d+)["\']',

        # data-post="happvpn/4241"
        rf'data-post=["\']'
        rf'{channel}/(\d+)["\']',

        # data-post='happvpn/4241'
        rf'data-post=[\'"]'
        rf'{channel}/(\d+)[\'"]',
    ]

    found = []

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            page,
            re.IGNORECASE,
        ):

            post_id = match.group(1)

            try:
                number = int(
                    post_id
                )
            except Exception:
                continue

            found.append(
                (
                    number,
                    (
                        "https://t.me/"
                        f"{channel_name}/"
                        f"{post_id}"
                    ),
                )
            )

    # --------------------------------------------------------
    # Уникальные ID
    # --------------------------------------------------------

    unique = {}

    for number, url in found:
        unique[number] = url

    result = [
        unique[number]
        for number in sorted(
            unique,
            reverse=True,
        )
    ]

    return result


def get_last_post_url(page):

    """
    Устойчивый поиск последнего поста.

    Берём максимальный ID сообщения.
    """

    posts = (
        extract_telegram_post_links(
            page
        )
    )

    if posts:

        return posts[0]

    # --------------------------------------------------------
    # Дополнительный fallback
    # --------------------------------------------------------

    channel_name = (
        TELEGRAM_CHANNEL
        .lstrip("@")
        .strip("/")
    )

    candidates = []

    patterns = [

        rf'data-post=["\']'
        rf'{re.escape(channel_name)}'
        rf'/(\d+)["\']',

        rf'{re.escape(channel_name)}'
        rf'/(\d+)',

    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            page,
            re.IGNORECASE,
        ):

            try:
                post_id = int(
                    match.group(1)
                )
            except Exception:
                continue

            candidates.append(
                post_id
            )

    if candidates:

        post_id = max(
            candidates
        )

        return (
            "https://t.me/"
            f"{channel_name}/"
            f"{post_id}"
        )

    print(
        "[TELEGRAM] Не найден последний "
        "пост"
    )

    print(
        "[TELEGRAM] HTML preview:"
    )

    print(
        page[:1000]
        .replace("\n", " ")
    )

    return None


def fetch_post(post_url):

    print(
        f"[TELEGRAM] Пост: {post_url}"
    )

    try:

        response = requests.get(
            post_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        print(
            "[TELEGRAM] POST HTTP "
            f"{response.status_code}"
        )

        if not response.ok:
            return ""

        return response.text

    except Exception as e:

        print(
            f"[TELEGRAM] Ошибка поста: {e}"
        )

        return ""


# ============================================================
# TELEGRAM URL FILTER
# ============================================================

def is_bad_telegram_url(url):

    try:

        p = urlsplit(url)

        host = (
            p.hostname or ""
        ).lower()

        path = (
            p.path or ""
        ).lower()

        # ----------------------------------------------------
        # Telegram
        # ----------------------------------------------------

        telegram_hosts = (
            "t.me",
            "telegram.me",
            "www.t.me",
            "www.telegram.me",
            "telegram.org",
            "www.telegram.org",
            "web.telegram.org",
            "webk.telegram.org",
            "desktop.telegram.org",
            "core.telegram.org",
        )

        if host in telegram_hosts:
            return True

        if host.endswith(
            ".telegram.org"
        ):
            return True

        if host.endswith(
            ".telegram.me"
        ):
            return True

        # ----------------------------------------------------
        # W3C / XML namespaces
        # ----------------------------------------------------

        if host in (
            "w3.org",
            "www.w3.org",
            "schema.org",
            "www.schema.org",
            "xmlns.com",
        ):
            return True

        # ----------------------------------------------------
        # Static files
        # ----------------------------------------------------

        blocked_extensions = (
            ".css",
            ".js",
            ".map",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".svg",
            ".ico",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
        )

        if path.endswith(
            blocked_extensions
        ):
            return True

        # ----------------------------------------------------
        # Telegram CDN
        # ----------------------------------------------------

        if (
            "telegram-cdn" in host
            or "cdn.telegram" in host
        ):
            return True

        return False

    except Exception:

        return True


# ============================================================
# HTTPS EXTRACTION
# ============================================================

def extract_https_urls_from_text(
    text
):

    results = []

    if not text:
        return results

    pattern = re.compile(
        r'https?://[^\s<>"\'\]\[()]+',
        re.IGNORECASE,
    )

    for match in pattern.finditer(
        text
    ):

        url = match.group(0)

        url = html.unescape(
            url
        )

        url = url.rstrip(
            ".,;:!?)]}>"
        )

        if not is_http_url(
            url
        ):
            continue

        if is_bad_telegram_url(
            url
        ):
            continue

        results.append(
            url
        )

    return dedupe(
        results
    )


# ============================================================
# TELEGRAM SOURCES
# ============================================================

def extract_telegram_sources(
    post_html
):

    parser = (
        TelegramHTMLParser()
    )

    try:

        parser.feed(
            post_html
        )

    except Exception as e:

        print(
            "[TELEGRAM] HTML parser: "
            f"{e}"
        )

    sources = []

    # --------------------------------------------------------
    # 1. href
    # --------------------------------------------------------

    for href, link_text in (
        parser.links
    ):

        href = normalize_url(
            href
        )

        if (
            is_http_url(href)
            and not is_bad_telegram_url(
                href
            )
        ):
            sources.append(
                href
            )

        # URL может находиться
        # только в тексте ссылки.
        sources.extend(
            extract_https_urls_from_text(
                link_text
            )
        )

    # --------------------------------------------------------
    # 2. Только ВИДИМЫЙ текст
    #
    # ВАЖНО:
    # здесь НЕ используется post_html.
    #
    # Поэтому URL из:
    #   <script>
    #   <link>
    #   xmlns
    #   CSS
    #   SVG
    # Telegram Web
    #
    # больше не попадут в источники.
    # --------------------------------------------------------

    visible_text = "\n".join(
        parser.texts
    )

    sources.extend(
        extract_https_urls_from_text(
            visible_text
        )
    )

    return dedupe(
        sources
    )


# ============================================================
# HAPP
# ============================================================

def extract_happ_links(text):

    if not text:
        return []

    pattern = re.compile(
        r'happ://crypt[0-9A-Za-z_\-./+=?&%]+crypt5',
        re.IGNORECASE,
    )

    return dedupe(
        match.group(0)
        for match in pattern.finditer(
            text
        )
    )


# ============================================================
# HPWNR PLATFORM
# ============================================================

def detect_hpwnr_asset():

    system = (
        platform.system()
        .lower()
    )

    machine = (
        platform.machine()
        .lower()
    )

    # --------------------------------------------------------
    # Linux
    # --------------------------------------------------------

    if system == "linux":

        # ВАЖНО:
        # реальные asset names hpwnr:
        #
        # hpwnr-linux-x86_64
        # hpwnr-linux-arm64
        #
        # а НЕ linux-amd64.
        # ----------------------------------------------------

        if machine in (
            "aarch64",
            "arm64",
            "armv8",
        ):
            return "hpwnr-linux-arm64"

        if machine in (
            "x86_64",
            "amd64",
        ):
            return "hpwnr-linux-x86_64"

        if machine.startswith(
            "arm"
        ):
            return "hpwnr-linux-arm64"

        return "hpwnr-linux-x86_64"

    # --------------------------------------------------------
    # macOS
    # --------------------------------------------------------

    if system == "darwin":

        if "arm" in machine:

            return (
                "hpwnr-darwin-arm64"
            )

        return (
            "hpwnr-darwin-x86_64"
        )

    # --------------------------------------------------------
    # Windows
    # --------------------------------------------------------

    if system == "windows":

        return (
            "hpwnr-windows-x86_64.exe"
        )

    return None


# ============================================================
# FIND LOCAL HPWNR
# ============================================================

def find_local_hpwnr():

    candidates = []

    path = Path(
        HPWNR_BIN
    )

    if path.is_absolute():

        candidates.append(
            path
        )

    else:

        candidates.append(
            Path.cwd() / path
        )

        candidates.append(
            HPWNR_DIR / path.name
        )

    for item in candidates:

        if (
            item.exists()
            and item.is_file()
        ):
            return item

    # --------------------------------------------------------
    # PATH
    # --------------------------------------------------------

    try:

        result = subprocess.run(
            [
                "which",
                HPWNR_BIN,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:

            value = (
                result.stdout
                .strip()
            )

            if value:

                path = Path(
                    value
                )

                if path.exists():
                    return path

    except Exception:
        pass

    return None


# ============================================================
# INSTALL HPWNR
# ============================================================

def install_hpwnr():

    if not AUTO_INSTALL_HPWNR:
        return None

    print(
        "[HPWNR] Локальный hpwnr "
        "не найден"
    )

    asset = (
        detect_hpwnr_asset()
    )

    if not asset:

        print(
            "[HPWNR] Неизвестная "
            "платформа"
        )

        return None

    try:

        api = (
            "https://api.github.com/repos/"
            f"{HPWNR_REPO}/releases/latest"
        )

        response = requests.get(
            api,
            headers={
                **HEADERS,
                "Accept":
                    "application/vnd.github+json",
            },
            timeout=REQUEST_TIMEOUT,
        )

        if not response.ok:

            print(
                "[HPWNR] GitHub API HTTP "
                f"{response.status_code}"
            )

            return None

        data = response.json()

        download_url = None
        asset_name = None

        for item in data.get(
            "assets",
            [],
        ):

            name = clean_string(
                item.get(
                    "name",
                    "",
                )
            )

            if not name:
                continue

            # Сначала точное совпадение.
            if name == asset:

                download_url = (
                    item.get(
                        "browser_download_url"
                    )
                )

                asset_name = name

                break

        # ----------------------------------------------------
        # Fallback:
        # GitHub может добавить расширение/архив.
        # ----------------------------------------------------

        if not download_url:

            asset_lower = (
                asset.lower()
            )

            for item in data.get(
                "assets",
                [],
            ):

                name = clean_string(
                    item.get(
                        "name",
                        "",
                    )
                )

                if (
                    asset_lower
                    in name.lower()
                ):

                    download_url = (
                        item.get(
                            "browser_download_url"
                        )
                    )

                    asset_name = name

                    break

        if not download_url:

            print(
                "[HPWNR] Не найден asset "
                f"{asset}"
            )

            print(
                "[HPWNR] Доступные assets:"
            )

            for item in data.get(
                "assets",
                [],
            ):

                print(
                    "  - "
                    + clean_string(
                        item.get(
                            "name",
                            "",
                        )
                    )
                )

            return None

        HPWNR_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination = (
            HPWNR_DIR / asset
        )

        print(
            "[HPWNR] Скачиваю "
            f"{asset_name}"
        )

        print(
            f"[HPWNR] URL: {download_url}"
        )

        r = requests.get(
            download_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if not r.ok:

            print(
                "[HPWNR] Download HTTP "
                f"{r.status_code}"
            )

            return None

        if not r.content:

            print(
                "[HPWNR] Пустой файл"
            )

            return None

        destination.write_bytes(
            r.content
        )

        destination.chmod(
            destination.stat().st_mode
            | stat.S_IEXEC
        )

        print(
            "[HPWNR] Installed: "
            f"{destination}"
        )

        return destination

    except Exception as e:

        print(
            f"[HPWNR] Install error: {e}"
        )

        return None


# ============================================================
# GET HPWNR
# ============================================================

def get_hpwnr():

    local = (
        find_local_hpwnr()
    )

    if local:

        print(
            "[HPWNR] Использую: "
            f"{local}"
        )

        return local

    return install_hpwnr()


# ============================================================
# DECRYPT HAPP
# ============================================================

def decrypt_happ(
    happ_url,
    hpwnr,
):

    print(
        "[HPWNR] Расшифровка Happ..."
    )

    commands = [

        # Основной вариант.
        [
            str(hpwnr),
            happ_url,
        ],

        # Fallback.
        [
            str(hpwnr),
            "decrypt",
            happ_url,
        ],
    ]

    for command in commands:

        try:

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=REQUEST_TIMEOUT,
            )

            output = (
                result.stdout
                + "\n"
                + result.stderr
            )

            if result.returncode != 0:
                continue

            # ------------------------------------------------
            # HTTPS subscription URL
            # ------------------------------------------------

            urls = (
                extract_https_urls_from_text(
                    output
                )
            )

            if urls:
                return urls

            # ------------------------------------------------
            # Непосредственно URI
            # ------------------------------------------------

            protocol_urls = (
                extract_protocol_links(
                    output
                )
            )

            if protocol_urls:
                return protocol_urls

        except Exception as e:

            print(
                f"[HPWNR] {e}"
            )

    return []


# ============================================================
# PROCESS HAPP LINKS
# ============================================================

def process_happ_links(
    happ_links
):

    if not happ_links:
        return []

    hpwnr = get_hpwnr()

    if not hpwnr:

        print(
            "[HPWNR] hpwnr недоступен"
        )

        return []

    sources = []

    for link in happ_links:

        print(
            "[HAPP] "
            f"{link[:100]}..."
        )

        urls = decrypt_happ(
            link,
            hpwnr,
        )

        for url in urls:

            if is_http_url(
                url
            ):
                sources.append(
                    url
                )

    return dedupe(
        sources
    )


# ============================================================
# HAPP
# ============================================================

def extract_happ_links(text):
    pattern = re.compile(
        r'happ://crypt[0-9A-Za-z_\-./+=?&%]+crypt5',
        re.IGNORECASE,
    )

    return dedupe(
        match.group(0)
        for match in pattern.finditer(text)
    )


def detect_hpwnr_asset():
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        if "aarch64" in machine:
            return "linux-arm64"

        if (
            "arm64" in machine
            or "armv8" in machine
        ):
            return "linux-arm64"

        return "linux-amd64"

    if system == "darwin":
        if "arm" in machine:
            return "darwin-arm64"

        return "darwin-amd64"

    if system == "windows":
        return "windows-amd64.exe"

    return None


def find_local_hpwnr():
    candidates = []

    path = Path(HPWNR_BIN)

    if path.is_absolute():
        candidates.append(path)

    else:
        candidates.append(
            Path.cwd() / path
        )

        candidates.append(
            HPWNR_DIR / path.name
        )

    for item in candidates:
        if item.exists():
            return item

    # PATH
    try:
        result = subprocess.run(
            ["which", HPWNR_BIN],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            value = result.stdout.strip()

            if value:
                return Path(value)

    except Exception:
        pass

    return None


def install_hpwnr():
    if not AUTO_INSTALL_HPWNR:
        return None

    print(
        "[HPWNR] Локальный hpwnr не найден"
    )

    asset = detect_hpwnr_asset()

    if not asset:
        print(
            "[HPWNR] Неизвестная платформа"
        )

        return None

    try:
        api = (
            "https://api.github.com/repos/"
            f"{HPWNR_REPO}/releases/latest"
        )

        response = requests.get(
            api,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if not response.ok:
            print(
                "[HPWNR] GitHub API HTTP "
                f"{response.status_code}"
            )

            return None

        data = response.json()

        download_url = None

        for item in data.get(
            "assets",
            [],
        ):
            name = item.get(
                "name",
                "",
            )

            if asset.lower() in name.lower():
                download_url = item.get(
                    "browser_download_url"
                )

                break

        if not download_url:
            print(
                "[HPWNR] Не найден asset "
                f"{asset}"
            )

            return None

        HPWNR_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination = (
            HPWNR_DIR / asset
        )

        print(
            "[HPWNR] Скачиваю "
            f"{download_url}"
        )

        r = requests.get(
            download_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if not r.ok:
            print(
                "[HPWNR] Download HTTP "
                f"{r.status_code}"
            )

            return None

        destination.write_bytes(
            r.content
        )

        destination.chmod(
            destination.stat().st_mode
            | stat.S_IEXEC
        )

        print(
            "[HPWNR] Installed: "
            f"{destination}"
        )

        return destination

    except Exception as e:
        print(
            f"[HPWNR] Install error: {e}"
        )

        return None


def get_hpwnr():
    local = find_local_hpwnr()

    if local:
        return local

    return install_hpwnr()


def decrypt_happ(happ_url, hpwnr):
    print(
        "[HPWNR] Расшифровка Happ..."
    )

    commands = [
        [
            str(hpwnr),
            happ_url,
        ],
        [
            str(hpwnr),
            "decrypt",
            happ_url,
        ],
    ]

    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=REQUEST_TIMEOUT,
            )

            output = (
                result.stdout
                + "\n"
                + result.stderr
            )

            if result.returncode == 0:
                urls = extract_https_urls_from_text(
                    output
                )

                if urls:
                    return urls

                # Иногда hpwnr выводит URI напрямую
                protocol_urls = (
                    extract_protocol_links(
                        output
                    )
                )

                if protocol_urls:
                    return protocol_urls

        except Exception as e:
            print(
                f"[HPWNR] {e}"
            )

    return []


def process_happ_links(happ_links):
    hpwnr = get_hpwnr()

    if not hpwnr:
        print(
            "[HPWNR] hpwnr недоступен"
        )

        return []

    sources = []

    for link in happ_links:
        print(
            f"[HAPP] {link[:100]}..."
        )

        urls = decrypt_happ(
            link,
            hpwnr,
        )

        for url in urls:
            if is_http_url(url):
                sources.append(url)

    return dedupe(sources)


# ============================================================
# PROTOCOL URI EXTRACTION
# ============================================================

def extract_protocol_links(text):
    if not text:
        return []

    results = []

    schemes = "|".join(
        re.escape(x)
        for x in PROTOCOLS
    )

    pattern = re.compile(
        rf'(?:{schemes})[^\s<>"\'\]\[()]+',
        re.IGNORECASE,
    )

    for match in pattern.finditer(text):
        value = match.group(0)

        value = value.rstrip(
            ".,;:!?)]}"
        )

        results.append(
            value
        )

    return dedupe(results)


# ============================================================
# JSON DETECTION
# ============================================================

def looks_like_xray_config(obj):
    if not isinstance(obj, dict):
        return False

    if (
        "inbounds" in obj
        and "outbounds" in obj
    ):
        return True

    if "outbounds" in obj:
        return True

    if (
        "protocol" in obj
        and (
            "settings" in obj
            or "streamSettings" in obj
        )
    ):
        return True

    return False


def extract_json_configs(obj):
    result = []

    def walk(value):
        if isinstance(value, dict):

            if looks_like_xray_config(value):
                result.append(value)

            for child in value.values():
                walk(child)

        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(obj)

    return result


def parse_json_configs(text):
    text = text.strip()

    if not text:
        return []

    if not (
        text.startswith("{")
        or text.startswith("[")
    ):
        return []

    try:
        obj = json.loads(text)

    except Exception:
        return []

    return extract_json_configs(obj)


# ============================================================
# JSON STRING VALUES
# ============================================================

def extract_json_strings(obj):
    result = []

    def walk(value):
        if isinstance(value, dict):

            for key, child in value.items():

                if isinstance(child, str):
                    result.append(child)

                walk(child)

        elif isinstance(value, list):

            for child in value:
                walk(child)

    walk(obj)

    return dedupe(result)


# ============================================================
# BASE64
# ============================================================

def decode_base64_text(value):
    value = clean_string(value)

    if not value:
        return ""

    if value.startswith(
        "data:text/plain;base64,"
    ):
        value = value.split(
            ",",
            1,
        )[1]

    value = re.sub(
        r"\s+",
        "",
        value,
    )

    # URL-safe Base64
    value += "=" * (
        (-len(value)) % 4
    )

    variants = [
        value,
        value.replace("-", "+")
        .replace("_", "/"),
    ]

    for variant in variants:
        try:
            raw = base64.b64decode(
                variant,
                validate=False,
            )

            text = raw.decode(
                "utf-8",
                errors="ignore",
            ).strip()

            if text:
                return text

        except Exception:
            pass

    return ""


def looks_like_base64(value):
    value = re.sub(
        r"\s+",
        "",
        clean_string(value),
    )

    if len(value) < 16:
        return False

    if not re.fullmatch(
        r"[A-Za-z0-9+/_=-]+",
        value,
    ):
        return False

    decoded = decode_base64_text(
        value
    )

    if not decoded:
        return False

    if extract_protocol_links(
        decoded
    ):
        return True

    if parse_json_configs(
        decoded
    ):
        return True

    return False


# ============================================================
# JSON → URI HELPERS
# ============================================================

def get_outbounds(config):
    if not isinstance(
        config,
        dict,
    ):
        return []

    outbounds = config.get(
        "outbounds",
        [],
    )

    if isinstance(
        outbounds,
        dict,
    ):
        outbounds = [outbounds]

    if not isinstance(
        outbounds,
        list,
    ):
        return []

    return [
        x
        for x in outbounds
        if isinstance(x, dict)
    ]


def is_usable_outbound(outbound):
    protocol = clean_string(
        outbound.get(
            "protocol",
            ""
        )
    ).lower()

    if protocol in (
        "",
        "freedom",
        "blackhole",
        "dns",
        "loopback",
        "dokodemo-door",
    ):
        return False

    return protocol in (
        "vless",
        "vmess",
        "trojan",
        "shadowsocks",
        "ss",
    )


def get_stream_settings(outbound):
    value = outbound.get(
        "streamSettings",
        {},
    )

    if isinstance(
        value,
        dict,
    ):
        return value

    return {}


def get_server_from_settings(settings):
    """
    Возвращает первый server/address
    из разных вариантов Xray JSON.
    """

    vnext = settings.get(
        "vnext"
    )

    if isinstance(
        vnext,
        list,
    ) and vnext:

        first = vnext[0]

        if isinstance(
            first,
            dict,
        ):
            return first

    servers = settings.get(
        "servers"
    )

    if isinstance(
        servers,
        list,
    ) and servers:

        first = servers[0]

        if isinstance(
            first,
            dict,
        ):
            return first

    return settings


def get_name(outbound, fallback=""):
    """
    Сохраняем:
      tag
      remarks
      name
      remark

    Приоритет:
      tag → remarks → name → remark
    """

    for key in (
        "tag",
        "remarks",
        "name",
        "remark",
    ):
        value = outbound.get(key)

        if value:
            return safe_name(value)

    return safe_name(fallback)


# ============================================================
# QUERY BUILDER
# ============================================================

def add_query(query, key, value):
    if value is None:
        return

    if isinstance(value, list):
        if not value:
            return

        value = ",".join(
            str(x)
            for x in value
        )

    value = clean_string(value)

    if value == "":
        return

    query[key] = value


# ============================================================
# VLESS
# ============================================================

def json_vless_to_uri(
    outbound,
    fallback_name="",
):
    settings = outbound.get(
        "settings",
        {},
    )

    if not isinstance(
        settings,
        dict,
    ):
        return []

    vnext = settings.get(
        "vnext",
        [],
    )

    if not isinstance(
        vnext,
        list,
    ):
        return []

    results = []

    stream = get_stream_settings(
        outbound
    )

    network = clean_string(
        stream.get(
            "network",
            "tcp",
        )
    ).lower()

    security = clean_string(
        stream.get(
            "security",
            "none",
        )
    ).lower()

    tls = stream.get(
        "tlsSettings",
        {},
    )

    reality = stream.get(
        "realitySettings",
        {},
    )

    ws = stream.get(
        "wsSettings",
        {},
    )

    grpc = stream.get(
        "grpcSettings",
        {},
    )

    http = stream.get(
        "httpSettings",
        {},
    )

    xhttp = stream.get(
        "xhttpSettings",
        {},
    )

    if not isinstance(tls, dict):
        tls = {}

    if not isinstance(reality, dict):
        reality = {}

    if not isinstance(ws, dict):
        ws = {}

    if not isinstance(grpc, dict):
        grpc = {}

    if not isinstance(http, dict):
        http = {}

    if not isinstance(xhttp, dict):
        xhttp = {}

    name = get_name(
        outbound,
        fallback_name,
    )

    for node in vnext:

        if not isinstance(
            node,
            dict,
        ):
            continue

        address = clean_string(
            node.get(
                "address",
                ""
            )
        )

        port = node.get(
            "port"
        )

        users = node.get(
            "users",
            [],
        )

        if not address or not port:
            continue

        if not isinstance(
            users,
            list,
        ):
            continue

        for user in users:

            if not isinstance(
                user,
                dict,
            ):
                continue

            uuid = clean_string(
                user.get(
                    "id",
                    ""
                )
            )

            if not uuid:
                continue

            query = {}

            # ------------------------------------------------
            # VLESS
            # ------------------------------------------------

            # VLESS standard:
            # encryption=none
            add_query(
                query,
                "encryption",
                user.get(
                    "encryption",
                    "none",
                ),
            )

            add_query(
                query,
                "flow",
                user.get(
                    "flow",
                    ""
                ),
            )

            # ------------------------------------------------
            # network
            # ------------------------------------------------

            add_query(
                query,
                "type",
                network or "tcp",
            )

            add_query(
                query,
                "security",
                security,
            )

            # ------------------------------------------------
            # TCP
            # ------------------------------------------------

            if network in (
                "tcp",
                "raw",
            ):
                tcp = stream.get(
                    "tcpSettings",
                    {},
                )

                if isinstance(
                    tcp,
                    dict,
                ):
                    header = tcp.get(
                        "header",
                        {}
                    )

                    if isinstance(
                        header,
                        dict,
                    ):
                        header_type = (
                            header.get(
                                "type",
                                ""
                            )
                        )

                        if header_type:
                            add_query(
                                query,
                                "headerType",
                                header_type,
                            )

                        request = header.get(
                            "request",
                            {}
                        )

                        if isinstance(
                            request,
                            dict,
                        ):
                            headers = request.get(
                                "headers",
                                {}
                            )

                            if isinstance(
                                headers,
                                dict,
                            ):
                                host = headers.get(
                                    "Host"
                                )

                                if host:
                                    add_query(
                                        query,
                                        "host",
                                        host,
                                    )

            # ------------------------------------------------
            # WS
            # ------------------------------------------------

            elif network == "ws":

                path = ws.get(
                    "path",
                    "/",
                )

                headers = ws.get(
                    "headers",
                    {},
                )

                add_query(
                    query,
                    "path",
                    path,
                )

                if isinstance(
                    headers,
                    dict,
                ):
                    host = headers.get(
                        "Host",
                        headers.get(
                            "host",
                            ""
                        ),
                    )

                    add_query(
                        query,
                        "host",
                        host,
                    )

            # ------------------------------------------------
            # gRPC
            # ------------------------------------------------

            elif network == "grpc":

                service_name = grpc.get(
                    "serviceName",
                    "",
                )

                add_query(
                    query,
                    "serviceName",
                    service_name,
                )

                multi_mode = grpc.get(
                    "multiMode"
                )

                if multi_mode:
                    add_query(
                        query,
                        "mode",
                        "multi",
                    )

            # ------------------------------------------------
            # HTTP/2
            # ------------------------------------------------

            elif network in (
                "http",
                "h2",
            ):

                path = http.get(
                    "path",
                    "/",
                )

                add_query(
                    query,
                    "path",
                    path,
                )

                host = http.get(
                    "host",
                    [],
                )

                if isinstance(
                    host,
                    list,
                ):
                    host = ",".join(
                        str(x)
                        for x in host
                    )

                add_query(
                    query,
                    "host",
                    host,
                )

            # ------------------------------------------------
            # xHTTP
            # ------------------------------------------------

            elif network == "xhttp":

                path = xhttp.get(
                    "path",
                    "/",
                )

                host = xhttp.get(
                    "host",
                    "",
                )

                mode = xhttp.get(
                    "mode",
                    "",
                )

                add_query(
                    query,
                    "path",
                    path,
                )

                add_query(
                    query,
                    "host",
                    host,
                )

                add_query(
                    query,
                    "mode",
                    mode,
                )

            # ------------------------------------------------
            # TLS
            # ------------------------------------------------

            if security == "tls":

                add_query(
                    query,
                    "sni",
                    tls.get(
                        "serverName",
                        ""
                    ),
                )

                add_query(
                    query,
                    "fp",
                    tls.get(
                        "fingerprint",
                        ""
                    ),
                )

                alpn = tls.get(
                    "alpn"
                )

                if isinstance(
                    alpn,
                    list,
                ):
                    # Сохраняем ALPN как в Xray
                    alpn = ",".join(
                        str(x)
                        for x in alpn
                    )

                add_query(
                    query,
                    "alpn",
                    alpn,
                )

                if tls.get(
                    "allowInsecure"
                ):
                    add_query(
                        query,
                        "allowInsecure",
                        "1",
                    )

            # ------------------------------------------------
            # REALITY
            # ------------------------------------------------

            elif security == "reality":

                add_query(
                    query,
                    "sni",
                    reality.get(
                        "serverName",
                        ""
                    ),
                )

                add_query(
                    query,
                    "fp",
                    reality.get(
                        "fingerprint",
                        ""
                    ),
                )

                add_query(
                    query,
                    "pbk",
                    reality.get(
                        "publicKey",
                        ""
                    ),
                )

                add_query(
                    query,
                    "sid",
                    reality.get(
                        "shortId",
                        ""
                    ),
                )

                add_query(
                    query,
                    "spx",
                    reality.get(
                        "spiderX",
                        ""
                    ),
                )

            # ------------------------------------------------
            # Build URI
            # ------------------------------------------------

            query_string = urlencode(
                query,
                doseq=False,
            )

            uri = (
                "vless://"
                f"{quote(uuid, safe='')}"
                "@"
                f"{address}:{port}"
            )

            if query_string:
                uri += "?" + query_string

            uri = build_uri_with_name(
                uri,
                name,
            )

            results.append(uri)

    return results


# ============================================================
# VMESS
# ============================================================

def json_vmess_to_uri(
    outbound,
    fallback_name="",
):
    settings = outbound.get(
        "settings",
        {},
    )

    if not isinstance(
        settings,
        dict,
    ):
        return []

    vnext = settings.get(
        "vnext",
        [],
    )

    if not isinstance(
        vnext,
        list,
    ):
        return []

    stream = get_stream_settings(
        outbound
    )

    network = clean_string(
        stream.get(
            "network",
            "tcp",
        )
    ).lower()

    security = clean_string(
        stream.get(
            "security",
            "none",
        )
    ).lower()

    tls = stream.get(
        "tlsSettings",
        {},
    )

    ws = stream.get(
        "wsSettings",
        {},
    )

    grpc = stream.get(
        "grpcSettings",
        {},
    )

    if not isinstance(tls, dict):
        tls = {}

    if not isinstance(ws, dict):
        ws = {}

    if not isinstance(grpc, dict):
        grpc = {}

    name = get_name(
        outbound,
        fallback_name,
    )

    results = []

    for node in vnext:

        if not isinstance(
            node,
            dict,
        ):
            continue

        address = clean_string(
            node.get(
                "address",
                ""
            )
        )

        port = node.get(
            "port"
        )

        users = node.get(
            "users",
            [],
        )

        if not address or not port:
            continue

        if not isinstance(
            users,
            list,
        ):
            continue

        for user in users:

            if not isinstance(
                user,
                dict,
            ):
                continue

            uuid = clean_string(
                user.get(
                    "id",
                    ""
                )
            )

            if not uuid:
                continue

            vmess = {
                "v": "2",
                "ps": name,
                "add": address,
                "port": str(port),
                "id": uuid,
                "aid": str(
                    user.get(
                        "alterId",
                        0,
                    )
                ),
                "scy": user.get(
                    "security",
                    "auto",
                ),
                "net": network,
                "type": "none",
                "host": "",
                "path": "",
                "tls": "",
                "sni": "",
            }

            if network == "ws":

                vmess["path"] = ws.get(
                    "path",
                    "/",
                )

                headers = ws.get(
                    "headers",
                    {},
                )

                if isinstance(
                    headers,
                    dict,
                ):
                    vmess["host"] = (
                        headers.get(
                            "Host",
                            headers.get(
                                "host",
                                ""
                            ),
                        )
                    )

            elif network == "grpc":

                vmess["path"] = grpc.get(
                    "serviceName",
                    "",
                )

                vmess["type"] = "none"

            if security in (
                "tls",
                "reality",
            ):
                vmess["tls"] = "tls"

                vmess["sni"] = (
                    tls.get(
                        "serverName",
                        "",
                    )
                )

            raw = json.dumps(
                vmess,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()

            encoded = (
                base64.b64encode(raw)
                .decode()
            )

            results.append(
                "vmess://"
                + encoded
            )

    return results


# ============================================================
# TROJAN
# ============================================================

def json_trojan_to_uri(
    outbound,
    fallback_name="",
):
    settings = outbound.get(
        "settings",
        {},
    )

    if not isinstance(
        settings,
        dict,
    ):
        return []

    servers = settings.get(
        "servers",
        [],
    )

    if not isinstance(
        servers,
        list,
    ):
        return []

    stream = get_stream_settings(
        outbound
    )

    network = clean_string(
        stream.get(
            "network",
            "tcp",
        )
    ).lower()

    security = clean_string(
        stream.get(
            "security",
            "none",
        )
    ).lower()

    tls = stream.get(
        "tlsSettings",
        {},
    )

    ws = stream.get(
        "wsSettings",
        {},
    )

    grpc = stream.get(
        "grpcSettings",
        {},
    )

    if not isinstance(tls, dict):
        tls = {}

    if not isinstance(ws, dict):
        ws = {}

    if not isinstance(grpc, dict):
        grpc = {}

    name = get_name(
        outbound,
        fallback_name,
    )

    results = []

    for server in servers:

        if not isinstance(
            server,
            dict,
        ):
            continue

        address = clean_string(
            server.get(
                "address",
                ""
            )
        )

        port = server.get(
            "port"
        )

        password = clean_string(
            server.get(
                "password",
                ""
            )
        )

        if not address or not port or not password:
            continue

        query = {}

        add_query(
            query,
            "type",
            network,
        )

        add_query(
            query,
            "security",
            security,
        )

        if network == "ws":

            add_query(
                query,
                "path",
                ws.get(
                    "path",
                    "/",
                ),
            )

            headers = ws.get(
                "headers",
                {},
            )

            if isinstance(
                headers,
                dict,
            ):
                add_query(
                    query,
                    "host",
                    headers.get(
                        "Host",
                        headers.get(
                            "host",
                            ""
                        ),
                    ),
                )

        elif network == "grpc":

            add_query(
                query,
                "serviceName",
                grpc.get(
                    "serviceName",
                    "",
                ),
            )

        if security == "tls":

            add_query(
                query,
                "sni",
                tls.get(
                    "serverName",
                    "",
                ),
            )

            add_query(
                query,
                "fp",
                tls.get(
                    "fingerprint",
                    "",
                ),
            )

            alpn = tls.get(
                "alpn"
            )

            if isinstance(
                alpn,
                list,
            ):
                alpn = ",".join(
                    str(x)
                    for x in alpn
                )

            add_query(
                query,
                "alpn",
                alpn,
            )

        uri = (
            "trojan://"
            f"{quote(password, safe='')}"
            "@"
            f"{address}:{port}"
        )

        if query:
            uri += "?" + urlencode(
                query
            )

        uri = build_uri_with_name(
            uri,
            name,
        )

        results.append(uri)

    return results


# ============================================================
# SHADOWSOCKS
# ============================================================

def json_ss_to_uri(
    outbound,
    fallback_name="",
):
    settings = outbound.get(
        "settings",
        {},
    )

    if not isinstance(
        settings,
        dict,
    ):
        return []

    servers = settings.get(
        "servers",
        [],
    )

    if not isinstance(
        servers,
        list,
    ):
        return []

    name = get_name(
        outbound,
        fallback_name,
    )

    results = []

    for server in servers:

        if not isinstance(
            server,
            dict,
        ):
            continue

        address = clean_string(
            server.get(
                "address",
                ""
            )
        )

        port = server.get(
            "port"
        )

        method = clean_string(
            server.get(
                "method",
                ""
            )
        )

        password = clean_string(
            server.get(
                "password",
                ""
            )
        )

        if not address or not port:
            continue

        if not method:
            continue

        userinfo = (
            f"{method}:{password}"
        )

        encoded = base64.b64encode(
            userinfo.encode()
        ).decode().rstrip("=")

        uri = (
            "ss://"
            f"{encoded}"
            "@"
            f"{address}:{port}"
        )

        uri = build_uri_with_name(
            uri,
            name,
        )

        results.append(uri)

    return results


# ============================================================
# JSON CONFIG → URI
# ============================================================

def json_config_to_uri(
    outbound,
    fallback_name="",
):
    protocol = clean_string(
        outbound.get(
            "protocol",
            ""
        )
    ).lower()

    if protocol == "vless":
        return json_vless_to_uri(
            outbound,
            fallback_name,
        )

    if protocol == "vmess":
        return json_vmess_to_uri(
            outbound,
            fallback_name,
        )

    if protocol == "trojan":
        return json_trojan_to_uri(
            outbound,
            fallback_name,
        )

    if protocol in (
        "shadowsocks",
        "ss",
    ):
        return json_ss_to_uri(
            outbound,
            fallback_name,
        )

    return []


def convert_json_configs_to_uris(
    configs
):
    result = []

    for config in configs:

        if not isinstance(
            config,
            dict,
        ):
            continue

        # ----------------------------------------------------
        # Если это сам outbound
        # ----------------------------------------------------

        if (
            "protocol" in config
            and "settings" in config
        ):
            name = get_name(
                config
            )

            result.extend(
                json_config_to_uri(
                    config,
                    name,
                )
            )

            continue

        # ----------------------------------------------------
        # Обычный Xray config
        # ----------------------------------------------------

        outbounds = get_outbounds(
            config
        )

        # Если root имеет remarks
        root_name = safe_name(
            config.get(
                "remarks",
                config.get(
                    "name",
                    "",
                ),
            )
        )

        for outbound in outbounds:

            if not is_usable_outbound(
                outbound
            ):
                continue

            tag = get_name(
                outbound,
                root_name,
            )

            uris = json_config_to_uri(
                outbound,
                tag,
            )

            if uris:
                result.extend(uris)

            else:
                protocol = clean_string(
                    outbound.get(
                        "protocol",
                        ""
                    )
                )

                print(
                    "[JSON] Пропущен "
                    f"unsupported protocol: "
                    f"{protocol}"
                    f" tag={tag}"
                )

    return dedupe(result)


# ============================================================
# PARSE CONTENT
# ============================================================

def parse_content(text):
    """
    Возвращает:
      direct_uris
      json_configs
    """

    if not text:
        return [], []

    direct_uris = []
    json_configs = []

    # --------------------------------------------------------
    # 1. Прямые URI
    # --------------------------------------------------------

    direct_uris.extend(
        extract_protocol_links(text)
    )

    # --------------------------------------------------------
    # 2. JSON
    # --------------------------------------------------------

    configs = parse_json_configs(
        text
    )

    json_configs.extend(
        configs
    )

    # --------------------------------------------------------
    # 3. URI внутри JSON strings
    # --------------------------------------------------------

    if configs:

        for config in configs:

            strings = (
                extract_json_strings(
                    config
                )
            )

            for value in strings:

                direct_uris.extend(
                    extract_protocol_links(
                        value
                    )
                )

    # --------------------------------------------------------
    # 4. Base64
    # --------------------------------------------------------

    stripped = text.strip()

    if looks_like_base64(
        stripped
    ):
        decoded = decode_base64_text(
            stripped
        )

        if decoded:

            direct_uris.extend(
                extract_protocol_links(
                    decoded
                )
            )

            json_configs.extend(
                parse_json_configs(
                    decoded
                )
            )

    return (
        dedupe(direct_uris),
        json_configs,
    )


# ============================================================
# DOWNLOAD
# ============================================================

def download_source(url):
    print(
        f"[DOWNLOAD] {url}"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )

        print(
            f"[DOWNLOAD] HTTP "
            f"{response.status_code}"
        )

        if not response.ok:
            return ""

        chunks = []
        total = 0

        for chunk in response.iter_content(
            chunk_size=65536
        ):
            if not chunk:
                continue

            total += len(chunk)

            if total > MAX_SOURCE_SIZE:
                print(
                    "[DOWNLOAD] Размер "
                    "превысил лимит"
                )

                return ""

            chunks.append(chunk)

        data = b"".join(
            chunks
        )

        return data.decode(
            "utf-8",
            errors="ignore",
        )

    except Exception as e:
        print(
            f"[DOWNLOAD] Ошибка: {e}"
        )

        return ""


# ============================================================
# WRAPPER URL
# ============================================================

def extract_wrapper_urls(url):
    """
    Поддержка:
      ?url=
      ?target=
      ?src=
      ?source=
      ?link=
      ?sub=
      ?subscription=
    """

    result = [url]

    try:
        query = parse_qs(
            urlsplit(url).query
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

                if is_http_url(value):
                    result.append(
                        value
                    )

    except Exception:
        pass

    return dedupe(result)


# ============================================================
# DEBUG
# ============================================================

def debug_preview(text):
    if not DEBUG_PREVIEW:
        return

    preview = text[:DEBUG_PREVIEW]

    print(
        "[DEBUG] Preview:"
    )

    print(
        preview
    )


# ============================================================
# PARSE SOURCE
# ============================================================

def parse_source(url):
    all_uris = []
    all_json = []

    candidates = (
        extract_wrapper_urls(url)
    )

    for candidate in candidates:

        content = download_source(
            candidate
        )

        if not content:
            continue

        debug_preview(
            content
        )

        uris, json_configs = (
            parse_content(
                content
            )
        )

        print(
            "[PARSE] URI: "
            f"{len(uris)}"
            " | JSON: "
            f"{len(json_configs)}"
        )

        all_uris.extend(
            uris
        )

        all_json.extend(
            json_configs
        )

        # ----------------------------------------------------
        # Если JSON обнаружен — также проверяем
        # строки внутри него.
        # ----------------------------------------------------

        for config in json_configs:

            for value in extract_json_strings(
                config
            ):
                all_uris.extend(
                    extract_protocol_links(
                        value
                    )
                )

        # ----------------------------------------------------
        # Если content является Base64,
        # parse_content уже раскрыл его.
        # ----------------------------------------------------

    return (
        dedupe(all_uris),
        all_json,
    )


# ============================================================
# GIST
# ============================================================

def update_gist(
    filename,
    content,
):
    if not GIST_TOKEN:
        raise RuntimeError(
            "GIST_TOKEN не задан"
        )

    if not GIST_ID:
        raise RuntimeError(
            "GIST_ID не задан"
        )

    url = (
        f"https://api.github.com/gists/"
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
            "happvpn-parser",
    }

    payload = {
        "files": {
            filename: {
                "content": content
            }
        }
    }

    response = requests.patch(
        url,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    if not response.ok:
        raise RuntimeError(
            "Gist update failed: "
            f"HTTP {response.status_code}\n"
            f"{response.text[:1000]}"
        )

    print(
        "[GIST] Updated:"
        f" {filename}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "========================================"
    )

    print(
        " HappVPN Telegram → URI parser"
    )

    print(
        "========================================"
    )

    # --------------------------------------------------------
    # Telegram channel
    # --------------------------------------------------------

    print(
        "[TELEGRAM] Получаю канал..."
    )

    channel_page = get_channel_page()

    if not channel_page:
        raise RuntimeError(
            "Не удалось получить Telegram канал"
        )

    post_url = get_last_post_url(
        channel_page
    )

    if not post_url:

        # Дополнительный вывод для диагностики,
        # но не печатаем весь HTML.
        print(
            "[TELEGRAM] Не удалось найти "
            "ссылку на пост."
        )

        print(
            "[TELEGRAM] HTML preview:"
        )

        print(
            re.sub(
                r"\s+",
                " ",
                channel_page[:1000],
            )
        )

        raise RuntimeError(
            "Не найден последний пост Telegram"
        )

    print(
        "[TELEGRAM] Последний пост:"
        f" {post_url}"
    )

    post_html = fetch_post(
        post_url
    )

    if not post_html:
        raise RuntimeError(
            "Не удалось получить последний "
            "пост Telegram"
        )

    # --------------------------------------------------------
    # Sources
    # --------------------------------------------------------

    normal_sources = (
        extract_telegram_sources(
            post_html
        )
    )

    happ_links = extract_happ_links(
        post_html
    )

    print(
        "[TELEGRAM] HTTPS sources:"
        f" {len(normal_sources)}"
    )

    print(
        "[TELEGRAM] Happ links:"
        f" {len(happ_links)}"
    )

    # --------------------------------------------------------
    # HAPP
    # --------------------------------------------------------

    happ_sources = (
        process_happ_links(
            happ_links
        )
    )

    print(
        "[HAPP] Decrypted sources:"
        f" {len(happ_sources)}"
    )

    sources = dedupe(
        normal_sources
        + happ_sources
    )

    print(
        "[SOURCES] TOTAL:"
        f" {len(sources)}"
    )

    # --------------------------------------------------------
    # Parse all
    # --------------------------------------------------------

    all_uri_configs = []
    all_json_configs = []

    for index, source in enumerate(
        sources,
        1,
    ):
        print(
            ""
        )

        print(
            f"[SOURCE {index}/{len(sources)}]"
        )

        print(
            source
        )

        uris, json_configs = (
            parse_source(
                source
            )
        )

        all_uri_configs.extend(
            uris
        )

        all_json_configs.extend(
            json_configs
        )

    # --------------------------------------------------------
    # JSON → URI
    # --------------------------------------------------------

    print(
        ""
    )

    print(
        "[JSON] Конвертирую JSON → URI..."
    )

    converted_json_uris = (
        convert_json_configs_to_uris(
            all_json_configs
        )
    )

    # --------------------------------------------------------
    # Merge
    # --------------------------------------------------------

    all_uri_configs = dedupe(
        all_uri_configs
        + converted_json_uris
    )

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    output = "\n".join(
        all_uri_configs
    )

    if output:
        output += "\n"

    print(
        ""
    )

    print(
        "========================================"
    )

    print(
        "[RESULT] Direct URI configs:"
        f" {len(all_uri_configs) - len(converted_json_uris)}"
    )

    print(
        "[RESULT] JSON configs converted:"
        f" {len(converted_json_uris)}"
    )

    print(
        "[RESULT] TOTAL URI configs:"
        f" {len(all_uri_configs)}"
    )

    print(
        "========================================"
    )

    if not all_uri_configs:
        raise RuntimeError(
            "Не найдено ни одного URI"
        )

    # --------------------------------------------------------
    # ВАЖНО:
    # В Gist записываются только URI.
    # Никакого JSON.
    # --------------------------------------------------------

    print(
        f"[GIST] Записываю {GIST_FILENAME}"
    )

    update_gist(
        GIST_FILENAME,
        output,
    )

    print(
        "[DONE] Готово."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:
        print(
            "\n[STOP] Interrupted"
        )

        sys.exit(130)

    except Exception as e:
        print(
            f"[FATAL] {e}"
        )

        sys.exit(1)