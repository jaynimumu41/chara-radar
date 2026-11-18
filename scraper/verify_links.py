"""驗證 events.json 每一筆的 sourceUrl 是否真的連得過去（不花 Gemini 配額）。
用瀏覽器 UA、跟隨轉址。回報每一筆的 HTTP 狀態，列出壞掉的（非 2xx/3xx）。
可被 scrape.py 匯入：check_url(url) -> (ok: bool, code: int)。"""
import html, json, re, sys, time, urllib.error, urllib.parse
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# 官方網站常擋資料中心 IP 的 bot（多回 403/429/503）。被擋時改用 reader 代理硬取，
# 不要直接放棄。r.jina.ai 會把目標頁轉成純文字 markdown（含標題/內文/日期），
# 對 page_mentions 關鍵字比對與 extract_dates 日期掃描都夠用。
READER_PROXY = "https://r.jina.ai/"
_BLOCKED_CODES = {401, 403, 429, 451, 503}
_PROTECTED_OFFICIAL_BLOCKS = {("www.kiddyland.co.jp", 403)}
_CHECK_CACHE = {}
_OFFICIAL_LISTING_CACHE = {}
_LAST_REQUEST_AT = {}
_HOST_MIN_INTERVAL = {
    "chiikawa-info.jp": 0.8,
    "r.jina.ai": 4.0,
}

_CHALLENGE_MARKERS = (
    "<title>just a moment",
    "title: just a moment",
    "performing security verification",
    "challenge-platform",
    "cf-chl-",
    "verify you are human",
)


def _is_challenge_page(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in _CHALLENGE_MARKERS)


def _is_unusable_reader_page(text: str) -> bool:
    """Reject reader challenges and terminal upstream 404/410 responses."""
    return _is_challenge_page(text) or bool(re.search(
        r"(?im)^Warning:\s*Target URL returned error (?:404|410)\b",
        text or "",
    ))


def _markdown_inline_html(text: str) -> str:
    """Preserve reader markdown links while escaping the visible label."""
    parts = []
    offset = 0
    for match in re.finditer(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text or ""):
        parts.append(html.escape(text[offset:match.start()]))
        label, url = match.groups()
        parts.append(
            f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'
        )
        offset = match.end()
    parts.append(html.escape((text or "")[offset:]))
    return "".join(parts)


def _reader_markdown_as_html(text: str) -> str:
    """Convert the reader's useful structure to small parser-compatible HTML."""
    result = []
    for line in (text or "").splitlines():
        if line.startswith("Title: "):
            result.append(f"<title>{html.escape(line[7:].strip())}</title>")
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            result.append(
                f"<h{level}>{_markdown_inline_html(heading.group(2))}</h{level}>"
            )
            continue
        result.append(html.escape(line))
    return "\n".join(result)


def _reader_markdown_fetch(url: str, timeout: int) -> str:
    """Fetch reader markdown, retrying a cached challenge only for Chiikawa."""
    # The unmodified canonical URL is intentionally requested without
    # X-No-Cache: Jina's canonical cache is often the only copy that survives
    # an origin-side Cloudflare challenge.  Only the cache-busted target asks
    # the reader to refresh its cache.
    targets: list[tuple[str, bool]] = [(url, False)]
    if (urllib.parse.urlparse(url).hostname or "") == "chiikawa-info.jp":
        separator = "&" if "?" in url else "?"
        fresh = f"{url}{separator}chara_radar={int(time.time())}"
        targets.extend(((fresh, True), (url, False)))
        if url.endswith("/index.html"):
            targets.append((url[:-len("index.html")], False))
        if url.startswith("https://"):
            targets.append(("http://" + url[len("https://"):], False))
    for attempt, (target, no_cache) in enumerate(targets):
        reader_url = READER_PROXY + target
        try:
            _polite_wait(reader_url)
            headers = {"User-Agent": UA}
            if no_cache:
                headers["X-No-Cache"] = "true"
            response = requests.get(
                reader_url,
                headers=headers,
                timeout=max(timeout, 45),
            )
            if 200 <= response.status_code < 400:
                result = response.content[:500000].decode("utf-8", "replace")
                if result.strip() and not _is_unusable_reader_page(result):
                    return _reader_markdown_as_html(result)
        except Exception:
            pass
        if attempt < len(targets) - 1:
            time.sleep(2 * (attempt + 1))
    return ""


def _network_url(url: str) -> str:
    """Fragments are client-side only; cache/check the actual network URL once."""
    return urllib.parse.urldefrag(url or "")[0]


