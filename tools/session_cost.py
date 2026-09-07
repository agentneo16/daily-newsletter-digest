#!/usr/bin/env python3
"""session_cost.py — tokens, wall-clock and API-list cost for a Claude Code or Codex session.

Usage:
  python3 tools/session_cost.py <claude-session.jsonl | codex-rollout.jsonl> [more files...]
  python3 tools/session_cost.py --marker <token>           # the Claude Code session whose transcript contains <token>
                                                           #   (the executor prints a unique token line first — the only safe selector)
  python3 tools/session_cost.py --session <id> --marker <token>   # the run inside a chosen session: from the Runtime-Gate token
                                                                  #   onward, plus only the subagents launched in that window
  python3 tools/session_cost.py --session <id>             # a Claude Code session by id (whole file — warns)
  python3 tools/session_cost.py --latest-claude            # newest-mtime Claude Code session — WARNING: concurrent sessions make this wrong
  python3 tools/session_cost.py --codex-run <token>        # the executor rollout that PRINTED the token (standalone line) + every
                                                           #   child thread it spawned or re-drove inside the run window — tagged
                                                           #   `digest_worker*` and untagged alike — each billed for EVERY one of
                                                           #   its in-window task cycles (a child driven twice inside the run was
                                                           #   paid for twice; the purity gate, by contrast, JUDGES only the last)
  python3 tools/session_cost.py --codex <executor.jsonl> <child.jsonl>...   # explicit rollouts (alias of bare paths; executor first)
  python3 tools/session_cost.py --latest-codex [N]         # the N most recently STARTED rollouts — WARNING: no ownership filter
  python3 tools/session_cost.py --selftest                 # the Codex usage fixtures: the bucket rule (input = total; cached /
                                                           #   cache-write are buckets of it) valid and over-subscribed, and the
                                                           #   malformed-container rule ('' / [] / a string / a list rejected,
                                                           #   an ABSENT last_token_usage still billed), plus the baseline
                                                           #   rule (a malformed event OUTSIDE the window leaves the baseline
                                                           #   UNKNOWN — the next valid event bills its own last_token_usage,
                                                           #   or, if it has none, bills NOTHING and only re-anchors the
                                                           #   baseline so the event after it differences correctly)

Claude Code: sums the `usage` of every distinct assistant message (Claude Code writes one record per content
block with the same message.id and the same usage — they are deduplicated by message.id, last record wins)
in the session file AND in the subagent transcripts it LAUNCHED (workers), per model. Those are selected by agentId — the ids
recorded on the executor's own Agent tool calls — not by "every file in the subagents/ folder": a delegated executor is itself a
subagent and shares that folder with agents it never launched. A launch whose agentId was never recorded CANNOT be named, and
the in-window siblings are not a safe stand-in for it (they may belong to another executor): those transcripts are NOT billed,
the launches are counted, a note names them, and the run is reported INCOMPLETE (exit 4) — pass their files explicitly to
include them. The same holds for a launch that IS named but produced no billable usage: the ids actually billed (the
`agent-<id>.jsonl` files that were found AND yielded at least one distinct assistant message carrying a valid `usage` dict)
are compared against the ids launched, and every launched id that billed nothing is counted as an unbilled launch, named in a
note, and marked INCOMPLETE the same way — a transcript that is missing, empty or unreadable, and one that holds only
metadata / user records or assistant records with `usage: null`, leave the totals short by that agent's whole run alike, and
neither must ever pass as a complete bill. The SAME rule now holds for Codex child threads: a child selected into the
run window whose cycles carried no valid usage event is named in a note, counted, and the run is INCOMPLETE (exit 4) —
before 2026-09-07 that promise was kept only on the Claude path (GPT-6 Astra, GitHub review loop 12). A child is billed for
EVERY one of its in-window cycles, so the test is per CYCLE as well as per thread: an in-window cycle that produced an
assistant turn and has NO billed usage event at or after its start is named as `<thread> cycle <n>` and marks the run
INCOMPLETE even when an earlier cycle of that same thread billed normally (loop 13). "At or after its start", not "inside
it": `token_count` totals are CUMULATIVE and are emitted AFTER the turn they pay for, so a cycle's tokens routinely land
past its own task_complete, and a mid-run cycle's tokens are swept into the NEXT event's delta. Only work with no later
reading at all is genuinely absent from the bill. All three invocation forms that declare an executor plus its children
— `--codex-run`, `--codex`, and the bare-path alias the Usage block documents — apply both tests identically.
Wall-clock = first → last timestamp.
Codex: bills PER TURN. `token_count` events carry a cumulative `total_token_usage`, so each event's bill is its delta from
the previous total (Codex re-emits an identical total after reasoning items — an unchanged total is not a turn and is skipped);
the "turns" column is therefore the number of billed deltas, not the number of files. When ANY cumulative field DECREASES
against the previous event the counter has restarted (a context reset / a new thread segment): that event is billed on its own
`last_token_usage` instead of a delta, so the request that opens the new segment is never lost as a zero. A request whose own
`last_token_usage.input_tokens` exceeds 272,000 is a long-context request: the token columns keep the ACTUAL counts and the
surcharge (one extra 1× copy of the input side, half an extra copy of the output side) is accumulated separately and added in
the COST only. Codex reports `input_tokens` as the TOTAL input of a request, with `cached_input_tokens` and
`cache_write_input_tokens` as BUCKETS of that total: the uncached column is input − cached − cache-write, so no
token is billed twice. An event whose cached + cache-write EXCEEDS its own total input contradicts that model: it is INVALID and is
skipped rather than clamped to zero, and the number skipped is printed as one note line. An event in which `total_token_usage`
or `last_token_usage` is PRESENT but not an object (a string, a list, a number, `null` — `""` and `[]` included) is INVALID the
same way: nothing is billed, and it is counted in the same note — never silently accepted, never a traceback. Because such an
event's own cumulative total is unreadable, the running baseline it advanced is UNKNOWN afterwards — wherever the event sits,
inside the window or outside it — so the next VALID event is billed on its own (normalised) `last_token_usage` instead of
`cur − stale_prev`, which would bill the malformed event's turn a second time. That recovers the next event's own request but
not the lost one, so if that recovering event falls IN the window the run is marked INCOMPLETE (exit 4); a recovery outside
the window bills nothing and needs no mark. When the recovering event has NO usable `last_token_usage` either (the key absent
or an empty object) there is nothing to fall back on: NOTHING is billed for it — never its cumulative total, which would
charge the whole session as one turn — it is counted as unrecoverable in its own note line (INCOMPLETE, exit 4, when it falls
in the window), and the baseline is re-anchored on its cumulative counters so every LATER event differences correctly.
Only an ABSENT key (no `info`, or no such key in it) is skipped in silence. A run that skipped any such event is a
PARTIAL result: the `runtime:` line ends with ` · INCOMPLETE (N invalid usage event(s) skipped)` and the tool exits 4 — including
the case where EVERY event was invalid, which still prints a zero row and a `runtime:` line for that model/effort (exit 4, never
the "no usage records found" exit 1: the events existed, they were unusable). GPT cache WRITES bill at 1.25× the
uncached input rate. Pass the main rollout plus each worker rollout to get the whole run.

Prices are API list (per MTok); the table below is the source of record.
Unknown models are summed but priced as "n/a" — add them to PRICES.
With --marker only records from the marker onward count (the run, not the session's earlier history). 1-hour cache writes
are priced at 2× the base input price (5-minute writes at 1.25×); an unpriced model flags the runtime line as incomplete.
Prints a table and one `runtime:` line ready to paste into a Step 11 log entry.
Exit codes: 0 = complete result · 1 = no usage records found · 3 = lookup / usage error · 4 = partial result (a complete table
was printed, but at least one invalid Codex usage event was skipped, at least one in-window delta had to be recovered from an
unknown baseline or could not be billed from one at all, or at least one subagent launch could not be billed — no recorded
agentId, or no billable usage record (a missing, empty or unreadable transcript, or one carrying only metadata / user records
or assistant records with `usage: null`) — and the printed totals are therefore not exact).
Session-directory configuration (DIGEST_HUB / CLAUDE_PROJECTS_ROOT / DIGEST_CLAUDE_DIRS / CODEX_SESSIONS_DIR) is derived in
worker_purity_check.py — see its "Configuration" paragraph; this tool reuses those constants.
"""
import glob, json, os, sys
from datetime import datetime

