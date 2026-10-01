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
from urllib.parse import urlsplit

import requests


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_CHANNEL = os.getenv(
    "TELEGRAM_CHANNEL",
    "happvpn",
).strip().lstrip("@").rstrip("/")

GIST_TOKEN = os.getenv("GIST_TOKEN", "").strip()
GIST_ID = os.getenv("GIST_ID", "").strip()

GIST_FILENAME = os.getenv(
    "GIST_FILENAME",
    "configs.txt",
)

REQUEST_TIMEOUT = int(
    os.getenv("REQUEST_TIMEOUT", "30")
)

MAX_SOURCE_SIZE = int(
    os.getenv(
        "MAX_SOURCE_SIZE",
        str(10 * 1024 * 1024),
    )
)

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Mobile Safari/537.36"
)

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
})


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
# TELEGRAM HTML PARSER
# ============================================================

class TelegramHTMLParser(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)

        self.links: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):

        if tag.lower() != "a":
            return

        for key, value in attrs:

            if key.lower() == "href" and value:
                self.links.append(
                    html.unescape(value.strip())
                )

    def handle_data(self, data):

        if data:
            self.text_parts.append(data)


# ============================================================
# HELPERS
# ============================================================

def normalize_url(url: str) -> str:

    url = html.unescape(url).strip()

    url = url.strip(
        " \t\r\n<>\"'`()[]{}"
    )

    url = url.replace("&amp;", "&")

    return url


def is_http_url(url: str) -> bool:

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

    seen = set()
    result = []

    for item in items:

        if item not in seen:

            seen.add(item)
            result.append(item)

    return result


# ============================================================
# FIND LAST TELEGRAM POST
# ============================================================

