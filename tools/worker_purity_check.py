#!/usr/bin/env python3
"""worker_purity_check.py — HARD GATE: did every extraction worker run on the executor's own model + effort?

Claude Code (pipeline Step 6 gate, run from inside the executing session):
  python3 tools/worker_purity_check.py --marker <token>    # the session whose transcript contains the DIGEST-RUN token the
                                                           #   executor printed AT THE RUNTIME GATE (before Step 0); the run
                                                           #   starts at that record — executor model/effort and every worker
                                                           #   launch are taken from that point on, so print it before Step 4
  python3 tools/worker_purity_check.py --session <id>      # a session by id (whole file — warns; use with --after for a window)
  python3 tools/worker_purity_check.py --claude <file>     # a session file (same as --session)
  ... --after HH:MM|ISO      # count only workers launched at/after that time (HH:MM is local; rolls back a day if in the future) —
                             #   the MIXED remedy: wait for a new minute, note it, re-run the named batches as tagged subagents,
                             #   discard the offenders' cards, re-check with --after
  ... --worker-tag TOKEN     # default DIGEST-WORKER: a subagent is an extraction worker iff the PROMPT ITS LAUNCHER PASSED
                             #   (the Agent tool_use `prompt` in the executor's transcript) starts with the tag — this works for
                             #   general-purpose AND fork subagents, and ignores review forks / advisors / helpers
Codex:
  python3 tools/worker_purity_check.py --codex-run <token> # the rollout that PRINTED the DIGEST-RUN token at its SELF-CHECK is the
                                                           #   executor; workers = child threads it spawned inside the run window
                                                           #   (their session_meta names the executor as parent_thread_id) whose
                                                           #   spawn task_name starts with the Codex tag `digest_worker` — the
                                                           #   spawn MESSAGE is encrypted on disk, so the prompt-text tag cannot be
                                                           #   read on Codex; the task_name is stored in clear. Each child is
                                                           #   JUDGED on its LAST in-window task cycle only (task_started →
                                                           #   the task_complete / turn_aborted that closed it, or the window
                                                           #   end if it is still running), so a thread re-driven for another
                                                           #   purpose after the run is not read back into it. COST is the
                                                           #   other half of that rule: session_cost bills EVERY in-window
                                                           #   cycle of a child (all of them were paid for), which is why
                                                           #   codex_run_files hands each child a LIST of cycles and the
                                                           #   purity gate reads only its last entry
                                                           #   A selected cycle that reached task_complete but contains NO
                                                           #   assistant message record is an OFFENDER (`no assistant turn in
                                                           #   its task cycle`) → MIXED: a child that produced no turn cannot
                                                           #   be shown to have run on the executor's model + effort
  python3 tools/worker_purity_check.py --codex <main.jsonl> <worker.jsonl>...   # explicit files (first = executor; ≥1 worker).
                                                           #   There is no run window here, so each child's LAST task cycle is
                                                           #   derived from its OWN task events (last task_started → the first
                                                           #   task_complete / turn_aborted that closed it, else end of file) and
                                                           #   judged by the SAME no-assistant-turn rule as the windowed mode:
                                                           #   a completed child that recorded no assistant message is MIXED

Exit 0 = PURE (every worker on the executor's model AND effort) · 1 = MIXED (offenders named) · 2 = NOTHING-TO-CHECK ·
3 = lookup/usage error (no PURITY line printed — a missing PURITY line is always a FAIL for the run).
PURE REQUIRES EVIDENCE, on both runtime paths: a model or effort that could not be read prints as `unknown` / `?`, and
`? == ?` is not proof of anything. A worker whose effort is unreadable is marked EVIDENCE-MISSING and counted as an
offender; an executor whose own model or effort is unreadable makes every worker an offender ("executor effort
unreadable"), because there is nothing to compare them against. The gate fails CLOSED — MIXED, exit 1 — rather than
reporting PURE off two missing values (GPT-6 Astra, GitHub review loop 12, 2026-09-07). An inline day with no workers
is unaffected: it is still NOTHING-TO-CHECK, since there is no worker whose purity could be in question.
The run window closes at the next DIGEST-RUN-* token printed in the same session (or end of file).
A token counts as PRINTED only when some LINE of an assistant text block, after stripping whitespace, backticks and asterisks,
is exactly the token: quoted mid-sentence, in a tool call or in a paste never counts.
Last line is machine-readable: `PURITY: PURE|MIXED|NOTHING-TO-CHECK · executor <model> <effort> · workers N × <model> <effort>`.
A tagged launch whose transcript is missing or has no assistant turn is reported (not skipped) and fails the gate; a launch that is
still running (async launch with no completion notification yet, or a synchronous launch with no result yet) is NOTHING-TO-CHECK.

Configuration (no machine-specific paths are hardcoded): HUB is derived from this file's own location (tools/ → repo root)
and can be overridden with DIGEST_HUB. Claude Code names a project's transcript folder by taking the working directory's absolute
path and replacing every "/" (and every other non-alphanumeric character, spaces included) with "-", so the searched
folder is derived from HUB under ~/.claude/projects — set CLAUDE_PROJECTS_ROOT to move that root, or DIGEST_CLAUDE_DIRS (colon-separated) to search extra folders. CODEX_SESSIONS_DIR
overrides the Codex rollout root (default ~/.codex/sessions).
"""
import re, glob, json, math, os, sys
from collections import Counter
from datetime import datetime, timedelta

HUB = os.environ.get("DIGEST_HUB") or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CLAUDE_PROJECTS_ROOT = os.environ.get("CLAUDE_PROJECTS_ROOT") or os.path.expanduser("~/.claude/projects")


def claude_project_dir(path):
    """Claude Code's transcript folder for a working directory: its absolute path with every "/" — and every other
    character that is not a letter, a digit or a "-" (spaces included) — replaced by "-", under ~/.claude/projects
    (CLAUDE_PROJECTS_ROOT overrides the root)."""
    return os.path.join(CLAUDE_PROJECTS_ROOT, re.sub(r"[^A-Za-z0-9-]", "-", os.path.abspath(path)))


