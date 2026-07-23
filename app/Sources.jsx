/* ============================================================
   app/Sources.jsx
   Source registry, tier dots, hover tooltip, rail panel, and the
   full Coverage page (14-day grid across all newsletters).

   Composes with:
     - app/styles-v3.css   (.src-chip, .src-tip, .cov-grid, .rail-btn, .cov-stat, .cov-row tokens)
     - app/Rail.jsx        (consumes SourcesRailPanel + TIER_DOT + TierDot)
     - app/DigestView.jsx  (consumes lookupSource + SourceTooltip + TierDot via SourceChip)
     - app/App.jsx         (consumes flattenSources + CoveragePage + sourcesByName/flat)
     - data/sources.json   (input — newsletters keyed by tier; categories list)

   Load order in index.html: this file is FIRST among the four JSX
   scripts, because its window.* exports (flattenSources, lookupSource,
   normName, TierDot, TIER_DOT, SourceTooltip, SourcesRailPanel,
   CoveragePage) are consumed by Rail.jsx, DigestView.jsx, and App.jsx.

   v4.x JSX — filename tracks major version only. Style class names
   match app/styles-v3.css (the v3 design language; v4 was a
   markup-only pass, CSS untouched).
   ============================================================ */

/* global React */
const { useState: useSS, useMemo: useSM } = React;

// ---- Flatten sources.json into a lookup ----
function flattenSources(sourcesDoc) {
  if (!sourcesDoc || !sourcesDoc.newsletters) return { byName: {}, flat: [], tiers: [] };
  const tiers = [];
  const flat = [];
  Object.entries(sourcesDoc.newsletters).forEach(([tierKey, tierObj]) => {
    const tierId = tierKey; // e.g. tier1_daily
    const shortTier = tierKey.split('_')[0]; // tier1
    (tierObj.sources || []).forEach(s => {
      const entry = { ...s, tier: shortTier, tierKey, tierDesc: tierObj.description };
      flat.push(entry);
    });
    tiers.push({ id: tierId, short: shortTier, description: tierObj.description, count: (tierObj.sources || []).length });
  });
  // Build byName lookup — digest items have `source` strings; match by normalized name.
  const byName = {};
  flat.forEach(s => {
    byName[normName(s.name)] = s;
  });
  return { byName, flat, tiers };
}

function normName(s) {
  return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}

// Match a digest item's source string to a registry entry (fuzzy fallback)
function lookupSource(digestSource, byName, flat) {
  if (!digestSource) return null;
  const key = normName(digestSource);
  if (byName[key]) return byName[key];
  // contains-either-way fallback
  for (const s of flat) {
    const sk = normName(s.name);
    if (sk.includes(key) || key.includes(sk)) return s;
  }
  return null;
}

const TIER_DOT = {
  tier1: { color: 'var(--accent)', label: 'Tier 1 · daily' },
  tier2: { color: '#d4a017', label: 'Tier 2 · near-daily' },
  tier3: { color: '#8a8068', label: 'Tier 3 · weekly' },
  tier4: { color: '#6b6456', label: 'Tier 4 · occasional' },
  tier5: { color: '#9b9280', label: 'Excluded / other' },
};

function TierDot({ tier, size = 7 }) {
  const t = TIER_DOT[tier] || TIER_DOT.tier5;
  return <span style={{ display: 'inline-block', width: size, height: size, borderRadius: '50%', background: t.color, flexShrink: 0 }} title={t.label} />;
}

// ---- Source tooltip shown on hover of source name in card ----
function SourceTooltip({ src, lastSeen }) {
  if (!src) return null;
  const t = TIER_DOT[src.tier] || TIER_DOT.tier5;
  return (
    <div className="src-tip" role="tooltip">
      <div className="src-tip-hdr">
        <TierDot tier={src.tier} size={8} />
        <span>{t.label.toUpperCase()}</span>
        {src.frequency && <span style={{ marginLeft: 'auto', color: 'var(--ink-4)' }}>{src.frequency}</span>}
      </div>
      <div className="src-tip-name">{src.name}</div>
      {src.days_in_14 != null && (
        <div className="src-tip-row"><span>Cadence</span><b>{src.days_in_14} / 14 days</b></div>
      )}
      {src.category && (
        <div className="src-tip-row"><span>Category</span><b>{src.category}</b></div>
      )}
      {lastSeen && (
        <div className="src-tip-row"><span>Last in digest</span><b>{lastSeen}</b></div>
      )}
      {src.include === false && (
        <div className="src-tip-row" style={{ color: '#c44' }}><span>Status</span><b>Excluded</b></div>
      )}
      {src.note && <div className="src-tip-note">{src.note}</div>}
    </div>
  );
}

