#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HappVPN Telegram → Gist URI parser

Что делает:
1. Берёт последний пост Telegram-канала.
2. Находит HTTPS subscription URLs.
3. Находит happ://crypt...crypt5 ссылки.
4. Расшифровывает happ:// через hpwnr.
5. Скачивает подписки.
6. Обрабатывает:
   - обычные URI
   - Base64
   - JSON
   - Xray JSON
7. Если получен JSON:
   - перебирает ВСЕ outbounds
   - сохраняет tag каждого proxy-*
   - конвертирует VLESS / VMess / Trojan / Shadowsocks
8. Поддерживает:
   - VLESS XHTTP
   - VLESS WS
   - VLESS gRPC
   - VLESS TCP
   - VLESS TLS
   - VLESS Reality
   - VMess WS/gRPC/TCP/TLS
   - Trojan WS/gRPC/TLS
   - Shadowsocks
9. В Gist публикуются ТОЛЬКО URI.
10. JSON в результирующий файл никогда не записывается.
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
    "happvpn"
).strip().lstrip("@")

GIST_TOKEN = os.getenv(
    "GIST_TOKEN",
    ""
).strip()

GIST_ID = os.getenv(
    "GIST_ID",
    ""
).strip()

GIST_FILENAME = os.getenv(
    "GIST_FILENAME",
    "happ.txt"
).strip()

REQUEST_TIMEOUT = int(
    os.getenv(
        "REQUEST_TIMEOUT",
        "30"
    )
)

MAX_SOURCE_SIZE = int(
    os.getenv(
        "MAX_SOURCE_SIZE",
        str(10 * 1024 * 1024)
    )
)

DEBUG_PREVIEW = int(
    os.getenv(
        "DEBUG_PREVIEW",
        "500"
    )
)


# ============================================================
# HPWNR
# ============================================================

HPWNR_BIN = os.getenv(
    "HPWNR_BIN",
    "hpwnr"
).strip()

HPWNR_DIR = Path(
    os.getenv(
        "HPWNR_DIR",
        ".hpwnr"
    )
)

AUTO_INSTALL_HPWNR = (
    os.getenv(
        "AUTO_INSTALL_HPWNR",
        "true"
    ).lower()
    in ("1", "true", "yes", "on")
)

HPWNR_REPO = os.getenv(
    "HPWNR_REPO",
    "Omegaplexx/hpwnr"
).strip()


# ============================================================
# USER AGENT
# ============================================================

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; "
    "K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/131.0.0.0 Mobile Safari/537.36"
)


HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
}


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


HAPP_SCHEMES = (
    "happ://crypt",
    "happ://crypt2",
    "happ://crypt3",
    "happ://crypt4",
    "happ://crypt5",
)


# ============================================================
# HTML PARSER
# ============================================================

class LinkParser(HTMLParser):

    def __init__(self):
        super().__init__()

        self.links = []
        self.text_parts = []
        self.current_href = None

    def handle_starttag(self, tag, attrs):

        if tag.lower() != "a":
            return

        attrs_dict = dict(attrs)

        self.current_href = attrs_dict.get(
            "href"
        )

    def handle_endtag(self, tag):

        if tag.lower() == "a":
            self.current_href = None

    def handle_data(self, data):

        if self.current_href:
            self.links.append(
                (
                    self.current_href,
                    data.strip()
                )
            )

        self.text_parts.append(data)


# ============================================================
# GENERAL HELPERS
# ============================================================

def normalize_url(url: str) -> str:

    url = html.unescape(
        url.strip()
    )

    url = url.strip(
        "\"'<>[]()"
    )

    return url


def is_http_url(url: str) -> bool:

    try:
        p = urlsplit(url)

        return p.scheme.lower() in (
            "http",
            "https",
        ) and bool(p.netloc)

    except Exception:
        return False


def dedupe(items):

    result = []
    seen = set()

    for item in items:

        if not item:
            continue

        item = item.strip()

        if not item:
            continue

        if item in seen:
            continue

        seen.add(item)
        result.append(item)

    return result


def clean_config_text(text: str) -> str:

    if not text:
        return ""

    text = text.replace(
        "\ufeff",
        ""
    )

    text = text.replace(
        "\r\n",
        "\n"
    )

    text = text.replace(
        "\r",
        "\n"
    )

    return text.strip()


def first_value(value, default=None):

    if isinstance(value, list):

        if not value:
            return default

        return value[0]

    if value is None:
        return default

    return value


# ============================================================
# TELEGRAM
# ============================================================

def get_channel_page():

    url = (
        f"https://t.me/s/"
        f"{quote(TELEGRAM_CHANNEL)}"
    )

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.text


def get_last_post_url(page: str):

    matches = re.findall(
        r'href="(/'
        + re.escape(TELEGRAM_CHANNEL)
        + r"/\d+)\"",
        page
    )

    if not matches:
        raise RuntimeError(
            "Не найден последний пост Telegram"
        )

    nums = []

    for x in matches:

        m = re.search(
            r"/(\d+)$",
            x
        )

        if m:
            nums.append(
                (
                    int(m.group(1)),
                    x
                )
            )

    if not nums:
        raise RuntimeError(
            "Не найден ID поста"
        )

    nums.sort(
        key=lambda x: x[0]
    )

    return (
        "https://t.me"
        + nums[-1][1]
    )


