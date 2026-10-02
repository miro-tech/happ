#!/usr/bin/env python3

import base64
import html
import json
import os
import platform
import re
import stat
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import (
    parse_qs,
    quote,
    unquote,
    urlencode,
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
        "1",
    ).strip().lower()
    not in (
        "0",
        "false",
        "no",
        "off",
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

    return (
        value
        .replace("#", "")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


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


def first_nonempty(*values):
    for value in values:
        value = clean_string(value)

        if value:
            return value

    return ""


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

        self.texts.append(data)

        if self.current_href is not None:
            self.current_text.append(data)

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

    channel_name = (
        TELEGRAM_CHANNEL
        .lstrip("@")
        .strip("/")
    )

    channel = re.escape(
        channel_name
    )

    patterns = [
        rf'https?://t\.me/'
        rf'{channel}/(\d+)',

        rf'href=["\']/'
        rf'{channel}/(\d+)["\']',

        rf'href=["\']https://t\.me/'
        rf'{channel}/(\d+)["\']',

        rf'data-post=["\']'
        rf'{channel}/(\d+)["\']',
    ]

    found = []

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

            found.append(
                (
                    post_id,
                    (
                        "https://t.me/"
                        f"{channel_name}/"
                        f"{post_id}"
                    ),
                )
            )

    unique = {}

    for post_id, url in found:
        unique[post_id] = url

    return [
        unique[post_id]
        for post_id in sorted(
            unique,
            reverse=True,
        )
    ]


def get_last_post_url(page):

    posts = (
        extract_telegram_post_links(
            page
        )
    )

    if posts:
        return posts[0]

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
        "[TELEGRAM] Не найден последний пост"
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
# TELEGRAM FILTER
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

        bad_hosts = {
            "t.me",
            "www.t.me",
            "telegram.me",
            "www.telegram.me",
            "telegram.org",
            "www.telegram.org",
            "web.telegram.org",
            "webk.telegram.org",
            "desktop.telegram.org",
            "core.telegram.org",
            "w3.org",
            "www.w3.org",
            "schema.org",
            "www.schema.org",
            "xmlns.com",
        }

        if host in bad_hosts:
            return True

        if host.endswith(
            ".telegram.org"
        ):
            return True

        if host.endswith(
            ".telegram.me"
        ):
            return True

        if (
            "telegram-cdn" in host
            or "cdn.telegram" in host
        ):
            return True

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

        return False

    except Exception:

        return True


def extract_https_urls_from_text(text):

    if not text:
        return []

    results = []

    pattern = re.compile(
        r'https?://[^\s<>"\'\]\[()]+',
        re.IGNORECASE,
    )

    for match in pattern.finditer(
        html.unescape(text)
    ):

        url = match.group(0)

        url = url.rstrip(
            ".,;:!?)]}>"
        )

        if not is_http_url(url):
            continue

        if is_bad_telegram_url(url):
            continue

        results.append(url)

    return dedupe(results)


# ============================================================
# TELEGRAM POST CONTENT
# ============================================================

def extract_post_visible_text(
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

    return (
        "\n".join(
            parser.texts
        ),
        parser,
    )


def extract_happ_links(text):

    if not text:
        return []

    # Не привязываемся к конкретному
    # расположению crypt5.
    #
    # Поддерживает:
    #
    # happ://crypt5/...
    # happ://crypt/...crypt5
    # happ://crypt3/...
    # и т.п.

    pattern = re.compile(
        r'happ://[^\s<>"\'`]+',
        re.IGNORECASE,
    )

    result = []

    for match in pattern.finditer(
        html.unescape(text)
    ):

        value = (
            match.group(0)
            .rstrip(
                ".,;:!?)]}>"
            )
        )

        if value.lower().startswith(
            "happ://"
        ):
            result.append(value)

    return dedupe(result)


def extract_telegram_sources(
    post_html
):

    visible_text, parser = (
        extract_post_visible_text(
            post_html
        )
    )

    sources = []

    # --------------------------------------------------------
    # HREF
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

        sources.extend(
            extract_https_urls_from_text(
                link_text
            )
        )

    # --------------------------------------------------------
    # Видимый текст сообщения
    # --------------------------------------------------------

    sources.extend(
        extract_https_urls_from_text(
            visible_text
        )
    )

    # --------------------------------------------------------
    # Иногда Telegram прячет URL
    # в HTML-атрибутах самого message-text.
    # Ищем HTTPS только внутри блоков
    # сообщения, а не во всём HTML.
    # --------------------------------------------------------

    message_blocks = re.findall(
        r'<div[^>]+class=["\'][^"\']*'
        r'tgme_widget_message_text[^"\']*'
        r'["\'][^>]*>(.*?)</div>',
        post_html,
        re.IGNORECASE | re.DOTALL,
    )

    for block in message_blocks:

        block = html.unescape(
            block
        )

        # HTML → текст
        block_text = re.sub(
            r"<[^>]+>",
            " ",
            block,
        )

        sources.extend(
            extract_https_urls_from_text(
                block_text
            )
        )

        # URL в href внутри текста сообщения
        for href in re.findall(
            r'href=["\']([^"\']+)["\']',
            block,
            re.IGNORECASE,
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
                sources.append(href)

    return dedupe(
        sources
    )


# ============================================================
# BASE64
# ============================================================

def decode_base64_text(value):

    value = clean_string(value)

    if not value:
        return None

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
    value = value.replace(
        "-",
        "+",
    ).replace(
        "_",
        "/",
    )

    padding = (
        4 - len(value) % 4
    ) % 4

    value += "=" * padding

    try:

        raw = base64.b64decode(
            value,
            validate=False,
        )

        return raw.decode(
            "utf-8",
            errors="replace",
        )

    except Exception:

        return None


def looks_like_base64(value):

    value = clean_string(
        value
    )

    if len(value) < 16:
        return False

    if not re.fullmatch(
        r"[A-Za-z0-9+/=_\-\s]+",
        value,
    ):
        return False

    decoded = (
        decode_base64_text(
            value
        )
    )

    if not decoded:
        return False

    low = decoded.lower()

    for scheme in PROTOCOLS:

        if scheme in low:
            return True

    if (
        low.startswith("{")
        or low.startswith("[")
    ):
        return True

    return False


# ============================================================
# DIRECT URI EXTRACTION
# ============================================================

def extract_protocol_links(
    text
):

    if not text:
        return []

    schemes = "|".join(
        re.escape(x)
        for x in PROTOCOLS
    )

    pattern = re.compile(
        rf'(?:{schemes})[^\s<>"\'`]+',
        re.IGNORECASE,
    )

    result = []

    for match in pattern.finditer(
        text
    ):

        value = (
            match.group(0)
            .rstrip(
                ".,;:!?)]}>"
            )
        )

        result.append(
            value
        )

    return dedupe(result)


# ============================================================
# JSON DETECTION
# ============================================================

def looks_like_xray_config(
    obj
):

    if not isinstance(
        obj,
        dict,
    ):
        return False

    if (
        isinstance(
            obj.get("inbounds"),
            list,
        )
        and isinstance(
            obj.get("outbounds"),
            list,
        )
    ):
        return True

    if isinstance(
        obj.get("outbounds"),
        list,
    ):
        return True

    if (
        obj.get("protocol")
        and (
            "settings" in obj
            or "streamSettings" in obj
        )
    ):
        return True

    return False


def extract_json_configs(
    obj
):

    result = []

    def walk(value):

        if isinstance(
            value,
            dict,
        ):

            if looks_like_xray_config(
                value
            ):
                result.append(value)

            for child in value.values():
                walk(child)

        elif isinstance(
            value,
            list,
        ):

            for child in value:
                walk(child)

    walk(obj)

    return result


def parse_json_text(
    text
):

    text = clean_string(
        text
    )

    if not text:
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
# JSON STRING RECURSION
# ============================================================

def extract_strings_from_json(
    obj
):

    result = []

    def walk(value):

        if isinstance(
            value,
            str,
        ):

            result.append(value)

        elif isinstance(
            value,
            dict,
        ):

            for child in value.values():
                walk(child)

        elif isinstance(
            value,
            list,
        ):

            for child in value:
                walk(child)

    walk(obj)

    return result


# ============================================================
# X-RAY OUTBOUNDS
# ============================================================

UTILITY_PROTOCOLS = {
    "freedom",
    "blackhole",
    "dns",
    "loopback",
    "dokodemo-door",
}


def get_outbounds(config):

    if not isinstance(
        config,
        dict,
    ):
        return []

    outbounds = (
        config.get(
            "outbounds"
        )
    )

    if isinstance(
        outbounds,
        list,
    ):
        return [
            x
            for x in outbounds
            if isinstance(
                x,
                dict,
            )
        ]

    if (
        config.get("protocol")
        and (
            config.get("settings")
            or config.get(
                "streamSettings"
            )
        )
    ):
        return [config]

    return []


def get_stream_settings(
    outbound
):

    value = (
        outbound.get(
            "streamSettings"
        )
    )

    if isinstance(
        value,
        dict,
    ):
        return value

    return {}


def get_primary_outbound(
    config
):

    for outbound in get_outbounds(
        config
    ):

        protocol = clean_string(
            outbound.get(
                "protocol"
            )
        ).lower()

        if protocol in UTILITY_PROTOCOLS:
            continue

        if (
            protocol
            and outbound.get(
                "settings"
            ) is not None
        ):
            return outbound

    return None


# ============================================================
# SERVER EXTRACTION
# ============================================================

def get_vless_servers(
    outbound
):

    settings = outbound.get(
        "settings"
    ) or {}

    vnext = settings.get(
        "vnext"
    )

    if not isinstance(
        vnext,
        list,
    ):
        return []

    return [
        item
        for item in vnext
        if isinstance(
            item,
            dict,
        )
    ]


def get_trojan_servers(
    outbound
):

    settings = outbound.get(
        "settings"
    ) or {}

    servers = settings.get(
        "servers"
    )

    if not isinstance(
        servers,
        list,
    ):
        return []

    return [
        item
        for item in servers
        if isinstance(
            item,
            dict,
        )
    ]


def get_ss_servers(
    outbound
):

    settings = outbound.get(
        "settings"
    ) or {}

    servers = settings.get(
        "servers"
    )

    if not isinstance(
        servers,
        list,
    ):
        return []

    return [
        item
        for item in servers
        if isinstance(
            item,
            dict,
        )
    ]


def get_outbound_name(
    outbound,
    config,
    index=0,
    total=1,
):

    tag = safe_name(
        outbound.get(
            "tag"
        )
    )

    remarks = safe_name(
        config.get(
            "remarks"
        )
        if isinstance(
            config,
            dict,
        )
        else ""
    )

    if tag:
        if total > 1:
            return (
                f"{tag}-{index + 1}"
            )

        return tag

    return remarks


# ============================================================
# VLESS
# ============================================================

def json_vless_to_uris(
    outbound,
    config,
):

    stream = get_stream_settings(
        outbound
    )

    network = clean_string(
        stream.get(
            "network",
            "tcp",
        )
    ).lower()

    if network == "raw":
        network = "tcp"

    security = clean_string(
        stream.get(
            "security",
            "none",
        )
    ).lower()

    tls = (
        stream.get(
            "tlsSettings"
        )
        or {}
    )

    reality = (
        stream.get(
            "realitySettings"
        )
        or {}
    )

    vnext = get_vless_servers(
        outbound
    )

    if not vnext:
        return []

    total_servers = len(
        vnext
    )

    result = []

    for server_index, server in enumerate(
        vnext
    ):

        address = clean_string(
            server.get(
                "address"
            )
        )

        port = server.get(
            "port"
        )

        users = server.get(
            "users"
        ) or []

        if not address or not port:
            continue

        if not users:
            continue

        for user_index, user in enumerate(
            users
        ):

            if not isinstance(
                user,
                dict,
            ):
                continue

            uuid = clean_string(
                user.get(
                    "id"
                )
            )

            if not uuid:
                continue

            params = {}

            params["encryption"] = (
                clean_string(
                    user.get(
                        "encryption"
                    )
                )
                or "none"
            )

            flow = clean_string(
                user.get(
                    "flow"
                )
            )

            if flow:
                params["flow"] = flow

            params["type"] = (
                network
            )

            params["security"] = (
                security
                or "none"
            )

            # ------------------------------------------------
            # xHTTP
            # ------------------------------------------------

            if network == "xhttp":

                xhttp = (
                    stream.get(
                        "xhttpSettings"
                    )
                    or {}
                )

                path = clean_string(
                    xhttp.get(
                        "path"
                    )
                )

                host = clean_string(
                    xhttp.get(
                        "host"
                    )
                )

                mode = clean_string(
                    xhttp.get(
                        "mode"
                    )
                )

                if path:
                    params["path"] = path

                if host:
                    params["host"] = host

                if mode:
                    params["mode"] = mode

            # ------------------------------------------------
            # WebSocket
            # ------------------------------------------------

            elif network == "ws":

                ws = (
                    stream.get(
                        "wsSettings"
                    )
                    or {}
                )

                path = clean_string(
                    ws.get(
                        "path"
                    )
                )

                headers = (
                    ws.get(
                        "headers"
                    )
                    or {}
                )

                host = clean_string(
                    headers.get(
                        "Host"
                    )
                    or headers.get(
                        "host"
                    )
                )

                if path:
                    params["path"] = path

                if host:
                    params["host"] = host

            # ------------------------------------------------
            # gRPC
            # ------------------------------------------------

            elif network == "grpc":

                grpc = (
                    stream.get(
                        "grpcSettings"
                    )
                    or {}
                )

                service_name = clean_string(
                    grpc.get(
                        "serviceName"
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

            # ------------------------------------------------
            # TCP / RAW
            # ------------------------------------------------

            elif network == "tcp":

                tcp = (
                    stream.get(
                        "tcpSettings"
                    )
                    or {}
                )

                header = (
                    tcp.get(
                        "header"
                    )
                    or {}
                )

                if (
                    clean_string(
                        header.get(
                            "type"
                        )
                    ).lower()
                    == "http"
                ):

                    request = (
                        header.get(
                            "request"
                        )
                        or {}
                    )

                    path = request.get(
                        "path"
                    )

                    host = request.get(
                        "headers",
                        {},
                    ).get(
                        "Host"
                    )

                    path = first_value(
                        path
                    )

                    host = first_value(
                        host
                    )

                    if path:
                        params[
                            "path"
                        ] = path

                    if host:
                        params[
                            "host"
                        ] = host

            # ------------------------------------------------
            # HTTP
            # ------------------------------------------------

            elif network in (
                "http",
                "h2",
            ):

                http_settings = (
                    stream.get(
                        "httpSettings"
                    )
                    or {}
                )

                path = clean_string(
                    http_settings.get(
                        "path"
                    )
                )

                host = http_settings.get(
                    "host"
                )

                host = first_value(
                    host
                )

                if path:
                    params[
                        "path"
                    ] = path

                if host:
                    params[
                        "host"
                    ] = host

            # ------------------------------------------------
            # TLS
            # ------------------------------------------------

            if security == "tls":

                sni = clean_string(
                    tls.get(
                        "serverName"
                    )
                )

                fingerprint = clean_string(
                    tls.get(
                        "fingerprint"
                    )
                )

                alpn = tls.get(
                    "alpn"
                )

                if sni:
                    params["sni"] = sni

                if fingerprint:
                    params["fp"] = fingerprint

                if isinstance(
                    alpn,
                    list,
                ):
                    alpn = ",".join(
                        clean_string(x)
                        for x in alpn
                        if clean_string(x)
                    )

                else:
                    alpn = clean_string(
                        alpn
                    )

                if alpn:
                    params["alpn"] = alpn

                if tls.get(
                    "allowInsecure"
                ) is True:
                    params[
                        "allowInsecure"
                    ] = "1"

            # ------------------------------------------------
            # REALITY
            # ------------------------------------------------

            if security == "reality":

                sni = clean_string(
                    reality.get(
                        "serverName"
                    )
                )

                fingerprint = clean_string(
                    reality.get(
                        "fingerprint"
                    )
                )

                public_key = clean_string(
                    reality.get(
                        "publicKey"
                    )
                )

                short_id = clean_string(
                    reality.get(
                        "shortId"
                    )
                )

                spider_x = clean_string(
                    reality.get(
                        "spiderX"
                    )
                )

                if sni:
                    params["sni"] = sni

                if fingerprint:
                    params["fp"] = fingerprint

                if public_key:
                    params["pbk"] = public_key

                if short_id:
                    params["sid"] = short_id

                if spider_x:
                    params["spx"] = spider_x

            query = urlencode(
                params,
                doseq=True,
            )

            uri = (
                "vless://"
                + quote(
                    uuid,
                    safe="",
                )
                + "@"
                + address
                + ":"
                + str(port)
            )

            if query:
                uri += "?" + query

            name = get_outbound_name(
                outbound,
                config,
                server_index,
                total_servers,
            )

            if len(users) > 1:
                if name:
                    name += (
                        f"-{user_index + 1}"
                    )

            uri = build_uri_with_name(
                uri,
                name,
            )

            result.append(uri)

    return result


# ============================================================
# VMESS
# ============================================================

def json_vmess_to_uris(
    outbound,
    config,
):

    settings = (
        outbound.get(
            "settings"
        )
        or {}
    )

    vnext = settings.get(
        "vnext"
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
    )

    security = clean_string(
        stream.get(
            "security"
        )
    ).lower()

    tls = (
        stream.get(
            "tlsSettings"
        )
        or {}
    )

    result = []

    for index, server in enumerate(
        vnext
    ):

        address = clean_string(
            server.get(
                "address"
            )
        )

        port = server.get(
            "port"
        )

        users = (
            server.get(
                "users"
            )
            or []
        )

        if not users:
            continue

        user = users[0]

        vm = {
            "v": "2",
            "ps": get_outbound_name(
                outbound,
                config,
                index,
                len(vnext),
            ),
            "add": address,
            "port": str(port),
            "id": clean_string(
                user.get("id")
            ),
            "aid": str(
                user.get(
                    "alterId",
                    0,
                )
            ),
            "scy": clean_string(
                user.get(
                    "security",
                    "auto",
                )
            ) or "auto",
            "net": network,
            "type": "none",
            "host": "",
            "path": "",
            "tls": "",
            "sni": "",
        }

        # WS
        if network == "ws":

            ws = (
                stream.get(
                    "wsSettings"
                )
                or {}
            )

            vm["path"] = clean_string(
                ws.get(
                    "path"
                )
            )

            vm["host"] = clean_string(
                (
                    ws.get(
                        "headers"
                    )
                    or {}
                ).get(
                    "Host"
                )
            )

        # gRPC
        elif network == "grpc":

            grpc = (
                stream.get(
                    "grpcSettings"
                )
                or {}
            )

            vm["path"] = clean_string(
                grpc.get(
                    "serviceName"
                )
            )

            vm["type"] = "none"

        # xHTTP
        elif network == "xhttp":

            xhttp = (
                stream.get(
                    "xhttpSettings"
                )
                or {}
            )

            vm["path"] = clean_string(
                xhttp.get(
                    "path"
                )
            )

            vm["host"] = clean_string(
                xhttp.get(
                    "host"
                )
            )

            if xhttp.get(
                "mode"
            ):
                vm["mode"] = clean_string(
                    xhttp.get(
                        "mode"
                    )
                )

        # TCP
        elif network in (
            "tcp",
            "raw",
        ):

            tcp = (
                stream.get(
                    "tcpSettings"
                )
                or {}
            )

            header = (
                tcp.get(
                    "header"
                )
                or {}
            )

            request = (
                header.get(
                    "request"
                )
                or {}
            )

            vm["type"] = clean_string(
                header.get(
                    "type",
                    "none",
                )
            ) or "none"

            vm["path"] = first_value(
                request.get(
                    "path"
                )
            )

            vm["host"] = first_value(
                (
                    request.get(
                        "headers"
                    )
                    or {}
                ).get(
                    "Host"
                )
            )

        if security == "tls":

            vm["tls"] = "tls"

            vm["sni"] = clean_string(
                tls.get(
                    "serverName"
                )
            )

        encoded = base64.b64encode(
            json.dumps(
                vm,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).decode()

        result.append(
            "vmess://"
            + encoded
        )

    return result


# ============================================================
# TROJAN
# ============================================================

def json_trojan_to_uris(
    outbound,
    config,
):

    servers = get_trojan_servers(
        outbound
    )

    if not servers:
        return []

    stream = get_stream_settings(
        outbound
    )

    security = clean_string(
        stream.get(
            "security",
            "tls",
        )
    )

    tls = (
        stream.get(
            "tlsSettings"
        )
        or {}
    )

    result = []

    for index, server in enumerate(
        servers
    ):

        address = clean_string(
            server.get(
                "address"
            )
        )

        port = server.get(
            "port"
        )

        password = clean_string(
            server.get(
                "password"
            )
        )

        if not address or not port:
            continue

        params = {
            "security": security
        }

        if security == "tls":

            sni = clean_string(
                tls.get(
                    "serverName"
                )
            )

            fp = clean_string(
                tls.get(
                    "fingerprint"
                )
            )

            if sni:
                params["sni"] = sni

            if fp:
                params["fp"] = fp

        network = clean_string(
            stream.get(
                "network"
            )
        )

        if network:
            params["type"] = (
                network
            )

        if network == "ws":

            ws = (
                stream.get(
                    "wsSettings"
                )
                or {}
            )

            path = clean_string(
                ws.get(
                    "path"
                )
            )

            host = clean_string(
                (
                    ws.get(
                        "headers"
                    )
                    or {}
                ).get(
                    "Host"
                )
            )

            if path:
                params["path"] = path

            if host:
                params["host"] = host

        elif network == "grpc":

            grpc = (
                stream.get(
                    "grpcSettings"
                )
                or {}
            )

            service = clean_string(
                grpc.get(
                    "serviceName"
                )
            )

            if service:
                params[
                    "serviceName"
                ] = service

        query = urlencode(
            params
        )

        uri = (
            "trojan://"
            + quote(
                password,
                safe="",
            )
            + "@"
            + address
            + ":"
            + str(port)
        )

        if query:
            uri += "?" + query

        uri = build_uri_with_name(
            uri,
            get_outbound_name(
                outbound,
                config,
                index,
                len(servers),
            ),
        )

        result.append(uri)

    return result


# ============================================================
# SHADOWSOCKS
# ============================================================

def json_ss_to_uris(
    outbound,
    config,
):

    servers = get_ss_servers(
        outbound
    )

    if not servers:
        return []

    result = []

    for index, server in enumerate(
        servers
    ):

        address = clean_string(
            server.get(
                "address"
            )
        )

        port = server.get(
            "port"
        )

        method = clean_string(
            server.get(
                "method"
            )
        )

        password = clean_string(
            server.get(
                "password"
            )
        )

        if (
            not address
            or not port
            or not method
        ):
            continue

        userinfo = (
            f"{method}:{password}"
        )

        encoded = base64.b64encode(
            userinfo.encode()
        ).decode().rstrip("=")

        uri = (
            "ss://"
            + encoded
            + "@"
            + address
            + ":"
            + str(port)
        )

        uri = build_uri_with_name(
            uri,
            get_outbound_name(
                outbound,
                config,
                index,
                len(servers),
            ),
        )

        result.append(uri)

    return result


# ============================================================
# JSON CONFIG → URI
# ============================================================

def json_config_to_uris(
    config
):

    if not isinstance(
        config,
        dict,
    ):
        return []

    result = []

    outbounds = get_outbounds(
        config
    )

    for outbound in outbounds:

        protocol = clean_string(
            outbound.get(
                "protocol"
            )
        ).lower()

        if not protocol:
            continue

        if protocol in UTILITY_PROTOCOLS:
            continue

        try:

            if protocol == "vless":

                result.extend(
                    json_vless_to_uris(
                        outbound,
                        config,
                    )
                )

            elif protocol == "vmess":

                result.extend(
                    json_vmess_to_uris(
                        outbound,
                        config,
                    )
                )

            elif protocol == "trojan":

                result.extend(
                    json_trojan_to_uris(
                        outbound,
                        config,
                    )
                )

            elif protocol in (
                "shadowsocks",
                "ss",
            ):

                result.extend(
                    json_ss_to_uris(
                        outbound,
                        config,
                    )
                )

        except Exception as e:

            print(
                "[JSON] Ошибка конвертации "
                f"{protocol}: {e}"
            )

    return dedupe(
        result
    )


def convert_json_configs_to_uris(
    configs
):

    result = []

    for config in configs:

        result.extend(
            json_config_to_uris(
                config
            )
        )

    return dedupe(
        result
    )


# ============================================================
# PARSE CONTENT
# ============================================================

def parse_content(
    content,
    depth=0,
):

    if depth > 6:
        return [], []

    if not content:
        return [], []

    if isinstance(
        content,
        bytes,
    ):

        content = content.decode(
            "utf-8",
            errors="replace",
        )

    content = clean_string(
        content
    )

    uri_configs = []
    json_configs = []

    # --------------------------------------------------------
    # Direct URI
    # --------------------------------------------------------

    uri_configs.extend(
        extract_protocol_links(
            content
        )
    )

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    if (
        content.startswith("{")
        or content.startswith("[")
    ):

        try:

            obj = json.loads(
                content
            )

            configs = (
                extract_json_configs(
                    obj
                )
            )

            json_configs.extend(
                configs
            )

            # URI strings внутри JSON
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

                if looks_like_base64(
                    value
                ):

                    decoded = (
                        decode_base64_text(
                            value
                        )
                    )

                    if decoded:

                        u, j = (
                            parse_content(
                                decoded,
                                depth + 1,
                            )
                        )

                        uri_configs.extend(u)
                        json_configs.extend(j)

        except Exception:
            pass

    # --------------------------------------------------------
    # Base64
    # --------------------------------------------------------

    if looks_like_base64(
        content
    ):

        decoded = (
            decode_base64_text(
                content
            )
        )

        if decoded:

            u, j = (
                parse_content(
                    decoded,
                    depth + 1,
                )
            )

            uri_configs.extend(u)
            json_configs.extend(j)

    return (
        dedupe(uri_configs),
        json_configs,
    )


# ============================================================
# DOWNLOAD SOURCE
# ============================================================

def download_source(
    url
):

    print(
        f"[DOWNLOAD] {url}"
    )

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )

        print(
            "[DOWNLOAD] HTTP "
            f"{response.status_code}"
        )

        if not response.ok:
            return ""

        content_length = response.headers.get(
            "Content-Length"
        )

        if content_length:

            try:

                if int(
                    content_length
                ) > MAX_SOURCE_SIZE:

                    print(
                        "[DOWNLOAD] Слишком "
                        "большой источник"
                    )

                    return ""

            except Exception:
                pass

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
                    "[DOWNLOAD] Превышен "
                    "MAX_SOURCE_SIZE"
                )

                return ""

            chunks.append(chunk)

        data = b"".join(
            chunks
        )

        return data.decode(
            response.encoding
            or "utf-8",
            errors="replace",
        )

    except Exception as e:

        print(
            f"[DOWNLOAD] Error: {e}"
        )

        return ""


# ============================================================
# DEBUG PREVIEW
# ============================================================

def debug_preview(
    content
):

    if not content:
        return

    preview = (
        content[:DEBUG_PREVIEW]
        .replace("\r", " ")
        .replace("\n", " ")
    )

    print(
        "[DEBUG] Preview:"
    )

    print(preview)


# ============================================================
# WRAPPER URL EXTRACTION
# ============================================================

def extract_wrapper_urls(
    url
):

    result = []

    try:

        parsed = urlsplit(
            url
        )

        query = parse_qs(
            parsed.query
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

                if is_http_url(
                    value
                ):
                    result.append(
                        value
                    )

    except Exception:
        pass

    return dedupe(
        result
    )


# ============================================================
# PARSE SOURCE
# ============================================================

def parse_source(
    source,
    visited=None,
):

    if visited is None:
        visited = set()

    source = normalize_url(
        source
    )

    if not source:
        return [], []

    if source in visited:
        return [], []

    visited.add(source)

    all_uris = []
    all_json = []

    # --------------------------------------------------------
    # Wrapper URL
    # --------------------------------------------------------

    wrapper_urls = (
        extract_wrapper_urls(
            source
        )
    )

    for wrapper in wrapper_urls:

        u, j = parse_source(
            wrapper,
            visited,
        )

        all_uris.extend(u)
        all_json.extend(j)

    # --------------------------------------------------------
    # Download
    # --------------------------------------------------------

    content = download_source(
        source
    )

    if not content:
        return (
            dedupe(all_uris),
            all_json,
        )

    debug_preview(
        content
    )

    u, j = parse_content(
        content
    )

    all_uris.extend(u)
    all_json.extend(j)

    # --------------------------------------------------------
    # Если внутри ответа есть HTTPS
    # --------------------------------------------------------

    for nested_url in (
        extract_https_urls_from_text(
            content
        )
    ):

        if nested_url == source:
            continue

        # Не превращаем обычные веб-страницы
        # в бесконечный crawl.
        try:

            host = (
                urlsplit(
                    nested_url
                ).hostname
                or ""
            ).lower()

        except Exception:

            continue

        if host in {
            "web.telegram.org",
            "telegram.org",
            "www.telegram.org",
            "t.me",
        }:
            continue

        # Только если URL похож на subscription.
        low = nested_url.lower()

        if any(
            x in low
            for x in (
                "sub",
                "config",
                "subscription",
                "profile",
                "clash",
                "v2ray",
                "sing",
            )
        ):

            nu, nj = parse_source(
                nested_url,
                visited,
            )

            all_uris.extend(nu)
            all_json.extend(nj)

    return (
        dedupe(all_uris),
        all_json,
    )


# ============================================================
# HPWNR
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

    if system != "linux":
        if system == "darwin":

            if "arm" in machine:
                return "darwin-arm64"

            return "darwin-amd64"

        if system == "windows":
            return "windows-amd64"

        return None

    if machine in (
        "x86_64",
        "amd64",
    ):
        return "linux-x86_64"

    if machine in (
        "aarch64",
        "arm64",
        "armv8",
    ):
        return "linux-arm64"

    if machine.startswith(
        "arm"
    ):
        return "linux-arm64"

    return "linux-x86_64"


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

        candidates.extend(
            [
                Path.cwd() / path,
                HPWNR_DIR / path.name,
                HPWNR_DIR / "hpwnr",
            ]
        )

    for item in candidates:

        if (
            item.exists()
            and item.is_file()
        ):
            return item

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


def choose_hpwnr_asset(
    assets
):

    target = (
        detect_hpwnr_asset()
    )

    if not assets:
        return None

    normalized = []

    for item in assets:

        name = clean_string(
            item.get(
                "name",
                ""
            )
        )

        if not name:
            continue

        low = name.lower()

        # Исключаем checksum/signature
        if any(
            x in low
            for x in (
                ".sha256",
                ".sha512",
                ".sig",
                ".asc",
                "checksum",
            )
        ):
            continue

        normalized.append(
            (
                name,
                item.get(
                    "browser_download_url"
                ),
                low,
            )
        )

    # --------------------------------------------------------
    # Точное совпадение по ожидаемому
    # --------------------------------------------------------

    if target:

        target_low = (
            target.lower()
        )

        for name, url, low in normalized:

            if (
                target_low in low
                or low.endswith(
                    target_low
                )
            ):
                return (
                    name,
                    url,
                )

    # --------------------------------------------------------
    # Linux x86_64
    # --------------------------------------------------------

    if target == "linux-x86_64":

        patterns = (
            (
                "linux"
                in low
                and (
                    "x86_64" in low
                    or "amd64" in low
                )
                and not any(
                    x in low
                    for x in (
                        "arm",
                        "aarch",
                    )
                )
            )
            for _, _, low in normalized
        )

        for item, matched in zip(
            normalized,
            patterns,
        ):

            if matched:

                name, url, _ = item

                return (
                    name,
                    url,
                )

    # --------------------------------------------------------
    # Linux ARM64
    # --------------------------------------------------------

    if target == "linux-arm64":

        for name, url, low in normalized:

            if (
                "linux" in low
                and (
                    "arm64" in low
                    or "aarch64" in low
                )
            ):

                return (
                    name,
                    url,
                )

    return None


def install_hpwnr():

    if not AUTO_INSTALL_HPWNR:
        return None

    print(
        "[HPWNR] Локальный hpwnr не найден"
    )

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

        assets = data.get(
            "assets",
            [],
        )

        selected = choose_hpwnr_asset(
            assets
        )

        if not selected:

            print(
                "[HPWNR] Не найден Linux "
                "x86_64 asset"
            )

            print(
                "[HPWNR] Доступные assets:"
            )

            for item in assets:

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

        asset_name, download_url = (
            selected
        )

        if not download_url:

            print(
                "[HPWNR] У asset нет "
                "download URL"
            )

            return None

        HPWNR_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination = (
            HPWNR_DIR / "hpwnr"
        )

        print(
            "[HPWNR] Asset: "
            f"{asset_name}"
        )

        print(
            "[HPWNR] Download: "
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
# HAPP DECRYPT
# ============================================================

def decrypt_happ(
    happ_url,
    hpwnr,
):

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

            if result.returncode != 0:
                continue

            protocol_urls = (
                extract_protocol_links(
                    output
                )
            )

            if protocol_urls:
                return protocol_urls

            https_urls = (
                extract_https_urls_from_text(
                    output
                )
            )

            if https_urls:
                return https_urls

        except Exception as e:

            print(
                f"[HPWNR] {e}"
            )

    return []


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
            f"{link[:120]}..."
        )

        urls = decrypt_happ(
            link,
            hpwnr,
        )

        sources.extend(
            urls
        )

    return dedupe(
        sources
    )


# ============================================================
# GIST
# ============================================================

def update_gist(
    content
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
            "GIST_FILENAME пуст"
        )

    url = (
        "https://api.github.com/gists/"
        + GIST_ID
    )

    headers = {
        "Authorization":
            f"Bearer {GIST_TOKEN}",
        "Accept":
            "application/vnd.github+json",
        "User-Agent":
            "HappVPN-Parser",
    }

    payload = {
        "files": {
            GIST_FILENAME: {
                "content": content
            }
        }
    }

    print(
        "[GIST] Обновляю "
        f"{GIST_FILENAME}"
    )

    response = requests.patch(
        url,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    print(
        f"[GIST] HTTP {response.status_code}"
    )

    if not response.ok:

        print(
            response.text[:1000]
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

    print(
        "[PARSER] Starting parser..."
    )

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

    channel_page = (
        get_channel_page()
    )

    if not channel_page:

        raise RuntimeError(
            "Не удалось получить "
            "Telegram channel"
        )

    post_url = (
        get_last_post_url(
            channel_page
        )
    )

    if not post_url:

        raise RuntimeError(
            "Не найден последний "
            "пост Telegram"
        )

    print(
        "[TELEGRAM] Последний пост: "
        f"{post_url}"
    )

    post_html = fetch_post(
        post_url
    )

    if not post_html:

        raise RuntimeError(
            "Не удалось получить "
            "Telegram post"
        )

    # --------------------------------------------------------
    # Извлекаем ВИДИМЫЙ текст
    # --------------------------------------------------------

    visible_text, _ = (
        extract_post_visible_text(
            post_html
        )
    )

    https_sources = (
        extract_telegram_sources(
            post_html
        )
    )

    happ_links = (
        extract_happ_links(
            visible_text
        )
    )

    # Если Happ ссылка была в HTML,
    # но не попала в visible text,
    # ищем её только в message blocks.
    if not happ_links:

        message_blocks = re.findall(
            r'tgme_widget_message_text'
            r'[^>]*>(.*?)</div>',
            post_html,
            re.IGNORECASE | re.DOTALL,
        )

        for block in message_blocks:

            block = re.sub(
                r"<[^>]+>",
                " ",
                html.unescape(
                    block
                ),
            )

            happ_links.extend(
                extract_happ_links(
                    block
                )
            )

        happ_links = dedupe(
            happ_links
        )

    print(
        "[TELEGRAM] HTTPS sources: "
        f"{len(https_sources)}"
    )

    for source in https_sources:
        print(
            "  "
            + source
        )

    print(
        "[TELEGRAM] Happ links: "
        f"{len(happ_links)}"
    )

    # --------------------------------------------------------
    # HPWNR
    # --------------------------------------------------------

    decrypted_sources = (
        process_happ_links(
            happ_links
        )
    )

    print(
        "[HAPP] Decrypted sources: "
        f"{len(decrypted_sources)}"
    )

    # --------------------------------------------------------
    # Sources
    # --------------------------------------------------------

    sources = dedupe(
        https_sources
        + decrypted_sources
    )

    print(
        "[SOURCES] TOTAL: "
        f"{len(sources)}"
    )

    if not sources:

        print(
            "[TELEGRAM] Visible text preview:"
        )

        print(
            visible_text[
                :DEBUG_PREVIEW
            ]
        )

    # --------------------------------------------------------
    # Parse all sources
    # --------------------------------------------------------

    direct_uris = []
    json_configs = []

    for index, source in enumerate(
        sources,
        start=1,
    ):

        print()
        print(
            f"[SOURCE {index}/{len(sources)}]"
        )

        print(source)

        uris, configs = (
            parse_source(
                source
            )
        )

        print(
            "[PARSE] URI: "
            f"{len(uris)}"
            " | JSON: "
            f"{len(configs)}"
        )

        direct_uris.extend(
            uris
        )

        json_configs.extend(
            configs
        )

    # --------------------------------------------------------
    # JSON → URI
    # --------------------------------------------------------

    print()
    print(
        "[JSON] Конвертирую JSON → URI..."
    )

    converted_uris = (
        convert_json_configs_to_uris(
            json_configs
        )
    )

    # --------------------------------------------------------
    # Final
    # --------------------------------------------------------

    direct_uris = dedupe(
        direct_uris
    )

    converted_uris = dedupe(
        converted_uris
    )

    all_uris = dedupe(
        direct_uris
        + converted_uris
    )

    print()
    print(
        "========================================"
    )

    print(
        "[RESULT] Direct URI configs: "
        f"{len(direct_uris)}"
    )

    print(
        "[RESULT] JSON configs converted: "
        f"{len(converted_uris)}"
    )

    print(
        "[RESULT] TOTAL URI configs: "
        f"{len(all_uris)}"
    )

    print(
        "========================================"
    )

    if not all_uris:

        raise RuntimeError(
            "Не найдено ни одного URI"
        )

    # --------------------------------------------------------
    # Gist content
    #
    # Только URI.
    # Никакого JSON.
    # --------------------------------------------------------

    gist_content = (
        "\n".join(
            all_uris
        )
        + "\n"
    )

    update_gist(
        gist_content
    )

    print()
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
            "\n[FATAL] Interrupted"
        )

        sys.exit(130)

    except Exception as e:

        print(
            f"[FATAL] {e}"
        )

        sys.exit(1)