#!/usr/bin/env python3
"""Generate daily newsletter digest HTML from JSON data files.

This is the minimalistic static-HTML renderer — the fallback artifact.
Live daily reading is via the SPA (index.html + app/). This script's outputs:

  summaries/daily-newsletter-summary-<date>.html  — static fallback (this file)
  data/index.json                                  — list of dates the SPA picks up
  data/sources.json                                — registry copy the SPA picks up
"""

import json
import shutil
import sys
import os
import re
from datetime import datetime

CATEGORIES = {
    "world_macro": {"name": "World & Macro", "tag_color": "#ef4444", "tag_class": "tag-world", "ts_bg": "rgba(239,68,68,0.15)", "ts_color": "var(--tag-world)", "priority": 1},
    "markets_investing": {"name": "Markets & Investing", "tag_color": "#f59e0b", "tag_class": "tag-finance", "ts_bg": "rgba(245,158,11,0.15)", "ts_color": "var(--tag-finance)", "priority": 2},
    "india_business": {"name": "India & Business", "tag_color": "#fb923c", "tag_class": "tag-india", "ts_bg": "rgba(251,146,60,0.15)", "ts_color": "var(--tag-india)", "priority": 3},
    "ai_tech": {"name": "AI & Technology", "tag_color": "#38bdf8", "tag_class": "tag-ai", "ts_bg": "rgba(56,189,248,0.15)", "ts_color": "var(--tag-ai)", "priority": 4},
    "deals_startups": {"name": "Deals & Startups", "tag_color": "#4ade80", "tag_class": "tag-deals", "ts_bg": "rgba(74,222,128,0.15)", "ts_color": "var(--tag-deals)", "priority": 5},
    "tax_compliance": {"name": "Tax & Compliance", "tag_color": "#f472b6", "tag_class": "tag-tax", "ts_bg": "rgba(244,114,182,0.15)", "ts_color": "var(--tag-tax)", "priority": 6},
    "career_learning": {"name": "Career & Learning", "tag_color": "#a78bfa", "tag_class": "tag-career", "ts_bg": "rgba(167,139,250,0.15)", "ts_color": "var(--tag-career)", "priority": 7},
    "sports_lifestyle": {"name": "Sports & Lifestyle", "tag_color": "#34d399", "tag_class": "tag-sports", "ts_bg": "rgba(52,211,153,0.15)", "ts_color": "var(--tag-sports)", "priority": 8},
    "uncategorized": {"name": "Uncategorized", "tag_color": "#64748b", "tag_class": "tag-uncategorized", "ts_bg": "rgba(100,116,139,0.15)", "ts_color": "#64748b", "priority": 9},
}

