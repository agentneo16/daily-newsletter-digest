/* ============================================================
   app/DigestView.jsx
   Main column for the digest page: masthead + nameplate + paper-sub
   strip, Main/Curious stream with Lead + Also-today aside + time-
   bucketed rest, individual Card rendering, global cross-archive
   search results, byline-stats footer.

   Composes with:
     - app/styles-v3.css   (.masthead, .paper-name, .paper-sub, .lead, .lead-main, .lead-aside, .card, .card-act, .src-chip, .sec-head, .time-block, .so-what, .bullets, .byline-stats tokens)
     - app/Sources.jsx     (consumes lookupSource, SourceTooltip, TierDot via the SourceChip subcomponent below)
     - app/App.jsx         (parent — wires every prop on DigestView; owns digest/date/activeTab/filters/read+bookmark sets/sources lookups)
     - data/<date>.json    (input — main[] + curious[] arrays of items with source/category/headline/one_liner/bullets/so_what/arrival_ist)

   Pure presentational — no state of its own except a local search-results memo.
   Exports DigestView + CATEGORIES (the category list) to window for App + Rail.

   v4.x JSX — filename tracks major version only.
   Class names match app/styles-v3.css unchanged from v3 → v4.
   ============================================================ */

/* global React, lookupSource, SourceTooltip, TierDot */
const { useState: useS2, useMemo: useM3 } = React;

const CATEGORIES = [
  { id: 'world_macro', name: 'World' },
  { id: 'markets_investing', name: 'Markets' },
  { id: 'india_business', name: 'India' },
  { id: 'ai_tech', name: 'AI & Tech' },
  { id: 'deals_startups', name: 'Deals' },
  { id: 'tax_compliance', name: 'Tax' },
  { id: 'career_learning', name: 'Career' },
  { id: 'sports_lifestyle', name: 'Sports' },
  { id: 'uncategorized', name: 'Misc' },
];

const CAT_LABEL = Object.fromEntries(CATEGORIES.map(c => [c.id, c.name]));
function catLabel(id) { return CAT_LABEL[id] || 'Misc'; }
function itemId(date, section, idx) { return `${date}:${section}:${idx}`; }

// Text of specialized-card payloads (hybrid_c / flavor_1) — used for search indexing.
function specialText(it) {
  return [
    ...(it.top_picks || []).map(p => `${p.headline} ${p.tagged_author || ''} ${p.synthesis}`),
    ...(it.tail || []).map(x => `${x.headline} ${x.teaser || ''} ${x.addendum || ''}`),
    ...(it.stories || []).map(s => `${s.headline} ${s.author || ''} ${s.synthesis}`),
  ].join(' ');
}

const MONTHS3 = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const DOW3 = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];

function classifyTime(arrival) {
  if (!arrival) return 'morning';
  const m = arrival.match(/(\d+):(\d+)\s*(AM|PM)/i);
  if (!m) return 'morning';
  let h = parseInt(m[1], 10);
  const mer = m[3].toUpperCase();
  if (mer === 'PM' && h !== 12) h += 12;
  if (mer === 'AM' && h === 12) h = 0;
  if (h < 6) return 'latenight';
  if (h < 12) return 'morning';
  if (h < 18) return 'afternoon';
  if (h < 22) return 'evening';
  return 'latenight';
}

const TIME_LABEL = {
  latenight: 'Late night',
  morning: 'Morning',
  afternoon: 'Afternoon',
  evening: 'Evening',
};

// ---- SourceChip — shows name + tier dot + tooltip on hover ----
function SourceChip({ name, sourcesByName, flat }) {
  const src = useM3(() => lookupSource(name, sourcesByName || {}, flat || []), [name, sourcesByName, flat]);
  return (
    <span className="src-chip">
      {src && <TierDot tier={src.tier} />}
      <span className="src-n">{name}</span>
      {src && <SourceTooltip src={src} />}
    </span>
  );
}

