"""驗證 events.json 每一筆的 sourceUrl 是否真的連得過去（不花 Gemini 配額）。
用瀏覽器 UA、跟隨轉址。回報每一筆的 HTTP 狀態，列出壞掉的（非 2xx/3xx）。
可被 scrape.py 匯入：check_url(url) -> (ok: bool, code: int)。"""
import sys, json, urllib.request, urllib.error, urllib.parse, ssl
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# 官方網站常擋資料中心 IP 的 bot（多回 403/429/503）。被擋時改用 reader 代理硬取，
# 不要直接放棄。r.jina.ai 會把目標頁轉成純文字 markdown（含標題/內文/日期），
# 對 page_mentions 關鍵字比對與 extract_dates 日期掃描都夠用。
READER_PROXY = "https://r.jina.ai/"
_BLOCKED_CODES = {401, 403, 429, 451, 503}
_CHECK_CACHE = {}


def _network_url(url: str) -> str:
    """Fragments are client-side only; cache/check the actual network URL once."""
    return urllib.parse.urldefrag(url or "")[0]


def _raw_fetch(url, timeout, want_text):
    """單次抓取，回傳 (ok, code, text)。例外往外丟。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        text = ""
        if want_text:
            text = r.read(200000).decode("utf-8", "replace")
        return (200 <= r.status < 400, r.status, text)


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

    code, blocked = -1, True
    try:
        ok, code, text = _raw_fetch(net_url, timeout, return_text)
        if ok:
            _CHECK_CACHE[cache_key] = (True, code, text)
            return pack(True, code, text)
        blocked = code in _BLOCKED_CODES
    except urllib.error.HTTPError as e:
        code, blocked = e.code, e.code in _BLOCKED_CODES
    except Exception:
        code, blocked = -1, True  # 連線/逾時等失敗也試代理

    # 被擋或失敗 → reader 代理 fallback（代理回純文字，當作可達且取得內容）
    if blocked:
        try:
            pok, _pcode, ptext = _raw_fetch(READER_PROXY + net_url, max(timeout, 45), True)
            if pok and ptext.strip():
                _CHECK_CACHE[cache_key] = (True, 200, ptext if return_text else "")
                return pack(True, 200, ptext if return_text else "")
        except Exception:
            pass
    _CHECK_CACHE[cache_key] = (False, code, "")
    return pack(False, code)


def fetch_html(url, timeout=20):
    """取得頁面原始 HTML（含 <meta og:>）字串；被 bot 防護擋住或失敗時，改用 reader 代理
    並要求回 HTML 格式（X-Return-Format: html，保留 meta tag 供 regex 解析）。失敗回 ''。"""
    if not url:
        return ""
    try:
        ok, code, text = _raw_fetch(url, timeout, True)
        if ok and text:
            return text
        blocked = code in _BLOCKED_CODES
    except urllib.error.HTTPError as e:
        blocked = e.code in _BLOCKED_CODES
    except Exception:
        blocked = True
    if blocked:
        try:
            req = urllib.request.Request(READER_PROXY + url, headers={
                "User-Agent": UA, "X-Return-Format": "html"})
            with urllib.request.urlopen(req, timeout=max(timeout, 45), context=_CTX) as r:
                return r.read(500000).decode("utf-8", "replace")
        except Exception:
            pass
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
    main()