// ---- Rail section: sources summary + new this week ----
function SourcesRailPanel({ sourcesDoc, flat, onOpenCoverage, lastSeenMap }) {
  if (!sourcesDoc) return null;
  const active = flat.filter(s => s.include !== false).length;
  const excluded = flat.filter(s => s.include === false).length;

  // new sources: those with a "note" that starts with "Auto-discovered" within last 21 days (approx from today)
  const newSources = flat.filter(s => {
    if (!s.note) return false;
    const m = s.note.match(/Auto-discovered\s+(\d{4}-\d{2}-\d{2})/);
    if (!m) return false;
    const d = new Date(m[1]);
    const days = (Date.now() - d.getTime()) / (1000 * 60 * 60 * 24);
    return days <= 45;
  }).slice(0, 5);

  return (
    <>
      <button className="rail-btn big" onClick={onOpenCoverage}>
        <span style={{ display: 'flex', justifyContent: 'space-between', width: '100%', alignItems: 'baseline' }}>
          <span>Sources &amp; Coverage</span>
          <b style={{ color: 'var(--accent)' }}>{active}</b>
        </span>
        <span style={{ display:'block', fontSize: '0.52rem', color: 'var(--ink-4)', letterSpacing: '0.14em', marginTop: 3, textAlign:'left' }}>
          {active} active · {excluded} excluded · see 14-day grid →
        </span>
      </button>
      {newSources.length > 0 && (
        <>
          <h3>Newly added</h3>
          <ul className="rail-list" style={{ fontSize: '0.66rem' }}>
            {newSources.map(s => (
              <li key={s.name} onClick={onOpenCoverage} title={s.note}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 5, overflow:'hidden' }}>
                  <TierDot tier={s.tier} />
                  <span style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', maxWidth: 160 }}>{s.name}</span>
                </span>
                <span className="k">new</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

// ---- Coverage page ----
function CoveragePage({ sourcesDoc, flat, tiers, allDates, allDigests, onClose, onFilterSource, activeSourceFilter }) {
  const [catFilter, setCatFilter] = useSS('');
  const [tierFilter, setTierFilter] = useSS('');
  const [showExcluded, setShowExcluded] = useSS(false);

  // Last 14 days of available digests
  const last14 = useSM(() => allDates.slice().sort().slice(-14), [allDates]);

  // Build source → Set of dates it appeared
  const coverage = useSM(() => {
    const map = {};
    flat.forEach(s => { map[normName(s.name)] = new Set(); });
    Object.entries(allDigests).forEach(([date, dig]) => {
      if (!dig) return;
      ['main','curious'].forEach(sec => {
        (dig[sec] || []).forEach(it => {
          const entry = lookupSource(it.source, Object.fromEntries(flat.map(f => [normName(f.name), f])), flat);
          if (entry) {
            if (!map[normName(entry.name)]) map[normName(entry.name)] = new Set();
            map[normName(entry.name)].add(date);
          }
        });
      });
    });
    return map;
  }, [flat, allDigests]);

  const sorted = useSM(() => {
    const filtered = flat.filter(s => {
      if (!showExcluded && s.include === false) return false;
      if (catFilter && s.category !== catFilter) return false;
      if (tierFilter && s.tier !== tierFilter) return false;
      return true;
    });
    // Sort by cadence (days_in_14 desc, then tier, then name)
    filtered.sort((a, b) => {
      const ca = a.days_in_14 != null ? a.days_in_14 : -1;
      const cb = b.days_in_14 != null ? b.days_in_14 : -1;
      if (cb !== ca) return cb - ca;
      return a.name.localeCompare(b.name);
    });
    return filtered;
  }, [flat, showExcluded, catFilter, tierFilter]);

  const cats = sourcesDoc?.categories || [];

  return (
    <div className="main-col coverage">
      <div className="masthead">
        <div className="left">Coverage · all sources</div>
        <div className="edition"><div>Registry v{sourcesDoc?.version} · updated {sourcesDoc?.updated}</div></div>
        <div className="weather"><button className="link-btn" onClick={onClose}>← back to digest</button></div>
      </div>

      <div className="paper-name" style={{ fontSize: '3.4rem' }}>Sources</div>
      <div className="paper-sub">
        <span>{flat.length} newsletters tracked</span>
        <span className="date-big">across {tiers.length} tiers &amp; {cats.length} categories</span>
        <span>hover for detail · click to filter</span>
      </div>

      {/* Summary stats */}
      <div className="cov-stats">
        {tiers.map(t => (
          <button key={t.id} className={`cov-stat ${tierFilter === t.short ? 'on' : ''}`} onClick={() => setTierFilter(tierFilter === t.short ? '' : t.short)}>
            <TierDot tier={t.short} size={9} />
            <b>{t.count}</b>
            <span>{(TIER_DOT[t.short] || {}).label || t.id}</span>
          </button>
        ))}
      </div>

      {/* Filter bar */}
      <div className="cov-filter-row">
        <div className="cov-filter-group">
          <span className="lbl">Category</span>
          <button className={catFilter === '' ? 'on' : ''} onClick={() => setCatFilter('')}>All</button>
          {cats.map(c => (
            <button key={c.id} className={catFilter === c.id ? 'on' : ''} onClick={() => setCatFilter(catFilter === c.id ? '' : c.id)}>{c.name}</button>
          ))}
        </div>
        <div className="cov-filter-group">
          <label className="cov-check">
            <input type="checkbox" checked={showExcluded} onChange={e => setShowExcluded(e.target.checked)} />
            Show excluded
          </label>
        </div>
      </div>

      {/* Grid */}
      <div className="cov-grid">
        <div className="cov-grid-head">
          <div className="c-name">Source</div>
          <div className="c-cat">Category</div>
          <div className="c-cadence">Cadence</div>
          <div className="c-dates">
            {last14.map(d => {
              const dd = new Date(d + 'T00:00:00');
              return <div key={d} className="dcell" title={d}><span className="dm">{dd.getDate()}</span><span className="dw">{['S','M','T','W','T','F','S'][dd.getDay()]}</span></div>;
            })}
          </div>
          <div className="c-total">14d</div>
        </div>
        {sorted.map(s => {
          const hits = coverage[normName(s.name)] || new Set();
          const last14hits = last14.filter(d => hits.has(d)).length;
          const isFilterActive = activeSourceFilter === s.name;
          return (
            <div key={s.name} className={`cov-row ${s.include === false ? 'excl' : ''} ${isFilterActive ? 'active' : ''}`}>
              <div className="c-name" onClick={() => onFilterSource(s.name)}>
                <TierDot tier={s.tier} />
                <div className="n-wrap">
                  <div className="n">{s.name}</div>
                  {s.note && <div className="nn">{s.note}</div>}
                </div>
              </div>
              <div className="c-cat">{s.category}</div>
              <div className="c-cadence">
                {s.days_in_14 != null ? <><b>{s.days_in_14}</b>/14</> : <span className="muted">{s.frequency || '—'}</span>}
              </div>
              <div className="c-dates">
                {last14.map(d => (
                  <div key={d} className={`dcell ${hits.has(d) ? 'hit' : ''}`} title={hits.has(d) ? `${s.name} · ${d}` : ''} />
                ))}
              </div>
              <div className={`c-total ${last14hits === 0 ? 'zero' : ''}`}>{last14hits}</div>
            </div>
          );
        })}
        {sorted.length === 0 && <div className="empty">No sources match your filters.</div>}
      </div>

      <div className="byline-stats">
        <div className="stat"><b>{flat.length}</b> total</div>
        <div className="stat"><b>{flat.filter(s=>s.include!==false).length}</b> active</div>
        <div className="stat"><b>{flat.filter(s=>s.include===false).length}</b> excluded</div>
        <div className="stat"><b>{Object.values(coverage).filter(s => s.size > 0).length}</b> seen in digests</div>
        <div className="stat" style={{ marginLeft: 'auto' }}>Registry updated {sourcesDoc?.updated}</div>
      </div>
    </div>
  );
}

window.flattenSources = flattenSources;
window.lookupSource = lookupSource;
window.normName = normName;
window.TierDot = TierDot;
window.TIER_DOT = TIER_DOT;
window.SourceTooltip = SourceTooltip;
window.SourcesRailPanel = SourcesRailPanel;
window.CoveragePage = CoveragePage;
