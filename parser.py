#!/usr/bin/env python3

from __future__ import annotations

import base64
import binascii
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
    urljoin,
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

# How many characters of an unrecognized response
# should be printed to Actions log.
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

SESSION.headers.update(
    {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }
)


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
# HTML PARSER
# ============================================================

class TelegramHTMLParser(HTMLParser):
    """
    Extracts links and visible text from Telegram HTML.
    """

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.links: list[str] = []
        self.text_parts: list[str] = []

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
# BASIC HELPERS
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
    config: str,
) -> str:

    config = html.unescape(
        config
    )

    config = config.replace(
        "\\/",
        "/",
    )

    config = config.strip()

    # Remove common surrounding characters.
    config = config.strip(
        "\"'`<>()[]{} ,;\r\n\t"
    )

    return config


# ============================================================
# TELEGRAM CHANNEL
# ============================================================

def get_channel_page() -> str:

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


# ============================================================
# FIND LAST POST
# ============================================================

def get_last_post_url(
    channel_html: str,
) -> str:

    # Match:
    # https://t.me/happvpn/4237
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

    # Fallback to relative links.
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


# ============================================================
# FETCH POST
# ============================================================

def fetch_post(
    post_url: str,
) -> str:

    candidates = [
        post_url + "?embed=1",
        post_url + "?embed=1&mode=tme",
    ]

    errors = []

    for url in candidates:

        try:

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

            if (
                response.ok
                and response.text
            ):

                return response.text

            errors.append(
                f"{url}: HTTP "
                f"{response.status_code}"
            )

        except Exception as exc:

            errors.append(
                f"{url}: "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

    raise RuntimeError(
        "Could not fetch Telegram post:\n"
        + "\n".join(errors)
    )


# ============================================================
# TELEGRAM URL FILTER
# ============================================================

def is_ignored_telegram_url(
    url: str,
) -> bool:

    low = url.lower()

    # Telegram's own infrastructure.
    ignored_hosts = (
        "t.me",
        "telegram.me",
        "telegram.org",
        "oauth.tg.dev",
        "telegram-widget.com",
    )

    try:

        host = (
            urlsplit(url)
            .hostname
            or ""
        ).lower()

    except Exception:

        return True

    if host in ignored_hosts:
        return True

    # Telegram widget / JS.
    ignored_fragments = (
        "telegram-widget.js",
        "/js/telegram-widget",
        "tgwidget",
    )

    if any(
        x in low
        for x in ignored_fragments
    ):
        return True

    # Media files.
    media_extensions = (
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
    )

    path = (
        urlsplit(url)
        .path
        .lower()
    )

    if path.endswith(
        media_extensions
    ):
        return True

    # Static scripts/styles.
    if path.endswith(
        (
            ".js",
            ".css",
            ".woff",
            ".woff2",
        )
    ):
        return True

    return False


# ============================================================
# EXTRACT URLS FROM POST
# ============================================================

def extract_post_urls(
    post_html: str,
) -> list[str]:

    parser = TelegramHTMLParser()

    parser.feed(
        post_html
    )

    urls = []

    # --------------------------------------------------------
    # href URLs
    # --------------------------------------------------------

    for url in parser.links:

        url = normalize_url(
            url
        )

        if (
            is_http_url(url)
            and not is_ignored_telegram_url(
                url
            )
        ):
            urls.append(url)

    # --------------------------------------------------------
    # Plain URLs in visible HTML/text.
    # --------------------------------------------------------

    text = "\n".join(
        parser.text_parts
    )

    text = html.unescape(
        text
    )

    plain_urls = re.findall(
        r"https?://[^\s\"'<>]+",
        text,
        flags=re.I,
    )

    for url in plain_urls:

        url = normalize_url(
            url
        )

        if (
            is_http_url(url)
            and not is_ignored_telegram_url(
                url
            )
        ):
            urls.append(url)

    # --------------------------------------------------------
    # Fallback: search entire HTML.
    # --------------------------------------------------------

    if not urls:

        raw_urls = re.findall(
            r"https?://[^\s\"'<>]+",
            post_html,
            flags=re.I,
        )

        for url in raw_urls:

            url = normalize_url(
                url
            )

            if (
                is_http_url(url)
                and not is_ignored_telegram_url(
                    url
                )
            ):
                urls.append(url)

    return unique_preserve_order(
        urls
    )


# ============================================================
# EXEC?URL= WRAPPER
# ============================================================

def extract_wrapped_urls(
    url: str,
) -> list[str]:

    result = [url]

    try:

        parsed = urlsplit(
            url
        )

        query = parse_qs(
            parsed.query,
            keep_blank_values=True,
        )

        # Common names.
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

            values = query.get(
                key,
                [],
            )

            for value in values:

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
            f"[WRAPPER] Failed to parse "
            f"{url}: {exc}"
        )

    return unique_preserve_order(
        result
    )


