"""Send a test event to Telegram via the notifier."""
import os
import sys
import sqlite3

BASE = '/home/urtzai/.hermes/skills/astronomical-events'
SRC = os.path.join(BASE, 'src')
sys.path.insert(0, SRC)
os.environ['WORKSPACE_DIR'] = BASE

from telegram_notifier import TelegramNotifier

def get_next_event(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('''
        SELECT news_id, title, event_date, priority, is_notified, 
               translated_title, translated_description, translated_viewing_info,
               event_page_url, event_type, visibility_level
        FROM events 
        WHERE is_notified = 0 
        ORDER BY event_date ASC 
        LIMIT 1
    ''')
    row = cur.fetchone()
    conn.close()
    if not row:
        print("No unnotified events found")
        return None
    return dict(row)

if __name__ == '__main__':
    db_path = os.path.join(BASE, 'data', 'events.db')
    event = get_next_event(db_path)
    
    if not event:
        print("No event to send")
        sys.exit(1)
    
    print(f"Sending event: {event['news_id']}")
    print(f"  Title: {event['title']}")
    print(f"  Translated title: {event.get('translated_title', 'N/A')}")
    print(f"  Priority: {event['priority']}")
    
    notifier = TelegramNotifier(workspace_dir=BASE)
    print(f"  Providers loaded: {len(notifier.providers)}")
    for p in notifier.providers:
        print(f"    - {p.id} ({p.name}): enabled={p.enabled}")
    
    result = notifier.send_event(event)
    print(f"  Result: {result}")
    
    if result:
        print("SUCCESS: Event sent to Telegram!")
    else:
        print("FAILED: Event not sent")
        sys.exit(1)