def _polite_wait(url: str) -> None:
    host = urllib.parse.urlparse(url).hostname or ""
    delay = _HOST_MIN_INTERVAL.get(host, 0)
    if delay <= 0:
        return
    now = time.monotonic()
    last = _LAST_REQUEST_AT.get(host, 0)
    wait = delay - (now - last)
    if wait > 0:
        time.sleep(wait)
    _LAST_REQUEST_AT[host] = time.monotonic()


def _prefer_reader_proxy(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if host == "chiikawa-info.jp" and "/p26/" in parsed.path:
        return True
    return host == "pokemonhubs.com"


def _is_protected_official_block(url: str, code: int) -> bool:
    """Recognize a narrow, observed whole-site bot block without hiding 404s."""
    host = urllib.parse.urlparse(url).hostname or ""
    return (host, code) in _PROTECTED_OFFICIAL_BLOCKS


def _official_listing_confirms_url(url: str, timeout: int) -> bool:
    """Confirm protected Chiikawa pages through a live official listing.

    This is deliberately pattern-based rather than a seed allowlist: the exact
    target URL must still be present in the current official aggregate page.
    """
    parsed = urllib.parse.urlparse(url)
    if (parsed.hostname or "") != "chiikawa-info.jp":
        return False
    if re.fullmatch(r"/p26/pus_[^/]+/index\.html", parsed.path):
        listing_url = "https://chiikawa-info.jp/pus.html"
    elif parsed.path == "/p26/chiikawaclinic/index.html":
        listing_url = "https://chiikawa-info.jp/index.html"
    else:
        return False
    listing = _OFFICIAL_LISTING_CACHE.get(listing_url, "")
    if not listing:
        listing = _reader_markdown_fetch(listing_url, timeout)
        if listing:
            _OFFICIAL_LISTING_CACHE[listing_url] = listing
    target = urllib.parse.urlunparse(parsed._replace(query="", fragment=""))
    return bool(listing and target in html.unescape(listing))


def _raw_fetch(url, timeout, want_text):
    """單次抓取，回傳 (ok, code, text)。例外往外丟。"""
    _polite_wait(url)
    parsed = urllib.parse.urlparse(url)
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.8",
    }
    if parsed.hostname == "chiikawa-info.jp":
        headers["Referer"] = "https://chiikawa-info.jp/index.html"
    with requests.get(
        url, headers=headers, timeout=timeout,
        allow_redirects=True, stream=True,
    ) as response:
        text = ""
        if want_text and 200 <= response.status_code < 400:
            raw = bytearray()
            for chunk in response.iter_content(chunk_size=32768):
                raw.extend(chunk)
                if len(raw) >= 200000:
                    break
            text = bytes(raw[:200000]).decode("utf-8", "replace")
        return (200 <= response.status_code < 400, response.status_code, text)


def _proxy_fetch(url: str, timeout: int) -> tuple[bool, int, str]:
    last_error = None
    for attempt in range(3):
        try:
            result = _raw_fetch(READER_PROXY + url, max(timeout, 45), True)
            if result[0] and _is_unusable_reader_page(result[2]):
                if attempt == 2:
                    return False, result[1], result[2]
                time.sleep(3 * (attempt + 1))
                continue
            return result
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in _BLOCKED_CODES or attempt == 2:
                raise
        except Exception as exc:
            last_error = exc
            if attempt == 2:
                raise
        time.sleep(3 * (attempt + 1))
    raise last_error