function Card({ id, item, section, onToggleRead, onToggleBookmark, isRead, isBookmarked, sourcesByName, flat }) {
  return (
    <article className={`card ${isRead ? 'read' : ''}`}>
      <div className="top-row">
        <SourceChip name={item.source} sourcesByName={sourcesByName} flat={flat} />
        <span className="cat">{catLabel(item.category)}</span>
        {item.arrival_ist && <span className="arrived">{item.arrival_ist}</span>}
        <span className="actions" role="group" aria-label="Card actions">
          <button className={`card-act bookmark ${isBookmarked ? 'on' : ''}`} aria-pressed={isBookmarked} aria-label={isBookmarked ? 'Remove from reading list' : 'Save to reading list'} onClick={() => onToggleBookmark(id, item, section)} title="Save">★</button>
          <button className={`card-act markread ${isRead ? 'on' : ''}`} aria-pressed={isRead} aria-label={isRead ? 'Mark as unread' : 'Mark as read'} onClick={() => onToggleRead(id)} title="Read">✓</button>
        </span>
      </div>
      <h3 dangerouslySetInnerHTML={{ __html: item.headline }} />
      {item.one_liner && <div className="one-liner" dangerouslySetInnerHTML={{ __html: item.one_liner }} />}
      {item.card_type === 'hybrid_c' ? (
        <>
          <ul className="top-picks">
            {(item.top_picks || []).map((pk, i) => (
              <li className="pick" key={i}>
                <div className="pick-headline">★ {pk.headline}{pk.link && <a className="pick-link" href={pk.link} target="_blank" rel="noreferrer">[link]</a>}</div>
                <div className="pick-synthesis">{pk.tagged_author && <b>{pk.tagged_author} </b>}<span dangerouslySetInnerHTML={{ __html: pk.synthesis }} /></div>
              </li>
            ))}
          </ul>
          {(item.tail || []).length > 0 && (
            <>
              <div className="tail-label">Also in this email</div>
              <ul className="tail">
                {item.tail.map((tl, i) => (
                  <li className="tail-item" key={i}>
                    <div className="tail-headline">{tl.headline}{tl.link && <a className="tail-link" href={tl.link} target="_blank" rel="noreferrer">[link]</a>}</div>
                    {tl.teaser && <div className="tail-teaser">{tl.teaser}</div>}
                    {tl.addendum && <div className="tail-addendum">{tl.addendum}</div>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      ) : item.card_type === 'flavor_1' ? (
        <ul className="top-picks">
          {(item.stories || []).map((st, i) => (
            <li className="pick" key={i}>
              <div className="pick-headline">★ {st.headline}{st.link && <a className="pick-link" href={st.link} target="_blank" rel="noreferrer">[link]</a>}</div>
              <div className="pick-synthesis">{st.author && <b>By {st.author}: </b>}<span dangerouslySetInnerHTML={{ __html: st.synthesis }} /></div>
            </li>
          ))}
        </ul>
      ) : (
        item.bullets && item.bullets.length > 0 && (
          <ul className="bullets">
            {item.bullets.map((b, i) => <li key={i} dangerouslySetInnerHTML={{ __html: b }} />)}
          </ul>
        )
      )}
      {item.so_what && <div className="so-what" dangerouslySetInnerHTML={{ __html: item.so_what }} />}
    </article>
  );
}

// ---- Global search results across all editions ----
function GlobalSearchResults({ search, allDigests, onPick }) {
  const results = useM3(() => {
    if (!search || search.length < 2) return [];
    const q = search.toLowerCase();
    const out = [];
    Object.entries(allDigests).forEach(([date, dig]) => {
      if (!dig) return;
      ['main','curious'].forEach(sec => {
        (dig[sec] || []).forEach((it, i) => {
          const hay = [it.headline, it.one_liner, it.source, (it.bullets||[]).join(' '), specialText(it), it.so_what].join(' ').toLowerCase();
          if (hay.includes(q)) out.push({ date, section: sec, item: it, i });
        });
      });
    });
    return out.sort((a,b) => b.date.localeCompare(a.date)).slice(0, 80);
  }, [search, allDigests]);

  if (!search || search.length < 2) {
    return <div className="empty">Type 2+ characters to search all editions.</div>;
  }
  if (results.length === 0) {
    return <div className="empty">No matches for "{search}".</div>;
  }
  return (
    <div className="search-results">
      <div style={{ fontFamily:'var(--font-mono)', fontSize:'0.62rem', color:'var(--ink-4)', letterSpacing:'0.14em', textTransform:'uppercase', marginBottom: 10 }}>
        {results.length} match{results.length===1?'':'es'} across {Object.keys(allDigests).length} editions
      </div>
      {results.map((r, idx) => (
        <div key={idx} className="result" onClick={() => onPick(r.date)}>
          <div className="meta">
            <span className="date">{r.date}</span>
            {' · '}<span className="source">{r.item.source}</span>
            {' · '}<span>{catLabel(r.item.category)}</span>
            {' · '}<span>{r.section === 'main' ? 'MAIN' : 'CURIOUS'}</span>
          </div>
          <h5 dangerouslySetInnerHTML={{ __html: r.item.headline }} />
          {r.item.one_liner && <div className="ol" dangerouslySetInnerHTML={{ __html: r.item.one_liner }} />}
        </div>
      ))}
    </div>
  );
}

// ---- Render a stream (main or curious) with its own lead + also-today + buckets ----
function Stream({ items, totalCount, date, section, onToggleRead, onToggleBookmark, readSet, bookmarkSet, filtered, sourcesByName, flat }) {
  if (!items.length) {
    return (
      <div className="empty" style={{ padding: '60px 20px' }}>
        {filtered ? `Nothing in ${section === 'main' ? 'Main' : 'Curious'} matches current filters.` : `No items in ${section === 'main' ? 'Main' : 'Curious'}.`}
      </div>
    );
  }

  const lead = items.find(m => m.so_what) || items[0];
  const lead_rest = items.slice(0, 7).filter(m => m !== lead);

  const remaining = items.filter(m => m !== lead);
  const byBucket = { morning: [], afternoon: [], evening: [], latenight: [] };
  remaining.forEach(m => byBucket[classifyTime(m.arrival_ist)].push(m));
  const bucketOrder = ['morning', 'afternoon', 'evening', 'latenight'];

  const leadId = itemId(date, section, lead._i);
  const sectionLabel = section === 'main' ? 'Main' : 'Curious';

  return (
    <>
      <div className="lead">
        <div className="lead-main">
          <div className="kicker">{sectionLabel} lead · {catLabel(lead.category)} · {lead.source}</div>
          <h1 dangerouslySetInnerHTML={{ __html: lead.headline }} />
          {lead.one_liner && <div className="deck" dangerouslySetInnerHTML={{ __html: lead.one_liner }} />}
          {lead.bullets && (
            <ul className="bullets" style={{ listStyle:'none', paddingLeft: 16, borderLeft:'2px solid var(--rule-2)', marginBottom: 14 }}>
              {lead.bullets.slice(0, 4).map((b, i) => <li key={i} style={{ padding:'4px 0', fontSize:'0.95rem', color:'var(--ink-2)', lineHeight: 1.5 }} dangerouslySetInnerHTML={{ __html: b }} />)}
            </ul>
          )}
          {lead.so_what && <div className="so-what" dangerouslySetInnerHTML={{ __html: lead.so_what }} />}
          <div className="lead-meta">
            <SourceChip name={lead.source} sourcesByName={sourcesByName} flat={flat} />
            {lead.arrival_ist && <><span>·</span><span>{lead.arrival_ist}</span></>}
            <span style={{ marginLeft: 'auto', display:'flex', gap: 6 }}>
              <button className={bookmarkSet.has(leadId) ? 'on' : ''}
                onClick={() => onToggleBookmark(leadId, lead, section)}
                style={{ background: 'transparent', border: '1px solid var(--rule)', width: 24, height: 24, cursor: 'pointer', color: bookmarkSet.has(leadId) ? 'var(--accent)' : 'var(--ink-4)', borderRadius: 2, fontFamily: 'var(--font-mono)' }}>★</button>
            </span>
          </div>
        </div>
        <aside className="lead-aside">
          <h2>Also in {sectionLabel.toLowerCase()}</h2>
          <ol>
            {lead_rest.slice(0, 7).map((it) => (
              <li key={it._i} onClick={() => {
                const el = document.getElementById(`card-${itemId(date, section, it._i)}`);
                if (el) {
                  const top = el.getBoundingClientRect().top + window.scrollY - 20;
                  window.scrollTo({ top, behavior: 'smooth' });
                }
              }}>
                <span className="ttl" dangerouslySetInnerHTML={{ __html: it.headline }} />
              </li>
            ))}
          </ol>
        </aside>
      </div>

      <section>
        <div className="sec-head">
          <h2>{sectionLabel === 'Main' ? 'The rest of the main edition' : 'More from curious'}</h2>
          <span className="count">{items.length} of {totalCount}</span>
        </div>
        {bucketOrder.map(b => {
          const list = byBucket[b];
          if (!list.length) return null;
          return (
            <div key={b}>
              <div className="time-block">{TIME_LABEL[b]} · {list.length}</div>
              {list.map((it) => {
                const id = itemId(date, section, it._i);
                return (
                  <div id={`card-${id}`} key={id}>
                    <Card id={id} item={it} section={section}
                      onToggleRead={onToggleRead} onToggleBookmark={onToggleBookmark}
                      isRead={readSet.has(id)} isBookmarked={bookmarkSet.has(id)}
                      sourcesByName={sourcesByName} flat={flat} />
                  </div>
                );
              })}
            </div>
          );
        })}
      </section>
    </>
  );
}

function DigestView({
  digest, date, activeTab,
  filters, timeFilters, search, searchScope, allDigests, onPick,
  readSet, bookmarkSet, onToggleRead, onToggleBookmark,
  sourcesByName, sourcesFlat,
}) {
  // Global search mode
  if (searchScope === 'all' && search && search.length >= 2) {
    return (
      <div className="main-col">
        <div className="masthead">
          <div className="left">Search · all editions</div>
          <div className="edition"><div>Results for "{search}"</div></div>
          <div className="weather">Scope: ALL</div>
        </div>
        <div className="paper-name" style={{ fontSize:'2.6rem' }}>Cross-archive search</div>
        <div className="paper-sub">
          <span>Query: "{search}"</span>
          <span className="date-big">across all editions</span>
          <span>click to jump</span>
        </div>
        <GlobalSearchResults search={search} allDigests={allDigests} onPick={onPick} />
      </div>
    );
  }

  if (!digest) return <div className="main-col"><div className="empty">No digest for this date.</div></div>;

  const passesFilter = (item) => {
    if (filters.size && !filters.has(item.category)) return false;
    if (timeFilters.size && !timeFilters.has(classifyTime(item.arrival_ist))) return false;
    if (search) {
      const q = search.toLowerCase();
      const hay = [item.headline, item.one_liner, item.source, (item.bullets||[]).join(' '), specialText(item), item.so_what].join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  };

  const mainAll = (digest.main || []).map((it, i) => ({ ...it, _i: i }));
  const curiousAll = (digest.curious || []).map((it, i) => ({ ...it, _i: i }));
  const mainItems = mainAll.filter(passesFilter);
  const curiousItems = curiousAll.filter(passesFilter);

  const totalMain = mainAll.length;
  const totalCurious = curiousAll.length;
  const activeItems = activeTab === 'main' ? mainItems : curiousItems;
  const activeTotal = activeTab === 'main' ? totalMain : totalCurious;

  const dt = new Date(date + 'T00:00:00');
  const dateDisplay = digest.date_display || `${MONTHS3[dt.getMonth()]} ${dt.getDate()}, ${dt.getFullYear()}`;
  const dayName = digest.day || DOW3[dt.getDay()];

  const uniqueSources = new Set([...mainAll, ...curiousAll].map(i => i.source)).size;
  const readMin = Math.round((totalMain * 0.8 + totalCurious * 0.5));

  const filtered = filters.size > 0 || timeFilters.size > 0 || !!search;

  return (
    <div className="main-col">
      <div className="masthead">
        <div className="left">{activeTab === 'main' ? 'Main' : 'Curious'} · {dayName}</div>
        <div className="edition">
          <div>Edition № {date.replace(/-/g,'.')}</div>
          <div className="vol">Vol 1 · 06:00 IST</div>
        </div>
        <div className="weather">{totalMain + totalCurious} items · ~{readMin} min</div>
      </div>

      <div className="paper-name">The Daily Digest</div>

      <div className="paper-sub">
        <span>Curated from {uniqueSources} sources</span>
        <span className="date-big">{dayName}, {dateDisplay}</span>
        <span>curated inbox edition</span>
      </div>

      <Stream
        items={activeItems}
        totalCount={activeTotal}
        date={date}
        section={activeTab}
        onToggleRead={onToggleRead}
        onToggleBookmark={onToggleBookmark}
        readSet={readSet}
        bookmarkSet={bookmarkSet}
        filtered={filtered}
        sourcesByName={sourcesByName}
        flat={sourcesFlat}
      />

      <div className="byline-stats">
        <div className="stat"><b>{totalMain}</b> main</div>
        <div className="stat"><b>{totalCurious}</b> curious</div>
        <div className="stat"><b>{uniqueSources}</b> sources</div>
        <div className="stat"><b>{readMin}</b> min read</div>
        <div className="stat" style={{ marginLeft: 'auto' }}>Generated 06:00 IST · {dateDisplay}</div>
      </div>
    </div>
  );
}

window.DigestView = DigestView;
window.CATEGORIES = CATEGORIES;