CSS = """:root {
      --bg: #0f1117;
      --card: #1a1d27;
      --border: #2a2d3a;
      --text: #e2e4ea;
      --muted: #8b8fa3;
      --accent: #6c8cff;
      --accent-dim: #3a4f8f;
      --tag-finance: #f59e0b;
      --tag-world: #ef4444;
      --tag-india: #fb923c;
      --tag-ai: #38bdf8;
      --tag-tax: #f472b6;
      --tag-deals: #4ade80;
      --tag-career: #a78bfa;
      --tag-sports: #34d399;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 0;
    }
    .header {
      background: linear-gradient(135deg, #1a1d27 0%, #232740 100%);
      border-bottom: 1px solid var(--border);
      padding: 40px 24px 32px;
      text-align: center;
    }
    .header h1 { font-size: 1.8rem; font-weight: 700; letter-spacing: -0.5px; margin-bottom: 6px; }
    .header .date { font-size: 0.95rem; color: var(--muted); margin-bottom: 16px; }
    .stats { display: flex; justify-content: center; gap: 32px; flex-wrap: wrap; }
    .stat .num { font-size: 1.6rem; font-weight: 700; color: var(--accent); }
    .stat .label { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
    .container { max-width: 880px; margin: 0 auto; padding: 28px 20px; }
    .tab-bar { display: flex; gap: 8px; margin-bottom: 28px; }
    .tab-btn {
      padding: 10px 24px; border-radius: 8px; font-size: 0.8rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: 1.5px; cursor: pointer;
      border: 2px solid transparent; transition: all 0.2s; display: flex; align-items: center; gap: 8px;
    }
    .tab-btn .badge { font-size: 0.7rem; font-weight: 700; padding: 1px 7px; border-radius: 10px; min-width: 20px; text-align: center; }
    .tab-btn.main-btn { background: rgba(108,140,255,0.1); color: #6c8cff; border-color: rgba(108,140,255,0.3); }
    .tab-btn.main-btn.active { background: rgba(108,140,255,0.2); border-color: #6c8cff; }
    .tab-btn.main-btn .badge { background: rgba(108,140,255,0.25); color: #6c8cff; }
    .tab-btn.curious-btn { background: rgba(167,139,250,0.1); color: #a78bfa; border-color: rgba(167,139,250,0.3); }
    .tab-btn.curious-btn.active { background: rgba(167,139,250,0.2); border-color: #a78bfa; }
    .tab-btn.curious-btn .badge { background: rgba(167,139,250,0.25); color: #a78bfa; }
    .tab-btn:not(.active) { opacity: 0.55; }
    .tab-btn:not(.active):hover { opacity: 0.8; }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    .tab-desc { font-size: 0.78rem; color: var(--muted); margin-bottom: 20px; }
    .top-stories {
      background: linear-gradient(135deg, rgba(108,140,255,0.08) 0%, rgba(108,140,255,0.03) 100%);
      border: 1px solid var(--accent-dim); border-radius: 12px; padding: 24px 28px; margin-bottom: 32px;
    }
    .top-stories.curious-stories {
      border-color: rgba(167,139,250,0.4);
      background: linear-gradient(135deg, rgba(167,139,250,0.08) 0%, rgba(167,139,250,0.03) 100%);
    }
    .top-stories h2 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1.5px; color: var(--accent); margin-bottom: 14px; }
    .top-stories.curious-stories h2 { color: #a78bfa; }
    .top-stories ul { list-style: none; }
    .top-stories li { padding: 6px 0; font-size: 0.92rem; border-bottom: 1px solid rgba(255,255,255,0.04); display: flex; align-items: baseline; gap: 10px; }
    .top-stories li:last-child { border-bottom: none; }
    .top-stories .ts-tag { font-size: 0.6rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; padding: 2px 7px; border-radius: 3px; white-space: nowrap; flex-shrink: 0; }
    .top-stories .ts-text b { color: #fff; }
    .section-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 2px; color: var(--muted); margin: 36px 0 16px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 24px 28px; margin-bottom: 16px; transition: border-color 0.2s; }
    .card:hover { border-color: var(--accent-dim); }
    .card-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 10px; }
    .source { font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; display: flex; align-items: center; gap: 8px; }
    .arrival-time { font-size: 0.65rem; color: var(--accent); font-weight: 600; text-transform: none; letter-spacing: 0; opacity: 0.8; }
    .tag { display: inline-block; padding: 2px 9px; border-radius: 20px; font-size: 0.65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; }
    .tag-world { background: rgba(239,68,68,0.12); color: var(--tag-world); }
    .tag-finance { background: rgba(245,158,11,0.12); color: var(--tag-finance); }
    .tag-india { background: rgba(251,146,60,0.12); color: var(--tag-india); }
    .tag-ai { background: rgba(56,189,248,0.12); color: var(--tag-ai); }
    .tag-tax { background: rgba(244,114,182,0.12); color: var(--tag-tax); }
    .tag-deals { background: rgba(74,222,128,0.12); color: var(--tag-deals); }
    .tag-career { background: rgba(167,139,250,0.12); color: var(--tag-career); }
    .tag-sports { background: rgba(52,211,153,0.12); color: var(--tag-sports); }
    .tag-uncategorized { background: rgba(100,116,139,0.12); color: #64748b; }
    .headline { font-size: 1.1rem; font-weight: 600; margin-bottom: 4px; line-height: 1.35; }
    .one-liner { font-size: 0.88rem; color: var(--muted); margin-bottom: 14px; font-style: italic; }
    .bullets { list-style: none; padding: 0; margin: 0; }
    .bullets li { padding: 5px 0 5px 18px; font-size: 0.9rem; position: relative; line-height: 1.5; border-bottom: 1px solid rgba(255,255,255,0.03); }
    .bullets li:last-child { border-bottom: none; }
    .bullets li::before { content: '\\25B8'; position: absolute; left: 0; color: var(--accent); font-size: 0.8rem; }
    .bullets li b { color: #fff; font-weight: 600; }
    .bullets li .num { color: var(--accent); font-weight: 700; }
    .so-what { margin-top: 12px; padding: 10px 16px; background: rgba(108,140,255,0.05); border-left: 3px solid var(--accent); border-radius: 0 6px 6px 0; font-size: 0.84rem; color: var(--muted); }
    .so-what b { color: var(--accent); font-weight: 600; }
    /* Hybrid C and Flavor 1 (roundup cards) */
    .card.hybrid-c .top-picks, .card.flavor-1 .top-picks { list-style: none; padding: 0; margin: 0 0 16px 0; }
    .card.hybrid-c .pick, .card.flavor-1 .pick { padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
    .card.hybrid-c .pick:last-child, .card.flavor-1 .pick:last-child { border-bottom: none; }
    .pick-headline { font-weight: 600; font-size: 0.96rem; color: #fff; margin-bottom: 4px; line-height: 1.35; }
    .pick-synthesis { font-size: 0.88rem; color: var(--text); line-height: 1.5; }
    .pick-link, .tail-link { color: var(--accent); text-decoration: none; font-size: 0.8rem; opacity: 0.6; margin-left: 4px; }
    .pick-link:hover, .tail-link:hover { opacity: 1; }
    .tail-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1.5px; color: var(--muted); margin: 18px 0 8px; padding-top: 14px; border-top: 1px solid var(--border); }
    .card.hybrid-c .tail { list-style: none; padding: 0; margin: 0; }
    .tail-item { padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.03); }
    .tail-item:last-child { border-bottom: none; }
    .tail-headline { font-size: 0.9rem; font-weight: 500; color: var(--text); margin-bottom: 3px; line-height: 1.4; }
    .tail-teaser { font-size: 0.82rem; color: var(--muted); font-style: italic; margin-bottom: 3px; line-height: 1.45; }
    .tail-addendum { font-size: 0.84rem; color: var(--text); padding-left: 4px; line-height: 1.45; }
    .tail-addendum::before { content: '\\25B8'; color: var(--accent); margin-right: 6px; }
    .empty-tab { text-align: center; padding: 60px 20px; color: var(--muted); }
    .empty-tab h3 { font-size: 1.1rem; color: var(--text); margin-bottom: 12px; font-weight: 600; }
    .empty-tab p { font-size: 0.88rem; max-width: 480px; margin: 0 auto 8px; }
    .tab-btn.registry-btn { background: rgba(74,222,128,0.1); color: #4ade80; border-color: rgba(74,222,128,0.3); }
    .tab-btn.registry-btn.active { background: rgba(74,222,128,0.2); border-color: #4ade80; }
    .tab-btn.registry-btn .badge { background: rgba(74,222,128,0.25); color: #4ade80; }
    .registry-section { margin-bottom: 36px; }
    .registry-section h3 { font-size: 0.85rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
    .registry-section h3.main-heading { color: #6c8cff; }
    .registry-section h3.curious-heading { color: #a78bfa; }
    .registry-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    .registry-table th { text-align: left; padding: 10px 14px; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); border-bottom: 2px solid var(--border); }
    .registry-table td { padding: 9px 14px; border-bottom: 1px solid rgba(255,255,255,0.04); }
    .registry-table tr:hover td { background: rgba(255,255,255,0.02); }
    .registry-table .freq { color: var(--muted); font-size: 0.8rem; }
    .time-divider {
      display: flex; align-items: center; gap: 10px;
      margin: 32px 0 20px; padding: 14px 20px;
      border-radius: 10px; font-size: 0.85rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: 1.2px;
    }
    .time-divider .time-icon { font-size: 1.1rem; }
    .time-divider .time-range { font-size: 0.68rem; font-weight: 400; opacity: 0.7; text-transform: none; letter-spacing: 0; }
    .time-divider .time-count {
      margin-left: auto; font-size: 0.7rem; font-weight: 700;
      padding: 2px 10px; border-radius: 10px; min-width: 24px; text-align: center;
    }
    .today-divider {
      background: linear-gradient(135deg, rgba(108,140,255,0.12) 0%, rgba(56,189,248,0.08) 100%);
      border: 1px solid rgba(108,140,255,0.3); color: #6c8cff;
    }
    .today-divider .time-count { background: rgba(108,140,255,0.2); color: #6c8cff; }
    .yesterday-divider {
      background: linear-gradient(135deg, rgba(139,143,163,0.08) 0%, rgba(139,143,163,0.04) 100%);
      border: 1px solid rgba(139,143,163,0.2); color: var(--muted);
    }
    .yesterday-divider .time-count { background: rgba(139,143,163,0.15); color: var(--muted); }
    .footer { text-align: center; padding: 32px 20px; color: var(--muted); font-size: 0.75rem; border-top: 1px solid var(--border); margin-top: 32px; }"""


