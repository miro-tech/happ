#!/usr/bin/env python3

from __future__ import annotations

import base64
import html
import json
import os
import re
import sys
import time
from html.parser import HTMLParser
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

# Main output.
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

def get_channel_page():

    url = (
        f"https://t.me/s/"
        f"{TELEGRAM_CHANNEL}"
    )

    print(
        f"[TELEGRAM] Reading channel: "
        f"{url}"
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
        for x in pattern.findall(
            channel_html
        )
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
            for x in pattern.findall(
                channel_html
            )
        ]

    if not ids:

        raise RuntimeError(
            "Could not find Telegram "
            "message IDs"
        )

    last_id = max(ids)

    post_url = (
        f"https://t.me/"
        f"{TELEGRAM_CHANNEL}/"
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


def fetch_post(
    post_url: str,
):

    url = (
        post_url
        + "?embed=1"
    )

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


def extract_post_urls(
    post_html: str,
):

    parser = TelegramHTMLParser()

    parser.feed(
        post_html
    )

    urls = []

    # href
    for url in parser.links:

        url = normalize_url(
            url
        )

        if (
            is_http_url(url)
            and not is_ignored_url(url)
        ):

            urls.append(url)

    # visible text
    text = "\n".join(
        parser.text_parts
    )

    text = html.unescape(
        text
    )

    for url in re.findall(
        r"https?://[^\s\"'<>]+",
        text,
        re.I,
    ):

        url = normalize_url(
            url
        )

        if (
            is_http_url(url)
            and not is_ignored_url(url)
        ):

            urls.append(url)

    return unique_preserve_order(
        urls
    )


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
            f"[WRAPPER] "
            f"{exc}"
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

    # Typical Xray/V2Ray configuration.
    keys = set(
        obj.keys()
    )

    if (
        "inbounds" in keys
        and "outbounds" in keys
    ):
        return True

    # Some exported configs can have only
    # outbounds.
    if "outbounds" in keys:
        return True

    # sing-box style.
    if (
        "inbounds" in keys
        and "outbounds" in keys
    ):
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

        # Search nested objects.
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

    configs = (
        extract_json_configs(
            obj
        )
    )

    return configs


# ============================================================
# JSON -> TEXT PROTOCOL SEARCH
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

        if (
            extract_protocol_links(
                decoded
            )
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
    # 1. Direct URI links.
    # --------------------------------------------------------

    uri_configs.extend(
        extract_protocol_links(
            text
        )
    )

    # --------------------------------------------------------
    # 2. JSON Xray/V2Ray configs.
    # --------------------------------------------------------

    json_configs.extend(
        parse_json_configs(
            text
        )
    )

    # --------------------------------------------------------
    # 3. If JSON, inspect all strings.
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
    # 4. Base64.
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
# MAIN
# ============================================================

def main():

    print("=" * 70)

    print(
        "Telegram latest post -> "
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
    # Telegram
    # --------------------------------------------------------

    channel_html = (
        get_channel_page()
    )

    post_url = (
        get_last_post_url(
            channel_html
        )
    )

    post_html = (
        fetch_post(
            post_url
        )
    )

    # --------------------------------------------------------
    # URLs
    # --------------------------------------------------------

    source_urls = (
        extract_post_urls(
            post_html
        )
    )

    print()
    print(
        f"[TELEGRAM] External HTTPS "
        f"sources: {len(source_urls)}"
    )

    for i, url in enumerate(
        source_urls,
        1,
    ):

        print(
            f"  {i}. {url}"
        )

    if not source_urls:

        raise RuntimeError(
            "No external HTTPS sources"
        )

    # --------------------------------------------------------
    # Parse
    # --------------------------------------------------------

    all_uri_configs = []
    all_json_configs = []

    for i, source_url in enumerate(
        source_urls,
        1,
    ):

        print()
        print("=" * 70)

        print(
            f"[{i}/{len(source_urls)}] "
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
    # Deduplicate URI configs.
    # --------------------------------------------------------

    all_uri_configs = (
        unique_preserve_order(
            x.strip()
            for x in all_uri_configs
            if x.strip()
        )
    )

    # --------------------------------------------------------
    # Deduplicate JSON configs.
    #
    # JSON configs don't necessarily have stable key order,
    # so serialize with sorted keys and use that as identity.
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
    # Statistics
    # --------------------------------------------------------

    print()
    print("=" * 70)

    print(
        f"[RESULT] URI configs: "
        f"{len(all_uri_configs)}"
    )

    print(
        f"[RESULT] JSON configs: "
        f"{len(unique_json)}"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # IMPORTANT:
    # Don't overwrite Gist with empty result.
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
    #
    # If JSON configs were found, write a proper JSON array.
    #
    # Otherwise write normal subscription URLs.
    # --------------------------------------------------------

    if unique_json:

        output_filename = (
            GIST_FILENAME
        )

        output = json.dumps(
            unique_json,
            ensure_ascii=False,
            indent=2,
        ) + "\n"

        print(
            "[RESULT] Output format: "
            "Xray/V2Ray JSON"
        )

    else:

        output_filename = (
            GIST_FILENAME
        )

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
    # Gist update
    # --------------------------------------------------------

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

    print()
    print(
        f"[DONE] JSON configs: "
        f"{len(unique_json)}"
    )

    print(
        f"[DONE] URI configs: "
        f"{len(all_uri_configs)}"
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        sys.exit(130)

    except Exception as exc:

        print(
            "[FATAL] "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        sys.exit(1)
