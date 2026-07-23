/* ============================================================
   app/Rail.jsx
   Left sidebar: brand, theme + font radio rows, Main/Curious tabs,
   search box, time-of-day chips, category chips, recent editions,
   reading list (bookmarks), and the Sources & Coverage entry point.

   Composes with:
     - app/styles-v3.css   (.rail, .rail-tabs, .rail-tab, .theme-row, .cat-chips, .time-chips, .search-box, .rail-list, .rail-btn tokens)
     - app/Sources.jsx     (consumes SourcesRailPanel — sources summary + newly-added list inside the rail)
     - app/App.jsx         (parent — wires every prop on Rail; owns theme/font/search/filters/bookmarks/tab state)

   Pure presentational component — no state of its own, no fetch, no
   localStorage. All state lifts to App; Rail receives values + setters
   as props. Component name normName collisions are dodged via local
   useM2 alias on useMemo.

   v4.x JSX — filename tracks major version only.
   ============================================================ */

/* global React, SourcesRailPanel */
const { useMemo: useM2 } = React;

const MONTHS2 = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const DOWs = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

function fmtDay2(iso) {
  const d = new Date(iso + 'T00:00:00');
  return MONTHS2[d.getMonth()] + ' ' + d.getDate();
}

const TIMES = [
  { id: 'morning', label: 'Morning' },
  { id: 'afternoon', label: 'Afternoon' },
  { id: 'evening', label: 'Evening' },
  { id: 'latenight', label: 'Late' },
];

