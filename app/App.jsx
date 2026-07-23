/* ============================================================
   app/App.jsx
   Root component + mount. Owns every piece of cross-component state:
   theme, font, current date, active tab (main/curious), search +
   scope, category + time filters, read set, bookmarks, sources doc,
   page mode (digest / coverage). Wires Rail + DigestView together;
   swaps in CoveragePage when page === 'coverage'.

   Composes with:
     - app/styles-v3.css   (.app shell — two-column grid: rail + main-col)
     - app/Sources.jsx     (consumes flattenSources + CoveragePage)
     - app/Rail.jsx        (consumes Rail — left sidebar)
     - app/DigestView.jsx  (consumes DigestView + CATEGORIES — main column)
     - data/index.json     (input — ordered list of available digest dates)
     - data/sources.json   (input — newsletter registry, fed to Sources.jsx flattener)
     - data/<date>.json    (input — per-day digest, lazy-fetched + cached in allDigests)

   Persistence. Everything that survives reload lives in localStorage
   under dd.* keys: dd.theme, dd.font, dd.date, dd.read, dd.bookmarks,
   dd.scope, dd.tab. Each setter writes-through.

   Load order in index.html: this file is LAST among the four JSX
   scripts, because it consumes window.Rail / window.DigestView /
   window.CATEGORIES / window.flattenSources / window.CoveragePage from
   the other three.

   v4.x JSX — filename tracks major version only.
   ============================================================ */

/* global React, ReactDOM, Rail, DigestView, CATEGORIES, CoveragePage, flattenSources */
const { useState: useS, useEffect: useE, useMemo: useM } = React;

const LS_THEME = 'dd.theme';
const LS_FONT = 'dd.font';
const LS_DATE = 'dd.date';
const LS_READ = 'dd.read';
const LS_BM = 'dd.bookmarks';
const LS_SCOPE = 'dd.scope';
const LS_TAB = 'dd.tab';

function loadLS(k, fallback) {
  try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
}
function saveLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }

function stripHtml(s) {
  const tmp = document.createElement('div');
  tmp.innerHTML = s || '';
  return tmp.textContent || '';
}

