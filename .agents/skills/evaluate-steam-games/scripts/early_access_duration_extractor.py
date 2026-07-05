#!/usr/bin/env python3
"""Extract the English Early Access duration answer from a Steam Store page."""

from __future__ import annotations

import argparse
import json
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SHARED_LIB = Path(__file__).resolve().parents[3] / "lib"
sys.path.insert(0, str(SHARED_LIB))

from steam_purchase_advisor.itad_client import USER_AGENT  # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


STORE_APP_URL = "https://store.steampowered.com/app/{appid}/"
DEVNOTES_ID = "devnotes_expander"
TARGET_QUESTION = "Approximately how long will this game be in Early Access?"
REQUEST_TIMEOUT_SECONDS = 30
RETRY_DELAYS = (1.0, 2.0)
TEXT_BREAK_TAGS = {"br", "div", "li", "ol", "p", "ul"}


class EarlyAccessDurationError(RuntimeError):
    """Raised when the duration answer cannot be retrieved or extracted."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def normalize_text(value: str) -> str:
    """Collapse HTML formatting whitespace without changing visible characters."""
    return " ".join(value.split())


class EarlyAccessDurationParser(HTMLParser):
    """Parse the duration answer from Steam's Early Access developer notes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.section_found = False
        self.question_found = False
        self._devnotes_depth = 0
        self._inside_heading = False
        self._capture_answer = False
        self._heading_parts: list[str] = []
        self._answer_parts: list[str] = []

    @property
    def answer(self) -> str:
        return normalize_text("".join(self._answer_parts))

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()

        if tag == "div":
            if self._devnotes_depth:
                self._devnotes_depth += 1
            elif dict(attrs).get("id") == DEVNOTES_ID:
                self.section_found = True
                self._devnotes_depth = 1

        if not self._devnotes_depth:
            return

        if tag == "h3":
            self._capture_answer = False
            self._inside_heading = True
            self._heading_parts = []
        elif self._capture_answer and tag in TEXT_BREAK_TAGS:
            self._answer_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self._devnotes_depth:
            return

        if tag == "h3" and self._inside_heading:
            heading = normalize_text("".join(self._heading_parts))
            self._inside_heading = False
            self._heading_parts = []
            if heading == TARGET_QUESTION:
                self.question_found = True
                self._capture_answer = True
        elif self._capture_answer and tag in TEXT_BREAK_TAGS:
            self._answer_parts.append(" ")

        if tag == "div":
            self._devnotes_depth -= 1
            if not self._devnotes_depth:
                self._inside_heading = False
                self._capture_answer = False

    def handle_data(self, data: str) -> None:
        if not self._devnotes_depth:
            return
        if self._inside_heading:
            self._heading_parts.append(data)
        elif self._capture_answer:
            self._answer_parts.append(data)


def parse_appid(value: str) -> int:
    appid = value.strip()
    if not appid.isascii() or not appid.isdigit() or int(appid) <= 0:
        raise argparse.ArgumentTypeError("appid must be a positive integer")
    return int(appid)


def store_url(appid: int) -> str:
    return f"{STORE_APP_URL.format(appid=appid)}?{urlencode({'l': 'english'})}"


def fetch_store_page(appid: int) -> tuple[str, str]:
    url = store_url(appid)
    request = Request(
        url,
        headers={
            "Accept": "text/html",
            "User-Agent": USER_AGENT,
        },
    )

    attempts = len(RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
            try:
                return url, body.decode(charset)
            except (LookupError, UnicodeDecodeError):
                return url, body.decode("utf-8", errors="replace")
        except HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt == attempts - 1:
                raise EarlyAccessDurationError(
                    f"steam_http_{exc.code}",
                    f"Steam Store request failed with HTTP {exc.code}.",
                ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt == attempts - 1:
                raise EarlyAccessDurationError(
                    "steam_request_failed",
                    "Steam Store request failed.",
                ) from exc

        time.sleep(RETRY_DELAYS[attempt])

    raise AssertionError("unreachable")


def extract_duration_answer(html: str) -> str:
    parser = EarlyAccessDurationParser()
    parser.feed(html)
    parser.close()

    if not parser.section_found:
        raise EarlyAccessDurationError(
            "early_access_section_not_found",
            "Steam returned no Early Access developer notes section.",
        )
    if not parser.question_found:
        raise EarlyAccessDurationError(
            "duration_question_not_found",
            "Steam returned no Early Access duration question.",
        )

    answer = parser.answer
    if not answer:
        raise EarlyAccessDurationError(
            "duration_answer_not_found",
            "Steam returned an empty Early Access duration answer.",
        )
    return answer


def emit_error(appid: int, url: str, exc: EarlyAccessDurationError) -> None:
    print(
        json.dumps(
            {
                "error": "early_access_duration_unavailable",
                "reason": exc.reason,
                "message": str(exc),
                "appid": appid,
                "url": url,
            },
            ensure_ascii=False,
            indent=2,
        ),
        file=sys.stderr,
    )


def main() -> int:
    argument_parser = argparse.ArgumentParser(
        description=(
            "Extract the developer's English answer to Steam's standard "
            "Early Access duration question."
        )
    )
    argument_parser.add_argument(
        "--appid",
        required=True,
        type=parse_appid,
        help="Steam app ID, e.g. 2769780",
    )
    args = argument_parser.parse_args()

    url = store_url(args.appid)
    try:
        _, html = fetch_store_page(args.appid)
        answer = extract_duration_answer(html)
    except EarlyAccessDurationError as exc:
        emit_error(args.appid, url, exc)
        return 2

    print(
        json.dumps(
            {
                "appid": args.appid,
                "url": url,
                "question": TARGET_QUESTION,
                "answer": answer,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