CLAUDE_DIRS = [claude_project_dir(HUB)]
CLAUDE_DIRS += [d for d in os.environ.get("DIGEST_CLAUDE_DIRS", "").split(":") if d]
CODEX_DIR = os.environ.get("CODEX_SESSIONS_DIR") or os.path.expanduser("~/.codex/sessions")
WORKER_TAG = "DIGEST-WORKER"


USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens")


def _usage_ints(d, base=None):
    """The four USAGE_FIELDS of D as ints. A field that is missing, not a number, or not FINITE (json.loads accepts NaN and
    Infinity) falls back to BASE's value for that field — for a CUMULATIVE dict that means "unchanged since the previous
    event", never a silent drop to 0 that would read as a counter reset and, worse, as a negative delta. With no BASE the
    fallback is 0. This helper never raises: every coercion failure lands on the fallback — a container that is not a dict at
    all (a string, a list, a number) is treated as carrying no fields, so it can never reach .get."""
    base = base if isinstance(base, dict) else {}
    d = d if isinstance(d, dict) else {}
    out = {}
    for f in USAGE_FIELDS:
        v = d.get(f)
        try:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                v = int(v)          # a numeric string still coerces; NaN / Infinity and everything else fall through
            out[f] = int(v)
        except (TypeError, ValueError, OverflowError):
            out[f] = int(base.get(f, 0))
    return out


def usage_delta(cur, prev, last):
    """The billable delta of ONE Codex `token_count` event — the single home of the counter-reset rule, shared by the purity
    gate and session_cost.read_codex. CUR / PREV are `total_token_usage` dicts (cumulative), LAST is the event's own
    `last_token_usage`. With no previous event (PREV is None) the event opens the reading and is billed on its own request.
    When ANY cumulative field DECREASES against PREV the counter has restarted (a context reset / a new thread segment) and
    the event is likewise billed on its own request — a reset signalled by a decreasing INPUT field while the output field
    keeps rising still bills that event's `last_token_usage` output, never the difference. Otherwise it is CUR − PREV
    per field. All three dicts are normalised to ints over USAGE_FIELDS FIRST (a field absent from CUR carries PREV's value —
    an absent cumulative field means unchanged, never 0), so a partial event can neither fake a counter reset nor produce a
    negative. The returned delta is clamped at 0 per field and is never negative. Returns a dict over USAGE_FIELDS."""
    if prev is None:
        src = _usage_ints(last if last else cur)
        return {f: max(src[f], 0) for f in USAGE_FIELDS}
    prev = _usage_ints(prev)
    cur = _usage_ints(cur, prev)
    last = _usage_ints(last)
    if any(cur[f] < prev[f] for f in USAGE_FIELDS):
        return {f: max(last[f], 0) for f in USAGE_FIELDS}   # counter restart: bill this event's OWN request, not a negative delta
    return {f: max(cur[f] - prev[f], 0) for f in USAGE_FIELDS}


def norm(model):
    return (model or "unknown").replace("[1m]", "")


def tilde(path):
    """An absolute path with the home directory folded back to `~` so nothing machine-specific is ever printed."""
    if not path:
        return path
    home = os.path.expanduser("~")
    p = str(path)
    return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone() if s else None