# input, cache_read, cache_write, output — $/MTok (API list, 2026-09-04)
LONG_CTX_INPUT = 272_000   # a Codex REQUEST whose own input exceeds this is billed at 2× input / 1.5× output for that whole request
LONG_CTX_HITS = 0          # how many such requests the current run contained (printed as a note when non-zero)
INVALID_EVENTS = 0         # Codex usage events skipped as invalid — a malformed usage container, or cached + cache-write over their total input (printed as a note)
UNBILLED_LAUNCHES = 0      # Claude subagent launches that could not be billed — no recorded agentId, or no billable usage record for the id (printed as a note)
RECOVERED_EVENTS = 0       # Codex deltas billed from the event's OWN last_token_usage because a malformed event left the baseline UNKNOWN (printed as a note)
UNRECOVERABLE_EVENTS = 0   # Codex events billed as NOTHING: a malformed event left the baseline UNKNOWN and the event carried no usable last_token_usage (printed as a note)
_BASELINE_UNKNOWN = object()   # sentinel: the running `total_token_usage` baseline was invalidated by a malformed event and cannot be differenced against
BILLED_CODEX_TURNS = 0     # billed turns the most recent read_codex() call contributed — 0 means the rollout carried no valid usage event inside its window
LAST_BILLED_CODEX_TS = None   # ts of the LAST event the most recent read_codex() actually billed — `token_count` totals are CUMULATIVE and
                              # emitted AFTER the work, so a cycle's tokens are carried by the first billed event at or after its start
UNBILLED_CODEX_CHILDREN = 0   # Codex child threads selected into the run window that billed nothing (printed as a note; the Codex twin of UNBILLED_LAUNCHES)
UNBILLED_CODEX_CYCLES = 0   # in-window CYCLES of an otherwise-billing child with an assistant turn and no billed usage event at or after their start
BILLED_MESSAGES = 0        # distinct assistant messages with a valid `usage` dict the most recent read_claude() call contributed — 0 means the transcript was
                           #   missing, empty or unreadable, or carried only metadata / user records / assistant records with `usage: null`
PRICES = {  # input, cache_read, cache_write (5-minute = 1.25× input, GPT cache writes likewise), output — $/MTok; 1-hour Claude cache writes = 2× the BASE input price
    "claude-opus-5":       (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4-8":     (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4-7":     (5.00, 0.50, 6.25, 25.00),
    "claude-fable-5-1":    (10.00, 0.25, 12.50, 50.00),
    "claude-fable-5":      (10.00, 1.00, 12.50, 50.00),
    "claude-sonnet-5":     (2.00, 0.20, 2.50, 10.00),
    "claude-sonnet-4-6":   (3.00, 0.30, 3.75, 15.00),
    "claude-haiku-4-5":    (1.00, 0.10, 1.25, 5.00),
    "gpt-5.6-sol":         (4.00, 0.40, 5.00, 20.00),
    "gpt-5.6-terra":       (2.00, 0.20, 2.50, 12.00),
    "gpt-5.6-luna":        (0.20, 0.02, 0.25, 1.20),
}
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worker_purity_check as wpc   # the one home of the token / window / rollout-lookup rules AND of the path derivation
CLAUDE_DIRS = wpc.CLAUDE_DIRS
CLAUDE_DIR = CLAUDE_DIRS[0]


MARKER = None  # when set, only records from the marker onward are counted (the run, not the whole session)


def find_claude_session(argv):
    """--marker / --session / --latest-claude → session file. The lookup itself lives in worker_purity_check (one kitchen)."""
    if argv[0] in ("--marker", "--session"):
        return wpc.find_claude_session(argv[0], argv[1])
    stamped = []
    for f in (f for d in CLAUDE_DIRS for f in glob.glob(os.path.join(d, "*.jsonl"))):
        try:   # a file that vanished between glob and stat is skipped, never a traceback
            stamped.append((os.path.getmtime(f), f))
        except OSError:
            continue
    if not stamped:
        sys.exit("no Claude Code session files found")
    f = max(stamped)[1]
    print(f"WARNING: --latest-claude picked the newest-mtime file ({os.path.basename(f)}); a concurrent session can be newer than the intended one — prefer --session <id> --marker <token>")
    return f


def codex_files(n):
    """The n most recently STARTED rollouts (by the ISO stamp in the filename), oldest first = the executor. WARNING: no ownership filter."""
    print("WARNING: --latest-codex takes the newest N rollouts on the machine regardless of who launched them — prefer --codex-run")
    files = glob.glob(os.path.join(CODEX_DIR, "*", "*", "*", "rollout-*.jsonl"))
    files.sort(key=lambda x: os.path.basename(x)[8:27])
    return files[-n:]


def wpc_closes_window(text, marker, seen):
    return wpc.closes_window(text, marker, seen)


def wpc_tokens(text):
    """The run tokens TEXT actually PRINTS as standalone reply lines — worker_purity_check owns the predicate."""
    return wpc.standalone_tokens(text)


def codex_run_files(token):
    """Executor = the rollout that PRINTED the DIGEST-RUN token; plus EVERY child thread it spawned inside the run window —
    tagged digest_worker* threads and untagged helpers alike, because all of them cost money (same rule as the Claude path)."""
    global CODEX_WINDOW
    files, others, CODEX_WINDOW = wpc.codex_run_files(token)
    if others:
        print(f"note: {len(others)} untagged child thread(s) (helpers / reviewers) included in the bill, ignored by the purity gate")
    print("note: the executor is billed only inside its run window (printed token → next new token or end of rollout); each child for every one of its in-window task cycles")
    return files + others


CODEX_WINDOW = None   # path -> the executor's bare (start, end) run window, or a child's LIST of in-window task cycles; set by --codex-run and read through wpc.cycle_window
CODEX_DIR = wpc.CODEX_DIR


def norm(model):
    if not model:
        return "unknown"
    m = model.replace("[1m]", "")
    for k in PRICES:
        if m.startswith(k):
            return k
    return m


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def read_claude(path, acc, span, window=False):
    """Returns True if the marker was PRINTED in THIS file (per-file, never sticky across files). Also sets the module-level
    BILLED_MESSAGES to the number of DISTINCT assistant messages carrying a valid `usage` dict that this call contributed to
    the accumulator — that is, the number of accumulator entries it added, not the number of JSONL records it walked. A
    transcript that is missing, empty or unreadable yields none, and so does one holding only metadata / user records or
    assistant records with `usage: null`: both are launches that cost the bill nothing readable, which is how main() tells a
    launch that was BILLED from one that only looked billed because its file existed."""
    global BILLED_MESSAGES
    BILLED_MESSAGES = 0
    marker_seen = False
    seen = {}  # message.id -> (key, usage) — one record per content block shares id + usage; last wins
    started = not (window and MARKER)
    seen_tokens = set()   # tokens printed so far — only a NEW one closes the run window
    for o in wpc.records(path):   # a file that vanishes mid-scan yields nothing instead of a traceback
        m = o.get("message")
        if window and MARKER:
            is_text = isinstance(m, dict) and m.get("role") == "assistant" and any(isinstance(b, dict) and b.get("type") == "text" for b in m.get("content") or [])
            texts = "\n".join(b.get("text") or "" for b in (m.get("content") or []) if isinstance(b, dict) and b.get("type") == "text") if is_text else ""
            if not started:
                seen_tokens.update(wpc_tokens(texts))
                if MARKER in wpc_tokens(texts):
                    started = True; marker_seen = True
                else:
                    continue
            elif wpc_closes_window(texts, MARKER, seen_tokens):
                break   # the next run's NEW token (a complete DIGEST-RUN-YYYY-MM-DD-HHMM not printed before) closes this run's window
            seen_tokens.update(wpc_tokens(texts))
        t = ts(o.get("timestamp"))
        if t and (window or not MARKER):   # wall-clock from the main file's window only
            span[0] = min(span[0], t) if span[0] else t
            span[1] = max(span[1], t) if span[1] else t
        if not (isinstance(m, dict) and isinstance(m.get("usage"), dict)):
            continue   # a record with "usage": null carries no billable buckets — skipped, never a traceback
        if str(m.get("model", "")).startswith("<"):
            continue   # <synthetic> API-retry notices carry zero usage and no price
        seen[m.get("id") or o.get("uuid")] = ((norm(m.get("model")), o.get("effort") or "?"), m["usage"])
    BILLED_MESSAGES = len(seen)   # the billed count is the accumulator entries this call added — not the records it walked
    for key, u in seen.values():
        a = acc.setdefault(key, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])   # uncached, cache_read, cache_write_5m, output, turns, cache_write_1h, extra uncached, extra cached, extra cache-write, extra output (the four trailing slots = the Codex long-context surcharge, each bucket priced at its OWN rate)
        cc = u.get("cache_creation") or {}
        w1h = cc.get("ephemeral_1h_input_tokens") or 0
        a[0] += (u.get("input_tokens") or 0)
        a[1] += (u.get("cache_read_input_tokens") or 0)
        a[2] += (u.get("cache_creation_input_tokens") or 0) - w1h
        a[3] += (u.get("output_tokens") or 0)
        a[4] += 1
        a[5] += w1h
    return marker_seen


