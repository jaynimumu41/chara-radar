"""把去重 + 過期過濾套用到現有 events.json（不呼叫 AI、不花配額）"""
import scrape

events = scrape.load_events()
before = len(events)
cleaned, past_removed, dup_removed = scrape.clean_events(events)
scrape.save_events(cleaned)
print(f"原本 {before} 筆")
print(f"移除過期：{past_removed} 筆")
print(f"去重合併：{dup_removed} 筆")
print(f"清理後：{len(cleaned)} 筆")