def render_card(nl):
    """Dispatch to appropriate renderer based on card_type. Default = single-card (existing layout)."""
    card_type = nl.get("card_type", "single")
    if card_type == "hybrid_c":
        return render_card_hybrid_c(nl)
    if card_type == "flavor_1":
        return render_card_flavor_1(nl)
    cat = CATEGORIES[nl["category"]]
    tag_label = cat["name"].split(" & ")[0] if "&" in cat["name"] else cat["name"].split(" ")[0]
    arrival = nl.get("arrival_ist", "")
    arrival_html = f' <span class="arrival-time">{arrival}</span>' if arrival else ''
    html = f'''    <div class="card">
      <div class="card-top">
        <span class="source">{nl["source"]}{arrival_html}</span>
        <span class="tag {cat["tag_class"]}">{tag_label}</span>
      </div>
      <div class="headline">{nl["headline"]}</div>
      <div class="one-liner">{nl["one_liner"]}</div>
      <ul class="bullets">
'''
    for b in nl["bullets"]:
        html += f'        <li>{b}</li>\n'
    html += '      </ul>\n'
    if nl.get("so_what"):
        html += f'      <div class="so-what"><b>So what:</b> {nl["so_what"]}</div>\n'
    html += '    </div>\n'
    return html


def render_card_hybrid_c(nl):
    """Render Hybrid C roundup card: Top picks block + Also-in-this-email tail block."""
    cat = CATEGORIES[nl["category"]]
    tag_label = cat["name"].split(" & ")[0] if "&" in cat["name"] else cat["name"].split(" ")[0]
    arrival = nl.get("arrival_ist", "")
    arrival_html = f' <span class="arrival-time">{arrival}</span>' if arrival else ''
    html = f'''    <div class="card hybrid-c">
      <div class="card-top">
        <span class="source">{nl["source"]}{arrival_html}</span>
        <span class="tag {cat["tag_class"]}">{tag_label}</span>
      </div>
      <div class="headline">{nl["headline"]}</div>
      <div class="one-liner">{nl["one_liner"]}</div>
      <ul class="top-picks">
'''
    for pick in nl.get("top_picks", []):
        link_html = f' <a class="pick-link" href="{pick["link"]}" target="_blank">[link]</a>' if pick.get("link") else ''
        tagged_author = pick.get("tagged_author", "")
        author_prefix = f'<b>{tagged_author}</b> ' if tagged_author else ''
        html += f'''        <li class="pick">
          <div class="pick-headline">&#9733; {pick["headline"]}{link_html}</div>
          <div class="pick-synthesis">{author_prefix}{pick["synthesis"]}</div>
        </li>
'''
    html += '      </ul>\n'
    tail = nl.get("tail", [])
    if tail:
        html += '      <div class="tail-label">Also in this email</div>\n      <ul class="tail">\n'
        for item in tail:
            link_html = f' <a class="tail-link" href="{item["link"]}" target="_blank">[link]</a>' if item.get("link") else ''
            html += f'        <li class="tail-item">\n'
            html += f'          <div class="tail-headline">{item["headline"]}{link_html}</div>\n'
            if item.get("teaser"):
                html += f'          <div class="tail-teaser">{item["teaser"]}</div>\n'
            if item.get("addendum"):
                html += f'          <div class="tail-addendum">{item["addendum"]}</div>\n'
            html += '        </li>\n'
        html += '      </ul>\n'
    if nl.get("so_what"):
        html += f'      <div class="so-what"><b>So what:</b> {nl["so_what"]}</div>\n'
    html += '    </div>\n'
    return html