def get_last_post() -> tuple[str, str]:

    """
    Gets the public Telegram channel page:

        https://t.me/s/<channel>

    Telegram normally places the newest messages at the
    end of the page.

    We extract message IDs and select the largest one.
    """

    url = (
        f"https://t.me/s/{TELEGRAM_CHANNEL}"
    )

    print(
        f"[TELEGRAM] Reading channel: {url}"
    )

    response = SESSION.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )

    print(
        f"[TELEGRAM] HTTP {response.status_code} "
        f"{len(response.content)} bytes"
    )

    response.raise_for_status()

    page = response.text

    # Telegram public channel message URLs.
    pattern = re.compile(
        rf"https?://t\.me/"
        rf"{re.escape(TELEGRAM_CHANNEL)}"
        rf"/(\d+)",
        re.I,
    )

    ids = [
        int(x)
        for x in pattern.findall(page)
    ]

    # Fallback: href may use /s/channel/id.
    if not ids:

        pattern2 = re.compile(
            rf"/(?:s/)?"
            rf"{re.escape(TELEGRAM_CHANNEL)}"
            rf"/(\d+)",
            re.I,
        )

        ids = [
            int(x)
            for x in pattern2.findall(page)
        ]

    if not ids:

        raise RuntimeError(
            "Could not find any Telegram "
            "message IDs on channel page"
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

    return post_url, page


# ============================================================
# FETCH LAST POST
# ============================================================

def fetch_last_post_html(
    post_url: str,
) -> str:

    candidates = [

        post_url + "?embed=1",

        post_url + "?embed=1&mode=tme",

        (
            f"https://t.me/s/"
            f"{TELEGRAM_CHANNEL}"
            f"/{post_url.rsplit('/', 1)[-1]}"
        ),

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

            if response.ok and response.text:

                return response.text

            errors.append(
                f"{url}: HTTP "
                f"{response.status_code}"
            )

        except Exception as exc:

            errors.append(
                f"{url}: "
                f"{type(exc).__name__}: {exc}"
            )

    raise RuntimeError(
        "Unable to read last Telegram post:\n"
        + "\n".join(errors)
    )


# ============================================================
# EXTRACT HTTPS LINKS
# ============================================================

def extract_https_links(
    source_html: str,
) -> list[str]:

    parser = TelegramHTMLParser()

    parser.feed(source_html)

    urls = []

    # Links from href.
    for url in parser.links:

        url = normalize_url(url)

        if is_http_url(url):

            urls.append(url)

    # Plain URLs inside HTML.
    urls.extend(
        re.findall(
            r"https?://[^\s\"'<>]+",
            source_html,
            flags=re.I,
        )
    )

    urls = [
        normalize_url(x)
        for x in urls
    ]

    urls = [
        x
        for x in urls
        if is_http_url(x)
    ]

    # Don't recursively parse Telegram links.
    urls = [
        x
        for x in urls
        if not re.match(
            r"^https?://(?:www\.)?t\.me/",
            x,
            re.I,
        )
    ]

    return unique_preserve_order(urls)


# ============================================================
# BASE64
# ============================================================

def looks_like_base64(
    value: str,
) -> bool:

    value = value.strip()

    if not value:
        return False

    compact = re.sub(
        r"\s+",
        "",
        value,
    )

    if len(compact) < 20:
        return False

    if not re.fullmatch(
        r"[A-Za-z0-9+/=_-]+",
        compact,
    ):
        return False

    compact += "=" * (
        (4 - len(compact) % 4) % 4
    )

    try:

        raw = base64.b64decode(
            compact,
            validate=False,
        )

        text = raw.decode(
            "utf-8",
            errors="ignore",
        )

        low = text.lower()

        return (
            "://" in text
            or "vless" in low
            or "vmess" in low
            or "trojan" in low
            or "hysteria" in low
            or "ss://" in low
        )

    except Exception:

        return False


def decode_base64(
    value: str,
) -> str | None:

    value = value.strip()

    compact = re.sub(
        r"\s+",
        "",
        value,
    )

    if compact.lower().startswith(
        "data:text/plain;base64,"
    ):

        compact = compact.split(
            ",",
            1,
        )[1]

    compact += "=" * (
        (4 - len(compact) % 4) % 4
    )

    try:

        raw = base64.b64decode(
            compact,
            validate=False,
        )

        return raw.decode(
            "utf-8",
            errors="ignore",
        )

    except Exception:

        return None


# ============================================================
# EXTRACT PROTOCOL LINKS
# ============================================================

def extract_protocol_links(
    text: str,
) -> list[str]:

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

    pattern = (
        rf"(?i)"
        rf"(?:{protocols})"
        rf"[^\s\"'<>]+"
    )

    found = re.findall(
        pattern,
        text,
    )

    result = []

    for item in found:

        item = item.strip(
            " \t\r\n,;\"'<>[](){}"
        )

        if item:
            result.append(item)

    return unique_preserve_order(
        result
    )


# ============================================================
# EXPAND CONTENT
# ============================================================

def expand_content(
    text: str,
    depth: int = 0,
) -> list[str]:

    if depth > 3:
        return [text]

    results = [text]

    links = extract_protocol_links(
        text
    )

    if links:

        results.append(
            "\n".join(links)
        )

    # Base64 subscription.
    if looks_like_base64(text):

        decoded = decode_base64(
            text
        )

        if (
            decoded
            and decoded.strip()
            != text.strip()
        ):

            results.extend(
                expand_content(
                    decoded,
                    depth + 1,
                )
            )

    # JSON.
    stripped = text.strip()

    if (
        stripped.startswith("{")
        or stripped.startswith("[")
    ):

        try:

            obj = json.loads(
                stripped
            )

            results.append(
                json.dumps(
                    obj,
                    ensure_ascii=False,
                )
            )

            def walk(value):

                if isinstance(
                    value,
                    str,
                ):

                    results.append(
                        value
                    )

                    if looks_like_base64(
                        value
                    ):

                        decoded = (
                            decode_base64(
                                value
                            )
                        )

                        if decoded:

                            results.extend(
                                expand_content(
                                    decoded,
                                    depth + 1,
                                )
                            )

                elif isinstance(
                    value,
                    dict,
                ):

                    for v in value.values():
                        walk(v)

                elif isinstance(
                    value,
                    list,
                ):

                    for v in value:
                        walk(v)

            walk(obj)

        except Exception:
            pass

    return results


# ============================================================
# DOWNLOAD SUBSCRIPTION
# ============================================================

def download_source(
    url: str,
) -> str | None:

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

            total += len(chunk)

            if total > MAX_SOURCE_SIZE:

                print(
                    "[SOURCE] too large"
                )

                return None

            chunks.append(chunk)

        raw = b"".join(chunks)

        text = raw.decode(
            "utf-8",
            errors="ignore",
        )

        if not text.strip():
            return None

        print(
            f"[SOURCE] received "
            f"{len(raw)} bytes"
        )

        return text

    except Exception as exc:

        print(
            f"[SOURCE] ERROR: "
            f"{type(exc).__name__}: {exc}"
        )

        return None


# ============================================================
# PARSE SOURCE
# ============================================================

def parse_source(
    url: str,
) -> list[str]:

    text = download_source(url)

    if not text:
        return []

    configs = []

    for expanded in expand_content(text):

        configs.extend(
            extract_protocol_links(
                expanded
            )
        )

    return unique_preserve_order(
        configs
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
            "telegram-v2ray-parser",
    }

    payload = {
        "files": {
            GIST_FILENAME: {
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
    # 1. Find latest post
    # --------------------------------------------------------

    post_url, _ = get_last_post()

    # --------------------------------------------------------
    # 2. Read latest post
    # --------------------------------------------------------

    post_html = fetch_last_post_html(
        post_url
    )

    # --------------------------------------------------------
    # 3. Extract HTTPS subscription URLs
    # --------------------------------------------------------

    source_urls = extract_https_links(
        post_html
    )

    print()
    print(
        f"[TELEGRAM] HTTPS sources: "
        f"{len(source_urls)}"
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
    # 4. Download every source
    # --------------------------------------------------------

    all_configs = []

    for i, source_url in enumerate(
        source_urls,
        1,
    ):

        print()
        print(
            f"[{i}/{len(source_urls)}] "
            f"Parsing source"
        )

        configs = parse_source(
            source_url
        )

        print(
            f"[SOURCE] configs: "
            f"{len(configs)}"
        )

        all_configs.extend(
            configs
        )

        time.sleep(0.5)

    # --------------------------------------------------------
    # 5. Deduplicate
    # --------------------------------------------------------

    all_configs = [
        x.strip()
        for x in all_configs
        if x.strip()
    ]

    all_configs = unique_preserve_order(
        all_configs
    )

    # Safety filter.
    all_configs = [
        x
        for x in all_configs
        if x.lower().startswith(
            PROTOCOLS
        )
    ]

    print()
    print("=" * 70)
    print(
        f"[RESULT] "
        f"Unique configs: "
        f"{len(all_configs)}"
    )
    print("=" * 70)

    if not all_configs:

        raise RuntimeError(
            "No supported configs found"
        )

    # --------------------------------------------------------
    # 6. Build output
    # --------------------------------------------------------

    output = (
        "\n".join(all_configs)
        + "\n"
    )

    # --------------------------------------------------------
    # 7. Update Gist
    # --------------------------------------------------------

    update_gist(
        output
    )

    print()
    print(
        "[DONE] Gist updated"
    )


if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        sys.exit(130)

    except Exception as exc:

        print(
            f"[FATAL] "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        sys.exit(1)
