from __future__ import annotations

import csv
import io
import json as json_mod
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from html import unescape
from pathlib import Path
from typing import Any, Iterable


def warn(message: str) -> None:
    print(f"[warn] {message}", file=sys.stderr)


def info(message: str) -> None:
    print(f"[info] {message}", file=sys.stderr)


def load_env_file(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE pairs from a local .env file if it exists."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_lasair_token() -> str:
    """Return the configured Lasair token, preferring the documented API name."""
    return (
        os.environ.get("LASAIR_API_TOKEN", "").strip()
        or os.environ.get("LASAIR_TOKEN", "").strip()
    )


def lasair_auth_headers() -> dict[str, str]:
    token = get_lasair_token()
    return {"Authorization": f"Token {token}"} if token else {}


def append_query_params(url: str, params: dict[str, Any]) -> str:
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items() if value is not None})
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def lasair_url(url: str, params: dict[str, Any] | None = None, *, include_token: bool = True) -> str:
    payload = dict(params or {})
    if include_token:
        token = get_lasair_token()
        if token:
            payload["token"] = token
    return append_query_params(url, payload) if payload else url


def mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_filename(text: str, fallback: str = "unknown") -> str:
    text = re.sub(r"[^A-Za-z0-9_.+-]+", "_", (text or "").strip())
    return text.strip("_") or fallback