def render_card_flavor_1(nl):
    """Render Ken Flavor 1 roundup card: all stories deep, no tail."""
    cat = CATEGORIES[nl["category"]]
    tag_label = cat["name"].split(" & ")[0] if "&" in cat["name"] else cat["name"].split(" ")[0]
    arrival = nl.get("arrival_ist", "")
    arrival_html = f' <span class="arrival-time">{arrival}</span>' if arrival else ''
    html = f'''    <div class="card flavor-1">
      <div class="card-top">
        <span class="source">{nl["source"]}{arrival_html}</span>
        <span class="tag {cat["tag_class"]}">{tag_label}</span>
      </div>
      <div class="headline">{nl["headline"]}</div>
      <div class="one-liner">{nl["one_liner"]}</div>
      <ul class="top-picks">
'''
    for story in nl.get("stories", []):
        link_html = f' <a class="pick-link" href="{story["link"]}" target="_blank">[link]</a>' if story.get("link") else ''
        author = story.get("author", "")
        author_prefix = f'<b>By {author}:</b> ' if author else ''
        html += f'''        <li class="pick">
          <div class="pick-headline">&#9733; {story["headline"]}{link_html}</div>
          <div class="pick-synthesis">{author_prefix}{story["synthesis"]}</div>
        </li>
'''
    html += '      </ul>\n'
    if nl.get("so_what"):
        html += f'      <div class="so-what"><b>So what:</b> {nl["so_what"]}</div>\n'
    html += '    </div>\n'
    return html