function App() {
  const [allDates, setAllDates] = useS([]);
  const [currentDate, setCurrentDate] = useS(() => loadLS(LS_DATE, null));
  const [digest, setDigest] = useS(null);
  const [loading, setLoading] = useS(true);
  const [allDigests, setAllDigests] = useS({});

  const [theme, setThemeRaw] = useS(() => loadLS(LS_THEME, 'auto'));
  const setTheme = (v) => { setThemeRaw(v); saveLS(LS_THEME, v); };

  const [fontChoice, setFontChoiceRaw] = useS(() => loadLS(LS_FONT, 'fraunces'));
  const setFontChoice = (v) => { setFontChoiceRaw(v); saveLS(LS_FONT, v); };

  const [activeTab, setActiveTabRaw] = useS(() => loadLS(LS_TAB, 'main'));
  const setActiveTab = (v) => { setActiveTabRaw(v); saveLS(LS_TAB, v); window.scrollTo({ top: 0 }); };

  const [search, setSearch] = useS('');
  const [searchScope, setSearchScopeRaw] = useS(() => loadLS(LS_SCOPE, 'today'));
  const setSearchScope = (v) => { setSearchScopeRaw(v); saveLS(LS_SCOPE, v); };

  const [filters, setFilters] = useS(new Set());
  const [timeFilters, setTimeFilters] = useS(new Set());

  const [readSet, setReadSetRaw] = useS(() => new Set(loadLS(LS_READ, [])));
  const setReadSet = (s) => { setReadSetRaw(s); saveLS(LS_READ, [...s]); };

  const [bookmarks, setBookmarksRaw] = useS(() => loadLS(LS_BM, []));
  const setBookmarks = (list) => { setBookmarksRaw(list); saveLS(LS_BM, list); };

  const bookmarkSet = useM(() => new Set(bookmarks.map(b => b.id)), [bookmarks]);

  // Sources
  const [sourcesDoc, setSourcesDoc] = useS(null);
  const [page, setPage] = useS('digest'); // 'digest' | 'coverage'
  const [activeSourceFilter, setActiveSourceFilter] = useS(null);

  const { byName: sourcesByName, flat: sourcesFlat, tiers: sourceTiers } = useM(
    () => flattenSources(sourcesDoc),
    [sourcesDoc]
  );

  // Apply theme + font to <html>
  useE(() => {
    const root = document.documentElement;
    if (theme === 'auto') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
  }, [theme]);

  useE(() => {
    const root = document.documentElement;
    if (fontChoice === 'fraunces') root.removeAttribute('data-font');
    else root.setAttribute('data-font', fontChoice);
  }, [fontChoice]);

  // Load index
  useE(() => {
    fetch('data/index.json').then(r => r.json()).then(dates => {
      setAllDates(dates);
      if (!currentDate || !dates.includes(currentDate)) {
        const latest = dates[dates.length - 1];
        setCurrentDate(latest);
        saveLS(LS_DATE, latest);
      }
    }).catch(e => console.error('index load', e));
    fetch('data/sources.json').then(r => r.json()).then(setSourcesDoc).catch(e => console.error('sources load', e));
  }, []);

  // Load current digest
  useE(() => {
    if (!currentDate) return;
    setLoading(true);
    fetch(`data/${currentDate}.json`).then(r => r.json()).then(d => {
      setDigest(d);
      setAllDigests(prev => ({ ...prev, [currentDate]: d }));
      setLoading(false);
    }).catch(e => { console.error(e); setLoading(false); setDigest(null); });
  }, [currentDate]);

  // Preload all digests when needed (search all OR coverage page)
  useE(() => {
    const needAll = (searchScope === 'all' && search.length >= 2) || page === 'coverage';
    if (!needAll || !allDates.length) return;
    const missing = allDates.filter(d => !(d in allDigests));
    if (!missing.length) return;
    Promise.all(missing.map(d =>
      fetch(`data/${d}.json`).then(r => r.json()).then(j => [d, j]).catch(() => [d, null])
    )).then(pairs => {
      setAllDigests(prev => {
        const next = { ...prev };
        pairs.forEach(([d, j]) => { next[d] = j; });
        return next;
      });
    });
  }, [searchScope, allDates, page, search]);

  const onPick = (d) => {
    setCurrentDate(d);
    saveLS(LS_DATE, d);
    setSearchScope('today');
    setSearch('');
    setPage('digest');
    window.scrollTo({ top: 0 });
  };

  const onToggleRead = (id) => {
    const next = new Set(readSet);
    if (next.has(id)) next.delete(id); else next.add(id);
    setReadSet(next);
  };

  const onToggleBookmark = (id, item, section) => {
    if (bookmarkSet.has(id)) {
      setBookmarks(bookmarks.filter(b => b.id !== id));
    } else {
      const date = id.split(':')[0];
      setBookmarks([{ id, date, section, headline: stripHtml(item.headline), source: item.source, category: item.category }, ...bookmarks]);
    }
  };

  const onRemoveBookmark = (id) => setBookmarks(bookmarks.filter(b => b.id !== id));

  const onGoToBookmark = (b) => {
    setPage('digest');
    if (b.date !== currentDate) {
      setCurrentDate(b.date);
      saveLS(LS_DATE, b.date);
    }
    if (b.section && b.section !== activeTab) setActiveTabRaw(b.section);
    setTimeout(() => {
      const el = document.getElementById(`card-${b.id}`);
      if (el) {
        const top = el.getBoundingClientRect().top + window.scrollY - 20;
        window.scrollTo({ top, behavior: 'smooth' });
      }
    }, 400);
  };

  const onClearRead = () => setReadSet(new Set());

  const mainCount = digest?.main?.length || 0;
  const curiousCount = digest?.curious?.length || 0;

  return (
    <div className="app">
      <Rail
        allDates={allDates}
        currentDate={currentDate || ''}
        onPick={onPick}
        theme={theme} setTheme={setTheme}
        fontChoice={fontChoice} setFontChoice={setFontChoice}
        search={search} setSearch={setSearch}
        searchScope={searchScope} setSearchScope={setSearchScope}
        bookmarks={bookmarks}
        onGoToBookmark={onGoToBookmark}
        onRemoveBookmark={onRemoveBookmark}
        onClearRead={onClearRead}
        readCount={readSet.size}
        filters={filters} setFilters={setFilters}
        timeFilters={timeFilters} setTimeFilters={setTimeFilters}
        categories={CATEGORIES}
        activeTab={activeTab} setActiveTab={setActiveTab}
        mainCount={mainCount} curiousCount={curiousCount}
        sourcesDoc={sourcesDoc}
        sourcesFlat={sourcesFlat}
        onOpenCoverage={() => { setPage('coverage'); window.scrollTo({ top: 0 }); }}
        page={page}
      />
      {page === 'coverage' ? (
        <CoveragePage
          sourcesDoc={sourcesDoc}
          flat={sourcesFlat}
          tiers={sourceTiers}
          allDates={allDates}
          allDigests={allDigests}
          onClose={() => { setPage('digest'); window.scrollTo({ top: 0 }); }}
          onFilterSource={(name) => {
            setActiveSourceFilter(name);
            setPage('digest');
            setSearch(name);
            setSearchScope('today');
          }}
          activeSourceFilter={activeSourceFilter}
        />
      ) : loading ? (
        <div className="main-col"><div className="empty">Loading…</div></div>
      ) : (
        <DigestView
          digest={digest}
          date={currentDate}
          activeTab={activeTab}
          filters={filters} timeFilters={timeFilters}
          search={search} searchScope={searchScope}
          allDigests={allDigests}
          onPick={onPick}
          readSet={readSet} bookmarkSet={bookmarkSet}
          onToggleRead={onToggleRead} onToggleBookmark={onToggleBookmark}
          sourcesByName={sourcesByName}
          sourcesFlat={sourcesFlat}
        />
      )}
    </div>
  );
}

function mount() {
  ReactDOM.createRoot(document.getElementById('root')).render(<App />);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', mount);
} else {
  mount();
}