def read_codex(path, acc, span, window=None):
    """Bills a rollout PER TURN. `token_count` carries a CUMULATIVE `total_token_usage`, so each event's bill is its delta
    from the previous total; Codex re-emits an identical total after reasoning items, and an unchanged total is skipped
    (it is not a turn and must not be counted as one). WINDOW is either a single (start, end) — the executor's run window —
    or a LIST of them, a child's in-window task cycles; wpc.cycle_window normalises the two shapes. Every event is walked so
    the running total stays correct, but a delta is accumulated only when its ts falls in SOME (start, end] — that is how the
    pre-window total is subtracted without a separate pass, and how a child driven MORE THAN ONCE inside the run is billed for
    every cycle (turn counts add up) rather than for its last one alone. A request
    whose own `last_token_usage.input_tokens` exceeds LONG_CTX_INPUT keeps its ACTUAL tokens in the columns; its surcharge
    (one extra 1× copy of each input bucket at its own rate, half an extra copy of the output side) is accumulated in the four trailing
    accumulator slots and priced in the COST formula only. A cumulative field that DECREASES means the counter restarted
    (context reset / new thread segment): that event is billed on its own `last_token_usage` and becomes the new baseline,
    so the request opening the new segment is not lost as a zero delta — that rule lives in worker_purity_check.usage_delta, the
    one home it shares with the purity gate. Model/effort are tracked CONTINUOUSLY through the whole file: records before the
    window set the starting values, records inside it update them, and every delta is billed under the model/effort in force AT
    that delta's own event, so a `turn_context` that switches model or effort inside the window is honoured instead of being
    back-dated to the previous model. Records AFTER the LAST window end are still ignored entirely.
    The running baseline PREV is the NORMALISED counters of each event (wpc._usage_ints against the previous baseline), never
    the raw dict: a field missing from one event carries the previous value forward, and that carried value must survive into
    the NEXT delta too — keeping the raw dict would let the omission read as 0 one event later and double-bill the difference.
    A MALFORMED event (either usage container present but not an object) invalidates that baseline wherever it sits, in the
    window or outside it: its own cumulative total is unreadable, so the counters it advanced are unknown and the NEXT valid
    event's `cur − prev` would silently bill the malformed event's turn a second time. The baseline is therefore marked
    UNKNOWN, and the next valid event is billed on its OWN normalised `last_token_usage` (usage_delta's "no previous reading"
    branch) and becomes the new baseline. That recovers the event's own request but not the lost one, so when the recovering
    event is IN the window the run is marked INCOMPLETE (exit 4); a recovery that lands outside the window bills nothing and
    needs no mark. The recovery needs a usable `last_token_usage` to bill: when the recovering event has NONE (the key is
    absent, or an empty object — a non-object was already rejected as malformed) there is nothing to fall back on, so NOTHING
    is billed for it (usage_delta's "no previous reading" branch would otherwise fall back to the CUMULATIVE total and bill
    the whole session as one turn). The event is counted as UNRECOVERABLE — its own note line, INCOMPLETE, exit 4 when it
    falls in the window — and the baseline is advanced from its cumulative counters, which ARE readable, so that every LATER
    event differences correctly instead of inheriting the unknown baseline."""
    global LONG_CTX_HITS, INVALID_EVENTS, RECOVERED_EVENTS, UNRECOVERABLE_EVENTS, BILLED_CODEX_TURNS, LAST_BILLED_CODEX_TS
    BILLED_CODEX_TURNS, LAST_BILLED_CODEX_TS = 0, None
    model, eff = None, "?"
    prev = {}
    wins = wpc.cycle_window(window)   # [] = whole rollout; one entry = a run window; several = a child's repeated task cycles
    last_end = max((b for _a, b in wins), default=None)
    tots = {}   # (model, effort) in force at the event -> that model's accumulator slots
    for o in wpc.records(path):   # a file that vanishes mid-scan yields nothing instead of a traceback
        raw = o.get("timestamp") or ""
        p = o.get("payload")
        if last_end and raw > last_end:
            break
        if not isinstance(p, dict):
            continue
        if p.get("model"):   # tracked through the WHOLE file: before the window these set the starting values, inside it they switch
            model = p["model"]
        if p.get("reasoning_effort") or p.get("effort"):
            eff = p.get("reasoning_effort") or p.get("effort")
        in_window = not wins or any(a < raw <= b for a, b in wins)
        if in_window:
            t = ts(raw)
            if t:
                span[0] = min(span[0], t) if span[0] else t
                span[1] = max(span[1], t) if span[1] else t
        if p.get("type") != "token_count" or not isinstance(p.get("info"), dict):
            continue
        info = p["info"]
        # Either usage container, PRESENT but not an object (a string, a list, a number, null — `""` and `[]` included), is a
        # malformed event. The isinstance test comes BEFORE any truthiness test on purpose: `if not cur` would swallow `""`
        # and `[]` as "nothing reported" and bill the run as complete. Only an ABSENT key is skipped in silence.
        if any(k in info and not isinstance(info[k], dict) for k in ("total_token_usage", "last_token_usage")):
            if in_window:
                INVALID_EVENTS += 1
                tots.setdefault((norm(model), eff), [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])   # a zero row, exactly as for an over-subscribed event
            prev = _BASELINE_UNKNOWN   # the malformed event's own cumulative total is unreadable, so the running baseline is now STALE
            continue                   # nothing is billed for this event — never a traceback
        cur = info.get("total_token_usage")
        if not cur:
            continue   # the key is ABSENT, or an empty object: nothing was reported for this event, so there is nothing to bill
        last = info.get("last_token_usage") or {}   # ABSENT is normal — it only feeds the long-context threshold, and {} means no surcharge
        lastn = wpc._usage_ints(last)   # normalised ONCE for the long-context threshold: "300000" coerces, NaN / Infinity fall back to 0 (no surcharge, no raise)
        recovered = prev is _BASELINE_UNKNOWN   # the previous event was malformed: cur − prev would bill the malformed event's own turn a second time
        if recovered and not last:
            # Recovering from an unknown baseline with NO request-level usage to bill instead: the delta is unknowable and
            # `usage_delta(cur, None, {})` would fall back to the CUMULATIVE total and bill the whole session as one turn.
            # Bill nothing, say so, and advance the baseline from this event's own (readable) cumulative counters so the
            # NEXT event differences correctly instead of inheriting the unknown baseline.
            if in_window:
                UNRECOVERABLE_EVENTS += 1
                tots.setdefault((norm(model), eff), [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])   # a zero row, exactly as for a malformed event
            prev = wpc._usage_ints(cur)
            continue
        base = None if recovered else prev      # `None` is usage_delta's "no previous reading" — it bills the event's OWN normalised last_token_usage
        delta = wpc.usage_delta(cur, base, last)   # counter-reset rule: one home, shared with the purity gate (it takes the RAW last — an empty dict must stay falsy there)
        prev = wpc._usage_ints(cur, base)   # the baseline is the NORMALISED counters: a field carried forward must survive into the next delta
        if recovered and in_window:
            RECOVERED_EVENTS += 1   # an approximation, not an exact delta — the run is an UNDERCOUNT/OVERCOUNT either way, so it is marked INCOMPLETE
        if not in_window or not any(delta.values()):
            continue   # an unchanged total is a re-emit after a reasoning item, not a turn
        if delta["cached_input_tokens"] + delta["cache_write_input_tokens"] > delta["input_tokens"]:
            INVALID_EVENTS += 1   # cached and cache-write are BUCKETS of the total input; over-subscribed = a contradictory event — skipped, not clamped
            tots.setdefault((norm(model), eff), [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])   # a zero row so a run whose events were ALL invalid still prints a runtime line for the model (with the INCOMPLETE suffix) instead of "no usage records found"
            continue
        uncached = delta["input_tokens"] - delta["cached_input_tokens"] - delta["cache_write_input_tokens"]   # Codex `input_tokens` is the TOTAL input; cached and cache-write are buckets OF it, not extras
        tot = tots.setdefault((norm(model), eff), [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])   # uncached, cache_read, cache_write, output, billed turns, (unused: 1h cache write), extra uncached, extra cached, extra cache-write, extra output
        req_in = lastn["input_tokens"]
        if req_in > LONG_CTX_INPUT:   # long-context surcharge: tokens stay ACTUAL, the extra copies are priced separately
            LONG_CTX_HITS += 1
            tot[6] += uncached                                               # one extra 1× copy of the input side, each bucket at its own rate
            tot[7] += delta["cached_input_tokens"]
            tot[8] += delta["cache_write_input_tokens"]
            tot[9] += delta["output_tokens"] * 0.5                           # half an extra copy of the output side (kept as a float — exact 1.5×)
        tot[0] += uncached
        tot[1] += delta["cached_input_tokens"]
        tot[2] += delta["cache_write_input_tokens"]
        tot[3] += delta["output_tokens"]
        tot[4] += 1
        LAST_BILLED_CODEX_TS = raw   # records are read oldest-first, so the last assignment is the latest billed event
    BILLED_CODEX_TURNS = sum(tot[4] for tot in tots.values())   # BILLED, not merely read: a zero row from an all-invalid rollout counts as nothing billed
    for key, tot in tots.items():   # an entry exists for every model that billed a valid delta OR had an event skipped as invalid (a zero row)
        a = acc.setdefault(key, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        for i in range(len(tot)):
            a[i] += tot[i]


def invalid_note():
    """The one note line for Codex usage events skipped as invalid — a malformed usage container, or cached + cache-write
    exceeding their total input. Any such event makes the run's totals an UNDERCOUNT, so the note is paired with
    incomplete_mark() on the runtime line and exit code 4."""
    if INVALID_EVENTS:
        print(f"note: {INVALID_EVENTS} Codex usage event(s) skipped as invalid — a malformed usage container, or cached + cache-write exceeding total input")
    if RECOVERED_EVENTS:
        print(f"note: {RECOVERED_EVENTS} Codex usage event(s) billed from their own last_token_usage — a malformed event left the running baseline unknown, so an exact delta could not be recovered")
    if UNRECOVERABLE_EVENTS:
        print(f"note: {UNRECOVERABLE_EVENTS} Codex usage event(s) not billed at all — a malformed event left the running baseline unknown and the event carried no last_token_usage to bill instead; the baseline was advanced from its cumulative counters so later events stay exact")


EXIT_PARTIAL = 4   # a complete table was printed, but something billable was left out or approximated (an invalid usage event, a delta recovered from an unknown baseline, an event unbillable from an unknown baseline, a subagent launch or a Codex worker thread that could not be billed)


def incomplete_mark():
    """The suffix the `runtime:` line carries when the printed total is known to be an UNDERCOUNT — empty when the run is
    complete. The causes can hold at once (a Codex usage event skipped as invalid, a Codex delta billed from an unknown
    baseline after a malformed event, a Codex event that could not be billed at all from an unknown baseline, a Claude
    subagent launch that could not be billed — no recorded agentId, or no billable usage record, a Codex worker thread that
    billed nothing at all, an in-window CYCLE of an otherwise-billing Codex worker with an assistant turn and no billed
    usage event at or after its start), so they are joined inside ONE `INCOMPLETE (...)`; a single cause reads exactly as
    before."""
    causes = []
    if INVALID_EVENTS:
        causes.append(f"{INVALID_EVENTS} invalid usage event(s) skipped")
    if RECOVERED_EVENTS:
        causes.append(f"{RECOVERED_EVENTS} usage event(s) billed from an unknown baseline")
    if UNRECOVERABLE_EVENTS:
        causes.append(f"{UNRECOVERABLE_EVENTS} usage event(s) not billed from an unknown baseline")
    if UNBILLED_LAUNCHES:
        causes.append(f"{UNBILLED_LAUNCHES} unbilled subagent launch(es)")
    if UNBILLED_CODEX_CHILDREN:
        causes.append(f"{UNBILLED_CODEX_CHILDREN} unbilled Codex worker thread(s)")
    if UNBILLED_CODEX_CYCLES:
        causes.append(f"{UNBILLED_CODEX_CYCLES} unbilled Codex worker cycle(s)")
    return f" · INCOMPLETE ({'; '.join(causes)})" if causes else ""


def is_codex(path):
    """A Codex rollout, by location or by filename — the one home of the test (main and the reader share it)."""
    return "/.codex/" in path or os.path.basename(path).startswith("rollout-")


def _fixture(input_t, cached, cwrite, output, last=None):
    """One synthetic gpt-5.6-sol xhigh rollout with a single token_count event carrying the given buckets. LAST overrides the
    event's own `last_token_usage` (the request-level dict the long-context threshold reads); by default it mirrors the totals."""
    import tempfile
    stamp = "2026-09-04T10:00:00.000Z"
    usage = {"input_tokens": input_t, "cached_input_tokens": cached, "cache_write_input_tokens": cwrite, "output_tokens": output}
    last_u = dict(usage) if last is None else last
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", prefix="rollout-selftest-", delete=False) as fh:
        fh.write(json.dumps({"timestamp": stamp, "type": "turn_context", "payload": {"model": "gpt-5.6-sol", "reasoning_effort": "xhigh"}}) + "\n")
        fh.write(json.dumps({"timestamp": stamp, "type": "event_msg",
                             "payload": {"type": "token_count", "model": "gpt-5.6-sol", "reasoning_effort": "xhigh",
                                         "info": {"total_token_usage": dict(usage), "last_token_usage": last_u}}}) + "\n")
        return fh.name


_ABSENT = object()   # sentinel: omit the key entirely (None is a PRESENT non-dict value, which the fixtures must be able to test)


def _usage_fixture(total, last=_ABSENT):
    """One synthetic gpt-5.6-sol xhigh rollout whose single `token_count` event carries the given `info` verbatim: TOTAL is the
    `total_token_usage` value and LAST the `last_token_usage` value, EACH OF ANY JSON TYPE, and `_ABSENT` omits that key
    entirely. `_fixture` builds only well-formed events; this one builds the malformed containers F1 has to reject."""
    import tempfile
    stamp = "2026-09-04T10:00:00.000Z"
    info = {} if total is _ABSENT else {"total_token_usage": total}
    if last is not _ABSENT:
        info["last_token_usage"] = last
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", prefix="rollout-selftest-", delete=False) as fh:
        fh.write(json.dumps({"timestamp": stamp, "type": "turn_context", "payload": {"model": "gpt-5.6-sol", "reasoning_effort": "xhigh"}}) + "\n")
        fh.write(json.dumps({"timestamp": stamp, "type": "event_msg",
                             "payload": {"type": "token_count", "model": "gpt-5.6-sol", "reasoning_effort": "xhigh", "info": info}}) + "\n")
        return fh.name


def _seq_fixture(events):
    """One synthetic gpt-5.6-sol xhigh rollout carrying SEVERAL `token_count` events in order: EVENTS is a list of
    (timestamp, info) and each `info` is written verbatim, so a malformed container can sit at any position. This is what the
    baseline rule needs and `_usage_fixture` (one event) cannot express."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", prefix="rollout-selftest-", delete=False) as fh:
        fh.write(json.dumps({"timestamp": events[0][0], "type": "turn_context", "payload": {"model": "gpt-5.6-sol", "reasoning_effort": "xhigh"}}) + "\n")
        for stamp, info in events:
            fh.write(json.dumps({"timestamp": stamp, "type": "event_msg",
                                 "payload": {"type": "token_count", "model": "gpt-5.6-sol", "reasoning_effort": "xhigh", "info": info}}) + "\n")
        return fh.name


def _totals(n):
    """A cumulative `total_token_usage` of N uncached input tokens and no other buckets — the simplest shape a delta can be
    read off, so a fixture's arithmetic is visible in the numbers themselves."""
    return {"input_tokens": n, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": 0}


def _run_main_windowed(path, window):
    """`_run_main` with a run WINDOW installed for the fixture, so events can sit outside it — the only way to test that a
    malformed event OUTSIDE the window still invalidates the baseline used inside it."""
    global CODEX_WINDOW
    CODEX_WINDOW = {path: window}
    try:
        return _run_main(path)
    finally:
        CODEX_WINDOW = None


def _run_main(path):
    """main() on one fixture with the run-level counters cleared, returning (exit code, the `runtime:` line)."""
    global INVALID_EVENTS, LONG_CTX_HITS, UNBILLED_LAUNCHES, RECOVERED_EVENTS, UNRECOVERABLE_EVENTS, UNBILLED_CODEX_CHILDREN, UNBILLED_CODEX_CYCLES
    import io, contextlib
    INVALID_EVENTS, LONG_CTX_HITS, UNBILLED_LAUNCHES, RECOVERED_EVENTS, UNRECOVERABLE_EVENTS = 0, 0, 0, 0, 0
    UNBILLED_CODEX_CHILDREN = UNBILLED_CODEX_CYCLES = 0
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main([path])
    os.unlink(path)
    return rc, next((l for l in buf.getvalue().splitlines() if l.startswith("runtime:")), "")


def _child_fixture(with_usage):
    """One synthetic Codex CHILD rollout carrying a `turn_context` and, when WITH_USAGE, a valid `token_count`; without it
    the thread has no usage record at all — the shape README L182 promises is named as unbilled. It writes no task events
    and no assistant turn, which is all the THREAD-level test needs (it fires on a selected child that billed nothing,
    whatever the thread did); the per-CYCLE test additionally requires an assistant turn, so F12/F13 build their own
    two-cycle child below. Corrected 2026-09-07: this docstring previously claimed a task cycle and an assistant turn the
    fixture never wrote — the records are unchanged, so F9/F10 still assert exactly what loop 13 accepted."""
    import tempfile
    stamp = "2026-09-04T10:00:00.000Z"
    recs = [{"timestamp": stamp, "type": "turn_context", "payload": {"model": "gpt-5.6-sol", "reasoning_effort": "xhigh"}}]
    if with_usage:
        u = {"input_tokens": 100, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": 10}
        recs.append({"timestamp": stamp, "type": "event_msg",
                     "payload": {"type": "token_count", "model": "gpt-5.6-sol", "reasoning_effort": "xhigh",
                                 "info": {"total_token_usage": dict(u), "last_token_usage": dict(u)}}})
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", prefix="rollout-selftest-child-", delete=False) as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")
        return fh.name


def _cycles_child_fixture(billed_cycles, usage_ts=None, overlap=False):
    """One synthetic Codex CHILD driven TWICE inside the run: two complete task cycles, each with an assistant turn.
    BILLED_CYCLES names which cycles (1 and/or 2) also emit a `token_count`. `total_token_usage` is CUMULATIVE, so cycle 2
    reports a strictly larger total than cycle 1 — an identical total is a re-emit after a reasoning item and is skipped as
    "not a turn", which would make a genuinely billed cycle 2 read as unbilled. Returns (path, cycles) where cycles is the
    (start, end] list read as the child's window. USAGE_TS, when given, is the timestamp written on the `token_count` of
    the FIRST billed cycle. OVERLAP makes cycle 1's window run to cycle 2's end — the production shape where starts outnumber
    completions (Session 191) — so F14 can place cycle 1's billed event exactly at cycle 2's start and pin the "at or after"
    boundary: the event is inside cycle 1's window (billed) and AT cycle 2's start (covers it)."""
    import tempfile
    recs, cycles, run = [], [], 0
    recs.append({"timestamp": "2026-09-04T09:59:00.000Z", "type": "turn_context",
                 "payload": {"model": "gpt-5.6-sol", "reasoning_effort": "xhigh"}})
    for c in (1, 2):
        cs = f"2026-09-04T10:0{c}:00.000Z"
        recs.append({"timestamp": cs, "type": "event_msg", "payload": {"type": "task_started"}})
        recs.append({"timestamp": f"2026-09-04T10:0{c}:01.000Z", "type": "response_item",
                     "payload": {"type": "message", "role": "assistant",
                                 "content": [{"type": "output_text", "text": f"cycle {c} did work"}]}})
        if c in billed_cycles:
            run += 100   # CUMULATIVE: cycle 2 must exceed cycle 1 or its delta is zero and reads as a re-emit
            u = {"input_tokens": run, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": c}
            uts = usage_ts if (usage_ts and c == min(billed_cycles)) else f"2026-09-04T10:0{c}:02.000Z"
            recs.append({"timestamp": uts, "type": "event_msg",
                         "payload": {"type": "token_count", "model": "gpt-5.6-sol", "reasoning_effort": "xhigh",
                                     "info": {"total_token_usage": dict(u),
                                              "last_token_usage": {"input_tokens": 100, "cached_input_tokens": 0,
                                                                   "cache_write_input_tokens": 0, "output_tokens": c}}}})
        ce = f"2026-09-04T10:0{c}:03.000Z"
        recs.append({"timestamp": ce, "type": "event_msg", "payload": {"type": "task_complete"}})
        cycles.append((cs, ce))
    if overlap:
        cycles[0] = (cycles[0][0], cycles[1][1])   # cycle 1 stays open until cycle 2 completes (overlapping windows)
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", prefix="rollout-selftest-cycles-", delete=False) as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")
        return fh.name, cycles


def _run_main_pair(executor, child, mode="--codex", windows=None):
    """main() on an executor + one child with the run-level counters cleared: (exit code, `runtime:` line, notes).
    MODE is the invocation form — "--codex", or None for the BARE-PATH alias the Usage block documents, which must behave
    identically (loop 13). WINDOWS, when given, is the CODEX_WINDOW map installed for the call, so a child can be given
    several in-window task cycles."""
    global INVALID_EVENTS, LONG_CTX_HITS, UNBILLED_LAUNCHES, RECOVERED_EVENTS, UNRECOVERABLE_EVENTS, UNBILLED_CODEX_CHILDREN, UNBILLED_CODEX_CYCLES
    import io as _io, contextlib
    INVALID_EVENTS, LONG_CTX_HITS, UNBILLED_LAUNCHES, RECOVERED_EVENTS, UNRECOVERABLE_EVENTS = 0, 0, 0, 0, 0
    UNBILLED_CODEX_CHILDREN = UNBILLED_CODEX_CYCLES = 0
    global CODEX_WINDOW
    buf = _io.StringIO()
    CODEX_WINDOW = windows
    try:
        with contextlib.redirect_stdout(buf):
            rc = main(([mode] if mode else []) + [executor, child])
    finally:
        CODEX_WINDOW = None
    for f in (executor, child):
        os.unlink(f)
    out = buf.getvalue().splitlines()
    return rc, next((l for l in out if l.startswith("runtime:")), ""), [l for l in out if l.startswith("note:")]


def selftest():
    """Codex usage fixtures — the bucket rule (F1–F3) and the malformed-container rule (F4–F5).
    VALID: Codex reports `input_tokens` as the TOTAL input, with cached and cache-write as
    buckets OF it, so 100 input / 20 cached / 30 cache-write / 7 output must DISPLAY 50 uncached + 20 cache_rd + 30 cache_wr
    (= 100 input tokens, nothing double-counted) and bill 50×4.00 + 20×0.40 + 30×5.00 + 7×20.00 per MTok.
    ADVERSARIAL: 100 input / 80 cached / 30 cache-write over-subscribes the total (80 + 30 > 100) — it contradicts the bucket
    model, so the event must be REJECTED (nothing BILLED) and counted in the skipped-events note, not clamped to zero. It still
    creates a ZERO row under its own (model, effort) key, so the third check can drive main() on a rollout whose events were ALL
    invalid and see a `runtime:` line with the INCOMPLETE suffix and exit 4 — never the "no usage records found" exit 1.
    MALFORMED CONTAINERS: a `total_token_usage` or `last_token_usage` that is PRESENT but not an object must be INVALID —
    including the FALSY `""` and `[]`, which a truthiness test would swallow as "nothing reported" and bill as a COMPLETE run.
    An ABSENT `last_token_usage` is the ordinary case, not a malformation, and must still bill normally at exit 0.
    BASELINE (F6–F7): a malformed event leaves the running cumulative baseline UNKNOWN wherever it sits. A malformed event
    BEFORE the window must not let the next in-window event difference against the stale total (which would bill the
    malformed event's turn twice) — it bills its own `last_token_usage` and the run is INCOMPLETE at exit 4. The identical
    malformed event AFTER the window end reaches no in-window delta at all and must leave an exact, COMPLETE result.
    UNRECOVERABLE (F8): the recovering event may itself carry NO `last_token_usage`. There is then nothing to bill it from —
    falling back to its CUMULATIVE total would charge the whole session as a single turn — so it must bill ZERO, count in its
    own note, and exit 4, while still re-anchoring the baseline so the NEXT in-window event's delta is exact (350 − 300 = 50,
    not 350)."""
    p = _fixture(100, 20, 30, 7)
    acc, span = {}, [None, None]
    read_codex(p, acc, span)
    os.unlink(p)
    (i, cr, cw, o, n, *_r), = acc.values()
    pr = PRICES["gpt-5.6-sol"]
    cost = (i * pr[0] + cr * pr[1] + cw * pr[2] + o * pr[3]) / 1e6
    want = (50 * 4.00 + 20 * 0.40 + 30 * 5.00 + 7 * 20.00) / 1e6
    ok = (i, cr, cw, o, n) == (50, 20, 30, 7, 1) and abs(cost - want) < 1e-12 and i + cr + cw == 100
    valid_line = f"selftest F1 valid (100/20/30): uncached={i} cache_rd={cr} cache_wr={cw} output={o} turns={n} input_total={i + cr + cw} cost=${cost:.6f} (expected ${want:.6f}) — {'PASS' if ok else 'FAIL'}"

    before = INVALID_EVENTS
    p = _fixture(100, 80, 30, 7)
    bad, span2 = {}, [None, None]
    read_codex(p, bad, span2)
    os.unlink(p)
    skipped = INVALID_EVENTS - before
    mark = incomplete_mark()
    want_mark = f" · INCOMPLETE ({INVALID_EVENTS} invalid usage event(s) skipped)"
    zero_row = list(bad.keys()) == [("gpt-5.6-sol", "xhigh")] and not any(v for v in next(iter(bad.values()), [1]))
    ok2 = zero_row and skipped == 1 and mark == want_mark   # rejected = a ZERO row under its own key, nothing billed, nothing under a wrong key
    print(valid_line)
    invalid_note()
    print(f"selftest F2 adversarial (100/80/30) REJECTED: nothing billed={zero_row} (expected True: one zero row keyed ('gpt-5.6-sol', 'xhigh')) skipped={skipped} (expected 1) | runtime suffix={mark!r} (expected {want_mark!r}) exit={EXIT_PARTIAL} (expected 4) — {'PASS' if ok2 else 'FAIL'}")

    rc, rt = _run_main(_fixture(100, 80, 30, 7))   # a clean slate so the printed count is this fixture's own
    want3 = " · INCOMPLETE (1 invalid usage event(s) skipped)"
    ok3 = rc == EXIT_PARTIAL and rt.startswith("runtime: gpt-5.6-sol xhigh ×0 · 0.0M tokens · $0.00 at API list") and rt.endswith(want3)
    print(f"selftest F3 all-invalid via main(): exit={rc} (expected {EXIT_PARTIAL}) line={rt!r} (expected a zero runtime line ending {want3!r}) — {'PASS' if ok3 else 'FAIL'}")

    # F4: a usage container that is PRESENT but not an object is INVALID — never silently accepted. `""` and `[]` are the
    # dangerous ones: they are FALSY, so a truthiness test would have swallowed them and reported the run as complete.
    good = {"input_tokens": 100, "cached_input_tokens": 20, "cache_write_input_tokens": 30, "output_tokens": 7}
    cases = [("total_token_usage=''", _usage_fixture("")),
             ("total_token_usage=[]", _usage_fixture([])),
             ("total_token_usage='junk'", _usage_fixture("junk")),
             ("total_token_usage=[1,2]", _usage_fixture([1, 2])),
             ("last_token_usage=''", _usage_fixture(dict(good), "")),
             ("last_token_usage='junk'", _usage_fixture(dict(good), "junk"))]
    ok4 = True
    for label, path in cases:
        rc4, rt4 = _run_main(path)
        good4 = rc4 == EXIT_PARTIAL and rt4.endswith(want3) and " ×0 · 0.0M tokens · $0.00 " in rt4
        ok4 = ok4 and good4
        print(f"selftest F4 malformed container {label}: exit={rc4} (expected {EXIT_PARTIAL}) line={rt4!r} (expected a zero runtime line ending {want3!r}) — {'PASS' if good4 else 'FAIL'}")

    # F5: an ABSENT `last_token_usage` is not malformed — it is the ordinary case (no request-level dict, so no long-context
    # surcharge). It must still bill normally and exit 0, or F4's rule would have turned every plain event into an undercount.
    rc5, rt5 = _run_main(_usage_fixture(dict(good)))
    want5 = "runtime: gpt-5.6-sol xhigh ×1 · 0.0M tokens · $0.00 at API list"
    ok5 = rc5 == 0 and rt5.startswith(want5) and "INCOMPLETE" not in rt5
    print(f"selftest F5 absent last_token_usage billed normally: exit={rc5} (expected 0) line={rt5!r} (expected a line opening {want5!r}, no INCOMPLETE) — {'PASS' if ok5 else 'FAIL'}")

    # F6: a malformed event OUTSIDE the window must NOT leave the running baseline stale. 100 (pre-window, valid) → 200
    # (pre-window, malformed `last_token_usage`) → 300 in-window carrying its own `last_token_usage` of 100. Differencing
    # against the stale 100 would bill 300 − 100 = 200 and charge the malformed event's turn a second time; the baseline is
    # UNKNOWN after it, so the in-window event bills its OWN request (100) and the run is INCOMPLETE (the exact delta is gone).
    win = ("2026-09-04T10:00:01.500Z", "2026-09-04T10:00:03.000Z")
    stale = [("2026-09-04T10:00:00.000Z", {"total_token_usage": _totals(100), "last_token_usage": _totals(100)}),
             ("2026-09-04T10:00:01.000Z", {"total_token_usage": _totals(200), "last_token_usage": "junk"}),
             ("2026-09-04T10:00:02.000Z", {"total_token_usage": _totals(300), "last_token_usage": _totals(100)})]
    p6 = _seq_fixture(stale)
    acc6, span6 = {}, [None, None]
    read_codex(p6, acc6, span6, win)
    os.unlink(p6)
    (i6, cr6, cw6, o6, n6, *_r6), = acc6.values()
    rc6, rt6 = _run_main_windowed(_seq_fixture(stale), win)
    want6 = " · INCOMPLETE (1 usage event(s) billed from an unknown baseline)"
    ok6 = (i6, cr6, cw6, o6, n6) == (100, 0, 0, 0, 1) and rc6 == EXIT_PARTIAL and rt6.endswith(want6) and " ×1 · " in rt6
    print(f"selftest F6 malformed event before the window: billed uncached={i6} turns={n6} (expected 100 and 1, NOT 200 — the stale baseline) | exit={rc6} (expected {EXIT_PARTIAL}) line={rt6!r} (expected it to end {want6!r}) — {'PASS' if ok6 else 'FAIL'}")

    # F7: the same malformed event placed AFTER the window end must change nothing — it invalidates a baseline no in-window
    # event ever reads, so the in-window delta stays exact (300 − 100 = 200) and the run is COMPLETE at exit 0.
    late = [("2026-09-04T10:00:00.000Z", {"total_token_usage": _totals(100), "last_token_usage": _totals(100)}),
            ("2026-09-04T10:00:02.000Z", {"total_token_usage": _totals(300), "last_token_usage": _totals(200)}),
            ("2026-09-04T10:00:04.000Z", {"total_token_usage": _totals(400), "last_token_usage": "junk"})]
    win7 = ("2026-09-04T10:00:01.000Z", "2026-09-04T10:00:03.000Z")
    p7 = _seq_fixture(late)
    acc7, span7 = {}, [None, None]
    read_codex(p7, acc7, span7, win7)
    os.unlink(p7)
    (i7, cr7, cw7, o7, n7, *_r7), = acc7.values()
    rc7, rt7 = _run_main_windowed(_seq_fixture(late), win7)
    ok7 = (i7, cr7, cw7, o7, n7) == (200, 0, 0, 0, 1) and rc7 == 0 and "INCOMPLETE" not in rt7 and " ×1 · " in rt7
    print(f"selftest F7 malformed event after the window end: billed uncached={i7} turns={n7} (expected 200 and 1, the exact delta) | exit={rc7} (expected 0) line={rt7!r} (expected no INCOMPLETE) — {'PASS' if ok7 else 'FAIL'}")

    # F8: the recovering event carries NO `last_token_usage` at all. 100 (pre-window, valid) → 200 (pre-window, malformed) →
    # 300 in-window with the key absent → 350 in-window (its own request = 50). The third event cannot be billed from an
    # unknown baseline and must NOT fall back to its cumulative 300; it bills zero and is counted in its own note, while the
    # baseline it re-anchors keeps the fourth event exact at 350 − 300 = 50.
    gap = [("2026-09-04T10:00:00.000Z", {"total_token_usage": _totals(100), "last_token_usage": _totals(100)}),
           ("2026-09-04T10:00:01.000Z", {"total_token_usage": _totals(200), "last_token_usage": "junk"}),
           ("2026-09-04T10:00:02.000Z", {"total_token_usage": _totals(300)}),
           ("2026-09-04T10:00:03.000Z", {"total_token_usage": _totals(350), "last_token_usage": _totals(50)})]
    win8 = ("2026-09-04T10:00:01.500Z", "2026-09-04T10:00:04.000Z")
    p8 = _seq_fixture(gap)
    acc8, span8 = {}, [None, None]
    read_codex(p8, acc8, span8, win8)
    os.unlink(p8)
    (i8, cr8, cw8, o8, n8, *_r8), = acc8.values()
    rc8, rt8 = _run_main_windowed(_seq_fixture(gap), win8)
    want8 = " · INCOMPLETE (1 usage event(s) not billed from an unknown baseline)"
    ok8 = (i8, cr8, cw8, o8, n8) == (50, 0, 0, 0, 1) and rc8 == EXIT_PARTIAL and rt8.endswith(want8) and " ×1 · " in rt8
    print(f"selftest F8 unknown baseline, no last_token_usage: billed uncached={i8} turns={n8} (expected 50 and 1 — the event bills NOTHING, not its cumulative 300, and the next delta stays exact) | exit={rc8} (expected {EXIT_PARTIAL}) line={rt8!r} (expected it to end {want8!r}) — {'PASS' if ok8 else 'FAIL'}")

    allok = ok and ok2 and ok3 and ok4 and ok5 and ok6 and ok7 and ok8
    ex9 = _fixture(100, 20, 30, 7)
    rc9, rt9, notes9 = _run_main_pair(ex9, _child_fixture(False))
    want9 = " · INCOMPLETE (1 unbilled Codex worker thread(s))"
    note9 = any("Codex worker thread(s) with no billable usage record" in n for n in notes9)
    ok9 = rc9 == EXIT_PARTIAL and rt9.endswith(want9) and note9
    print(f"selftest F9 Codex child with NO usage record: exit={rc9} (expected {EXIT_PARTIAL}) line={rt9!r} (expected it "
          f"to end {want9!r}) note named the thread={note9} (expected True) — {'PASS' if ok9 else 'FAIL'}")

    ex10 = _fixture(100, 20, 30, 7)
    rc10, rt10, notes10 = _run_main_pair(ex10, _child_fixture(True))
    ok10 = rc10 == 0 and "INCOMPLETE" not in rt10 and not any("no billable usage record" in n for n in notes10) and " ×2 · " in rt10
    print(f"selftest F10 same child WITH a valid usage event: exit={rc10} (expected 0) line={rt10!r} (expected two billed "
          f"turns and no INCOMPLETE) — {'PASS' if ok10 else 'FAIL'}")

    # F11 — the SAME F9/F10 pairs driven through the bare-path alias. `--codex <executor> <children>` and a bare
    # `<executor> <children>` are documented as the same invocation, so they must reach the same verdict; until loop 13
    # the child-usage check was keyed on the flag, and the alias silently exited 0.
    ex11 = _fixture(100, 20, 30, 7)
    rc11, rt11, notes11 = _run_main_pair(ex11, _child_fixture(False), mode=None)
    # The two runs name DIFFERENT temp children, so the comparable part is the message up to the thread it names; the
    # tail is asserted separately to be this run's own child, not an empty or borrowed name.
    thread_note = lambda ns: next((x for x in ns if "Codex worker thread(s) with no billable usage record" in x), "")
    head = lambda x: x.split("not billed: ")[0]
    tail = lambda x: x.split("not billed: ")[-1] if "not billed: " in x else ""
    same_note = (head(thread_note(notes11)) == head(thread_note(notes9)) != ""
                 and tail(thread_note(notes11)).startswith("selftest-child-"))
    ex11b = _fixture(100, 20, 30, 7)
    rc11b, rt11b, notes11b = _run_main_pair(ex11b, _child_fixture(True), mode=None)
    ok11 = (rc11 == EXIT_PARTIAL and rt11.endswith(want9) and same_note
            and rc11b == 0 and "INCOMPLETE" not in rt11b and " ×2 · " in rt11b)
    print(f"selftest F11 bare-path alias of --codex: unbilled child exit={rc11} (expected {EXIT_PARTIAL}) line={rt11!r} "
          f"(expected it to end {want9!r}) note identical to F9 up to the thread it names={same_note} (expected True) | billed child exit={rc11b} "
          f"(expected 0) line={rt11b!r} (expected two billed turns and no INCOMPLETE) — {'PASS' if ok11 else 'FAIL'}")

    # F12/F13 — a child driven TWICE inside the run. It is billed for EVERY in-window cycle, so a cycle that produced an
    # assistant turn but no usage event is a shortfall even though the thread as a whole billed. Summing the cycles before
    # the test hid that (loop 13).
    exec_win = ("2026-09-04T09:58:00.000Z", "2026-09-04T10:05:00.000Z")
    ex12 = _fixture(100, 20, 30, 7)
    ch12, cyc12 = _cycles_child_fixture({1})   # usage in cycle 1 only
    rc12, rt12, notes12 = _run_main_pair(ex12, ch12, windows={ex12: exec_win, ch12: cyc12})
    want12 = " · INCOMPLETE (1 unbilled Codex worker cycle(s))"
    note12 = next((x for x in notes12 if "Codex worker cycle(s)" in x), "")
    named12 = note12.endswith("cycle 2") and "cycle 1" not in note12   # the UNBILLED cycle, and only it
    ok12 = rc12 == EXIT_PARTIAL and rt12.endswith(want12) and named12
    print(f"selftest F12 child billed in cycle 1, silent in cycle 2: exit={rc12} (expected {EXIT_PARTIAL}) line={rt12!r} "
          f"(expected it to end {want12!r}) note={note12!r} (expected it to name cycle 2 and not cycle 1) — {'PASS' if ok12 else 'FAIL'}")

    ex13 = _fixture(100, 20, 30, 7)
    ch13, cyc13 = _cycles_child_fixture({1, 2})   # both cycles bill
    rc13, rt13, notes13 = _run_main_pair(ex13, ch13, windows={ex13: exec_win, ch13: cyc13})
    ok13 = (rc13 == 0 and "INCOMPLETE" not in rt13 and not any("Codex worker cycle(s)" in x for x in notes13)
            and " ×3 · " in rt13)   # the executor's turn + one per billed cycle: a cycle billed is a cycle counted
    print(f"selftest F13 same child billing in BOTH cycles: exit={rc13} (expected 0) line={rt13!r} (expected three billed "
          f"turns — the executor plus one per cycle — and no INCOMPLETE) — {'PASS' if ok13 else 'FAIL'}")

    # F14 — the boundary of "at or after its start" (loop 14, Astra): OVERLAPPING cycles (cycle 1 open until cycle 2
    # completes, the Session 191 shape) and cycle 1's only usage event stamped EXACTLY at cycle 2's start — inside cycle 1's
    # window, so it is billed, and AT cycle 2's start, so by the stated rule it covers cycle 2. `<=` flagged cycle 2; `<` does not.
    ex14 = _fixture(100, 20, 30, 7)
    ch14, cyc14 = _cycles_child_fixture({1}, usage_ts=cyc12[1][0], overlap=True)   # usage in cycle 1 only, stamped at cycle 2's start
    rc14, rt14, notes14 = _run_main_pair(ex14, ch14, windows={ex14: exec_win, ch14: cyc14})
    ok14 = rc14 == 0 and "INCOMPLETE" not in rt14 and not any("Codex worker cycle(s)" in x for x in notes14)
    print(f"selftest F14 billed event stamped exactly at cycle 2's start: exit={rc14} (expected 0) line={rt14!r} "
          f"(expected no INCOMPLETE — an event AT the start covers the cycle) — {'PASS' if ok14 else 'FAIL'}")

    allok = allok and ok9 and ok10 and ok11 and ok12 and ok13 and ok14
    print("selftest: PASS" if allok else "selftest: FAIL")
    return 0 if allok else 1


def main(argv):
    files = []
    if argv and argv[0] == "--selftest":
        if len(argv) > 1:   # --selftest is a mode, not a filter: trailing arguments would be silently ignored
            print(f"--selftest takes no other arguments; got {argv[1:]}"); return 3
        return selftest()
    if not argv or argv[0] in ("-h", "--help"):
        if len(argv) > 1:
            print(f"{argv[0]} takes no other arguments; got {argv[1:]}"); return 3
        print(__doc__); return 0
    global MARKER, UNBILLED_LAUNCHES, UNBILLED_CODEX_CHILDREN, UNBILLED_CODEX_CYCLES
    if argv.count("--marker") > 1:
        print("--marker given twice"); return 3
    if argv[0] in ("--codex", "--codex-run", "--latest-codex") and "--marker" in argv:
        print(f"--marker does not combine with {argv[0]} (Codex runs are windowed by their own token)"); return 3
    if argv[0] == "--codex" and len(argv) < 2:
        print("--codex needs at least one rollout path (executor first, then its child threads)"); return 3
    if "--marker" in argv and argv[0] != "--marker":   # --marker <token> anywhere else: window the run inside the chosen session
        k = argv.index("--marker")
        if k + 1 >= len(argv):
            print("--marker needs the DIGEST-RUN token"); return 3
        MARKER = argv[k + 1]; argv = argv[:k] + argv[k + 2:]
    if argv and argv[0] in ("--marker", "--session") and len(argv) < 2:
        print(f"{argv[0]} needs a value"); return 3
    if argv and argv[0] in ("--marker", "--session", "--latest-claude", "--codex-run") and len(argv) > (2 if argv[0] != "--latest-claude" else 1):
        print(f"unexpected arguments after {argv[0]}: {argv[2:] if argv[0] != '--latest-claude' else argv[1:]}"); return 3
    if argv[0] in ("--latest-claude", "--marker", "--session"):
        files = [find_claude_session(argv)]
        if argv[0] == "--marker":
            MARKER = argv[1]
    elif argv[0] == "--codex-run":
        files = codex_run_files(argv[1] if len(argv) > 1 else "")
    elif argv[0] == "--latest-codex":
        if len(argv) > 2 or (len(argv) == 2 and not argv[1].isdigit()):
            print("--latest-codex takes an optional whole number"); return 3
        n = int(argv[1]) if len(argv) > 1 else 1
        if n < 1:
            print("--latest-codex needs a count of 1 or more"); return 3
        files = codex_files(n)
    else:
        files = argv[1:] if argv[0] == "--codex" else argv   # `--codex <executor> <children…>` mirrors worker_purity_check; bare paths still work
    mode = argv[0]   # captured before the loop: only --codex-run / --codex declare an executor followed by ITS children
    acc, span = {}, [None, None]
    missing_marker = False
    files = [os.path.expanduser(f) for f in files]
    missing = [f for f in files if not os.path.isfile(f)]
    if missing:   # a bad path must fail as a one-line lookup error, never as a traceback
        print("no such file: " + ", ".join(wpc.tilde(f) for f in missing)); return 3
    if MARKER and any(is_codex(f) for f in files):   # a Codex rollout is windowed by its own token; --marker would be silently ignored
        print("--marker does not apply to Codex rollouts (they are windowed by their own token — use --codex-run <token>)"); return 3
    # `--codex-run` and `--codex` declare an executor followed by ITS children — and so does the BARE-PATH form, which the
    # usage text calls "alias of bare paths; executor first". Before 2026-09-07 the alias was excluded here, so the same
    # executor + unbilled child exited 4 through `--codex` and 0 with no INCOMPLETE through its documented equivalent
    # (GPT-6 Astra, GitHub review loop 13). `--latest-codex` is deliberately NOT an alias: it has no ownership filter, so
    # its extra files are unrelated rollouts, not this executor's children.
    codex_alias = not mode.startswith("--") and bool(files) and is_codex(files[0])
    codex_children = files[1:] if (mode in ("--codex-run", "--codex") or codex_alias) else []
    unbilled_children, unbilled_cycles = [], []
    for f in files:
        if is_codex(f):
            w = CODEX_WINDOW.get(f) if CODEX_WINDOW else None
            if CODEX_WINDOW and not w:   # a child with no window would silently be billed whole-rollout
                print(f"WARNING: {os.path.basename(f)} has no run window — billed whole-rollout")
            read_codex(f, acc, span, w)
            if f in codex_children and not BILLED_CODEX_TURNS:
                # A child selected into the run window that billed NOTHING is as unbilled as a Claude launch with no
                # usage record: the thread was identified, no usage came back, and the totals are short by its whole
                # run. README "a child with no valid usage record" promises this on BOTH runtimes; before 2026-09-07 it
                # was true only for Claude children (GPT-6 Astra, GitHub review loop 12).
                unbilled_children.append(os.path.basename(f)[8:27] or os.path.basename(f))
            elif f in codex_children:
                # The thread billed SOMETHING — but it is billed for every one of its in-window cycles, so a thread that
                # worked in a LATER cycle whose usage never arrived is still short by that cycle (GPT-6 Astra, loop 13).
                # The test cannot be "no billed event inside (cs, ce]": `token_count` carries a CUMULATIVE total and is
                # emitted AFTER the turn it pays for, so a cycle's tokens routinely land past its own task_complete, and
                # a mid-run cycle's tokens are swept up by the NEXT event's delta (cur − prev spans it). What is
                # genuinely lost is work with NO billed event at or after the cycle's start: those tokens were never
                # reported by any later cumulative reading. A cycle counts only when it also produced an ASSISTANT TURN
                # — work that reached the model and returned is billable, an empty cycle (spawned, nothing said) is not
                # a shortfall. The assistant predicate is wpc's kitchen, and it is asked ONLY about cycles that already
                # failed the timestamp test, so a fully billed run walks no extra file.
                for i, (cs, ce) in enumerate(wpc.cycle_window(w)):
                    if LAST_BILLED_CODEX_TS is not None and LAST_BILLED_CODEX_TS < cs and wpc.codex_has_assistant_turn(f, cs, ce):   # strictly before: an event AT the start covers the cycle ("at or after its start", loop 14)
                        unbilled_cycles.append(f"{os.path.basename(f)[8:27] or os.path.basename(f)} cycle {i + 1}")
        else:
            marker_seen = read_claude(f, acc, span, window=True)
            if MARKER and not marker_seen:   # per FILE — a later file that never printed the marker is reported too
                print(f"marker {MARKER!r} was never PRINTED in {os.path.basename(f)} — nothing billed")
                missing_marker = True
                continue
            sid = os.path.splitext(os.path.basename(f))[0]
            print(f"session: {sid}" + ("  (counting the run window: from the printed marker to the next DIGEST-RUN token or end of file)" if MARKER else "  (whole session — pass --marker to count only the run)"))
            subs = [w for w in glob.glob(os.path.join(wpc.worker_dir(f), "*.jsonl")) if os.path.abspath(w) != os.path.abspath(f)]
            # Bill the agents this executor actually LAUNCHED, by agentId — every one of them cost money, tagged or not.
            # Selecting by folder+timestamp instead would bill every SIBLING agent when the executor is itself a subagent
            # (its workers sit flat beside it in the shared subagents/ folder).
            detail = {}
            ids = wpc.launched_agent_ids(f, MARKER, detail=detail)
            picked = [w for w in subs if wpc.agent_file_id(w) in ids]
            if detail.get("without_id"):
                # A launch whose agentId was never recorded cannot be named, and the remaining in-window siblings are NOT a
                # safe stand-in: a delegated executor shares its subagents/ folder with agents it never launched, so billing
                # "the rest" charges this run for someone else's work. Bill only what is named and declare the shortfall.
                UNBILLED_LAUNCHES += detail["without_id"]
                print(f"note: {detail['without_id']} subagent launch(es) without a recorded agentId — their transcripts are not billed; pass their files explicitly to include them")
            subs = picked
            billed_ids = set()
            for w in subs:
                read_claude(w, acc, span if not MARKER else [span[0], span[1]])   # subagents never widen a windowed wall-clock
                if BILLED_MESSAGES:   # BILLED, not merely read: at least one distinct assistant message with a valid usage dict
                    billed_ids.add(wpc.agent_file_id(w))
            unread = sorted(i for i in ids if i not in billed_ids)
            if unread:
                # A launch whose agentId IS recorded but which billed nothing is just as unbilled as one that was never
                # named: the id was selected, no usage came back, and the totals are short by that agent's whole run. A file
                # that exists is not a bill — a transcript holding only metadata / user records, or assistant records with
                # `usage: null`, is as empty a bill as a missing file. Name the ids so the shortfall can be closed by
                # passing the files explicitly.
                UNBILLED_LAUNCHES += len(unread)
                print(f"note: {len(unread)} launched subagent(s) with no billable usage record — not billed: {', '.join(unread)}; pass their files explicitly to include them")
    if unbilled_children:
        UNBILLED_CODEX_CHILDREN += len(unbilled_children)
        print(f"note: {len(unbilled_children)} Codex worker thread(s) with no billable usage record — not billed: "
              f"{', '.join(unbilled_children)}")
    if unbilled_cycles:
        UNBILLED_CODEX_CYCLES += len(unbilled_cycles)
        print(f"note: {len(unbilled_cycles)} Codex worker cycle(s) with an assistant turn but no billable usage record "
              f"— not billed: {', '.join(unbilled_cycles)}")
    if missing_marker:
        return 3
    invalid_note()   # printed BEFORE the empty-accumulator exit: a run whose only events were invalid must still say why
    if not acc:
        print("no usage records found"); return 1
    if any(k.startswith("gpt-") for k, _e in acc):
        print("note: Codex prices = published API list incl. 1.25× cache-write and >272K long-context rules; subscription plans bill differently")
    if LONG_CTX_HITS:
        print(f"note: {LONG_CTX_HITS} Codex request(s) over 272K input billed at the long-context rate")
    print(f"{'model':<20}{'effort':<8}{'turns':>6}{'uncached':>12}{'cache_rd':>12}{'cache_wr5m':>12}{'cache_wr1h':>12}{'output':>10}{'cost $':>9}")
    total, vol, unpriced = 0.0, 0, []
    parts = []
    for (k, eff), (i, cr, cw, o, n, w1, xu, xc, xw, xo) in sorted(acc.items()):
        p = PRICES.get(k)
        c = (i * p[0] + cr * p[1] + cw * p[2] + w1 * p[0] * 2 + o * p[3] + xu * p[0] + xc * p[1] + xw * p[2] + xo * p[3]) / 1e6 if p else None   # 1h cache write = 2× BASE input; xi/xo = the long-context surcharge (cost only — the columns keep ACTUAL tokens)
        total += c or 0
        vol += i + cr + cw + w1 + o
        if c is None: unpriced.append(k)
        print(f"{k:<20}{eff:<8}{n:>6}{i:>12,}{cr:>12,}{cw:>12,}{w1:>12,}{o:>10,}{(f'{c:9.2f}' if c is not None else '      n/a')}")
        parts.append(f"{k} {eff} ×{n}")
    mins = (span[1] - span[0]).total_seconds() / 60 if span[0] and span[1] else 0
    print(f"{'TOTAL':<34}{'':>12}{'':>12}{'':>12}{'':>12}{vol:>10,}{total:9.2f}")
    print(f"wall-clock: {mins:.0f} min ({span[0].strftime('%H:%M') if span[0] else '?'}→{span[1].strftime('%H:%M') if span[1] else '?'} UTC)")
    flag = f" · ⚠ UNPRICED: {', '.join(unpriced)} (total is incomplete — add to PRICES)" if unpriced else ""
    print(f"runtime: {' · '.join(parts)} · {vol/1e6:.1f}M tokens · ${total:.2f} at API list · {mins:.0f} min{flag}{incomplete_mark()}")
    return EXIT_PARTIAL if (INVALID_EVENTS or RECOVERED_EVENTS or UNRECOVERABLE_EVENTS or UNBILLED_LAUNCHES
                            or UNBILLED_CODEX_CHILDREN or UNBILLED_CODEX_CYCLES) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