def render_top_stories(newsletters, is_curious=False):
    cls = ' curious-stories' if is_curious else ''
    stories = newsletters[:5]
    html = f'    <div class="top-stories{cls}">\n      <h2>Top Stories</h2>\n      <ul>\n'
    for nl in stories:
        cat = CATEGORIES[nl["category"]]
        tag_label = cat["name"].split(" & ")[0] if "&" in cat["name"] else cat["name"].split(" ")[0]
        headline_bold = nl["headline"].split(" — ")[0] if " — " in nl["headline"] else nl["headline"]
        rest = nl["one_liner"]
        html += f'''        <li>
          <span class="ts-tag" style="background:{cat["ts_bg"]};color:{cat["ts_color"]};">{tag_label}</span>
          <span class="ts-text"><b>{headline_bold}</b> &mdash; {rest}</span>
        </li>
'''
    html += '      </ul>\n    </div>\n'
    return html


def parse_arrival_hour(arrival_ist):
    """Parse arrival_ist string (e.g., '3:31 AM', '7:45 PM') to 24h hour. Returns None if unparseable."""
    if not arrival_ist:
        return None
    try:
        t = datetime.strptime(arrival_ist.strip(), "%I:%M %p")
        return t.hour + t.minute / 60.0
    except ValueError:
        try:
            t = datetime.strptime(arrival_ist.strip(), "%I:%M%p")
            return t.hour + t.minute / 60.0
        except ValueError:
            return None


def is_today_email(nl):
    """Return True if email arrived 'today' (12:00 AM - 5:29 AM IST), False for 'yesterday' (5:30 AM - 11:59 PM IST)."""
    arrival = nl.get("arrival_ist")
    if not arrival:
        return False
    hour = parse_arrival_hour(arrival)
    if hour is None:
        return False
    return hour < 5.5


def render_section_cards(newsletters, is_curious=False, show_top_stories=False):
    """Render category-grouped cards for a list of newsletters, optionally with Top Stories."""
    if not newsletters:
        return ''
    html = ''
    if show_top_stories and len(newsletters) >= 2:
        html += render_top_stories(newsletters, is_curious)
    by_cat = {}
    for nl in newsletters:
        cat = nl["category"]
        by_cat.setdefault(cat, []).append(nl)
    sorted_cats = sorted(by_cat.keys(), key=lambda c: (-len(by_cat[c]), CATEGORIES[c]["priority"]))
    for cat_id in sorted_cats:
        cat = CATEGORIES[cat_id]
        html += f'\n    <div class="section-label">{cat["name"]}</div>\n\n'
        for nl in by_cat[cat_id]:
            html += render_card(nl)
    return html


