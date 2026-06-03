"""一次性維護：把新版規則套用到現有 data/events.json
  1) 移除雜訊（棒球/路跑等非購物情報）
  2) 對有真實來源連結、但日期未定者，重抓來源頁補日期（不花 AI）
  3) 啟發式去重 + AI 群組去重（1 次配額）
  4) 移除過期、存檔
用法：python recheck.py
"""
import sys
from scrape import (load_events, save_events, is_noise, is_sports_noise,
                    apply_extracted_dates, clean_events, ai_dedup, check_url,
                    is_trusted_date_source, load_env, detect_ai_backend, KeyRotator)

def main():
    events = load_events()
    print(f"起始 {len(events)} 筆")

    # 1) 移除雜訊：標題命中一般雜訊，或 標題/原始標題/摘要 命中體育路跑類
    kept = []
    for e in events:
        if (is_noise(e.get("title", ""))
                or is_sports_noise(e.get("title", ""), e.get("sourceTitle", ""),
                                   e.get("summaryZh", ""))):
            print(f"  🗑️  移除雜訊：{e.get('title')}")
            continue
        kept.append(e)
    events = kept

    # 2) 補日期：只從可信網域（官方/新聞稿/場館頁）補，一般新聞不補（易抓錯）
    for e in events:
        if e.get("startDate") and e.get("endDate"):
            continue
        url = e.get("sourceUrl", "")
        if not is_trusted_date_source(url):
            continue
        try:
            ok, code, html = check_url(url, return_text=True)
        except Exception as ex:
            print(f"  ⚠️  抓取失敗 {url}: {ex}"); continue
        if not ok:
            continue
        before = (e.get("startDate"), e.get("endDate"))
        apply_extracted_dates(e, html, 2026, is_html=True)
        if (e.get("startDate"), e.get("endDate")) != before:
            print(f"  📅 {e.get('title')} → {e.get('startDate') or '—'} ~ {e.get('endDate') or '—'}")

    # 3) 去重
    events, past_removed, dup_removed = clean_events(events)
    print(f"  啟發式：移除過期 {past_removed}、去重 {dup_removed}")

    backend = detect_ai_backend(load_env())
    if backend:
        rotator = KeyRotator(*backend)
        events, ai_removed = ai_dedup(events, rotator)
        print(f"  AI 去重：{ai_removed} 筆")
    else:
        print("  （無 API key，略過 AI 去重）")

    save_events(events)
    print(f"完成，總計 {len(events)} 筆")

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