def strip_tags(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def first_float(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def normalize_tns_name(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r"\s+", "", name)
    for prefix in ("SN", "AT"):
        if name.upper().startswith(prefix) and len(name) > len(prefix):
            return name[len(prefix):]
    return name


def canonical_name(*names: str | None) -> str:
    for name in names:
        if not name:
            continue
        cleaned = str(name).strip()
        if cleaned and cleaned != "-":
            return cleaned
    return "unknown"


def request_bytes(url: str, *, timeout: int = 45, headers: dict[str, str] | None = None) -> bytes:
    hdrs = {
        "User-Agent": (
            "sn-target-downloader/0.1 "
            "(public astronomy data collector; contact: local observing script)"
        )
    }
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def request_json(url: str, *, timeout: int = 45, headers: dict[str, str] | None = None) -> Any:
    import json

    data = request_bytes(url, timeout=timeout, headers=headers)
    return json.loads(data.decode("utf-8", "replace"))


def download_file(url: str, dest: Path, *, timeout: int = 60, overwrite: bool = False) -> bool:
    if dest.exists() and not overwrite:
        return True
    try:
        data = request_bytes(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        warn(f"download failed: {url} ({exc})")
        return False
    mkdir(dest.parent)
    dest.write_bytes(data)
    return True


def save_text(path: Path, text: str) -> None:
    mkdir(path.parent)
    path.write_text(text, encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    mkdir(path.parent)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


class TnsCredentials:
    def __init__(self, tns_id: str, name: str, cred_type: str, api_key: str = ""):
        self.tns_id = int(tns_id)
        self.name = name
        self.cred_type = cred_type
        self.api_key = api_key

    @property
    def is_bot(self) -> bool:
        return self.cred_type == "bot" and bool(self.api_key)

    @property
    def is_user(self) -> bool:
        return self.cred_type == "user"

    def to_marker_json(self) -> str:
        return json_mod.dumps({"tns_id": self.tns_id, "type": self.cred_type, "name": self.name})


def get_tns_credentials() -> TnsCredentials | None:
    bot_id = os.environ.get("TNS_BOT_ID", "").strip()
    bot_name = os.environ.get("TNS_BOT_NAME", "").strip()
    bot_key = os.environ.get("TNS_API_KEY", "").strip()
    if bot_id and bot_name and bot_key:
        return TnsCredentials(bot_id, bot_name, "bot", bot_key)

    user_id = os.environ.get("TNS_USER_ID", "").strip()
    user_name = os.environ.get("TNS_USER_NAME", "").strip()
    if user_id and user_name:
        return TnsCredentials(user_id, user_name, "user")

    return None


def tns_has_bot() -> bool:
    creds = get_tns_credentials()
    return creds is not None and creds.is_bot


def tns_auth_headers() -> dict[str, str]:
    creds = get_tns_credentials()
    if not creds:
        return {}
    return {"User-Agent": f"tns_marker{creds.to_marker_json()}"}


def tns_auth_headers_with_content_type() -> dict[str, str]:
    hdrs = tns_auth_headers()
    if hdrs:
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    return hdrs


def parse_rate_limits(headers: dict[str, str] | None) -> dict[str, int | None]:
    result: dict[str, int | None] = {"remaining": None, "limit": None, "reset": None}
    if not headers:
        return result
    for key, field in [
        ("x-rate-limit-remaining", "remaining"),
        ("x-rate-limit-limit", "limit"),
        ("x-rate-limit-reset", "reset"),
    ]:
        for hdr_name, hdr_value in headers.items():
            if hdr_name.lower() == key.lower():
                try:
                    result[field] = int(hdr_value)
                except (ValueError, TypeError):
                    pass
    return result


class RateLimitTracker:
    def __init__(self, pause_s: float = 6.5, respect_headers: bool = True):
        self.pause_s = pause_s
        self.respect_headers = respect_headers
        self.remaining: int | None = None
        self.reset_time: float | None = None
        self.request_count = 0
        self.skip_count = 0
        self.skipped_reasons: list[str] = []

    def update_from_headers(self, headers: dict[str, str] | None) -> None:
        if not self.respect_headers or not headers:
            return
        limits = parse_rate_limits(headers)
        if limits["remaining"] is not None:
            self.remaining = limits["remaining"]
        if limits["reset"] is not None:
            self.reset_time = time.time() + float(limits["reset"])

    def wait_if_needed(self) -> float:
        waited = 0.0
        if self.respect_headers:
            if self.remaining is not None and self.remaining <= 0 and self.reset_time is not None:
                sleep_for = max(self.reset_time - time.time() + 1.0, 1.0)
                if sleep_for > 0:
                    info(f"Rate limit reached; sleeping {sleep_for:.0f}s")
                    time.sleep(sleep_for)
                    waited = sleep_for
                self.remaining = None
                self.reset_time = None
            elif self.pause_s > 0:
                time.sleep(self.pause_s)
                waited = self.pause_s
        elif self.pause_s > 0:
            time.sleep(self.pause_s)
            waited = self.pause_s
        return waited

    def handle_429(self, headers: dict[str, str] | None) -> float:
        retry_after = None
        if headers:
            for name, value in headers.items():
                if name.lower() == "retry-after":
                    try:
                        retry_after = int(value)
                    except ValueError:
                        pass
        sleep_for = float(retry_after or 60)
        info(f"429 Too Many Requests; sleeping {sleep_for:.0f}s")
        time.sleep(sleep_for)
        self.remaining = None
        self.reset_time = None
        return sleep_for

    def has_budget(self, max_requests: int) -> bool:
        if max_requests <= 0:
            return True
        return self.request_count < max_requests

    def record_request(self) -> None:
        self.request_count += 1

    def record_skip(self, reason: str) -> None:
        self.skip_count += 1
        self.skipped_reasons.append(reason)

    def summary(self) -> dict[str, Any]:
        return {
            "requests": self.request_count,
            "skipped": self.skip_count,
            "skip_reasons": "; ".join(self.skipped_reasons) if self.skipped_reasons else "",
        }

    def remaining_budget(self, max_requests: int) -> int:
        if max_requests <= 0:
            return 0
        return max(0, max_requests - self.request_count)


def request_json_rate_limited(
    url: str,
    tracker: RateLimitTracker,
    *,
    max_requests: int = 0,
    timeout: int = 60,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    post_data: bytes | None = None,
) -> tuple[Any | None, dict[str, str]]:
    if not tracker.has_budget(max_requests):
        tracker.record_skip(f"budget exhausted {url}")
        return None, {}

    tracker.wait_if_needed()

    hdrs = {
        "User-Agent": (
            "sn-target-downloader/0.2 "
            "(public astronomy data collector; contact: local observing script)"
        )
    }
    if headers:
        hdrs.update(headers)

    try:
        req = urllib.request.Request(url, headers=hdrs, data=post_data, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            tracker.update_from_headers(dict(response.headers.items()))
            tracker.record_request()
            data = response.read()
            resp_headers = dict(response.headers.items())
            return json_mod.loads(data.decode("utf-8", "replace")), resp_headers
    except urllib.error.HTTPError as exc:
        resp_headers = dict(exc.headers.items()) if exc.headers else {}
        tracker.update_from_headers(resp_headers)
        if exc.code == 429:
            tracker.handle_429(resp_headers)
            try:
                req2 = urllib.request.Request(url, headers=hdrs, data=post_data, method=method)
                with urllib.request.urlopen(req2, timeout=timeout) as response:
                    tracker.update_from_headers(dict(response.headers.items()))
                    tracker.record_request()
                    data = response.read()
                    resp_headers = dict(response.headers.items())
                    return json_mod.loads(data.decode("utf-8", "replace")), resp_headers
            except Exception as exc2:
                warn(f"TNS API retry failed: {exc2}")
                return None, resp_headers
        warn(f"HTTP {exc.code} for {url}")
        return None, resp_headers
    except Exception as exc:
        warn(f"Request failed for {url}: {exc}")
        return None, {}


def request_bytes_rate_limited(
    url: str,
    tracker: RateLimitTracker,
    *,
    max_requests: int = 0,
    timeout: int = 60,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    post_data: bytes | None = None,
) -> tuple[bytes | None, dict[str, str]]:
    if not tracker.has_budget(max_requests):
        tracker.record_skip(f"budget exhausted {url}")
        return None, {}

    tracker.wait_if_needed()

    hdrs = {
        "User-Agent": (
            "sn-target-downloader/0.2 "
            "(public astronomy data collector; contact: local observing script)"
        )
    }
    if headers:
        hdrs.update(headers)

    try:
        req = urllib.request.Request(url, headers=hdrs, data=post_data, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            tracker.update_from_headers(dict(response.headers.items()))
            tracker.record_request()
            data = response.read()
            resp_headers = dict(response.headers.items())
            return data, resp_headers
    except urllib.error.HTTPError as exc:
        resp_headers = dict(exc.headers.items()) if exc.headers else {}
        tracker.update_from_headers(resp_headers)
        if exc.code == 429:
            tracker.handle_429(resp_headers)
            try:
                req2 = urllib.request.Request(url, headers=hdrs, data=post_data, method=method)
                with urllib.request.urlopen(req2, timeout=timeout) as response:
                    tracker.update_from_headers(dict(response.headers.items()))
                    tracker.record_request()
                    data = response.read()
                    resp_headers = dict(response.headers.items())
                    return data, resp_headers
            except Exception as exc2:
                warn(f"TNS API retry failed: {exc2}")
                return None, resp_headers
        warn(f"HTTP {exc.code} for {url}")
        return None, resp_headers
    except Exception as exc:
        warn(f"Request failed for {url}: {exc}")
        return None, {}


def read_csv_rows(path: Path, *, delimiter: str = ",") -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))