def render_tab(newsletters, is_curious=False):
    if not newsletters:
        label = "forwarded" if is_curious else ""
        return f'''    <div class="empty-tab">
      <h3>No {label} newsletters today</h3>
      <p>No newsletters were received for this tab on this date.</p>
    </div>
'''
    today_nls = [nl for nl in newsletters if is_today_email(nl)]
    yesterday_nls = [nl for nl in newsletters if not is_today_email(nl)]

    has_arrival_data = any(nl.get("arrival_ist") for nl in newsletters)

    if not has_arrival_data:
        by_cat = {}
        for nl in newsletters:
            cat = nl["category"]
            by_cat.setdefault(cat, []).append(nl)
        sorted_cats = sorted(by_cat.keys(), key=lambda c: (-len(by_cat[c]), CATEGORIES[c]["priority"]))
        html = render_top_stories(newsletters, is_curious)
        for cat_id in sorted_cats:
            cat = CATEGORIES[cat_id]
            html += f'\n    <div class="section-label">{cat["name"]}</div>\n\n'
            for nl in by_cat[cat_id]:
                html += render_card(nl)
        return html

    html = ''

    if today_nls:
        html += f'\n    <div class="time-divider today-divider"><span class="time-icon">&#127769;</span> Today &middot; Overnight <span class="time-range">12:00 AM &ndash; 5:29 AM IST</span> <span class="time-count">{len(today_nls)}</span></div>\n'
        html += render_section_cards(today_nls, is_curious, show_top_stories=True)

    if yesterday_nls:
        html += f'\n    <div class="time-divider yesterday-divider"><span class="time-icon">&#128240;</span> Yesterday <span class="time-range">5:30 AM &ndash; 11:59 PM IST</span> <span class="time-count">{len(yesterday_nls)}</span></div>\n'
        html += render_section_cards(yesterday_nls, is_curious, show_top_stories=True)

    return html


def load_registry():
    """Load newsletter registry from config folder."""
    registry_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "newsletter-registry.json")
    if not os.path.exists(registry_path):
        return None
    with open(registry_path, 'r') as f:
        return json.load(f)


def render_registry_table(sources, heading_class="main-heading"):
    """Render a table of newsletter sources."""
    sorted_sources = sorted(sources, key=lambda s: (CATEGORIES.get(s["category"], {}).get("priority", 99), s["name"]))

    html = '    <table class="registry-table">\n'
    html += '      <thead><tr><th>#</th><th>Source</th><th>Category</th><th>Frequency</th></tr></thead>\n'
    html += '      <tbody>\n'
    for i, src in enumerate(sorted_sources, 1):
        cat = CATEGORIES.get(src["category"], CATEGORIES["uncategorized"])
        tag_label = cat["name"]
        freq = src.get("frequency", "—").replace("_", " ").title()
        html += f'      <tr><td>{i}</td><td>{src["name"]}</td>'
        html += f'<td><span class="tag {cat["tag_class"]}">{tag_label}</span></td>'
        html += f'<td class="freq">{freq}</td></tr>\n'
    html += '      </tbody>\n    </table>\n'
    return html


def render_reading_list():
    """Render the Reading List tab from the live registry."""
    registry = load_registry()
    if not registry:
        return '    <div class="empty-tab"><h3>Registry not found</h3><p>newsletter-registry.json missing from config folder.</p></div>\n'

    main_sources = []
    for tier_key in ["tier1_daily", "tier2_near_daily", "tier3_weekly", "substack_long_reads"]:
        tier = registry.get("newsletters", {}).get(tier_key, {})
        for src in tier.get("sources", []):
            if src.get("include", True):
                main_sources.append(src)

    curious_sources = []
    fwd_tier = registry.get("newsletters", {}).get("forwarded_secondary", {})
    for src in fwd_tier.get("sources", []):
        if src.get("include", True):
            curious_sources.append(src)

    html = f'''    <div class="registry-section">
      <h3 class="main-heading">MAIN &mdash; main mailbox ({len(main_sources)} sources)</h3>
{render_registry_table(main_sources, "main-heading")}
    </div>

    <div class="registry-section">
      <h3 class="curious-heading">CURIOUS &mdash; secondary mailbox, forwarded into main ({len(curious_sources)} sources)</h3>
{render_registry_table(curious_sources, "curious-heading")}
    </div>
'''
    return html