def records(path):
    """Parsed JSONL records; a file that vanishes or cannot be read yields nothing (the caller then reports it), instead of
    aborting the batch. Only OBJECT records are yielded: a line that parses to null, a number, a string or a list is not a
    record and is skipped, so every caller can call .get on what it receives."""
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if isinstance(o, dict):
                yield o


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join((b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text"))   # a block with "text": null joins as empty, never a TypeError
    return ""


PREAMBLE_MARKS = ("<recommended_plugins>", "# AGENTS.md instructions", "<environment_context>")


def is_preamble(txt):
    return any(mk in txt for mk in PREAMBLE_MARKS)


# ---------------------------------------------------------------- Claude Code
def parse_parent(path, marker=None, after=None, out=None):
    """Executor profile + tagged launches from the run window.
    Window = from the first record containing `marker` (if given) to the end; `after` further filters launches.
    OUT, when a dict is passed, receives the raw launch bookkeeping of the window — `agent_ids` (every agentId recorded for an
    Agent launch, tagged or not), `launches` (how many launches the window held) and `without_id` (how many of them never
    recorded an agentId). It is filled BEFORE the "no assistant turns" early return, so a caller that only wants the ids
    always gets them; `after` does NOT filter it (that filter belongs to the tagged-worker loop below)."""
    in_window = marker is None
    marker_seen = False
    exec_turns = {}          # message.id -> (model, effort)
    marker_exec = None       # (model, effort) of the assistant record that printed the marker = the run's executor
    launches = {}            # tool_use_id -> (prompt, timestamp)
    agent_of = {}            # tool_use_id -> agentId
    async_ids, done_ids = set(), set()   # async launches; agentIds whose task-notification has arrived
    failed = {}              # tool_use_id -> error text (launch refused: concurrency limit, permission, outage)
    seen_tokens = set()      # every token printed so far (before and inside the window) — only a NEW one closes the window
    for o in records(path):
        m = o.get("message")
        if not isinstance(m, dict) or m.get("role") != "assistant":
            # task-notifications also arrive as queue-operation / attachment records with no message dict
            done_ids.update(TASK_ID_RE.findall(json.dumps(o, ensure_ascii=False)))
        txt = assistant_text(m) if isinstance(m, dict) and m.get("role") == "assistant" else ""
        if not in_window:
            seen_tokens.update(standalone_tokens(txt))
            if marker in standalone_tokens(txt):
                in_window = True; marker_seen = True
            else:
                continue
        elif marker is not None and txt and closes_window(txt, marker, seen_tokens):
            break   # the next run's token closes this run's window
        seen_tokens.update(standalone_tokens(txt))
        if not isinstance(m, dict):
            continue
        t = ts(o.get("timestamp"))
        if m.get("role") == "assistant" and str(m.get("model", "")).startswith("<"):
            continue   # <synthetic> retry notices carry no model
        if m.get("role") == "assistant":
            exec_turns[m.get("id") or o.get("uuid")] = (norm(m.get("model")), o.get("effort") or "?")
            if marker_exec is None and m.get("model"):
                marker_exec = (norm(m.get("model")), o.get("effort") or "?")
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Agent":
                    launches[b.get("id")] = (str((b.get("input") or {}).get("prompt", "")), t)
        elif m.get("role") == "user":
            r = o.get("toolUseResult")
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in launches:
                    body = text_of(b.get("content"))
                    if isinstance(r, dict) and r.get("agentId"):
                        agent_of[b["tool_use_id"]] = r["agentId"]
                    else:
                        mm = AGENT_ID_RE.search(json.dumps(o, ensure_ascii=False))   # some fork launches record the id only in the result text
                        if mm and not b.get("is_error"):
                            agent_of[b["tool_use_id"]] = mm.group(1)
                    if b.get("is_error") or (isinstance(r, str) and r.lower().startswith("error")):
                        failed[b["tool_use_id"]] = (body or str(r))[:120]
                    elif "Async agent launched" in body:
                        async_ids.add(b["tool_use_id"])   # the agentId arrives at launch; completion comes later as a task-notification
    if marker is not None and not marker_seen:
        print(f"marker {marker!r} was never PRINTED in {os.path.basename(path)} (as a standalone assistant reply line)"); sys.exit(EXIT_LOOKUP)
    if isinstance(out, dict):
        out["agent_ids"] = {agent_of[t] for t in launches if agent_of.get(t)}
        out["launches"] = len(launches)
        out["without_id"] = sum(1 for t in launches if not agent_of.get(t) and t not in failed)   # a REFUSED launch has no transcript to bill, so it never forces the fallback
    if not exec_turns:
        return None, [], 0
    models = Counter(v[0] for v in exec_turns.values()); efforts = Counter(v[1] for v in exec_turns.values())
    majority = (models.most_common(1)[0][0], efforts.most_common(1)[0][0])
    executor = marker_exec if (marker is not None and marker_exec) else majority
    if marker is not None and marker_exec and majority != marker_exec:
        print(f"note: later turns in this session ran on {majority[0]} {majority[1]}; the executor is taken from the record that printed the marker ({marker_exec[0]} {marker_exec[1]})")
    tagged, untagged = [], 0
    for tid, (prompt, t) in launches.items():
        if after and t and t < after:
            continue
        if prompt.lstrip().startswith(WORKER_TAG):
            aid = agent_of.get(tid)
            if tid in failed:
                relaunched = any(p2.strip() == prompt.strip() and t2 and t and t2 > t and tid2 not in failed for tid2, (p2, t2) in launches.items())
                if relaunched:
                    continue   # the executor re-issued the same batch after the refusal — the refusal is superseded
                tagged.append((tid, aid, t, "failed: " + failed[tid])); continue
            running = (aid is None) or (tid in async_ids and aid not in done_ids)
            tagged.append((tid, aid, t, running))
        else:
            untagged += 1
    return executor, tagged, untagged


def profile_claude(path):
    """(model, effort, output tokens, tool calls, turns) — deduplicated by message.id."""
    seen, tools = {}, 0
    for o in records(path):
        m = o.get("message")
        if not (isinstance(m, dict) and m.get("role") == "assistant") or str(m.get("model", "")).startswith("<"):
            continue   # <synthetic> retry notices carry no model
        u = m.get("usage") if isinstance(m.get("usage"), dict) else {}   # a record with "usage": null (or anything not a dict) counts as a turn with 0 output
        seen[m.get("id") or o.get("uuid")] = (norm(m.get("model")), o.get("effort") or "?", (u.get("output_tokens") or 0))
        for b in m.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                tools += 1
    if not seen:
        return None
    models = Counter(v[0] for v in seen.values()); efforts = Counter(v[1] for v in seen.values())
    return models.most_common(1)[0][0], efforts.most_common(1)[0][0], sum(v[2] for v in seen.values()), tools, len(seen)


TOKEN_RE = re.compile(r"DIGEST-RUN-\d{4}-\d{2}-\d{2}-\d{4}")


def standalone_tokens(text):
    """The run tokens TEXT actually PRINTS: a token counts only when some LINE of the assistant text, after stripping
    whitespace, backticks and asterisks, is exactly that token. Quoted mid-sentence, in a tool call or in a paste never
    counts — that is what keeps a narration or a review from selecting (or closing) somebody else's run window.
    This is the one home of the predicate; session_cost.py imports it rather than re-deriving it."""
    out = []
    for line in (text or "").splitlines():
        s = line.strip().strip("`*").strip()
        if TOKEN_RE.fullmatch(s):
            out.append(s)
    return out


QUIET_SECS = 120   # a transcript still being written gets a new record at least this often (one record per content block)
PLACEHOLDER_TOKEN = "DIGEST-RUN-1999-01-01-0000"   # the docs' impossible-date example; quoting it never closes a window
TASK_ID_RE = re.compile(r"<task-id>([0-9a-f]{8,})</task-id>")
AGENT_ID_RE = re.compile(r"agentId[\"\\:\s]+([0-9a-f]{8,})")


def closes_window(text, marker, seen=None):
    """True when TEXT prints a NEW complete run token — one that is not MARKER, not the docs' impossible-date example and
    not already printed earlier in the session (SEEN) — i.e. the next run has started. Re-quoting an earlier token (a Step 11
    narration of the backfill's token), the `<FILE>-<HHMM>` placeholder and prose that merely mentions `DIGEST-RUN-` never
    close a window. Only a STANDALONE-LINE token can close (see standalone_tokens): a token quoted inside a sentence is a
    mention, not a new run. Callers that pass SEEN must add every token they encounter to it as they go."""
    seen = seen or set()
    return any(t != marker and t != PLACEHOLDER_TOKEN and t not in seen for t in standalone_tokens(text))


def assistant_text(m):
    return "\n".join((b.get("text") or "") for b in (m.get("content") or []) if isinstance(b, dict) and b.get("type") == "text") if isinstance(m, dict) else ""


def transcript_finished(path):
    """A subagent transcript is finished when its last assistant MESSAGE (all records sharing that message id — Claude Code
    writes one record per content block) issued no tool call AND the file has been quiet for QUIET_SECS. Either test alone
    misreads a worker mid-turn: a text or thinking block lands before the tool_use block of the same message."""
    last_id, blocks, stop = None, [], None
    for o in records(path):
        m = o.get("message")
        if not (isinstance(m, dict) and m.get("role") == "assistant"):
            continue
        mid = m.get("id") or o.get("uuid")
        if mid != last_id:
            last_id, blocks = mid, []
        blocks.extend(b for b in m.get("content") or [] if isinstance(b, dict))
        stop = m.get("stop_reason")
    if last_id is None:
        return False
    if stop in ("end_turn", "stop_sequence"):
        return True
    if any(b.get("type") == "tool_use" for b in blocks):
        return False
    import time
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return False   # the transcript vanished: conservatively NOT finished, never a traceback
    return time.time() - mt >= QUIET_SECS


CODEX_WORKER_TAG = "digest_worker"   # Codex: spawn_agent task_name prefix (stored in clear; the spawn message is encrypted on disk)
EXIT_LOOKUP = 3   # lookup / usage error — distinct from 2 (NOTHING-TO-CHECK); no PURITY line is printed


def printed_marker_ts(path, token):
    """Timestamp of the first ASSISTANT TEXT block that PRINTS the token as a standalone reply line, else None.
    Tool inputs, tool results, pasted user text and a token quoted mid-sentence do not count — that is how a quoted
    token elsewhere stays harmless (see standalone_tokens).
    The scan is line-by-line (only lines that MENTION the token are parsed at all, so a huge transcript stays cheap) but it
    applies the same OBJECT rule as records(): a line that parses to a bare string, a number or a list is not a record and is
    skipped, so a token sitting inside such a line can never reach .get."""
    try:   # a file that vanishes or cannot be read between the glob and the open is skipped, never a traceback
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            if token not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if not isinstance(o, dict):
                continue   # same OBJECT rule as records(): a bare string / number / list line is not a record
            m = o.get("message")
            if isinstance(m, dict) and m.get("role") == "assistant":
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "text" and token in standalone_tokens(b.get("text") or ""):
                        return o.get("timestamp") or ""
    return None


def find_claude_session(kind, val):
    if kind == "--marker":
        if len(val) < 12:
            print(f"--marker {val!r}: too short to be unique (use the DIGEST-RUN-<FILE>-<HHMM> token)"); sys.exit(EXIT_LOOKUP)
        hits = []
        for d in CLAUDE_DIRS:
            for f in glob.glob(os.path.join(d, "*.jsonl")) + glob.glob(os.path.join(d, "*", "subagents", "*.jsonl")):   # a delegated executor prints the token inside a subagent transcript
                t = printed_marker_ts(f, val)
                if t is not None:
                    hits.append((t, f))
        if not hits:
            print(f"--marker {val!r}: no session PRINTED it as a standalone reply line; quoted mentions do not count"); sys.exit(EXIT_LOOKUP)
        hits.sort()
        if len(hits) > 1:
            print(f"note: {len(hits)} sessions printed the marker; using the earliest ({os.path.basename(hits[0][1])})")
        return hits[0][1]
    if kind == "--claude" or os.path.isfile(val):
        f = os.path.expanduser(val)
        if not os.path.isfile(f):
            print(f"--claude {tilde(val)}: no such file"); sys.exit(EXIT_LOOKUP)
        return f
    for d in CLAUDE_DIRS:
        f = os.path.join(d, val + ".jsonl")
        if os.path.isfile(f):
            return f
    print(f"--session {val}: not found under {[tilde(d) for d in CLAUDE_DIRS]}"); sys.exit(EXIT_LOOKUP)


def worker_dir(f):
    """Where a session's subagent transcripts live: `<sid>/subagents/` beside a top-level session file; a delegated executor
    that is itself a subagent has its workers flat beside it in the same subagents/ folder."""
    d = os.path.dirname(f)
    if os.path.basename(d) == "subagents":
        return d
    return os.path.join(d, os.path.splitext(os.path.basename(f))[0], "subagents")


AGENT_FILE_RE = re.compile(r"^agent-([0-9a-fA-F]+)\.jsonl$")


def agent_file_id(path):
    """The agentId a subagent transcript is named for (`agent-<id>.jsonl`), or None for any other file in the folder."""
    m = AGENT_FILE_RE.match(os.path.basename(path or ""))
    return m.group(1) if m else None


def launched_agent_ids(path, marker=None, detail=None):
    """The set of agentIds the session at PATH actually LAUNCHED inside the run window (from the printed MARKER onward, or the
    whole file when MARKER is None) — every Agent tool_use/tool_result pair, tagged worker or not. This is what a caller
    should select `agent-<id>.jsonl` files by: a delegated executor that is ITSELF a subagent shares its subagents/ folder
    with every sibling agent, so picking by folder (or by timestamp) bills work it never launched.
    DETAIL, when a dict is passed, also receives `launches` and `without_id` — a launch whose agentId was never recorded
    cannot be named; session_cost counts such launches as unbilled and marks its result INCOMPLETE (exit 4) rather than guessing."""
    out = {}
    try:
        parse_parent(path, marker, None, out=out)
    except SystemExit:   # an unprinted marker is the caller's own lookup error to report; here it simply means "no launches"
        pass
    if isinstance(detail, dict):
        detail.update({"launches": out.get("launches", 0), "without_id": out.get("without_id", 0)})
    return out.get("agent_ids", set())


def run_claude(kind, val, after, marker=None):
    f = find_claude_session(kind, val)
    sid = os.path.splitext(os.path.basename(f))[0]
    marker = val if kind == "--marker" else marker
    if marker is None:
        print("WARNING: no --marker — the executor profile covers the WHOLE session history; a session that switched model/effort before `run news` will be misread. Prefer --marker.")
    executor, tagged, untagged = parse_parent(f, marker, after)
    print(f"session: {sid}")
    if not executor:
        print("PURITY: NOTHING-TO-CHECK · no assistant turns in the run window"); return 2
    exec_model, exec_eff = executor
    print(f"executor: {exec_model} · {exec_eff}" + ("  (from the marker onward)" if marker else ""))
    if untagged:
        print(f"  ({untagged} subagent launch(es) without the {WORKER_TAG!r} prefix — review forks / advisors / helpers — ignored)")
    subdir = worker_dir(f)
    workers, bad, inflight = [], [], 0
    for tid, aid, t, running in tagged:
        if isinstance(running, str):
            bad.append((tid[:14], "tagged launch " + running)); continue
        if running:
            w = os.path.join(subdir, f"agent-{aid}.jsonl") if aid else None
            if w and transcript_finished(w):
                pass   # the notification was not seen (window closed first) but the transcript ended cleanly
            else:
                inflight += 1; continue   # no result yet, or an async launch whose task-notification has not arrived
        w = os.path.join(subdir, f"agent-{aid}.jsonl")
        if not os.path.isfile(w):
            bad.append((aid[:14], "tagged launch but no transcript on disk")); continue
        p = profile_claude(w)
        if not p:
            bad.append((aid[:14], "tagged transcript with no assistant turn")); continue
        workers.append((aid[:14], p))
    exec_evidence = ("executor effort unreadable" if exec_eff == "?" else
                     "executor model unreadable" if exec_model == "unknown" else None)   # no evidence = never PURE
    for name, (m, e, out, tools, turns) in workers:
        missing = (e == "?" or m == "unknown")
        ok = not missing and exec_evidence is None and m == exec_model and e == exec_eff
        mark = "EVIDENCE-MISSING" if (missing or exec_evidence) else ("ok" if ok else "MIXED")
        print(f"  worker {name:<16} {m:<18} {e:<7} out={out:>7} tools={tools:>3} turns={turns:>3}  {mark}")
        if not ok:
            bad.append((name, exec_evidence or f"{m} {e}"))
    for name, why in bad:
        if not any(name == n for n, _ in workers):
            print(f"  MIXED  {name:<16} {why}")
    if bad:   # a MIXED verdict is never masked by workers still running
        wc0 = Counter((m, e) for _, (m, e, *_r) in workers)
        wdesc0 = " + ".join(f"{n} × {m} {e}" for (m, e), n in wc0.most_common()) or "0"
        print(f"PURITY: MIXED · executor {exec_model} {exec_eff} · workers {wdesc0} · offenders: " + ", ".join(f"{n}={w}" for n, w in bad) + (f" · {inflight} still running" if inflight else "")); return 1
    if inflight:
        print(f"PURITY: NOTHING-TO-CHECK · {inflight} tagged worker(s) still running (no result recorded yet) — wait for them to finish and re-run"); return 2
    if not workers and not bad:
        print("PURITY: NOTHING-TO-CHECK · no tagged worker launches in the window (inline day, or the workers were not launched with the tag)"); return 2
    wc = Counter((m, e) for _, (m, e, *_r) in workers)
    wdesc = " + ".join(f"{n} × {m} {e}" for (m, e), n in wc.most_common()) or "0"
    print(f"PURITY: PURE · executor {exec_model} {exec_eff} · workers {wdesc}"); return 0


# ---------------------------------------------------------------- Codex
def codex_meta(path, at=None, since=None):
    """Session meta + model/effort (+ first prompt, output tokens). With AT (an ISO timestamp), model/effort are the ones in
    force AT that moment — the executor is what printed the token, not whatever the REPL switched to afterwards.
    SINCE (an ISO timestamp) is the lower bound of a task cycle: it bounds the cycle-scoped readings (first prompt, output
    tokens) but deliberately NOT model/effort, which stay "the last record with ts <= AT" — a model switch made BEFORE the
    cycle opened is still the one in force during it, and a cycle that carries no switch of its own must not read `unknown`.
    The cycle-scoped output is the SUM of the per-event deltas inside the cycle, not "cumulative at AT minus cumulative before
    SINCE": when a cumulative DECREASES the counter has restarted (context reset / new thread segment) and that event is billed
    on its own `last_token_usage`, so a reset inside the cycle no longer swallows the output that preceded it. The reset is
    judged on the FULL cumulative dict via usage_delta (the same home session_cost uses), so a reset signalled by a decreasing
    input field while output keeps rising is caught too; the first in-cycle event's PREV is the last full cumulative dict
    recorded before SINCE (None when the cycle opens the thread). The baseline is the NORMALISED counters (_usage_ints
    against the previous baseline) and is persisted after EVERY token_count event, including one that omits a field —
    mirroring read_codex: keeping the raw dict would let the omission read as 0 one event later, hiding a counter reset."""
    meta, model, eff, first_prompt, out, base = {}, None, "?", None, 0, None
    for o in records(path):
        p = o.get("payload")
        if not isinstance(p, dict):
            continue
        raw = o.get("timestamp") or ""
        if at and raw > at and (p.get("model") or p.get("reasoning_effort") or p.get("effort")):
            continue   # a later model/effort switch does not belong to this run
        cycle = not (since and raw < since) and not (at and raw > at)
        if o.get("type") == "session_meta" and not meta:   # a forked child carries the parent's session_meta too — only the FIRST is its own
            spawn = ((p.get("source") or {}).get("subagent") or {}).get("thread_spawn") if isinstance(p.get("source"), dict) else None
            meta = {"id": p.get("id"), "cwd": p.get("cwd"), "originator": p.get("originator"), "start": p.get("timestamp") or o.get("timestamp"),
                    "parent": (spawn or {}).get("parent_thread_id"), "task": os.path.basename((spawn or {}).get("agent_path") or "")}
        if p.get("model"):
            model = p["model"]
        if p.get("reasoning_effort") or p.get("effort"):
            eff = p.get("reasoning_effort") or p.get("effort")
        if cycle and first_prompt is None and p.get("type") in ("user_message", "message") and p.get("role", "user") == "user":
            txt = text_of(p.get("content")) or str(p.get("message", ""))
            if txt.strip() and not is_preamble(txt):   # the first user record is the harness preamble, not the paste
                first_prompt = txt
        if p.get("type") == "token_count" and isinstance(p.get("info"), dict):
            tot_u = p["info"].get("total_token_usage")
            if not tot_u:
                continue
            if not isinstance(tot_u, dict):
                continue   # a malformed usage container makes the event INVALID: it contributes nothing and does not move the baseline
            last_u = p["info"].get("last_token_usage")
            last_u = last_u if isinstance(last_u, dict) else {}
            if not since:
                cum = tot_u.get("output_tokens")
                if cycle and cum is not None:
                    out = cum         # whole-thread reading: the cumulative total as of AT
                base = _usage_ints(tot_u, base)
                continue
            if raw < since:
                base = _usage_ints(tot_u, base)   # the last FULL cumulative reading just before the cycle opened
            elif cycle:               # cycle-scoped: sum the per-event DELTAS, reset-aware (same rule as session_cost.read_codex)
                out += usage_delta(tot_u, base, last_u)["output_tokens"]
                base = _usage_ints(tot_u, base)   # the NORMALISED baseline is persisted after EVERY event, including one that omitted a field
    return meta, norm(model), eff, first_prompt or "", out


def codex_task_events(path):
    """[(ts, type)] for every task_started / task_complete / turn_aborted event of a thread — one cycle per task it was driven with."""
    out = []
    for o in records(path):
        p = o.get("payload") or {}
        if isinstance(p, dict) and p.get("type") in ("task_started", "task_complete", "turn_aborted"):
            out.append((o.get("timestamp") or "", p["type"]))
    return out


def codex_state(path):
    """'done' (last task event task_complete) · 'running' (task_started) · 'aborted' (turn_aborted) · 'empty'."""
    ev = codex_task_events(path)
    if not ev:
        return "empty"
    return {"task_complete": "done", "task_started": "running", "turn_aborted": "aborted"}[ev[-1][1]]


def codex_cycles(path, start, end):
    """EVERY task cycle of a child thread inside the run window (START, END], oldest first: a list of (cycle_start,
    cycle_end) where cycle_start is the ts of a task_started in the window and cycle_end the ts of the first
    task_complete / turn_aborted that closed it INSIDE the window — or END when no such event falls in (cycle_start, END],
    i.e. the cycle is still running as far as this run is concerned. The closing search is bounded by END so a completion
    that happened AFTER the run window can never be pulled back into it. Empty when the thread was never driven inside the
    window. A thread re-driven for something else AFTER the run is never read back in either way.
    The two consumers split on this list: the PURITY gate judges a child on its LAST entry only (the batch it was last
    driven with inside the run), while session_cost BILLS every entry — each in-window cycle was separately paid for."""
    ev = codex_task_events(path)
    out = []
    for cs in (t for t, k in ev if k == "task_started" and start < t <= end):
        ce = next((t for t, k in ev if cs < t <= end and k in ("task_complete", "turn_aborted")), end)
        out.append((cs, ce))
    return out


def codex_has_assistant_turn(path, cs, ce):
    """True when the thread recorded at least one ASSISTANT MESSAGE (payload type "message", role assistant) inside the
    cycle (CS, CE]. A cycle that reached task_complete with no such record produced nothing that can be checked against the
    executor's model + effort, so the purity gate must report it as an offender rather than count it as a clean worker."""
    for o in records(path):
        raw = o.get("timestamp") or ""
        if not (cs < raw <= ce):
            continue
        p = o.get("payload")
        if isinstance(p, dict) and p.get("type") == "message" and p.get("role") == "assistant":
            return True
    return False


def cycle_window(w):
    """The cycle list for one rollout, normalised: codex_run_files hands the EXECUTOR a bare (start, end) tuple and every
    CHILD a list of cycles, so both consumers discriminate here (a bare tuple has a string first element) instead of
    re-deriving the rule. Returns a list of (start, end); an empty/None window returns []."""
    if not w:
        return []
    return [tuple(w)] if isinstance(w[0], str) else [tuple(c) for c in w]


def cycle_state(path, ce, cs=None):
    """'done' / 'aborted' / 'running' for the cycle that ended at CE — the event that closed it, or none yet. CS (the cycle
    start) bounds the search from below, so only an event belonging to THIS cycle can report it closed."""
    for t, k in codex_task_events(path):
        if t == ce and k in ("task_complete", "turn_aborted") and (cs is None or t > cs):
            return "done" if k == "task_complete" else "aborted"
    return "running"


def run_codex(files, after, untagged=0, at=None, windows=None):
    if not files:
        print("--codex needs the executor rollout and at least one worker rollout"); return EXIT_LOOKUP
    main = files[0]
    meta, em, ee, fp, _ = codex_meta(main, at=at)
    print(f"executor rollout: {os.path.basename(main)[8:27]} · {em} · {ee} · cwd={tilde(meta.get('cwd'))}")
    if untagged:
        print(f"  ({untagged} child thread(s) whose task_name does not start with {CODEX_WORKER_TAG!r} — helpers / reviewers — ignored)")
    workers, bad, inflight = [], [], 0
    exec_evidence = ("executor effort unreadable" if ee == "?" else
                     "executor model unreadable" if em == "unknown" else None)   # no evidence = never PURE
    for w in files[1:]:
        cycles = cycle_window((windows or {}).get(w))   # a child's in-window cycles under --codex-run; explicit --codex has none
        cyc = cycles[-1] if cycles else None   # the gate judges the LAST in-window cycle; session_cost bills all of them
        if cyc:
            cs, ce = cyc
            m, wm, we, wfp, out = codex_meta(w, at=ce, since=cs)   # ce is bounded by the run window, so nothing after it leaks in
            state = cycle_state(w, ce, cs)
            st = ts(cs)
        else:
            m, wm, we, wfp, out = codex_meta(w)
            ev = codex_task_events(w)
            starts = [t for t, k in ev if k == "task_started"]
            cs = starts[-1] if starts else first_ts(w)   # the LAST task the thread was driven with (followup_task re-uses threads)
            st = ts(cs) if cs else None
            state = codex_state(w)
            if cs:   # explicit --codex has no run window, so the child's LAST task cycle is derived from its OWN task events:
                     #   cs → the first task_complete / turn_aborted that closed it, else the end of the file
                ce_own = next((t for t, k in ev if t > cs and k in ("task_complete", "turn_aborted")), None) or last_ts(w) or cs
                cyc = (cs, ce_own)   # judged by codex_has_assistant_turn exactly as in the windowed mode
        name = os.path.basename(w)[8:27]
        if after and st and st < after:
            continue
        if state == "aborted":
            bad.append((name, "thread aborted before task_complete — spawn a fresh tagged thread for that batch")); continue
        if wm == "unknown" or state != "done":
            inflight += 1; print(f"  worker {name} still running"); continue   # no model record yet, or no task_complete for its last task
        if cyc and not codex_has_assistant_turn(w, cyc[0], cyc[1]):
            bad.append((name, "no assistant turn in its task cycle")); continue   # completed with nothing to check = never PURE
        missing = (we == "?")   # an unknown MODEL is already routed to `inflight` above; an unknown EFFORT was not
        ok = not missing and exec_evidence is None and wm == em and we == ee
        mark = "EVIDENCE-MISSING" if (missing or exec_evidence) else ("ok" if ok else "MIXED")
        print(f"  worker {name} {wm:<14} {we:<7} out={out:>7}  {mark}")
        workers.append((name, (wm, we)))
        if not ok:
            bad.append((name, exec_evidence or f"{wm} {we}"))
    if bad:
        wc0 = Counter(v for _, v in workers); wdesc0 = " + ".join(f"{n} × {m} {e}" for (m, e), n in wc0.most_common())
        print(f"PURITY: MIXED · executor {em} {ee} · workers {wdesc0} · offenders: " + ", ".join(f"{n}={w}" for n, w in bad) + (f" · {inflight} still running" if inflight else "")); return 1
    if inflight:
        print(f"PURITY: NOTHING-TO-CHECK · {inflight} tagged worker thread(s) still running — wait for them to finish and re-run"); return 2
    if not workers:
        print(f"PURITY: NOTHING-TO-CHECK · no child thread with task_name {CODEX_WORKER_TAG}* spawned by the executor inside the run window (inline day, or spawned without the tag — on an --after re-check: the replacements were not spawned as tagged threads)"); return 2
    wc = Counter(v for _, v in workers); wdesc = " + ".join(f"{n} × {m} {e}" for (m, e), n in wc.most_common())
    if bad:
        print(f"PURITY: MIXED · executor {em} {ee} · workers {wdesc} · offenders: " + ", ".join(f"{n}={w}" for n, w in bad)); return 1
    print(f"PURITY: PURE · executor {em} {ee} · workers {wdesc}"); return 0


def codex_run_files(token):
    """Executor = the rollout that PRINTED the DIGEST-RUN token as a standalone reply line (earliest wins); workers = child
    threads (session_meta parent_thread_id = executor) driven inside the run window whose spawn task_name starts with
    CODEX_WORKER_TAG. Returns (files, untagged_children, windows) where WINDOWS maps every rollout — the executor AND every
    child, tagged or not — to what it is judged and billed on: the executor to a bare (start, end) tuple for the run window,
    each child to a LIST of every in-window task cycle it was driven with. Both callers key off that dict (through
    cycle_window), so no rollout is ever read whole by accident; the purity gate then reads a child's LAST cycle while
    session_cost bills every one of them."""
    if not token or len(token) < 12:
        print("--codex-run needs the DIGEST-RUN-<FILE>-<HHMM> token the Codex executor printed at its SELF-CHECK"); sys.exit(EXIT_LOOKUP)
    files = glob.glob(os.path.join(CODEX_DIR, "*", "*", "*", "rollout-*.jsonl"))
    files.sort(key=lambda x: os.path.basename(x)[8:27])
    hits = []
    for f in files:
        try:   # a rollout that vanishes between the glob and the open is skipped, never a traceback
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if token not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if not isinstance(o, dict):
                    continue   # same OBJECT rule as records(): a bare string / number / list line is not a record
                p = o.get("payload") or {}
                if isinstance(p, dict) and p.get("role") == "assistant" and p.get("type") == "message" and token in standalone_tokens(text_of(p.get("content"))):   # the executor's own reply, printed as a standalone line (output_text); agent_message envelopes, user pastes and mid-sentence quotes do not count
                    hits.append((o.get("timestamp") or "", f)); break
    if not hits:
        print(f"--codex-run: no rollout PRINTED {token!r} as a standalone assistant reply line (quoted mentions do not count)"); sys.exit(EXIT_LOOKUP)
    hits.sort()
    start, mainf = hits[0]   # the rollout whose RECORD printing the token is earliest = the executor; later mentions are reviews or the next session quoting it
    end = codex_window_end(mainf, token, start)
    exec_id = codex_meta(mainf)[0].get("id")
    def driven_in_window(f):   # spawned OR re-driven (followup_task) inside the window — a re-used thread has an old first record
        return any(start < t <= end for t, k in codex_task_events(f) if k == "task_started")
    children = [(f, m) for f, m in ((f, codex_meta(f)[0]) for f in files if (first_ts(f) or "") <= end) if m.get("parent") == exec_id and driven_in_window(f)]
    workers = [f for f, m in children if (m.get("task") or "").startswith(CODEX_WORKER_TAG)]
    others = [f for f, m in children if f not in workers]
    windows = {mainf: (start, end)}
    for f, _m in children:
        cycles = codex_cycles(f, start, end)
        if cycles:
            windows[f] = cycles
    return [mainf] + workers, others, windows   # (executor + tagged workers, untagged children — helpers/reviewers: ignored by purity, billed by cost)


def first_ts(path):
    for o in records(path):
        if o.get("timestamp"):
            return o["timestamp"]
    return None


def last_ts(path):
    """The timestamp of the rollout's last stamped record — the upper bound of a cycle that never recorded a closing event."""
    last = None
    for o in records(path):
        if o.get("timestamp"):
            last = o["timestamp"]
    return last


def codex_window_end(path, token, start):
    """The run window in a Codex rollout: from the printed token to the next different complete token printed by the
    executor, else the rollout's last record. Worker rollouts must have STARTED inside it."""
    last = start
    seen = set()
    for o in records(path):
        t = o.get("timestamp") or ""
        p = o.get("payload") or {}
        txt = text_of(p.get("content")) if isinstance(p, dict) and p.get("role") == "assistant" and p.get("type") == "message" else ""
        if t <= start:
            seen.update(standalone_tokens(txt))   # tokens printed before/at the marker (earlier runs, the example beside it) never close
            continue
        if txt and closes_window(txt, token, seen):
            return t
        seen.update(standalone_tokens(txt))
        last = max(last, t)
    return last


def parse_after(val):
    now = datetime.now().astimezone()
    try:
        if len(val) <= 5:
            h, mnt = val.split(":"); a = now.replace(hour=int(h), minute=int(mnt), second=0, microsecond=0)
            return a - timedelta(days=1) if a > now else a
        return datetime.fromisoformat(val).astimezone()
    except ValueError:
        print(f"--after {val!r}: not HH:MM or ISO"); sys.exit(EXIT_LOOKUP)


def main(argv):
    global WORKER_TAG
    after = None
    worker_tag_given = False
    if "--worker-tag" in argv:
        i = argv.index("--worker-tag")
        if i + 1 >= len(argv): print("--worker-tag needs a value"); return EXIT_LOOKUP
        WORKER_TAG = argv[i + 1]; argv = argv[:i] + argv[i + 2:]; worker_tag_given = True
    if "--after" in argv:
        i = argv.index("--after")
        if i + 1 >= len(argv): print("--after needs HH:MM or an ISO timestamp"); return EXIT_LOOKUP
        after = parse_after(argv[i + 1]); argv = argv[:i] + argv[i + 2:]
        print(f"counting only workers launched at/after {after.strftime('%Y-%m-%d %H:%M %Z')} (earlier launches = superseded offenders, skipped)")
    marker = None
    if argv and argv[0] in ("--codex", "--codex-run") and worker_tag_given:   # the flag is stripped before the mode is known, so it is checked here
        print(f"--worker-tag does not apply to {argv[0]} (Codex workers are identified by the fixed {CODEX_WORKER_TAG!r} task_name prefix — the spawn prompt is encrypted on disk)"); return EXIT_LOOKUP
    if argv and argv[0] in ("--codex", "--codex-run") and "--marker" in argv:
        print(f"--marker does not combine with {argv[0]} (Codex runs are windowed by their own token)"); return EXIT_LOOKUP
    if argv and argv[0] != "--marker" and "--marker" in argv:   # `--session <id> --marker <token>`: window that session by the token
        i = argv.index("--marker")
        if i + 1 >= len(argv): print("--marker needs the DIGEST-RUN token"); return EXIT_LOOKUP
        marker = argv[i + 1]; argv = argv[:i] + argv[i + 2:]
    if not argv or argv[0] in ("-h", "--help"):
        if len(argv) > 1:   # `--help <junk>`: a usage error, not a request for the docstring
            print(f"{argv[0]} takes no other arguments; got {argv[1:]}"); return EXIT_LOOKUP
        print(__doc__); return EXIT_LOOKUP
    if argv[0] in ("--marker", "--session", "--claude", "--codex-run") and len(argv) != 2:
        print(f"{argv[0]} takes exactly one value; got {argv[1:]}"); return EXIT_LOOKUP
    if argv[0] in ("--marker", "--session", "--claude"):
        return run_claude(argv[0], argv[1], after, marker)
    if argv[0] == "--codex-run":
        files, others, windows = codex_run_files(argv[1])
        return run_codex(files, after, len(others), at=windows[files[0]][0], windows=windows)   # the EXECUTOR's entry is a bare (start, end) tuple, so [0] is the run-window start (children hold cycle LISTS)
    if argv[0] == "--codex":
        if len(argv) < 3:
            print("--codex needs the executor rollout and at least one worker rollout"); return EXIT_LOOKUP
        paths = [os.path.expanduser(a) for a in argv[1:]]
        missing = [q for q in paths if not os.path.isfile(q)]
        if missing:   # a bad path must fail as a one-line lookup error, never as a traceback
            print("--codex: no such file: " + ", ".join(tilde(q) for q in missing)); return EXIT_LOOKUP
        return run_codex(paths, after)
    print(__doc__); return EXIT_LOOKUP


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