# ============================================================
# BASE64 DECODER
# ============================================================

def base64_decode_variants(
    value: str,
) -> list[str]:

    results = []

    if not value:
        return results

    value = value.strip()

    # Remove data URI.
    if value.lower().startswith(
        "data:text/plain;base64,"
    ):

        value = value.split(
            ",",
            1,
        )[1]

    # Remove whitespace.
    compact = re.sub(
        r"\s+",
        "",
        value,
    )

    # --------------------------------------------------------
    # Standard Base64
    # --------------------------------------------------------

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

            text = raw.decode(
                "utf-8",
                errors="ignore",
            )

            if text.strip():

                results.append(
                    text
                )

        except (
            ValueError,
            binascii.Error,
        ):
            continue

    return unique_preserve_order(
        results
    )


def looks_like_base64(
    value: str,
) -> bool:

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

    # Try decoding.
    decoded = base64_decode_variants(
        compact
    )

    for text in decoded:

        low = text.lower()

        if (
            "://" in text
            or "vless" in low
            or "vmess" in low
            or "trojan" in low
            or "hysteria" in low
            or "tuic" in low
            or "ss://" in low
        ):

            return True

    return False


# ============================================================
# PROTOCOL EXTRACTION
# ============================================================

def extract_protocol_links(
    text: str,
) -> list[str]:

    if not text:
        return []

    text = html.unescape(
        text
    )

    text = text.replace(
        "\\/",
        "/",
    )

    # JSON may contain escaped quotes.
    text = text.replace(
        "\\u0026",
        "&",
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

        # Remove trailing punctuation
        # which belongs to surrounding text.
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
# JSON RECURSION
# ============================================================

def walk_json(
    value,
) -> list[str]:

    results = []

    if isinstance(
        value,
        str,
    ):

        results.append(
            value
        )

    elif isinstance(
        value,
        dict,
    ):

        for key, val in value.items():

            # Keys can contain useful data.
            results.append(
                str(key)
            )

            results.extend(
                walk_json(val)
            )

    elif isinstance(
        value,
        list,
    ):

        for item in value:

            results.extend(
                walk_json(item)
            )

    return results


# ============================================================
# CONTENT EXPANSION
# ============================================================

def expand_content(
    text: str,
    depth: int = 0,
) -> list[str]:

    if not text:
        return []

    if depth > 4:
        return [text]

    results = [
        text
    ]

    # --------------------------------------------------------
    # Direct protocol URLs.
    # --------------------------------------------------------

    results.extend(
        extract_protocol_links(
            text
        )
    )

    # --------------------------------------------------------
    # Base64.
    # --------------------------------------------------------

    if looks_like_base64(
        text
    ):

        for decoded in (
            base64_decode_variants(
                text
            )
        ):

            if (
                decoded.strip()
                != text.strip()
            ):

                results.extend(
                    expand_content(
                        decoded,
                        depth + 1,
                    )
                )

    # --------------------------------------------------------
    # JSON.
    # --------------------------------------------------------

    stripped = text.strip()

    if (
        stripped.startswith("{")
        or stripped.startswith("[")
    ):

        try:

            obj = json.loads(
                stripped
            )

            values = walk_json(
                obj
            )

            for value in values:

                results.extend(
                    expand_content(
                        value,
                        depth + 1,
                    )
                )

        except Exception:
            pass

    # --------------------------------------------------------
    # Also try to find Base64-looking chunks inside
    # larger responses.
    # --------------------------------------------------------

    # This is useful when a subscription response
    # contains a JSON/YAML field with Base64 content.
    tokens = re.findall(
        r"[A-Za-z0-9_-]{40,}",
        text,
    )

    for token in tokens[:100]:

        if looks_like_base64(
            token
        ):

            for decoded in (
                base64_decode_variants(
                    token
                )
            ):

                results.extend(
                    expand_content(
                        decoded,
                        depth + 1,
                    )
                )

    return results


# ============================================================
# DOWNLOAD SOURCE
# ============================================================

def download_source(
    url: str,
) -> str | None:

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

        content_type = (
            response.headers.get(
                "content-type",
                "",
            )
        )

        print(
            f"[SOURCE] Content-Type: "
            f"{content_type}"
        )

        if not response.ok:

            print(
                "[SOURCE] skipped "
                f"HTTP {response.status_code}"
            )

            return None

        chunks = []
        total = 0

        for chunk in response.iter_content(
            chunk_size=65536
        ):

            if not chunk:
                continue

            total += len(chunk)

            if (
                total
                > MAX_SOURCE_SIZE
            ):

                print(
                    "[SOURCE] skipped: "
                    "response too large"
                )

                return None

            chunks.append(
                chunk
            )

        raw = b"".join(
            chunks
        )

        # ----------------------------------------------------
        # UTF-8 / UTF-8 with BOM.
        # ----------------------------------------------------

        text = raw.decode(
            "utf-8-sig",
            errors="ignore",
        )

        if not text.strip():

            print(
                "[SOURCE] empty response"
            )

            return None

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
# DEBUG PREVIEW
# ============================================================

def print_debug_preview(
    text: str,
):

    preview = text[:DEBUG_PREVIEW]

    preview = preview.replace(
        "\r",
        "\\r",
    )

    preview = preview.replace(
        "\n",
        "\\n",
    )

    print(
        "[DEBUG] Response preview:"
    )

    print(
        preview
    )


# ============================================================
# PARSE ONE URL
# ============================================================

def parse_source(
    original_url: str,
) -> list[str]:

    # --------------------------------------------------------
    # Build URL candidates.
    # --------------------------------------------------------

    candidates = []

    candidates.extend(
        extract_wrapped_urls(
            original_url
        )
    )

    # --------------------------------------------------------
    # Download every candidate.
    # --------------------------------------------------------

    all_configs = []

    for candidate in (
        unique_preserve_order(
            candidates
        )
    ):

        text = download_source(
            candidate
        )

        if not text:
            continue

        # ----------------------------------------------------
        # Expand/decode.
        # ----------------------------------------------------

        expanded = expand_content(
            text
        )

        configs = []

        for item in expanded:

            configs.extend(
                extract_protocol_links(
                    item
                )
            )

        configs = unique_preserve_order(
            configs
        )

        if configs:

            print(
                f"[SOURCE] "
                f"{candidate}"
            )

            print(
                f"[SOURCE] configs: "
                f"{len(configs)}"
            )

            all_configs.extend(
                configs
            )

        else:

            print(
                f"[SOURCE] configs: 0 "
                f"for {candidate}"
            )

            # Only show diagnostics for actual
            # subscription candidates.
            if (
                not candidate.lower()
                .endswith(
                    (
                        ".js",
                        ".css",
                        ".jpg",
                        ".jpeg",
                        ".png",
                        ".gif",
                        ".webp",
                    )
                )
            ):

                print_debug_preview(
                    text
                )

    return unique_preserve_order(
        all_configs
    )


# ============================================================
# VALIDATE CONFIG
# ============================================================

def is_supported_config(
    value: str,
) -> bool:

    value = value.strip()

    return value.lower().startswith(
        PROTOCOLS
    )


# ============================================================
# UPDATE GIST
# ============================================================

def update_gist(
    content: str,
):

    if not GIST_TOKEN:

        raise RuntimeError(
            "GIST_TOKEN is missing"
        )

    if not GIST_ID:

        raise RuntimeError(
            "GIST_ID is missing"
        )

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
            GIST_FILENAME: {
                "content": content
            }
        }
    }

    print()
    print(
        f"[GIST] Updating "
        f"{GIST_FILENAME}"
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
            "GitHub Gist update failed"
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
        "subscriptions -> Gist"
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
    # 1. Read public channel.
    # --------------------------------------------------------

    channel_html = (
        get_channel_page()
    )

    # --------------------------------------------------------
    # 2. Find newest post.
    # --------------------------------------------------------

    post_url = (
        get_last_post_url(
            channel_html
        )
    )

    # --------------------------------------------------------
    # 3. Fetch newest post.
    # --------------------------------------------------------

    post_html = fetch_post(
        post_url
    )

    # --------------------------------------------------------
    # 4. Extract external URLs.
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
            "No external HTTPS links "
            "found in latest post"
        )

    # --------------------------------------------------------
    # 5. Parse every source.
    # --------------------------------------------------------

    all_configs = []

    for i, source_url in enumerate(
        source_urls,
        1,
    ):

        print()
        print(
            "=" * 70
        )

        print(
            f"[{i}/{len(source_urls)}] "
            f"Processing source"
        )

        print(
            source_url
        )

        configs = parse_source(
            source_url
        )

        print(
            f"[SOURCE] Total configs: "
            f"{len(configs)}"
        )

        all_configs.extend(
            configs
        )

        time.sleep(
            0.5
        )

    # --------------------------------------------------------
    # 6. Normalize / deduplicate.
    # --------------------------------------------------------

    normalized = []

    for config in all_configs:

        config = clean_config(
            config
        )

        if is_supported_config(
            config
        ):

            normalized.append(
                config
            )

    all_configs = (
        unique_preserve_order(
            normalized
        )
    )

    # --------------------------------------------------------
    # 7. Statistics.
    # --------------------------------------------------------

    print()
    print("=" * 70)

    print(
        "[RESULT] "
        f"Unique configs: "
        f"{len(all_configs)}"
    )

    print("=" * 70)

    protocol_counts = {}

    for config in all_configs:

        protocol = config.split(
            "://",
            1
        )[0].lower()

        protocol_counts[
            protocol
        ] = (
            protocol_counts.get(
                protocol,
                0
            )
            + 1
        )

    for protocol, count in sorted(
        protocol_counts.items()
    ):

        print(
            f"  {protocol}: {count}"
        )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Never overwrite Gist with an empty result.
    # --------------------------------------------------------

    if not all_configs:

        raise RuntimeError(
            "No supported configs found. "
            "Gist was NOT modified."
        )

    # --------------------------------------------------------
    # 8. Build subscription.
    # --------------------------------------------------------

    output = (
        "\n".join(
            all_configs
        )
        + "\n"
    )

    # --------------------------------------------------------
    # 9. Update Gist.
    # --------------------------------------------------------

    update_gist(
        output
    )

    print()
    print(
        "[DONE] "
        f"{len(all_configs)} configs "
        "written to Gist"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\nInterrupted."
        )

        sys.exit(130)

    except Exception as exc:

        print(
            "\n[FATAL] "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        sys.exit(1)