def fetch_post(post_url: str):

    response = requests.get(
        post_url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.text


# ============================================================
# TELEGRAM URL FILTER
# ============================================================

def is_ignored_url(url: str) -> bool:

    try:

        p = urlsplit(url)

        host = p.netloc.lower()

        if host.endswith(
            "t.me"
        ):
            return True

        if host.endswith(
            "telegram.me"
        ):
            return True

        path = p.path.lower()

        bad_ext = (
            ".js",
            ".css",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".svg",
            ".woff",
            ".woff2",
            ".ttf",
        )

        if path.endswith(bad_ext):
            return True

        return False

    except Exception:
        return True


# ============================================================
# HAPP LINKS
# ============================================================

def extract_happ_links(text: str):

    result = []

    for scheme in HAPP_SCHEMES:

        pattern = (
            re.escape(scheme)
            + r"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+"
        )

        result.extend(
            re.findall(
                pattern,
                text,
                flags=re.I
            )
        )

    return dedupe(result)


def detect_platform():

    system = platform.system().lower()

    machine = platform.machine().lower()

    if system == "linux":

        if "aarch64" in machine:
            return "linux-arm64"

        if "arm64" in machine:
            return "linux-arm64"

        if "x86_64" in machine:
            return "linux-amd64"

        return "linux-amd64"

    if system == "darwin":

        if "arm64" in machine:
            return "darwin-arm64"

        return "darwin-amd64"

    if system == "windows":

        return "windows-amd64"

    return "linux-amd64"


def find_local_hpwnr():

    # PATH
    try:

        result = subprocess.run(
            [
                "which",
                HPWNR_BIN
            ],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:

            path = result.stdout.strip()

            if path:
                return path

    except Exception:
        pass

    # Local directory
    candidates = [
        HPWNR_DIR / "hpwnr",
        HPWNR_DIR / "hpwnr.exe",
        Path("./hpwnr"),
        Path("./hpwnr.exe"),
    ]

    for path in candidates:

        if path.exists():

            try:
                path.chmod(
                    path.stat().st_mode
                    | stat.S_IEXEC
                )
            except Exception:
                pass

            return str(path)

    return None


def install_hpwnr():

    if not AUTO_INSTALL_HPWNR:
        return None

    print(
        "[HPWNR] hpwnr не найден, "
        "пытаюсь установить..."
    )

    HPWNR_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    platform_name = detect_platform()

    api_url = (
        "https://api.github.com/repos/"
        + HPWNR_REPO
        + "/releases/latest"
    )

    try:

        response = requests.get(
            api_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        release = response.json()

    except Exception as e:

        print(
            f"[WARN] Не удалось получить "
            f"hpwnr release: {e}"
        )

        return None

    assets = release.get(
        "assets",
        []
    )

    selected = None

    for asset in assets:

        name = asset.get(
            "name",
            ""
        )

        lname = name.lower()

        if platform_name in lname:

            selected = asset

            break

    if selected is None:

        # Вторичная эвристика
        for asset in assets:

            name = asset.get(
                "name",
                ""
            ).lower()

            if (
                "linux" in name
                and (
                    "arm64" in name
                    or "amd64" in name
                    or "x86_64" in name
                )
            ):

                selected = asset
                break

    if selected is None:

        print(
            "[WARN] Подходящий hpwnr asset "
            "не найден"
        )

        return None

    download_url = selected.get(
        "browser_download_url"
    )

    if not download_url:
        return None

    archive_name = selected.get(
        "name",
        "hpwnr"
    )

    archive_path = (
        HPWNR_DIR
        / archive_name
    )

    try:

        with requests.get(
            download_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            stream=True
        ) as r:

            r.raise_for_status()

            with open(
                archive_path,
                "wb"
            ) as f:

                for chunk in r.iter_content(
                    1024 * 1024
                ):

                    if chunk:
                        f.write(chunk)

    except Exception as e:

        print(
            f"[WARN] Ошибка загрузки hpwnr: {e}"
        )

        return None

    # Если скачали обычный executable
    if archive_path.suffix == "":

        try:

            archive_path.chmod(
                archive_path.stat().st_mode
                | stat.S_IEXEC
            )

            return str(archive_path)

        except Exception:
            pass

    # tar.gz
    if (
        archive_path.name.endswith(
            ".tar.gz"
        )
        or archive_path.name.endswith(
            ".tgz"
        )
    ):

        try:

            subprocess.run(
                [
                    "tar",
                    "-xzf",
                    str(archive_path),
                    "-C",
                    str(HPWNR_DIR)
                ],
                check=True
            )

        except Exception as e:

            print(
                f"[WARN] tar error: {e}"
            )

            return None

    # zip
    elif archive_path.name.endswith(
        ".zip"
    ):

        try:

            subprocess.run(
                [
                    "unzip",
                    "-o",
                    str(archive_path),
                    "-d",
                    str(HPWNR_DIR)
                ],
                check=True
            )

        except Exception as e:

            print(
                f"[WARN] unzip error: {e}"
            )

            return None

    return find_local_hpwnr()


def get_hpwnr():

    binary = find_local_hpwnr()

    if binary:
        return binary

    return install_hpwnr()


def decrypt_happ_link(link: str):

    binary = get_hpwnr()

    if not binary:

        print(
            "[WARN] hpwnr недоступен"
        )

        return []

    commands = [
        [
            binary,
            link
        ],
        [
            binary,
            "decrypt",
            link
        ],
    ]

    for command in commands:

        try:

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=REQUEST_TIMEOUT
            )

            output = (
                result.stdout
                + "\n"
                + result.stderr
            )

            if result.returncode != 0:
                continue

            urls = re.findall(
                r'https?://[^\s<>"\']+',
                output
            )

            urls = [
                normalize_url(x)
                for x in urls
            ]

            urls = [
                x for x in urls
                if is_http_url(x)
            ]

            if urls:
                return dedupe(urls)

        except Exception as e:

            print(
                f"[WARN] hpwnr error: {e}"
            )

    return []


def process_happ_links(happ_links):

    result = []

    for link in happ_links:

        print(
            "[HAPP] Расшифровка..."
        )

        urls = decrypt_happ_link(
            link
        )

        if urls:

            print(
                f"[HAPP] Получено URL: "
                f"{len(urls)}"
            )

            result.extend(urls)

        else:

            print(
                "[HAPP] URL не получен"
            )

    return dedupe(result)


# ============================================================
# NORMAL TELEGRAM SOURCES
# ============================================================

def extract_source_urls(post_html: str):

    parser = LinkParser()

    parser.feed(
        post_html
    )

    result = []

    # href
    for href, text in parser.links:

        href = normalize_url(
            href or ""
        )

        if (
            is_http_url(href)
            and not is_ignored_url(href)
        ):
            result.append(href)

        # URL inside anchor text
        if text:

            found = re.findall(
                r'https?://[^\s<>"\']+',
                text
            )

            for url in found:

                url = normalize_url(
                    url
                )

                if (
                    is_http_url(url)
                    and not is_ignored_url(url)
                ):
                    result.append(url)

    # Raw HTML text
    plain = html.unescape(
        re.sub(
            r"<[^>]+>",
            " ",
            post_html
        )
    )

    found = re.findall(
        r'https?://[^\s<>"\']+',
        plain
    )

    for url in found:

        url = normalize_url(
            url
        )

        if (
            is_http_url(url)
            and not is_ignored_url(url)
        ):
            result.append(url)

    return dedupe(result)


# ============================================================
# WRAPPER URL
# ============================================================

def extract_wrapper_urls(url: str):

    result = [url]

    try:

        p = urlsplit(url)

        query = parse_qs(
            p.query
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
                []
            ):

                value = unquote(
                    value
                ).strip()

                if is_http_url(value):
                    result.append(value)

    except Exception:
        pass

    return dedupe(result)


# ============================================================
# JSON DETECTION
# ============================================================

def looks_like_xray_config(obj) -> bool:

    if not isinstance(
        obj,
        dict
    ):
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

    if isinstance(obj, dict):

        if looks_like_xray_config(obj):
            result.append(obj)

        for value in obj.values():

            result.extend(
                extract_json_configs(value)
            )

    elif isinstance(obj, list):

        for item in obj:

            result.extend(
                extract_json_configs(item)
            )

    return result


def parse_json_configs(text: str):

    text = clean_config_text(
        text
    )

    if not text:
        return []

    if not (
        text.startswith("{")
        or text.startswith("[")
    ):
        return []

    try:

        obj = json.loads(
            text
        )

    except Exception:
        return []

    return extract_json_configs(
        obj
    )


# ============================================================
# JSON STRING EXTRACTION
# ============================================================

def extract_strings_recursive(obj):

    result = []

    if isinstance(obj, dict):

        for value in obj.values():

            result.extend(
                extract_strings_recursive(
                    value
                )
            )

    elif isinstance(obj, list):

        for value in obj:

            result.extend(
                extract_strings_recursive(
                    value
                )
            )

    elif isinstance(obj, str):

        result.append(obj)

    return result


# ============================================================
# BASE64
# ============================================================

def try_base64_decode(text: str):

    value = text.strip()

    if value.startswith(
        "data:text/plain;base64,"
    ):

        value = value.split(
            ",",
            1
        )[1]

    value = re.sub(
        r"\s+",
        "",
        value
    )

    if not value:
        return None

    candidates = [
        value,
        value.replace("-", "+")
             .replace("_", "/")
    ]

    for candidate in candidates:

        try:

            padding = (
                "="
                * (
                    (-len(candidate))
                    % 4
                )
            )

            raw = base64.b64decode(
                candidate
                + padding,
                validate=False
            )

            decoded = raw.decode(
                "utf-8",
                errors="replace"
            )

            if decoded.strip():
                return decoded

        except Exception:
            continue

    return None


def looks_like_base64(text: str) -> bool:

    value = re.sub(
        r"\s+",
        "",
        text.strip()
    )

    if len(value) < 16:
        return False

    if not re.fullmatch(
        r"[A-Za-z0-9+/=_-]+",
        value
    ):
        return False

    decoded = try_base64_decode(
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
# URI EXTRACTION
# ============================================================

def extract_protocol_links(text: str):

    if not text:
        return []

    escaped = "|".join(
        re.escape(x)
        for x in PROTOCOLS
    )

    pattern = (
        "("
        + escaped
        + r")[^\s<>'\"`]+"
    )

    found = re.findall(
        pattern,
        text,
        flags=re.I
    )

    # Above regex with capture returns only scheme.
    # Use second regex for full links.

    pattern_full = (
        "(?:"
        + escaped
        + ")"
        + r"[^\s<>'\"`]+"
    )

    links = re.findall(
        pattern_full,
        text,
        flags=re.I
    )

    result = []

    for link in links:

        link = link.rstrip(
            ".,;:)]}"
        )

        result.append(
            link
        )

    return dedupe(result)


# ============================================================
# X-RAY OUTBOUND HELPERS
# ============================================================

def get_outbounds(data):

    if isinstance(
        data,
        dict
    ):

        outbounds = data.get(
            "outbounds"
        )

        if isinstance(
            outbounds,
            list
        ):
            return outbounds

    elif isinstance(
        data,
        list
    ):

        return [
            x
            for x in data
            if isinstance(x, dict)
        ]

    return []


def get_outbound_name(obj):

    """
    Имя конкретного proxy.

    Для твоего JSON:
        "tag": "proxy-11"

    → #proxy-11

    Приоритет:
        tag
        remarks
        remark
        name
        ps
        label
    """

    if not isinstance(
        obj,
        dict
    ):
        return "Proxy"

    for key in (
        "tag",
        "remarks",
        "remark",
        "name",
        "ps",
        "label",
        "title",
    ):

        value = obj.get(
            key
        )

        if value is None:
            continue

        value = str(
            value
        ).strip()

        if value:
            return value

    return "Proxy"


def get_stream_settings(outbound):

    if not isinstance(
        outbound,
        dict
    ):
        return {}

    stream = outbound.get(
        "streamSettings"
    )

    if isinstance(
        stream,
        dict
    ):
        return stream

    return {}


def get_server_from_settings(settings):

    if not isinstance(
        settings,
        dict
    ):
        return None, None

    # VLESS / VMess
    for key in (
        "vnext",
        "servers",
    ):

        items = settings.get(
            key
        )

        if (
            isinstance(items, list)
            and items
        ):

            item = items[0]

            if isinstance(
                item,
                dict
            ):

                address = (
                    item.get("address")
                    or item.get("host")
                    or item.get("server")
                )

                port = item.get(
                    "port"
                )

                return address, port

    # Direct
    address = (
        settings.get("address")
        or settings.get("server")
        or settings.get("host")
    )

    port = settings.get(
        "port"
    )

    return address, port


# ============================================================
# URI BUILDERS
# ============================================================

def build_uri_query(params):

    clean = {}

    for key, value in params.items():

        if value is None:
            continue

        if isinstance(
            value,
            bool
        ):

            value = (
                "true"
                if value
                else "false"
            )

        if isinstance(
            value,
            list
        ):

            value = ",".join(
                str(x)
                for x in value
                if x is not None
            )

        value = str(
            value
        )

        if not value:
            continue

        clean[key] = value

    return urlencode(
        clean,
        doseq=False
    )


def build_uri_fragment(name):

    if not name:
        name = "Proxy"

    return quote(
        str(name).strip(),
        safe=""
    )


# ============================================================
# VLESS
# ============================================================

def json_vless_to_uri(outbound):

    try:

        settings = outbound.get(
            "settings",
            {}
        )

        stream = get_stream_settings(
            outbound
        )

        vnext = settings.get(
            "vnext",
            []
        )

        if not (
            isinstance(vnext, list)
            and vnext
        ):
            return None

        server = vnext[0]

        if not isinstance(
            server,
            dict
        ):
            return None

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

        if not address or not port:
            return None

        if not (
            isinstance(users, list)
            and users
        ):
            return None

        user = users[0]

        if not isinstance(
            user,
            dict
        ):
            return None

        uuid = user.get(
            "id"
        )

        if not uuid:
            return None

        # ----------------------------------------------------
        # Basic
        # ----------------------------------------------------

        params = {
            "encryption": (
                user.get("encryption")
                or "none"
            ),
            "flow": user.get(
                "flow"
            ),
        }

        # ----------------------------------------------------
        # Network
        # ----------------------------------------------------

        network = (
            stream.get("network")
            or "tcp"
        )

        # Xray can use raw for TCP.
        # Standard VLESS URI uses tcp.
        if network == "raw":
            network = "tcp"

        params["type"] = network

        # ----------------------------------------------------
        # TCP
        # ----------------------------------------------------

        if network == "tcp":

            tcp = stream.get(
                "tcpSettings",
                {}
            )

            if isinstance(
                tcp,
                dict
            ):

                header = tcp.get(
                    "header",
                    {}
                )

                if isinstance(
                    header,
                    dict
                ):

                    header_type = header.get(
                        "type"
                    )

                    if (
                        header_type
                        and header_type != "none"
                    ):
                        params[
                            "headerType"
                        ] = header_type

                    request = header.get(
                        "request",
                        {}
                    )

                    if isinstance(
                        request,
                        dict
                    ):

                        headers = request.get(
                            "headers",
                            {}
                        )

                        if isinstance(
                            headers,
                            dict
                        ):

                            host = (
                                headers.get(
                                    "Host"
                                )
                                or headers.get(
                                    "host"
                                )
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
                                params[
                                    "host"
                                ] = host

        # ----------------------------------------------------
        # WebSocket
        # ----------------------------------------------------

        elif network == "ws":

            ws = stream.get(
                "wsSettings",
                {}
            )

            if isinstance(
                ws,
                dict
            ):

                path = ws.get(
                    "path"
                )

                if path:
                    params[
                        "path"
                    ] = path

                headers = ws.get(
                    "headers",
                    {}
                )

                if isinstance(
                    headers,
                    dict
                ):

                    host = (
                        headers.get(
                            "Host"
                        )
                        or headers.get(
                            "host"
                        )
                    )

                    if host:
                        params[
                            "host"
                        ] = host

        # ----------------------------------------------------
        # gRPC
        # ----------------------------------------------------

        elif network == "grpc":

            grpc = stream.get(
                "grpcSettings",
                {}
            )

            if isinstance(
                grpc,
                dict
            ):

                service_name = (
                    grpc.get(
                        "serviceName"
                    )
                    or grpc.get(
                        "service_name"
                    )
                )

                if service_name:
                    params[
                        "serviceName"
                    ] = service_name

                if grpc.get(
                    "multiMode"
                ) is True:

                    params[
                        "mode"
                    ] = "multi"

        # ----------------------------------------------------
        # XHTTP / SplitHTTP
        # ----------------------------------------------------

        elif network in (
            "xhttp",
            "splithttp",
        ):

            xhttp = stream.get(
                "xhttpSettings"
            )

            if not isinstance(
                xhttp,
                dict
            ):

                xhttp = stream.get(
                    "splitHttpSettings",
                    {}
                )

            if isinstance(
                xhttp,
                dict
            ):

                path = xhttp.get(
                    "path"
                )

                if path:
                    params[
                        "path"
                    ] = path

                host = xhttp.get(
                    "host"
                )

                if host:
                    params[
                        "host"
                    ] = host

                mode = xhttp.get(
                    "mode"
                )

                if mode:
                    params[
                        "mode"
                    ] = mode

        # ----------------------------------------------------
        # HTTP / H2
        # ----------------------------------------------------

        elif network in (
            "http",
            "h2",
        ):

            http = (
                stream.get(
                    "httpSettings"
                )
                or stream.get(
                    "http2Settings"
                )
                or {}
            )

            if isinstance(
                http,
                dict
            ):

                path = http.get(
                    "path"
                )

                if path:
                    params[
                        "path"
                    ] = path

                host = http.get(
                    "host"
                )

                if isinstance(
                    host,
                    list
                ):
                    host = ",".join(
                        str(x)
                        for x in host
                    )

                if host:
                    params[
                        "host"
                    ] = host

        # ----------------------------------------------------
        # HTTP Upgrade
        # ----------------------------------------------------

        elif network == "httpupgrade":

            settings_upgrade = stream.get(
                "httpupgradeSettings",
                {}
            )

            if isinstance(
                settings_upgrade,
                dict
            ):

                path = settings_upgrade.get(
                    "path"
                )

                if path:
                    params[
                        "path"
                    ] = path

                host = settings_upgrade.get(
                    "host"
                )

                if host:
                    params[
                        "host"
                    ] = host

        # ----------------------------------------------------
        # Security
        # ----------------------------------------------------

        security = (
            stream.get(
                "security"
            )
            or "none"
        )

        params[
            "security"
        ] = security

        # ----------------------------------------------------
        # TLS
        # ----------------------------------------------------

        if security == "tls":

            tls = stream.get(
                "tlsSettings",
                {}
            )

            if isinstance(
                tls,
                dict
            ):

                server_name = tls.get(
                    "serverName"
                )

                if server_name:
                    params[
                        "sni"
                    ] = server_name

                fingerprint = tls.get(
                    "fingerprint"
                )

                if fingerprint:
                    params[
                        "fp"
                    ] = fingerprint

                alpn = tls.get(
                    "alpn"
                )

                if isinstance(
                    alpn,
                    list
                ):
                    alpn = ",".join(
                        str(x)
                        for x in alpn
                    )

                if alpn:
                    params[
                        "alpn"
                    ] = alpn

                if tls.get(
                    "allowInsecure"
                ) is True:

                    params[
                        "allowInsecure"
                    ] = "1"

        # ----------------------------------------------------
        # REALITY
        # ----------------------------------------------------

        elif security == "reality":

            reality = stream.get(
                "realitySettings",
                {}
            )

            if isinstance(
                reality,
                dict
            ):

                server_name = reality.get(
                    "serverName"
                )

                if server_name:
                    params[
                        "sni"
                    ] = server_name

                fingerprint = reality.get(
                    "fingerprint"
                )

                if fingerprint:
                    params[
                        "fp"
                    ] = fingerprint

                public_key = reality.get(
                    "publicKey"
                )

                if public_key:
                    params[
                        "pbk"
                    ] = public_key

                short_id = reality.get(
                    "shortId"
                )

                if short_id:
                    params[
                        "sid"
                    ] = short_id

                spider_x = reality.get(
                    "spiderX"
                )

                if spider_x:
                    params[
                        "spx"
                    ] = spider_x

        # ----------------------------------------------------
        # Fragment / finalmask
        #
        # Сохраняем только если JSON имеет
        # стандартный fragment-параметр.
        # ----------------------------------------------------

        fragment = stream.get(
            "fragment"
        )

        if isinstance(
            fragment,
            dict
        ):

            if fragment.get(
                "packets"
            ):
                params[
                    "fragment"
                ] = "true"

        # ----------------------------------------------------
        # NAME
        # ----------------------------------------------------

        name = get_outbound_name(
            outbound
        )

        query = build_uri_query(
            params
        )

        uri = (
            "vless://"
            + quote(
                str(uuid),
                safe=""
            )
            + "@"
            + str(address)
            + ":"
            + str(port)
            + "?"
            + query
            + "#"
            + build_uri_fragment(
                name
            )
        )

        return uri

    except Exception as e:

        print(
            "[WARN] VLESS conversion failed: "
            f"{e}"
        )

        return None


# ============================================================
# VMESS
# ============================================================

def json_vmess_to_uri(outbound):

    try:

        settings = outbound.get(
            "settings",
            {}
        )

        stream = get_stream_settings(
            outbound
        )

        vnext = settings.get(
            "vnext",
            []
        )

        if not (
            isinstance(vnext, list)
            and vnext
        ):
            return None

        server = vnext[0]

        if not isinstance(
            server,
            dict
        ):
            return None

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

        if not address or not port:
            return None

        if not (
            isinstance(users, list)
            and users
        ):
            return None

        user = users[0]

        if not isinstance(
            user,
            dict
        ):
            return None

        vmess_obj = {
            "v": "2",
            "ps": get_outbound_name(
                outbound
            ),
            "add": address,
            "port": str(port),
            "id": user.get(
                "id",
                ""
            ),
            "aid": str(
                user.get(
                    "alterId",
                    0
                )
            ),
            "scy": user.get(
                "security",
                "auto"
            ),
            "net": stream.get(
                "network",
                "tcp"
            ),
            "type": "none",
            "host": "",
            "path": "",
            "tls": "",
            "sni": "",
        }

        network = stream.get(
            "network",
            "tcp"
        )

        if network == "raw":
            network = "tcp"

        vmess_obj[
            "net"
        ] = network

        # ----------------------------------------------------
        # TCP
        # ----------------------------------------------------

        if network == "tcp":

            tcp = stream.get(
                "tcpSettings",
                {}
            )

            if isinstance(
                tcp,
                dict
            ):

                header = tcp.get(
                    "header",
                    {}
                )

                if isinstance(
                    header,
                    dict
                ):

                    request = header.get(
                        "request",
                        {}
                    )

                    if isinstance(
                        request,
                        dict
                    ):

                        headers = request.get(
                            "headers",
                            {}
                        )

                        if isinstance(
                            headers,
                            dict
                        ):

                            host = (
                                headers.get(
                                    "Host"
                                )
                                or headers.get(
                                    "host"
                                )
                            )

                            if isinstance(
                                host,
                                list
                            ):
                                host = (
                                    host[0]
                                    if host
                                    else ""
                                )

                            vmess_obj[
                                "host"
                            ] = host or ""

        # ----------------------------------------------------
        # WS
        # ----------------------------------------------------

        elif network == "ws":

            ws = stream.get(
                "wsSettings",
                {}
            )

            if isinstance(
                ws,
                dict
            ):

                vmess_obj[
                    "path"
                ] = ws.get(
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

                    vmess_obj[
                        "host"
                    ] = (
                        headers.get(
                            "Host"
                        )
                        or headers.get(
                            "host"
                        )
                        or ""
                    )

        # ----------------------------------------------------
        # gRPC
        # ----------------------------------------------------

        elif network == "grpc":

            grpc = stream.get(
                "grpcSettings",
                {}
            )

            if isinstance(
                grpc,
                dict
            ):

                vmess_obj[
                    "path"
                ] = (
                    grpc.get(
                        "serviceName"
                    )
                    or grpc.get(
                        "service_name"
                    )
                    or ""
                )

        # ----------------------------------------------------
        # XHTTP
        # ----------------------------------------------------

        elif network in (
            "xhttp",
            "splithttp",
        ):

            xhttp = (
                stream.get(
                    "xhttpSettings"
                )
                or stream.get(
                    "splitHttpSettings"
                )
                or {}
            )

            if isinstance(
                xhttp,
                dict
            ):

                vmess_obj[
                    "path"
                ] = xhttp.get(
                    "path",
                    ""
                )

                vmess_obj[
                    "host"
                ] = xhttp.get(
                    "host",
                    ""
                )

                if xhttp.get(
                    "mode"
                ):
                    vmess_obj[
                        "mode"
                    ] = xhttp.get(
                        "mode"
                    )

        # ----------------------------------------------------
        # TLS
        # ----------------------------------------------------

        security = stream.get(
            "security",
            ""
        )

        if security == "tls":

            tls = stream.get(
                "tlsSettings",
                {}
            )

            if isinstance(
                tls,
                dict
            ):

                vmess_obj[
                    "tls"
                ] = "tls"

                vmess_obj[
                    "sni"
                ] = tls.get(
                    "serverName",
                    ""
                )

                alpn = tls.get(
                    "alpn"
                )

                if alpn:
                    vmess_obj[
                        "alpn"
                    ] = alpn

        raw = json.dumps(
            vmess_obj,
            ensure_ascii=False,
            separators=(
                ",",
                ":"
            )
        ).encode(
            "utf-8"
        )

        encoded = base64.b64encode(
            raw
        ).decode()

        return (
            "vmess://"
            + encoded
        )

    except Exception as e:

        print(
            "[WARN] VMess conversion failed: "
            f"{e}"
        )

        return None


# ============================================================
# TROJAN
# ============================================================

def json_trojan_to_uri(outbound):

    try:

        settings = outbound.get(
            "settings",
            {}
        )

        stream = get_stream_settings(
            outbound
        )

        servers = settings.get(
            "servers",
            []
        )

        if not (
            isinstance(servers, list)
            and servers
        ):
            return None

        server = servers[0]

        if not isinstance(
            server,
            dict
        ):
            return None

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
            or password is None
        ):
            return None

        params = {}

        network = stream.get(
            "network"
        )

        if network:
            params[
                "type"
            ] = network

        # WS
        if network == "ws":

            ws = stream.get(
                "wsSettings",
                {}
            )

            if isinstance(
                ws,
                dict
            ):

                path = ws.get(
                    "path"
                )

                if path:
                    params[
                        "path"
                    ] = path

                headers = ws.get(
                    "headers",
                    {}
                )

                if isinstance(
                    headers,
                    dict
                ):

                    host = (
                        headers.get(
                            "Host"
                        )
                        or headers.get(
                            "host"
                        )
                    )

                    if host:
                        params[
                            "host"
                        ] = host

        # gRPC
        elif network == "grpc":

            grpc = stream.get(
                "grpcSettings",
                {}
            )

            if isinstance(
                grpc,
                dict
            ):

                service_name = (
                    grpc.get(
                        "serviceName"
                    )
                    or grpc.get(
                        "service_name"
                    )
                )

                if service_name:
                    params[
                        "serviceName"
                    ] = service_name

                if grpc.get(
                    "multiMode"
                ) is True:

                    params[
                        "mode"
                    ] = "multi"

        # XHTTP
        elif network in (
            "xhttp",
            "splithttp",
        ):

            xhttp = (
                stream.get(
                    "xhttpSettings"
                )
                or stream.get(
                    "splitHttpSettings"
                )
                or {}
            )

            if isinstance(
                xhttp,
                dict
            ):

                path = xhttp.get(
                    "path"
                )

                if path:
                    params[
                        "path"
                    ] = path

                host = xhttp.get(
                    "host"
                )

                if host:
                    params[
                        "host"
                    ] = host

                mode = xhttp.get(
                    "mode"
                )

                if mode:
                    params[
                        "mode"
                    ] = mode

        # TLS
        security = stream.get(
            "security"
        )

        if security == "tls":

            params[
                "security"
            ] = "tls"

            tls = stream.get(
                "tlsSettings",
                {}
            )

            if isinstance(
                tls,
                dict
            ):

                sni = tls.get(
                    "serverName"
                )

                if sni:
                    params[
                        "sni"
                    ] = sni

                fp = tls.get(
                    "fingerprint"
                )

                if fp:
                    params[
                        "fp"
                    ] = fp

                alpn = tls.get(
                    "alpn"
                )

                if isinstance(
                    alpn,
                    list
                ):
                    alpn = ",".join(
                        str(x)
                        for x in alpn
                    )

                if alpn:
                    params[
                        "alpn"
                    ] = alpn

        query = build_uri_query(
            params
        )

        uri = (
            "trojan://"
            + quote(
                str(password),
                safe=""
            )
            + "@"
            + str(address)
            + ":"
            + str(port)
        )

        if query:
            uri += (
                "?"
                + query
            )

        uri += (
            "#"
            + build_uri_fragment(
                get_outbound_name(
                    outbound
                )
            )
        )

        return uri

    except Exception as e:

        print(
            "[WARN] Trojan conversion failed: "
            f"{e}"
        )

        return None


# ============================================================
# SHADOWSOCKS
# ============================================================

def json_ss_to_uri(outbound):

    try:

        settings = outbound.get(
            "settings",
            {}
        )

        servers = settings.get(
            "servers",
            []
        )

        if not (
            isinstance(servers, list)
            and servers
        ):
            return None

        server = servers[0]

        if not isinstance(
            server,
            dict
        ):
            return None

        address = server.get(
            "address"
        )

        port = server.get(
            "port"
        )

        method = server.get(
            "method"
        )

        password = server.get(
            "password"
        )

        if (
            not address
            or not port
            or not method
            or password is None
        ):
            return None

        userinfo = (
            str(method)
            + ":"
            + str(password)
        )

        encoded = (
            base64.urlsafe_b64encode(
                userinfo.encode(
                    "utf-8"
                )
            )
            .decode()
            .rstrip("=")
        )

        uri = (
            "ss://"
            + encoded
            + "@"
            + str(address)
            + ":"
            + str(port)
            + "#"
            + build_uri_fragment(
                get_outbound_name(
                    outbound
                )
            )
        )

        return uri

    except Exception as e:

        print(
            "[WARN] Shadowsocks conversion failed: "
            f"{e}"
        )

        return None


# ============================================================
# JSON → URI DISPATCHER
# ============================================================

def json_config_to_uri(config):

    if not isinstance(
        config,
        dict
    ):
        return None

    protocol = str(
        config.get(
            "protocol",
            ""
        )
    ).lower()

    if protocol == "vless":
        return json_vless_to_uri(
            config
        )

    if protocol == "vmess":
        return json_vmess_to_uri(
            config
        )

    if protocol == "trojan":
        return json_trojan_to_uri(
            config
        )

    if protocol in (
        "shadowsocks",
        "ss",
    ):
        return json_ss_to_uri(
            config
        )

    return None


# ============================================================
# CONVERT ALL OUTBOUNDS
# ============================================================

def convert_json_configs_to_uris(
    json_configs
):

    result = []

    for config in json_configs:

        if not isinstance(
            config,
            dict
        ):
            continue

        # ----------------------------------------------------
        # Полный Xray config
        # ----------------------------------------------------

        outbounds = config.get(
            "outbounds"
        )

        if isinstance(
            outbounds,
            list
        ):

            print(
                "[JSON] Найден Xray config: "
                f"{len(outbounds)} outbounds"
            )

            for outbound in outbounds:

                if not isinstance(
                    outbound,
                    dict
                ):
                    continue

                protocol = str(
                    outbound.get(
                        "protocol",
                        ""
                    )
                ).lower()

                name = get_outbound_name(
                    outbound
                )

                # Служебные
                if protocol in (
                    "",
                    "freedom",
                    "blackhole",
                    "dns",
                    "loopback",
                    "http",
                ):

                    continue

                uri = json_config_to_uri(
                    outbound
                )

                if uri:

                    result.append(
                        uri
                    )

                    print(
                        "[JSON→URI] "
                        f"{protocol} | {name}"
                    )

                else:

                    print(
                        "[SKIP] "
                        f"{protocol} | {name}"
                    )

            continue

        # ----------------------------------------------------
        # Один outbound
        # ----------------------------------------------------

        protocol = str(
            config.get(
                "protocol",
                ""
            )
        ).lower()

        if not protocol:
            continue

        name = get_outbound_name(
            config
        )

        uri = json_config_to_uri(
            config
        )

        if uri:

            result.append(
                uri
            )

            print(
                "[JSON→URI] "
                f"{protocol} | {name}"
            )

        else:

            print(
                "[SKIP] "
                f"{protocol} | {name}"
            )

    return dedupe(
        result
    )


# ============================================================
# PARSE CONTENT
# ============================================================

def parse_content(
    text: str,
    depth=0
):

    if depth > 5:
        return [], []

    text = clean_config_text(
        text
    )

    if not text:
        return [], []

    uri_configs = []
    json_configs = []

    # --------------------------------------------------------
    # 1. Direct URI
    # --------------------------------------------------------

    uri_configs.extend(
        extract_protocol_links(
            text
        )
    )

    # --------------------------------------------------------
    # 2. JSON
    # --------------------------------------------------------

    parsed_json = parse_json_configs(
        text
    )

    if parsed_json:

        json_configs.extend(
            parsed_json
        )

        # URI strings inside JSON
        for obj in parsed_json:

            strings = (
                extract_strings_recursive(
                    obj
                )
            )

            for value in strings:

                uri_configs.extend(
                    extract_protocol_links(
                        value
                    )
                )

        return (
            dedupe(uri_configs),
            json_configs
        )

    # --------------------------------------------------------
    # 3. Base64
    # --------------------------------------------------------

    if looks_like_base64(
        text
    ):

        decoded = try_base64_decode(
            text
        )

        if decoded:

            nested_uris, nested_json = (
                parse_content(
                    decoded,
                    depth + 1
                )
            )

            uri_configs.extend(
                nested_uris
            )

            json_configs.extend(
                nested_json
            )

    return (
        dedupe(uri_configs),
        json_configs
    )


# ============================================================
# DOWNLOAD SOURCE
# ============================================================

def download_source(url: str):

    print(
        f"[GET] {url}"
    )

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            stream=True
        )

        response.raise_for_status()

        content = bytearray()

        for chunk in response.iter_content(
            chunk_size=64 * 1024
        ):

            if not chunk:
                continue

            content.extend(
                chunk
            )

            if len(content) > MAX_SOURCE_SIZE:

                raise RuntimeError(
                    "Source exceeds "
                    f"{MAX_SOURCE_SIZE} bytes"
                )

        return bytes(
            content
        ).decode(
            "utf-8",
            errors="replace"
        )

    except Exception as e:

        print(
            f"[WARN] Download failed: "
            f"{e}"
        )

        return ""


# ============================================================
# DEBUG PREVIEW
# ============================================================

def debug_preview(
    url,
    content
):

    if not DEBUG_PREVIEW:
        return

    preview = clean_config_text(
        content
    )[:DEBUG_PREVIEW]

    if preview:

        print(
            "[PREVIEW]"
        )

        print(
            preview
        )

        print(
            "[/PREVIEW]"
        )


# ============================================================
# PARSE SOURCE
# ============================================================

def parse_source(
    source_url: str
):

    all_uri = []
    all_json = []

    candidates = extract_wrapper_urls(
        source_url
    )

    for url in candidates:

        content = download_source(
            url
        )

        if not content:
            continue

        debug_preview(
            url,
            content
        )

        uri_configs, json_configs = (
            parse_content(
                content
            )
        )

        print(
            "[PARSE] "
            f"URI={len(uri_configs)} "
            f"JSON={len(json_configs)}"
        )

        all_uri.extend(
            uri_configs
        )

        all_json.extend(
            json_configs
        )

    return (
        dedupe(all_uri),
        all_json
    )


# ============================================================
# GIST
# ============================================================

def update_gist(
    content: str
):

    if not GIST_TOKEN:
        raise RuntimeError(
            "GIST_TOKEN не задан"
        )

    if not GIST_ID:
        raise RuntimeError(
            "GIST_ID не задан"
        )

    if not GIST_FILENAME:
        raise RuntimeError(
            "GIST_FILENAME не задан"
        )

    api_url = (
        "https://api.github.com/gists/"
        + GIST_ID
    )

    headers = {
        "Authorization":
            f"Bearer {GIST_TOKEN}",
        "Accept":
            "application/vnd.github+json",
        "X-GitHub-Api-Version":
            "2022-11-28",
        "User-Agent":
            "happ-parser",
    }

    payload = {
        "files": {
            GIST_FILENAME: {
                "content": content
            }
        }
    }

    response = requests.patch(
        api_url,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    if not response.ok:

        raise RuntimeError(
            "Gist update failed: "
            f"{response.status_code} "
            f"{response.text[:1000]}"
        )

    print(
        "[GIST] Обновлён: "
        f"{GIST_FILENAME}"
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
    # Telegram
    # --------------------------------------------------------

    print(
        "[TELEGRAM] Получаю канал..."
    )

    page = get_channel_page()

    post_url = get_last_post_url(
        page
    )

    print(
        f"[TELEGRAM] Последний пост: "
        f"{post_url}"
    )

    post = fetch_post(
        post_url
    )

    # --------------------------------------------------------
    # Normal HTTPS sources
    # --------------------------------------------------------

    source_urls = extract_source_urls(
        post
    )

    print(
        "[TELEGRAM] HTTPS sources: "
        f"{len(source_urls)}"
    )

    # --------------------------------------------------------
    # Happ encrypted sources
    # --------------------------------------------------------

    happ_links = extract_happ_links(
        post
    )

    print(
        "[TELEGRAM] HAPP links: "
        f"{len(happ_links)}"
    )

    decrypted_sources = (
        process_happ_links(
            happ_links
        )
    )

    print(
        "[HAPP] Decrypted sources: "
        f"{len(decrypted_sources)}"
    )

    source_urls.extend(
        decrypted_sources
    )

    source_urls = dedupe(
        source_urls
    )

    print(
        "[TOTAL] Sources: "
        f"{len(source_urls)}"
    )

    # --------------------------------------------------------
    # Parse all sources
    # --------------------------------------------------------

    all_uri_configs = []
    all_json_configs = []

    for index, source_url in enumerate(
        source_urls,
        1
    ):

        print(
            ""
        )

        print(
            f"========== SOURCE {index}/"
            f"{len(source_urls)} =========="
        )

        uri_configs, json_configs = (
            parse_source(
                source_url
            )
        )

        all_uri_configs.extend(
            uri_configs
        )

        all_json_configs.extend(
            json_configs
        )

    all_uri_configs = dedupe(
        all_uri_configs
    )

    # --------------------------------------------------------
    # JSON → URI
    # --------------------------------------------------------

    print(
        ""
    )

    print(
        "========== JSON → URI =========="
    )

    converted_json_uris = (
        convert_json_configs_to_uris(
            all_json_configs
        )
    )

    # --------------------------------------------------------
    # Final merge
    # --------------------------------------------------------

    all_uri_configs.extend(
        converted_json_uris
    )

    all_uri_configs = dedupe(
        all_uri_configs
    )

    # --------------------------------------------------------
    # Safety check:
    # never publish JSON
    # --------------------------------------------------------

    final_lines = []

    for line in all_uri_configs:

        line = line.strip()

        if not line:
            continue

        # Только поддерживаемые URI
        if not line.lower().startswith(
            PROTOCOLS
        ):
            continue

        # Никогда не публикуем JSON
        if line.startswith(
            "{"
        ) or line.startswith(
            "["
        ):
            continue

        final_lines.append(
            line
        )

    final_lines = dedupe(
        final_lines
    )

    output = (
        "\n".join(
            final_lines
        )
        + "\n"
    )

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    print(
        ""
    )

    print(
        "========================================"
    )

    print(
        "[RESULT] Direct URI configs: "
        f"{len(all_uri_configs) - len(converted_json_uris)}"
    )

    print(
        "[RESULT] JSON configs converted: "
        f"{len(converted_json_uris)}"
    )

    print(
        "[RESULT] TOTAL URI configs: "
        f"{len(final_lines)}"
    )

    print(
        "========================================"
    )

    # --------------------------------------------------------
    # Preview
    # --------------------------------------------------------

    if final_lines:

        print(
            ""
        )

        print(
            "[RESULT] First configs:"
        )

        for line in final_lines[:10]:

            print(
                line
            )

    else:

        print(
            "[WARN] Итоговый список пуст"
        )

    # --------------------------------------------------------
    # Gist
    # --------------------------------------------------------

    update_gist(
        output
    )

    print(
        ""
    )

    print(
        "[DONE]"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\n[STOP]"
        )

        sys.exit(130)

    except Exception as e:

        print(
            f"[FATAL] {e}"
        )

        sys.exit(1)