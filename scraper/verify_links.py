"""驗證 events.json 每一筆的 sourceUrl 是否真的連得過去（不花 Gemini 配額）。
用瀏覽器 UA、跟隨轉址。回報每一筆的 HTTP 狀態，列出壞掉的（非 2xx/3xx）。
可被 scrape.py 匯入：check_url(url) -> (ok: bool, code: int)。"""
import sys, json, urllib.request, urllib.error, ssl
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def check_url(url, timeout=20, return_text=False):
    """回傳 (ok, code) 或 (ok, code, text)。ok=True 代表連得到（2xx/3xx）。
    Google 搜尋連結視為可用（一定有結果頁）。"""
    none_text = "" if return_text else None
    def pack(ok, code, text=""):
        return (ok, code, text) if return_text else (ok, code)
    if not url:
        return pack(False, 0)
    if "google.com/search" in url or "news.google.com" in url:
        return pack(True, 200)  # 搜尋頁一定開得了
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            text = ""
            if return_text:
                raw = r.read(200000)  # 讀前 200KB 足夠涵蓋標題/meta
                text = raw.decode("utf-8", "replace")
            return pack(200 <= r.status < 400, r.status, text)
    except urllib.error.HTTPError as e:
        # 有些站對 bot 回 403，但內容存在——如實回報，交給呼叫端判斷
        return pack(False, e.code)
    except Exception:
        return pack(False, -1)


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
