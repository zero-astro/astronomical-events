"""Web Dashboard - Astronomical Events Skill.

Simple FastAPI dashboard showing upcoming astronomical events.
Provides a clean web interface for browsing events by priority and date.

Usage:
    python3 scripts/main.py dashboard              # Start web dashboard (port 8080)
    python3 scripts/main.py dashboard --port 9000   # Custom port
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    from fastapi import FastAPI, Query
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse, JSONResponse
    from pydantic import BaseModel
except ImportError:
    print("FastAPI not installed. Install with: pip install fastapi uvicorn")
    sys.exit(1)

from db_manager import DatabaseManager
from classifier import get_priority_emoji, format_visibility_label

logger = logging.getLogger(__name__)


# ─── Pydantic Models ────────────────────────────────────────────────────────

class EventSummary(BaseModel):
    """Event summary for API responses."""
    news_id: str
    title: str
    event_date: Optional[str]
    time_label: str
    priority: int
    priority_emoji: str
    event_type: str
    visibility_level: Optional[int] = None
    visibility_label: Optional[str] = None
    thumbnail_url: Optional[str] = None


class DashboardStats(BaseModel):
    """Dashboard statistics."""
    total_events: int
    upcoming_7d: int
    upcoming_30d: int
    by_priority: dict  # {priority: count}


# ─── FastAPI App ────────────────────────────────────────────────────────────

app = FastAPI(
    title="Astronomical Events Dashboard",
    description="Real-time astronomical events monitoring dashboard",
    version="1.0.0",
)


def _get_db(db_path: str) -> DatabaseManager:
    """Get database connection."""
    return DatabaseManager(db_path)


def _format_event(event, days_ahead: int = 365) -> Optional[EventSummary]:
    """Format event for display."""
    from datetime import datetime as dt
    
    today = dt.now().date()
    if not event.event_date or (event.event_date.date() - today).days > days_ahead:
        return None

    delta_days = (event.event_date.date() - today).days
    if delta_days < 0:
        time_label = "past"
    elif delta_days == 0:
        time_label = "today"
    elif delta_days == 1:
        time_label = "tomorrow"
    else:
        time_label = f"{delta_days} days away"

    return EventSummary(
        news_id=event.news_id,
        title=event.title,
        event_date=event.event_date.isoformat() if event.event_date else None,
        time_label=time_label,
        priority=event.priority,
        priority_emoji=get_priority_emoji(event.priority),
        event_type=event.event_type or "unknown",
        visibility_level=event.visibility_level,
        visibility_label=format_visibility_label(event.visibility_level) if event.visibility_level else None,
        thumbnail_url=event.thumbnail_url,
    )


# ─── API Endpoints ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard_index():
    """Main dashboard page."""
    return HTMLResponse(content=_get_dashboard_html())


@app.get("/api/events")
async def api_events(
    days: int = Query(30, ge=1, le=365),
    priority: Optional[int] = Query(None, ge=1, le=5),
    db_path: str = str(Path(__file__).parent.parent / "data" / "events.db"),
):
    """Get upcoming events as JSON."""
    db = _get_db(db_path)
    try:
        all_events = db.get_upcoming_events(days=days)
        if priority:
            all_events = [e for e in all_events if e.priority == priority]

        events = [_format_event(e, days) for e in all_events]
        return JSONResponse(content=[e.model_dump() for e in events if e])
    finally:
        db.close()


@app.get("/api/stats")
async def api_stats(db_path: str = str(Path(__file__).parent.parent / "data" / "events.db")):
    """Get dashboard statistics."""
    db = _get_db(db_path)
    try:
        total = db.get_event_count()
        upcoming_7d = len(db.get_upcoming_events(days=7))
        upcoming_30d = len(db.get_upcoming_events(days=30))

        by_priority = {}
        for p in range(1, 6):
            count = len(db.get_events_by_priority(p))
            if count > 0:
                by_priority[str(p)] = count

        return DashboardStats(
            total_events=total,
            upcoming_7d=upcoming_7d,
            upcoming_30d=upcoming_30d,
            by_priority=by_priority,
        ).model_dump()
    finally:
        db.close()


@app.get("/api/events/today")
async def api_events_today(db_path: str = str(Path(__file__).parent.parent / "data" / "events.db")):
    """Get events happening today."""
    db = _get_db(db_path)
    try:
        all_events = db.get_upcoming_events(days=1)
        events = [_format_event(e, 1) for e in all_events]
        return JSONResponse(content=[e.model_dump() for e in events if e])
    finally:
        db.close()


# ─── HTML Dashboard ────────────────────────────────────────────────────────

def _get_dashboard_html():
    """Generate dashboard HTML."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Astronomical Events Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
        h1 {{ font-size: 2rem; margin-bottom: 0.5rem; background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .subtitle {{ color: #94a3b8; margin-bottom: 2rem; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
        .stat-card {{ background: #1e293b; border-radius: 12px; padding: 1.5rem; text-align: center; }}
        .stat-value {{ font-size: 2.5rem; font-weight: bold; color: #60a5fa; }}
        .stat-label {{ color: #94a3b8; margin-top: 0.5rem; }}
        .events-list {{ background: #1e293b; border-radius: 12px; overflow: hidden; }}
        .event-item {{ padding: 1.5rem; border-bottom: 1px solid #334155; display: flex; gap: 1rem; align-items: center; }}
        .event-item:last-child {{ border-bottom: none; }}
        .priority-badge {{ font-size: 2rem; min-width: 50px; text-align: center; }}
        .event-info {{ flex: 1; }}
        .event-title {{ font-weight: 600; margin-bottom: 0.25rem; }}
        .event-meta {{ color: #94a3b8; font-size: 0.9rem; }}
        .filter-bar {{ display: flex; gap: 1rem; margin-bottom: 1.5rem; align-items: center; }}
        select, button {{ background: #1e293b; color: #e2e8f0; border: 1px solid #475569; padding: 0.5rem 1rem; border-radius: 8px; cursor: pointer; }}
        select:hover, button:hover {{ border-color: #60a5fa; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔭 Astronomical Events Dashboard</h1>
        <p class="subtitle">Real-time monitoring of celestial events</p>

        <div class="stats-grid" id="stats"></div>

        <div class="filter-bar">
            <label>Days ahead:</label>
            <select id="daysFilter" onchange="loadEvents()">
                <option value="7">7 days</option>
                <option value="30" selected>30 days</option>
                <option value="90">90 days</option>
                <option value="365">1 year</option>
            </select>
            <label>P1 only:</label>
            <input type="checkbox" id="p1Filter" onchange="loadEvents()">
        </div>

        <div class="events-list" id="events"></div>
    </div>

    <script>
        async function loadStats() {{
            const res = await fetch('/api/stats');
            const data = await res.json();
            document.getElementById('stats').innerHTML = `
                <div class="stat-card"><div class="stat-value">{{data.total_events}}</div><div class="stat-label">Total Events</div></div>
                <div class="stat-card"><div class="stat-value">{{data.upcoming_7d}}</div><div class="stat-label">Next 7 Days</div></div>
                <div class="stat-card"><div class="stat-value">{{data.upcoming_30d}}</div><div class="stat-label">Next 30 Days</div></div>
            `;
        }}

        async function loadEvents() {{
            const days = document.getElementById('daysFilter').value;
            const p1Only = document.getElementById('p1Filter').checked;
            let url = `/api/events?days=${{days}}`;
            if (p1Only) url += '&priority=1';

            const res = await fetch(url);
            const events = await res.json();

            const sorted = events.sort((a, b) => new Date(a.event_date || '9999') - new Date(b.event_date || '9999'));

            document.getElementById('events').innerHTML = sorted.map(e => `
                <div class="event-item">
                    <div class="priority-badge">${{e.priority_emoji}}</div>
                    <div class="event-info">
                        <div class="event-title">${{e.title}}</div>
                        <div class="event-meta">${{e.time_label}} • P${{e.priority}} • ${{e.event_type}}${{e.visibility_label ? ' • ' + e.visibility_label : ''}}</div>
                    </div>
                </div>
            `).join('');
        }}

        loadStats();
        loadEvents();
    </script>
</body>
</html>"""


# ─── CLI Entry Point ────────────────────────────────────────────────────────

def cmd_dashboard(config: dict):
    """Start the web dashboard."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Web Dashboard")
    parser.add_argument("--port", type=int, default=8080, help="Port to run on (default: 8080)")
    args, _ = parser.parse_known_args()

    print(f"Starting dashboard at http://localhost:{args.port}")
    print("Press Ctrl+C to stop.")

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)