def check_url(url, timeout=20, return_text=False):
    """回傳 (ok, code) 或 (ok, code, text)。ok=True 代表連得到（2xx/3xx）。
    Google 搜尋連結視為可用。**被 bot 防護擋住（403/429/503…）或連線失敗時，
    自動改用 reader 代理再試一次，不直接放棄。**"""
    def pack(ok, code, text=""):
        return (ok, code, text) if return_text else (ok, code)
    if not url:
        return pack(False, 0)
    if "google.com/search" in url or "news.google.com" in url:
        return pack(True, 200)  # 搜尋頁一定開得了
    net_url = _network_url(url)
    cache_key = (net_url, bool(return_text))
    if cache_key in _CHECK_CACHE:
        ok, code, text = _CHECK_CACHE[cache_key]
        return pack(ok, code, text if return_text else "")

    proxy_tried = False
    if _prefer_reader_proxy(net_url):
        proxy_tried = True
        try:
            pok, _pcode, ptext = _proxy_fetch(net_url, timeout)
            if pok and ptext.strip():
                _CHECK_CACHE[cache_key] = (True, 200, ptext if return_text else "")
                return pack(True, 200, ptext if return_text else "")
        except Exception:
            pass

    code, blocked = -1, True
    try:
        # Always inspect a bounded response body: a Cloudflare challenge often
        # returns HTTP 200, so status-only verification can report a false OK.
        ok, code, text = _raw_fetch(net_url, timeout, True)
        challenge = ok and _is_challenge_page(text)
        if ok and not challenge:
            cached_text = text if return_text else ""
            _CHECK_CACHE[cache_key] = (True, code, cached_text)
            return pack(True, code, cached_text)
        blocked = code in _BLOCKED_CODES or challenge
    except urllib.error.HTTPError as e:
        code, blocked = e.code, e.code in _BLOCKED_CODES
    except Exception:
        code, blocked = -1, True  # 連線/逾時等失敗也試代理

    # 被擋或失敗 → reader 代理 fallback（代理回純文字，當作可達且取得內容）
    if blocked:
        if (urllib.parse.urlparse(net_url).hostname or "") == "chiikawa-info.jp":
            markdown_html = _reader_markdown_fetch(net_url, timeout)
            if markdown_html:
                cached_text = markdown_html if return_text else ""
                _CHECK_CACHE[cache_key] = (True, 200, cached_text)
                return pack(True, 200, cached_text)
            if not return_text and _official_listing_confirms_url(net_url, timeout):
                _CHECK_CACHE[cache_key] = (True, 200, "")
                return pack(True, 200)
        try:
            if not proxy_tried:
                pok, _pcode, ptext = _proxy_fetch(net_url, timeout)
                if pok and ptext.strip():
                    _CHECK_CACHE[cache_key] = (True, 200, ptext if return_text else "")
                    return pack(True, 200, ptext if return_text else "")
        except Exception:
            pass
    if _is_protected_official_block(net_url, code):
        _CHECK_CACHE[cache_key] = (True, code, "")
        return pack(True, code)
    _CHECK_CACHE[cache_key] = (False, code, "")
    return pack(False, code)


def fetch_html(url, timeout=20):
    """取得頁面原始 HTML（含 <meta og:>）字串；被 bot 防護擋住或失敗時，改用 reader 代理
    並要求回 HTML 格式（X-Return-Format: html，保留 meta tag 供 regex 解析）。失敗回 ''。"""
    if not url:
        return ""
    try:
        ok, code, text = _raw_fetch(url, timeout, True)
        if ok and text and not _is_challenge_page(text):
            return text
        blocked = code in _BLOCKED_CODES or _is_challenge_page(text)
    except urllib.error.HTTPError as e:
        blocked = e.code in _BLOCKED_CODES
    except Exception:
        blocked = True
    if blocked:
        # Chiikawa's challenge is reproduced by the reader's HTML renderer.
        # Its markdown renderer is independently cached and remains usable;
        # convert that structured text back to lightweight compatible HTML.
        if (urllib.parse.urlparse(url).hostname or "") == "chiikawa-info.jp":
            return _reader_markdown_fetch(url, timeout)
        try:
            response = requests.get(
                READER_PROXY + url,
                headers={"User-Agent": UA, "X-Return-Format": "html"},
                timeout=max(timeout, 45),
            )
            if 200 <= response.status_code < 400:
                result = response.content[:500000].decode("utf-8", "replace")
                if result.strip() and not _is_unusable_reader_page(result):
                    return result
        except Exception:
            pass
        # Some protected sites make the reader's HTML renderer reproduce the
        # challenge page while its default markdown renderer has the real
        # document. Convert only headings, titles and links back to lightweight
        # HTML so existing deterministic parsers keep their contract.
        markdown_html = _reader_markdown_fetch(url, timeout)
        if markdown_html:
            return markdown_html
    return ""


def page_mentions(text, keywords):
    """頁面內容（含 meta/og:title，多為伺服器端輸出）是否提到任一關鍵字。"""
    if not text:
        return False
    low = text.lower()
    return any(k.lower() in low for k in keywords)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = Path(__file__).parent.parent / "data" / "events.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    bad = []
    for e in d:
        ok, code = check_url(e.get("sourceUrl"))
        mark = "OK " if ok else "壞 "
        print(f"  [{mark}{code:>4}] {e['brand']:<8} {e['title'][:34]}")
        if not ok:
            bad.append((e["id"], e["brand"], e["title"], code, e.get("sourceUrl")))
    print(f"\n共 {len(d)} 筆，壞掉 {len(bad)} 筆")
    for id_, brand, title, code, url in bad:
        print(f"  ✗ [{code}] {id_} {brand} {title[:30]}\n      {url}")
    return bad


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