def generate(data):
    main_nls = data["main"]
    curious_nls = data["curious"]
    total = len(main_nls) + len(curious_nls)
    sources = len(set(nl["source"] for nl in main_nls + curious_nls))
    read_time = max(total, 5)
    reading_list_html = render_reading_list()
    registry = load_registry()
    main_count = sum(len(registry.get("newsletters", {}).get(t, {}).get("sources", [])) for t in ["tier1_daily", "tier2_near_daily", "tier3_weekly", "substack_long_reads"]) if registry else 0
    curious_count = len(registry.get("newsletters", {}).get("forwarded_secondary", {}).get("sources", [])) if registry else 0
    registry_total = main_count + curious_count

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Daily Briefing &mdash; {data["date_display"]}</title>
  <style>
    {CSS}
  </style>
</head>
<body>

<div class="header">
  <h1>Your Daily Briefing</h1>
  <div class="date">{data["day"]}, {data["date_display"]}</div>
  <div class="stats">
    <div class="stat"><div class="num">{total}</div><div class="label">Newsletters</div></div>
    <div class="stat"><div class="num">{sources}</div><div class="label">Sources</div></div>
    <div class="stat"><div class="num">~{read_time}</div><div class="label">Min Read</div></div>
  </div>
</div>

<div class="container">

  <div class="tab-bar">
    <div class="tab-btn main-btn active" onclick="switchTab('main')">
      MAIN <span class="badge">{len(main_nls)}</span>
    </div>
    <div class="tab-btn curious-btn" onclick="switchTab('curious')">
      CURIOUS <span class="badge">{len(curious_nls)}</span>
    </div>
    <div class="tab-btn registry-btn" onclick="switchTab('registry')">
      READING LIST <span class="badge">{registry_total}</span>
    </div>
  </div>

  <div id="tab-main" class="tab-content active">
    <div class="tab-desc">Direct subscriptions &middot; main mailbox</div>
{render_tab(main_nls, is_curious=False)}
  </div>

  <div id="tab-curious" class="tab-content">
    <div class="tab-desc">Secondary mailbox (optional) &middot; newsletters forwarded into the main mailbox</div>
{render_tab(curious_nls, is_curious=True)}
  </div>

  <div id="tab-registry" class="tab-content">
    <div class="tab-desc">Approved newsletter sources &middot; Updated dynamically</div>
{reading_list_html}
  </div>

</div>

<div class="footer">
  <p>Generated from {total} newsletters &middot; {data["date_display"]}</p>
</div>

<script>
function switchTab(tab) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
  document.querySelector('.' + tab + '-btn').classList.add('active');
}}
</script>

</body>
</html>'''
    return html


# ---- SPA runtime indices (in addition to static HTML fallback) ----------

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}\.json$')


def update_runtime_indices():
    """Write data/index.json and data/sources.json so the SPA runtime can load.
    Called on every digest generation so the index list stays fresh."""
    base = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base, "data")

    # index.json — sorted list of YYYY-MM-DD strings derived from data/*.json filenames
    dates = sorted(
        f[:-5] for f in os.listdir(data_dir)
        if DATE_RE.match(f)
    )
    index_path = os.path.join(data_dir, "index.json")
    with open(index_path, 'w') as f:
        json.dump(dates, f, separators=(',', ':'))

    # sources.json — verbatim copy of config/newsletter-registry.json
    registry_path = os.path.join(base, "config", "newsletter-registry.json")
    sources_path = os.path.join(data_dir, "sources.json")
    if os.path.exists(registry_path):
        shutil.copyfile(registry_path, sources_path)

    return len(dates)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 generate_digest.py <data.json>")
        sys.exit(1)

    with open(sys.argv[1], 'r') as f:
        data = json.load(f)

    html = generate(data)
    base = os.path.dirname(os.path.abspath(__file__))
    outdir = os.path.join(base, "summaries")
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, f"daily-newsletter-summary-{data['date_file']}.html")
    with open(outpath, 'w') as f:
        f.write(html)

    n_dates = update_runtime_indices()

    size = os.path.getsize(outpath)
    print(f"Generated {outpath} ({size:,} bytes)")
    print(f"Updated data/index.json ({n_dates} dates) and data/sources.json")