function Rail({
  allDates, currentDate, onPick,
  theme, setTheme, fontChoice, setFontChoice,
  search, setSearch, searchScope, setSearchScope,
  bookmarks, onGoToBookmark, onRemoveBookmark,
  onClearRead, readCount,
  filters, setFilters, categories,
  timeFilters, setTimeFilters,
  activeTab, setActiveTab,
  mainCount, curiousCount,
  sourcesDoc, sourcesFlat, onOpenCoverage, page,
}) {
  const recent = useM2(() => allDates.slice().sort().reverse().slice(0, 10), [allDates]);
  const total = allDates.length;

  return (
    <aside className="rail">
      <div className="brand">
        <span className="mark">Digest</span>
        <span className="sub">v1.0</span>
      </div>
      <div className="owner">personal edition · {total} editions</div>

      {/* Theme + font */}
      <div className="theme-row" role="radiogroup" aria-label="Color theme">
        <button role="radio" aria-checked={theme==='auto'} className={theme==='auto'?'on':''} onClick={()=>setTheme('auto')}>Auto</button>
        <button role="radio" aria-checked={theme==='light'} className={theme==='light'?'on':''} onClick={()=>setTheme('light')}>Light</button>
        <button role="radio" aria-checked={theme==='dark'} className={theme==='dark'?'on':''} onClick={()=>setTheme('dark')}>Dark</button>
      </div>
      <div className="theme-row" role="radiogroup" aria-label="Headline font">
        <button role="radio" aria-checked={fontChoice==='fraunces'} className={fontChoice==='fraunces'?'on':''} onClick={()=>setFontChoice('fraunces')}>Fraunces</button>
        <button role="radio" aria-checked={fontChoice==='trebuchet'} className={fontChoice==='trebuchet'?'on':''} onClick={()=>setFontChoice('trebuchet')}>Trebuchet</button>
      </div>

      {/* PRIMARY TABS: MAIN / CURIOUS (only visible on digest page) */}
      {page === 'digest' && (
        <>
          <h3 style={{ marginTop: 20 }}>View</h3>
          <div className="rail-tabs" role="tablist" aria-label="Digest view">
            <button
              role="tab"
              aria-selected={activeTab === 'main'}
              className={`rail-tab ${activeTab === 'main' ? 'on' : ''}`}
              onClick={() => setActiveTab('main')}
            >
              <span className="t-label">Main</span>
              <span className="t-sub">main mailbox</span>
              <span className="t-count" aria-label={`${mainCount} items`}>{mainCount}</span>
            </button>
            <button
              role="tab"
              aria-selected={activeTab === 'curious'}
              className={`rail-tab ${activeTab === 'curious' ? 'on' : ''}`}
              onClick={() => setActiveTab('curious')}
            >
              <span className="t-label">Curious</span>
              <span className="t-sub">secondary mailbox · forwarded to main</span>
              <span className="t-count" aria-label={`${curiousCount} items`}>{curiousCount}</span>
            </button>
          </div>
        </>
      )}

      <h3>Search</h3>
      <input
        type="text"
        className="search-box"
        placeholder="headline, source, keyword…"
        value={search}
        onChange={e => setSearch(e.target.value)}
      />
      <div className="search-scope">
        Scope:{' '}
        <button onClick={() => setSearchScope(searchScope === 'today' ? 'all' : 'today')}>
          {searchScope === 'today' ? 'today only' : `all ${total} editions`}
        </button>
      </div>

      <h3>Time of day</h3>
      <div className="time-chips" role="group" aria-label="Filter by time of day">
        {TIMES.map(t => {
          const on = timeFilters.has(t.id);
          return (
            <button key={t.id} aria-pressed={on} className={on?'on':''} onClick={() => {
              const next = new Set(timeFilters);
              if (on) next.delete(t.id); else next.add(t.id);
              setTimeFilters(next);
            }}>{t.label}</button>
          );
        })}
      </div>

      <h3>Category</h3>
      <div className="cat-chips" role="group" aria-label="Filter by category">
        {categories.map(c => {
          const on = filters.has(c.id);
          return (
            <button key={c.id} aria-pressed={on} className={on?'on':''} onClick={() => {
              const next = new Set(filters);
              if (on) next.delete(c.id); else next.add(c.id);
              setFilters(next);
            }}>{c.name}</button>
          );
        })}
      </div>

      <h3>Recent editions</h3>
      <ul className="rail-list" role="list">
        {recent.map(d => {
          const dt = new Date(d + 'T00:00:00');
          const isCurrent = d === currentDate;
          return (
            <li key={d} onClick={() => onPick(d)} className={isCurrent ? 'on' : ''} aria-current={isCurrent ? 'page' : undefined}>
              <span>{fmtDay2(d)}</span>
              <span className="k">{DOWs[dt.getDay()]}</span>
            </li>
          );
        })}
      </ul>

      <h3>Reading list {bookmarks.length > 0 && `· ${bookmarks.length}`}</h3>
      {bookmarks.length === 0 ? (
        <div style={{ fontFamily:'var(--font-mono)', fontSize:'0.62rem', color:'var(--ink-4)', padding:'4px 0', lineHeight:1.5 }}>
          Star any card to save it here.
        </div>
      ) : (
        <ul className="rail-list tall">
          {bookmarks.map(b => (
            <li key={b.id} onClick={() => onGoToBookmark(b)} title={b.headline}>
              <span style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', maxWidth:'150px' }}>{b.headline}</span>
              <span
                className="k"
                role="button"
                tabIndex={0}
                aria-label={`Remove ${b.headline} from reading list`}
                onClick={(e) => { e.stopPropagation(); onRemoveBookmark(b.id); }}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); onRemoveBookmark(b.id); } }}
                style={{ cursor:'pointer' }}
                title="Remove"
              >×</span>
            </li>
          ))}
        </ul>
      )}

      {/* Sources & Coverage */}
      <div style={{ marginTop: 14 }}>
        {sourcesDoc && (
          <SourcesRailPanel
            sourcesDoc={sourcesDoc}
            flat={sourcesFlat}
            onOpenCoverage={onOpenCoverage}
          />
        )}
      </div>

      {readCount > 0 && (
        <div style={{ marginTop: 16 }}>
          <button className="rail-btn" onClick={onClearRead}>Clear {readCount} read</button>
        </div>
      )}

      <div style={{ flex:1 }} />
      <div style={{ fontFamily:'var(--font-mono)', fontSize:'0.52rem', color:'var(--ink-4)', letterSpacing:'0.1em', paddingTop:14, textTransform:'uppercase' }}>
        Local · no server · JSON in /data/
      </div>
    </aside>
  );
}

window.Rail = Rail;
