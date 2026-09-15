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
  python3 tools/worker_purity_check.py --selftest          # self-contained synthetic transcripts (v6.26): the finish rule's
                                                           #   cut, killed, failed, resumed and still-running shapes, the
                                                           #   complete shapes that stay PURE, and a Codex child cut
                                                           #   mid-cycle; exit 0 = every check passed. Reads nothing under
                                                           #   ~/.claude or ~/.codex
  python3 tools/worker_purity_check.py --selftest --census # the same, then the finish rule over EVERY real subagent
                                                           #   transcript on this machine whose parent holds a notice
                                                           #   (~/.claude/projects, files older than 30 minutes): every worker
                                                           #   the parent reports killed or failed must flag — through the
                                                           #   real gate, on its real transcript and real notice records —
                                                           #   every file the loop-1 rule flagged must still flag, a
                                                           #   sample of 20 completed text-ending workers must not, and
                                                           #   every completed worker the parent notified more than once
                                                           #   must flag once its file is cut back to the parent's
                                                           #   previous notice (loop 3), every resume a parent's
                                                           #   SendMessage got accepted must read still running as parent
                                                           #   and worker stood at that moment, and every failed resume
                                                           #   attempt must leave the verdict as it was (loop 4)

Exit 0 = PURE (every worker on the executor's model AND effort) · 1 = MIXED (offenders named) · 2 = NOTHING-TO-CHECK ·
3 = lookup/usage error (no PURITY line printed — a missing PURITY line is always a FAIL for the run).
PURE REQUIRES EVIDENCE, on both runtime paths: a model or effort that could not be read prints as `unknown` / `?`, and
`? == ?` is not proof of anything. A COMPLETED worker whose model OR effort is unreadable is marked EVIDENCE-MISSING
and counted as an offender — on Codex, "still running" is decided by the cycle state alone, never by a missing model; an executor whose own model or effort is unreadable makes every worker an offender ("executor effort
unreadable"), because there is nothing to compare them against. The gate fails CLOSED — MIXED, exit 1 — rather than
reporting PURE off two missing values (GPT-6 Astra, GitHub review loop 12, 2026-09-07). An inline day with no workers
is unaffected: it is still NOTHING-TO-CHECK, since there is no worker whose purity could be in question. But a run
with subagent launches that carry NO tag and no tagged worker at all is MIXED, not NOTHING-TO-CHECK: something was
launched and nothing about it can be read, which is the opposite of nothing to check (/kun M5).
The run window closes at the next token OF THE SAME FAMILY printed in the same session (or end of file): a
DIGEST-RUN window closes only at the next DIGEST-RUN-* token. A second
family, `DUAL-REVIEW-GEN <G>`, is the line a dual-review execute-mode reviewer prints first (G is the generation id,
`DUAL-REVIEW-GEN-<YYYYMMDD>-<6 hex>`); the skill's `check --run` reads it to find the reviewer's own window, and it
never opens or closes a digest window.
A token counts as PRINTED only when some LINE of an assistant text block, after stripping whitespace, backticks and asterisks,
is exactly the token: quoted mid-sentence, in a tool call or in a paste never counts.
Last line is machine-readable: `PURITY: PURE|MIXED|NOTHING-TO-CHECK · executor <model> <effort> · workers N × <model> <effort>`.
A tagged launch whose transcript is missing or has no assistant turn is reported (not skipped) and fails the gate; a launch that is
still running (async launch with no completion notification yet, or a synchronous launch with no result yet, or a worker the parent
resumed after its last notification) is NOTHING-TO-CHECK.
A launch result that says the worker runs in the background — `Async agent launched …`, or a fork's `Fork started —
processing in background` — is an async launch (v6.26 loop 3; Astra loop 2, N2).
FINISHED BEFORE JUDGED (Claude Code; v6.26 — execute-mode GATE 4 finding 1, then Astra's loop-1 H1–H3, loop-2 N1 and loop-3 N3–N4):
A finished worker is judged only when its transcript shows it finished: the parent's notification, when there is one, says completed, a final reply follows its last tool call, any earlier notification and any follow-up message that resumed it, the file holds every tool call the notification counts, and the file ends on a newline.
A worker the parent reports stopped or failed, or a transcript cut before its final reply, is EVIDENCE-MISSING and the run is MIXED.
A worker with no notification and no final reply is still running.
The offender's own line reads `worker killed by parent` / `worker failed by parent` (any status but `completed`, whatever
the transcript looks like), or `transcript incomplete (<why>)` with <why> one or more of `ends mid tool_use` · `no
finishing reply after the last tool call` · `ends before its finishing turn` · `no trailing newline` · `notice counts N
tool calls, file holds M`. A worker the parent notified more than once (re-driven after it finished) is judged on its
LAST run — the records after the parent's previous notification — so <why> then opens `last run: `, reads `no assistant
message` when nothing of that run is on disk, and counts as `notices count P then N tool calls, last run holds M` (see
transcript_incomplete); that run begins on a message boundary, so a message the boundary splits is read whole (loop 4).
A worker whose FOLLOW-UP MESSAGE RESUMED it — the parent's SendMessage came back accepted (`Resuming agent …`) after the
worker's last notification — is running again: that older notification is not the notification for its current run,
so it is still running until one arrives, unless its file is quiet and the run from the resume onward already ends on a
finishing reply (the no-notice rule). A resume attempt that failed resumed nothing (v6.26 loop 4; Astra loop 3, N3).
Not covered: a message `queued for delivery … at its next tool round` to a worker whose run then ends before that round
also starts a new run, with no resume record to see (seen on one real worker, 2026-09-09); noted for the next version.
These are indicators read from what is on disk and from the parent's notice — positive
evidence that the worker finished, not a proof that every transcript is whole (see completion_gap). Codex children are
judged by task-cycle state, which a cut rollout cannot pass: its cycle never closes, so it reads `still running`, never
PURE.

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


# A dated snapshot id — `claude-haiku-4-5-20251001` — is the same model as its base, priced identically.
SUFFIX_DATE_RE = re.compile(r"-\d{8}$")


def norm(model):
    """A model id with its no-cost decorations removed: the `[1m]` context marker and a trailing `-YYYYMMDD`
    snapshot date. THE ONE HOME, imported by session_cost (/kun #2, F9).

    There were two of these. This one stripped `[1m]` only; session_cost's stripped the date as well, because its
    price lookup is an exact match and a dated id has no row of its own. They agreed on every id either had seen,
    which is exactly the shape of a trap: the purity gate would have read `claude-opus-5-20260401` as a DIFFERENT
    model from the executor's `claude-opus-5` and called a pure run MIXED, while the cost tool priced them the
    same."""
    if not model:
        return "unknown"
    return SUFFIX_DATE_RE.sub("", model.replace("[1m]", ""))


def tilde(path):
    """An absolute path with the home directory folded back to `~` so nothing machine-specific is ever printed."""
    if not path:
        return path
    home = os.path.expanduser("~")
    p = str(path)
    return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone() if s else None


def _stamp(value):
    """A Claude Code record's timestamp as ts() reads it, or None when it is missing or not an ISO timestamp — never an
    exception. The last-run boundary (last_notice → last_assistant_message) compares a worker's records with its
    parent's notices on this one clock."""
    try:
        return ts(value) if isinstance(value, str) else None
    except ValueError:
        return None


# Codex rollout timestamps are compared as STRINGS — `start < t <= end` for the run window and every task cycle.
# That is correct only while every timestamp is the same fixed-width UTC form, because lexical order equals
# chronological order only then. It held on all 6,023 records measured and was asserted nowhere, so a producer that
# switched to an offset (`+05:30`) or dropped the milliseconds would have silently reordered every window rather
# than failing (/kun L13).
TS_CANON_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")


def ts_ok(value):
    """True when VALUE is the canonical fixed-width UTC stamp that string comparison is valid for."""
    return isinstance(value, str) and bool(TS_CANON_RE.fullmatch(value))


def require_ts(value, where):
    """VALUE, or exit 3 naming the record. Called wherever a timestamp is about to be ORDERED as a string — an
    unusable stamp is a lookup error (the code this tool already uses for "I cannot answer"), never a silently
    wrong window."""
    if value == "" or ts_ok(value):   # "" is the sentinel lower bound codex_cycles_all documents, never a record stamp (codex_records rejects those)
        return value
    print(f"timestamp {value!r} in {where} is not the canonical YYYY-MM-DDTHH:MM:SS.mmmZ form these comparisons "
          f"order as strings — refusing to guess the ordering", file=sys.stderr)
    sys.exit(EXIT_LOOKUP)


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


def codex_records(path):
    """Every record of a Codex rollout, with its timestamp VALIDATED at the point of parse (Astra loop 1, finding 4).

    `require_ts` used to guard the task events only, so `codex_meta` and `codex_turn_runtimes` still ordered raw
    strings. An offset stamp (`…T15:30:02.000+05:30`) sorts BEFORE the same instant written as `…T10:00:02.000Z`,
    which silently moved a turn out of its cycle: Astra's repro fed one Luna/low turn at an offset stamp into a
    Sol/xhigh cycle and the gate reported no unreadable turns and no offenders — a hidden turn, not a caught one.

    Validating in the READER rather than at each comparison is what makes that structural: a new function that walks
    a rollout inherits the guarantee instead of having to remember it."""
    base = os.path.basename(path)
    for o in records(path):
        raw = o.get("timestamp")
        if not isinstance(raw, str) or raw == "":
            # A record with NO usable stamp cannot be placed in any cycle window, so a comparison would silently drop
            # it. That is harmless for inert records but fatal for evidence: an assistant turn, a model-bearing
            # context, or a task/usage event with a null, empty, false or missing timestamp is UNREADABLE evidence —
            # exit 3, never a silent PURE (v6.24 loop 3; Astra's null/empty probe hid a Luna turn behind PURE).
            pl = o.get("payload")
            if isinstance(pl, dict) and (is_assistant_work(pl) or pl.get("model") or pl.get("reasoning_effort")
                                          or pl.get("effort") or pl.get("type") in ("token_count", "task_started", "task_complete")):
                print(f"record in {base} carries evidence ({pl.get('type') or 'model context'}) but no usable timestamp "
                      f"({raw!r}) — cannot place it in any cycle; refusing to judge", file=sys.stderr)
                sys.exit(EXIT_LOOKUP)
            yield o
            continue
        require_ts(raw, f"{base} record")
        yield o


# The two SENTINEL bounds `codex_cycles_all` documents: "" sorts before every ISO stamp and "~" (0x7E) after every
# one. They are deliberately not timestamps, so the bound check has to know them by name rather than reject them.
TS_SENTINELS = ("", "~")


SKIPPED_HEADS = []        # rollouts the discovery scan could not read a canonical head timestamp from


def scan_records(path):
    """Every record of a rollout, for the DISCOVERY scan — lenient about timestamps, and it stops at the first
    unreadable one.

    THE STRICT READER IS FOR EVIDENCE, NOT FOR CANDIDATES (/kun #2, F3). `codex_records` exits 3 on a stamp that
    cannot be ordered as a string, which is right for the executor and the children whose model and effort are
    being judged: a mis-ordered turn there is a wrong verdict. But `codex_run_files` calls `first_ts` and
    `head_meta` on EVERY rollout under ~/.codex/sessions — 1,027 of them, 2.09 GB, none of them belonging to this
    digest — and one malformed stamp in a stranger's session would have exited 3 on every digest lookup, including
    a historical cost query. A rollout whose head cannot be read is not a candidate; it is counted and named once
    on stderr, and the scan goes on."""
    base = os.path.basename(path)
    for o in records(path):
        if not ts_ok(o.get("timestamp") or ""):
            SKIPPED_HEADS.append(base)
            return
        yield o


def require_bound(value, what):
    """A cycle bound (`at`, `since`, `cs`, `ce`) is compared against record stamps as a string, so it has to be the
    same shape — or one of the two sentinels that mean "unbounded". None is left alone."""
    return value if not value or value in TS_SENTINELS else require_ts(value, what)


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
    notice_hist = {}         # agentId -> every copy of every task-notification for it, in file order (v6.26 loops 2–3)
    notice_at, envs = {}, set()   # agentId -> file position where its latest distinct notice was first written (loop 4)
    sends, resumed = {}, {}  # SendMessage tool_use_id -> its `to`; agentId -> [(file position, timestamp)] per accepted resume
    failed = {}              # tool_use_id -> error text (launch refused: concurrency limit, permission, outage)
    seen_tokens = set()      # every token printed so far (before and inside the window) — only a NEW one closes the window
    for pos, o in enumerate(records(path)):
        m = o.get("message")
        if not isinstance(m, dict) or m.get("role") != "assistant":
            # task-notifications also arrive as queue-operation / attachment records with no message dict
            dumped = json.dumps(o, ensure_ascii=False)
            done_ids.update(TASK_ID_RE.findall(dumped))
            for n_aid, n_status, n_calls, n_env in record_notices(o, dumped):
                # a resumed worker notifies again: the LAST notice is its state, and the one before it opens its last run
                notice_hist.setdefault(n_aid, []).append((n_status, n_calls, n_env, o.get("timestamp")))
                if (n_aid, n_env) not in envs:
                    envs.add((n_aid, n_env)); notice_at[n_aid] = pos
            for r_aid in accepted_resumes(o, sends):
                resumed.setdefault(r_aid, []).append((pos, o.get("timestamp")))   # the parent started a new run of it
        elif isinstance(m, dict) and m.get("role") == "assistant":
            sends.update((b.get("id"), str((b.get("input") or {}).get("to") or "")) for b in m.get("content") or []
                         if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "SendMessage")
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
                    elif any(mk in body for mk in ASYNC_LAUNCH_MARKS):
                        async_ids.add(b["tool_use_id"])   # the agentId arrives at launch; completion comes later as a task-notification
    if marker is not None and not marker_seen:
        print(f"marker {marker!r} was never PRINTED in {os.path.basename(path)} (as a standalone assistant reply line)"); sys.exit(EXIT_LOOKUP)
    if isinstance(out, dict):
        out["agent_ids"] = {agent_of[t] for t in launches if agent_of.get(t)}
        out["launches"] = len(launches)
        out["without_id"] = sum(1 for t in launches if not agent_of.get(t) and t not in failed)   # a REFUSED launch has no transcript to bill, so it never forces the fallback
    if not exec_turns:
        return None, [], []
    models = Counter(v[0] for v in exec_turns.values()); efforts = Counter(v[1] for v in exec_turns.values())
    majority = (models.most_common(1)[0][0], efforts.most_common(1)[0][0])
    executor = marker_exec if (marker is not None and marker_exec) else majority
    if marker is not None and marker_exec and majority != marker_exec:
        print(f"note: later turns in this session ran on {majority[0]} {majority[1]}; the executor is taken from the record that printed the marker ({marker_exec[0]} {marker_exec[1]})")
    # UNTAGGED is a LIST of (tool_use_id, agent_id), not a count (Astra loop 1, finding 6). A verdict that says "1
    # launch could not be read" and does not say WHICH leaves the operator grepping a 40 MB transcript for it.
    notice_of = {a: last_notice(h) for a, h in notice_hist.items()}
    # REOPENED (v6.26 loop 4; Astra loop 3, N3). A resume the parent's SendMessage got ACCEPTED started a new run of the
    # worker, and a notice written before it says nothing about that run — a real worker read PURE on its previous run
    # for the 4.381 s between the accepted resume (17:24:01.982Z) and its first new assistant record (17:24:06.363Z); of
    # the census's 102 real accepted resumes, read as they stood when accepted, loop 3 read 91 PURE and the other 11 on
    # the failed notice the resume had just superseded (`worker failed by parent`). So a resume recorded
    # after the worker's latest notice was first written, or of a worker with no notice, opens a run no notice has
    # closed: the worker is still running, and REOPENED holds that resume's time (the LAST such resume's), from which the
    # no-notice rule in run_claude reads its last run. Positions, not clocks, order the two: both are records of this file.
    # A notice written after the resume closes that run, and the loop-3 last-run judgment applies unchanged.
    reopened = {}
    for a, rs in resumed.items():
        later = [r for r in rs if r[0] > notice_at.get(a, -1)]
        if later:
            reopened[a] = _stamp(later[-1][1]) or LAST_RUN_UNREADABLE
    tagged, untagged = [], []
    for tid, (prompt, t) in launches.items():
        if after and t and t < after:
            continue
        if prompt.lstrip().startswith(WORKER_TAG):
            aid = agent_of.get(tid)
            if tid in failed:
                relaunched = any(p2.strip() == prompt.strip() and t2 and t and t2 > t and tid2 not in failed for tid2, (p2, t2) in launches.items())
                if relaunched:
                    continue   # the executor re-issued the same batch after the refusal — the refusal is superseded
                tagged.append((tid, aid, t, "failed: " + failed[tid], None, None)); continue
            reopen = reopened.get(aid) if aid else None
            running = (aid is None) or (tid in async_ids and aid not in done_ids) or reopen is not None
            # NOTICE is what the parent says about how the worker ENDED — last_notice's (status, tool calls, last-run start,
            # previous tool calls) — and is judged before the transcript (v6.26 loops 2–3). None while the worker is still
            # running. An async worker whose id was seen with no readable envelope gets no status: a notice without a status
            # is not a completed one. A synchronous launch has no notification at all; its returned tool_result is the
            # completion evidence.
            notice = None if running else notice_of.get(aid) or ((None, None, None, None) if tid in async_ids
                                                                  else ("completed", None, None, None))
            tagged.append((tid, aid, t, running, notice, reopen))
        else:
            untagged.append((tid, agent_of.get(tid)))
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


def turn_verdict(turns, em, ee):
    """Judge a worker's evidenced turns against the executor's (model, effort). Returns (unreadable, offenders): a turn whose
    model or effort could not be read is UNREADABLE (EVIDENCE-MISSING — no evidence is never PURE); a readable turn that does
    not match the executor is an OFFENDER. One home for both runtimes, so the Claude and Codex gates cannot drift."""
    unreadable = [t for t in turns if t[1] == "unknown" or t[2] == "?"]
    offenders = [t for t in turns if t not in unreadable and (t[1], t[2]) != (em, ee)]
    return unreadable, offenders


def turn_why(unreadable, offenders):
    """The offender text for a per-turn failure: the offending (model, effort) and the timestamp of the turn that carried it,
    plus a count when more than one turn is involved. Named turns are what make the verdict actionable — 'this worker is
    MIXED' does not say which turn to look at."""
    if unreadable:
        t = unreadable[0]
        return f"unreadable runtime ({t[1]} {t[2]}) at {t[0]}" + (f" (+{len(unreadable) - 1} more turn(s))" if len(unreadable) > 1 else "")
    t = offenders[0]
    return f"{t[1]} {t[2]} at {t[0]}" + (f" (+{len(offenders) - 1} more off-runtime turn(s))" if len(offenders) > 1 else "")


def claude_turn_runtimes(path):
    """(ts, model, effort) for EVERY distinct assistant message in a Claude transcript, deduplicated by message id exactly
    as profile_claude does (Claude Code writes one record per content block, all sharing the id). profile_claude returns the
    MAJORITY pair, which is the right summary for the printed line but the wrong thing to gate on: a worker that ran two
    pinned turns and one off-runtime turn has a pinned majority and is not pure (GPT-6 Astra full pass, finding 1, repro R2).
    The gate reads this list; the printed line still shows the majority."""
    seen = {}
    for o in records(path):
        m = o.get("message")
        if not (isinstance(m, dict) and m.get("role") == "assistant") or str(m.get("model", "")).startswith("<"):
            continue   # <synthetic> retry notices carry no model — same exclusion as profile_claude
        seen[m.get("id") or o.get("uuid")] = (o.get("timestamp") or "", norm(m.get("model")), o.get("effort") or "?")
    return list(seen.values())


TOKEN_RE = re.compile(r"DIGEST-RUN-\d{4}-\d{2}-\d{2}-\d{4}"   # digest runs
                      r"|DUAL-REVIEW-GEN DUAL-REVIEW-GEN-\d{8}-[0-9a-f]{6}")               # a dual-review execute-mode reviewer's window (`DUAL-REVIEW-GEN <G>`)


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
NOTICE_STATUS_RE = re.compile(r"<status>([A-Za-z_-]+)</status>")   # a status that is not one plain word reads as no status
NOTICE_CALLS_RE = re.compile(r"<tool_uses>(\d+)</tool_uses>")
# A launch result saying the worker runs in the BACKGROUND — its completion arrives later as a task-notification. The real
# vocabulary on this machine (2026-09-12, 968 Agent launch results): `Async agent launched successfully. …
# The agent is working in the background.` (931) and `Fork started — processing in background` (34, every one inside a
# fork child's own transcript, where its launch is inherited history). The fork wording used to read as a SYNCHRONOUS
# result, so a fork worker with no notice was judged as already finished (v6.26 loop 3; Astra loop 2, N2).
ASYNC_LAUNCH_MARKS = ("Async agent launched", "Fork started", "background")
LAST_RUN_UNREADABLE = "unreadable"   # last_notice's last-run start when no copy of the previous notice has a timestamp
# A SendMessage result saying the parent RESUMED a stopped worker — a new run of it has started (v6.26 loop 4; Astra loop
# 3, N3). The real vocabulary on this machine (2026-09-12, 122 accepted resumes): `{"success":true,
# "message":"Resuming agent <7-char id>","resumedAgentId":…}` (119), the same with the id only under `pin` (1), and an
# older wording, `Agent "<id>" was stopped (failed|completed); resumed it in the background with your message.` (2).
# NOT a resume: `success:false … could not be resumed: No transcript found` (13 failed attempts — nothing ran), and
# `Message queued for delivery to <id> at its next tool round.` (146 — the worker was still running, so no new run).
RESUME_MARKS = ("Resuming agent", "resumed it in the background")


def record_notices(o, dumped=None):
    """[(agent id, status, tool calls, envelope)] for every task-notification envelope in record O, in the order they
    appear — the parent's own word on how a worker ENDED (v6.26 loop 2; Astra loop 1, H2). STATUS is the envelope's
    `<status>`, None when it has none; TOOL CALLS is its `<usage><tool_uses>` count as an int, None when it has none;
    ENVELOPE is the envelope's own text, what tells two copies of one notice from two notices (last_notice). DUMPED is
    O as json.dumps already produced it (parse_parent dumps each record once for TASK_ID_RE).

    The real vocabulary, read from every transcript on this machine on 2026-09-12: `completed` (3,447
    envelopes), `failed` (151 — an API error ended the worker) and `killed` (79 — "Agent … was stopped by Claude"). No
    `stopped` or `interrupted` status exists. A Monitor event arrives in the same envelope with no status and a non-hex
    id, so TASK_ID_RE never keys it. `<tool_uses>` counts the worker's client `tool_use` blocks (server-side tool calls
    are not in it) — on every worker whose last notice says completed (815 in Astra's 851-worker population, 820 in the
    live census) it never exceeds the file's own count. A completed notice always carries it; a killed or failed one
    never does. A resumed worker's later notice counts its own run, or its own run on top of the count before it
    (transcript_incomplete). Each envelope is read up to the next envelope's start
    as well as its own close, so a notice quoted inside another one's <result> text cannot lend it its status or count.
    An ASSISTANT record never carries the parent's notice: an envelope quoted in the executor's own reply is a mention."""
    m = o.get("message")
    if isinstance(m, dict) and m.get("role") == "assistant":
        return []
    s = dumped if dumped is not None else json.dumps(o, ensure_ascii=False)
    out = []
    for seg in s.split("<task-notification>")[1:]:
        seg = seg.split("</task-notification>", 1)[0]
        aid, status, calls = TASK_ID_RE.search(seg), NOTICE_STATUS_RE.search(seg), NOTICE_CALLS_RE.search(seg)
        if aid:
            out.append((aid.group(1), status.group(1) if status else None, int(calls.group(1)) if calls else None, seg))
    return out


def send_results(o, sends):
    """[(tool_use_id, result JSON)] for every SendMessage result in record O (v6.26 loop 4). SENDS maps each SendMessage
    call's tool_use id to its `to`; a result answering any other call is skipped. The JSON is the record's
    `toolUseResult` and, when that carries no `success`, the tool result's own text, which holds the same JSON; None when
    neither reads."""
    m = o.get("message")
    out = []
    for b in (m.get("content") if isinstance(m, dict) and isinstance(m.get("content"), list) else []):
        if not (isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in sends):
            continue
        r = o.get("toolUseResult")
        if not (isinstance(r, dict) and "success" in r):
            try:
                r = json.loads(text_of(b.get("content")))
            except ValueError:
                r = None
        out.append((b["tool_use_id"], r if isinstance(r, dict) else None))
    return out


def resumed_agent(r, to):
    """The agent id a SendMessage result R resumed — R says so (RESUME_MARKS, or it names a `resumedAgentId`) and
    `success` is true — else None. The id is its `resumedAgentId`, else `pin.id`, else the call's TO. A failed attempt
    (`success:false`) resumed nothing (v6.26 loop 4)."""
    if not (isinstance(r, dict) and r.get("success") is True):
        return None
    if not (r.get("resumedAgentId") or any(mk in str(r.get("message") or "") for mk in RESUME_MARKS)):
        return None
    pin = r.get("pin") if isinstance(r.get("pin"), dict) else {}
    return str(r.get("resumedAgentId") or pin.get("id") or to or "") or None


def accepted_resumes(o, sends):
    """The agent ids whose RESUME record O accepted — the parent's SendMessage result saying a stopped worker was resumed,
    so a new run of it has started (v6.26 loop 4; Astra loop 3, N3). Read by send_results, judged by resumed_agent."""
    return [a for a in (resumed_agent(r, sends[tid]) for tid, r in send_results(o, sends)) if a]


def last_notice(history):
    """(status, tool calls, last-run start, previous tool calls) for one worker from HISTORY — every copy of every notice
    the parent holds for it, in file order, as (status, tool calls, envelope, record timestamp) — or None when HISTORY is
    empty. THE ONE FOLD, used by parse_parent and by the census (v6.26 loop 3; Astra loop 2, N1).

    STATUS and TOOL CALLS are the LAST copy's in file order — the loop-2 rule, unchanged. The parent usually writes a
    notice more than once, byte for byte (the queue record, the delivered message, attachments: in the live census 784 of
    the 970 distinct envelopes have exactly two copies, 185 have three to eleven and 1 has one), so copies with the same
    envelope text are ONE notice, and a different text is a different notice — each carries its own `<result>` and
    `<duration_ms>`.
    A worker the parent re-drove after it finished (a SendMessage, or a background task waking it) notifies once per run,
    and each notice closes one run, so its LAST run starts after the notice before the last one. LAST-RUN START is the
    earliest timestamp among that previous notice's copies, as a datetime: None when the worker has one notice (the
    whole file is its run), LAST_RUN_UNREADABLE when no copy of the previous notice has a readable timestamp. PREVIOUS
    TOOL CALLS is that previous notice's `<tool_uses>`, None when it carries none."""
    if not history:
        return None
    status, calls, env, _t = history[-1]
    prev = [h for h in history if h[2] != env]
    if not prev:
        return status, calls, None, None
    penv = prev[-1][2]
    stamps = [s for s in (_stamp(h[3]) for h in history if h[2] == penv) if s is not None]
    return status, calls, (min(stamps) if stamps else LAST_RUN_UNREADABLE), prev[-1][1]


def token_family(token):
    """Which KIND of run a token opens and closes: `DUAL-REVIEW-GEN` (a dual-review execute-mode reviewer) or
    `DIGEST-RUN` (this pipeline)."""
    t = token or ""
    return "DUAL-REVIEW-GEN" if t.startswith("DUAL-REVIEW-GEN") else "DIGEST-RUN"


def closes_window(text, marker, seen=None):
    """True when TEXT prints a NEW complete run token OF THE SAME FAMILY as MARKER — one that is not MARKER, not the
    docs' impossible-date example and not already printed earlier in the session (SEEN) — i.e. the next run of this
    kind has started. Re-quoting an earlier token (a Step 11 narration of the backfill's token), the `<FILE>-<HHMM>`
    placeholder and prose that merely mentions `DIGEST-RUN-` never close a window. Only a STANDALONE-LINE token can
    close (see standalone_tokens): a token quoted inside a sentence is a mention, not a new run. Callers that pass
    SEEN must add every token they encounter to it as they go.

    THE FAMILY TEST is why a run of another kind in the middle of a digest session no longer truncates the digest's
    window. `TOKEN_RE` matches every family, and until v6.23 any different token closed any window — so a standalone
    token of another family printed after the digest's token ended the digest's run early, hiding every worker launched
    afterwards from the purity gate and every turn afterwards from the cost (code-review run 1, finding 4). A DIGEST-RUN
    window now closes only at the next DIGEST-RUN token, and a DUAL-REVIEW-GEN window only at the next one of its own."""
    seen = seen or set()
    fam = token_family(marker)
    return any(t != marker and t != PLACEHOLDER_TOKEN and t not in seen and token_family(t) == fam
               for t in standalone_tokens(text))


def assistant_text(m):
    return "\n".join((b.get("text") or "") for b in (m.get("content") or []) if isinstance(b, dict) and b.get("type") == "text") if isinstance(m, dict) else ""


def last_assistant_message(path, since=None):
    """The LAST assistant MESSAGE of a Claude transcript — THE ONE GROUPER, shared by transcript_finished, finish_gap and
    transcript_incomplete. Claude Code writes one record per content block, all sharing the message id, so a message is
    every consecutive record carrying that id. Returns (message id, its content blocks in order, the stop_reason of its
    LAST record, the tool_use ids a `tool_result` answered in any record from that message's first record onward, the
    number of distinct client `tool_use` ids in the WHOLE file — what a notice's `<tool_uses>` counts); the id is None
    when the file holds no assistant record.
    SINCE (v6.26 loop 3), a datetime from last_notice — or, loop 4, the resume that started a worker's current run — reads
    the worker's LAST run only, and the fifth value is then the tool calls of that run alone; the id is None when nothing
    of that run is on disk. The run begins on a MESSAGE boundary (loop 4; Astra loop 3, N4): at the first record of the
    message that holds the first assistant record stamped after SINCE, and every record from there on counts, in file
    order. A message the boundary splits is read whole, in the later run: its first block can be written before the
    parent's notice for the run before it (transcript_incomplete), and a later block cannot belong to a run that had
    already ended."""
    last_id, blocks, stop, answered, calls = None, [], None, set(), set()

    def take(o):
        nonlocal last_id, blocks, stop, answered
        m = o.get("message")
        if not (isinstance(m, dict) and m.get("role") == "assistant"):
            if isinstance(m, dict) and isinstance(m.get("content"), list):
                answered.update(b.get("tool_use_id") for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result")
            return
        mid = m.get("id") or o.get("uuid")
        if mid != last_id:
            last_id, blocks, answered = mid, [], set()   # only a result recorded after THIS message can answer its calls
        new = [b for b in m.get("content") or [] if isinstance(b, dict)]
        blocks.extend(new)
        calls.update(b.get("id") for b in new if b.get("type") == "tool_use")
        stop = m.get("stop_reason")

    started, held, held_id = since is None, [], None   # HELD: the records of the message in progress, until SINCE is passed
    for o in records(path):
        if started:
            take(o); continue
        m = o.get("message")
        asst = isinstance(m, dict) and m.get("role") == "assistant"
        if asst and (m.get("id") or o.get("uuid")) != held_id:
            held, held_id = [], m.get("id") or o.get("uuid")   # an earlier message ended wholly before SINCE: its run closed
        if held_id is not None:
            held.append(o)
        t = _stamp(o.get("timestamp")) if asst else None
        if t is not None and t > since:
            started = True
            for h in held:   # this message's records from its first one on, the ones stamped before SINCE included
                take(h)
    return last_id, blocks, stop, answered, len(calls)


def transcript_finished(path):
    """A subagent transcript is finished when its last assistant MESSAGE (all records sharing that message id — Claude Code
    writes one record per content block) issued no tool call AND the file has been quiet for QUIET_SECS. Either test alone
    misreads a worker mid-turn: a text or thinking block lands before the tool_use block of the same message.
    This answers only "has the file stopped moving?" — the RUNNING decision. Quiet is not finished: run_claude also asks
    finish_gap before it judges a worker with no notice (v6.26 loop 2, Astra H3)."""
    last_id, blocks, stop, _answered, _calls = last_assistant_message(path)
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


def finish_gap(last):
    """Why the transcript's LAST assistant message is not a FINISHING REPLY, or None when it is (v6.26 loop 2). LAST is
    last_assistant_message's tuple. A finishing reply calls no tool, no tool result is recorded after it, and it ends on a
    text block or carries end_turn / stop_sequence. Anything else is a transcript that stops before the reply the worker
    finished with:
      `ends mid tool_use` — the message calls a tool no later record answers (loop 1's first test, kept word for word);
      `no finishing reply after the last tool call` — the calls were answered, or a tool result follows the message, and no
         assistant message comes after that (Astra H1: a newline-aligned cut right after a tool result read PURE —
         answered calls prove nothing about the reply that should have followed them; one real worker ends this way);
      `ends before its finishing turn` — no tool call, but the last block is thinking or a server-side tool block and the
         stop reason is neither end_turn nor stop_sequence (loop 1's second test, now without its null-stop condition).
    A null stop_reason on a final TEXT reply is how Claude Code writes an ordinary ending — 536 of the 851 notified worker
    transcripts on this machine end on a null stop (528 completed + 8 killed), and 529 of those end on text (528 completed
    + 1 killed) — so the text test is what keeps the ordinary ending, and the parent's status, not the
    tail, is what catches the one killed worker that ends on text (completion_gap)."""
    last_id, blocks, stop, answered, _calls = last
    if last_id is None:
        return "no assistant message"
    calls = [b.get("id") for b in blocks if b.get("type") == "tool_use"]
    if any(c not in answered for c in calls):
        return "ends mid tool_use"
    if calls or answered:
        return "no finishing reply after the last tool call"
    if (blocks and blocks[-1].get("type") == "text") or stop in ("end_turn", "stop_sequence"):
        return None
    return "ends before its finishing turn"


def ends_in_newline(path):
    """True / False for the file's last byte being "\\n" (Claude Code ends every record with one, so a last line without it
    was cut mid-write); None when the file cannot be read to its end. records() skips an unparsable line by design, so
    this reads the last byte directly."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            if not fh.tell():
                return True
            fh.seek(-1, os.SEEK_END)
            return fh.read(1) == b"\n"
    except OSError:
        return None


def transcript_incomplete(path, notice_calls=None, since=None, prev_calls=None):
    """Why a worker's transcript does not show that it FINISHED — a list of reasons, empty when it does (v6.26; loop 1
    from execute-mode GATE 4 finding 1, loop 2 from Astra's H1–H3, loop 3 from her N1, loop 4 from her N3–N4).
    NOTICE_CALLS, SINCE and PREV_CALLS are last_notice's tool calls, last-run start and previous tool calls for this
    worker; all three are None when the parent holds no notice, and SINCE is None when it holds one — except for a
    worker the parent resumed after its last notice, whose SINCE is that resume's time (see the end of this note).

    A completion notice proves the worker FINISHED. It proves nothing about the model and effort of turns that are not
    on disk, and every other part of this gate judges only the turns it can read — so a cut file used to read PURE on
    the turns that happened to survive. The GATE 4 fixture kept 12 of a real worker's 62 records and the parent kept its
    notice: `PURITY: PURE`, exit 0. No evidence is never PURE, and 50 missing turns are missing evidence. Three
    independent indicators, each one a cut this file cannot explain any other way:
      1. the tail — finish_gap: the last message must be a finishing reply;
      2. `no trailing newline` — the file's last byte, read directly (`last byte unreadable` when it cannot be read);
      3. `notice counts N tool calls, file holds M` — the notice counted more tool calls than the file holds, so calls are
         missing from disk. One-sided on purpose: a file may hold MORE than its notice counts (80 of the 820 completed
         workers here do, none holds fewer — a fork's inherited history, or a resumed worker's earlier runs), so
         "fewer on disk" is the only direction that means a cut. It is what catches a newline-aligned cut between a message's text block and
         its tool_use block — the surviving text looks exactly like a final reply.
    A RESUMED worker — one the parent notified more than once — is judged on its LAST run (v6.26 loop 3): the records from
    the first one stamped after SINCE, in file order. An earlier run's final reply and tool calls cannot stand in for a
    later run that is missing (Astra loop 2, N1: a worker cut right after its first run, both notices kept, read PURE).
    Indicators 1 and 2 read that run, the reasons open `last run: `, and a run with nothing on disk reads `no assistant
    message`. Indicator 3 reads the pair of notices, because Claude Code counts a later run in one of two ways — on the 67
    completed workers here notified more than once, every pair of consecutive notices that both carry a count does one
    or the other: 77 pairs count the run alone, 21 count it on top of the previous count, 1 fits both (a previous count
    of 0), 0 fit neither; 9 more pairs follow a notice that carries no count. So:
      - the later notice counts FEWER than the previous one (N < P): a new count, so the last run must hold N calls;
      - the later notice counts at least as many (N ≥ P): the run alone or on top of P, so the last run must hold N − P;
      - the previous notice carries no count (killed, failed): the file must hold N, as indicator 3.
    That reason reads `notices count P then N tool calls, last run holds M`. When N ≥ P a run counted alone is held only
    to N − P, the weaker reading, so that no whole worker flags. A SINCE of LAST_RUN_UNREADABLE fails closed (`last run:
    previous notice has no timestamp`).
    THE BOUNDARY is the previous notice's own time, and it falls on a MESSAGE boundary (loop 4; Astra loop 3, N4). A
    notice is written a few seconds after its run ends, and when the parent's next message reaches the worker inside that
    gap the last run's first records are stamped before it: on one real worker the re-drive and the thinking block of a
    message whose tool call lands after the notice. Loop 3 cut at the first RECORD after it, which can split one message:
    Astra's boundary-split has the tool call before the notice and the same message's text after it, and read PURE on the
    text alone. The run now begins at the first record of the message holding its first assistant record after the
    notice (last_assistant_message), so a split message is read whole, in the later run — and on the 67 completed
    workers here notified more than once, exactly one has a boundary that splits a message: giving that message to
    the EARLIER run instead would leave its run 4 of the 5 calls its notices count, and flag a whole worker. What the
    boundary still leaves out is a message written wholly inside the gap. That can only lower the last run's count or
    leave it with no message — MIXED, not a wrong PURE (Astra's fast-zero-second, a whole text-only run finished before
    the previous notice, reads MIXED for that reason).
    A worker RESUMED after its last notice, with no notice since (loop 4), comes here only through run_claude's no-notice
    rule: NOTICE_CALLS and PREV_CALLS are None and SINCE is the resume's time, so indicators 1 and 2 read the run the
    resume started and there is no count to hold it to.
    These are indicators, not a proof that a transcript is whole: a file cut after a final text reply, with no notice
    to count against, has nothing on disk to show it."""
    if since == LAST_RUN_UNREADABLE:
        return ["last run: previous notice has no timestamp"]
    last = last_assistant_message(path, since)
    why = []
    gap = finish_gap(last)
    if gap:
        why.append(gap)
    nl = ends_in_newline(path)
    if nl is None:
        why.append("last byte unreadable")   # fail closed: a file that cannot be read to its end is not shown to be whole
    elif not nl:
        why.append("no trailing newline")
    if notice_calls is not None:
        if since is not None and prev_calls is not None:
            need = notice_calls if notice_calls < prev_calls else notice_calls - prev_calls
            if last[4] < need:
                why.append(f"notices count {prev_calls} then {notice_calls} tool calls, last run holds {last[4]}")
        else:
            held = last[4] if since is None else last_assistant_message(path)[4]
            if notice_calls > held:
                why.append(f"notice counts {notice_calls} tool calls, file holds {held}")
    if since is not None and why:
        why[0] = "last run: " + why[0]
    return why


def completion_gap(path, notice=None, since=None):
    """The offender text for a worker whose transcript does not show it finished, or None when it does — THE ONE
    JUDGEMENT, called by run_claude for every worker it judges and by the census for every real worker (v6.26 loop 2).
    NOTICE is last_notice's (status, tool calls, last-run start, previous tool calls) for this worker, or None when the
    parent holds none (a quiet worker run_claude let through only after transcript_finished AND finish_gap). SINCE, for a
    worker with no notice, is the time of the resume that started its current run (v6.26 loop 4): that run is then the
    one read, as for a notified worker's last run, with no count to hold it to.
    THE PARENT'S WORD COMES FIRST: a status other than `completed` is the verdict whatever the transcript looks like — a
    killed worker can end on an ordinary text line (Astra H2: a real worker ends "Both sites block WebFetch (403). Let
    me try firecrawl scrape as a fallback fetcher." and its parent says killed), and four killed workers end on an
    answered tool call. Only a completed worker is then read for the cut indicators in transcript_incomplete."""
    if notice is not None and notice[0] != "completed":
        return f"worker {notice[0]} by parent" if notice[0] else "completion notice carries no status"
    why = transcript_incomplete(path, *(notice[1:] if notice else (None, since, None)))
    return "transcript incomplete (" + "; ".join(why) + ")" if why else None


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
        # NOT "ignored": when there is no tagged worker this same list decides a MIXED verdict two branches below,
        # and a line that called them ignored contradicted the exit code (Astra loop 1, finding 6).
        print(f"  ({len(untagged)} subagent launch(es) without the {WORKER_TAG!r} prefix — review forks / advisors / "
              f"helpers; not counted as workers)")
        for tid, aid in untagged:
            print(f"      untagged launch {tid} · agent {aid or '(no agent id recorded)'}")
    subdir = worker_dir(f)
    workers, bad, inflight, turn_rt, gap = [], [], 0, {}, {}
    for tid, aid, t, running, notice, reopen in tagged:
        if isinstance(running, str):
            bad.append((tid[:14], "tagged launch " + running)); continue
        if running:
            w = os.path.join(subdir, f"agent-{aid}.jsonl") if aid else None
            # No notice in the window. transcript_finished still answers "has the file stopped moving?", but quiet is not
            # finished (v6.26 loop 2, Astra H3): the worker is judged only when its last message is ALSO a finishing
            # reply. A thinking-only or tool-only tail with no notice is still running — never PURE. A worker the parent
            # RESUMED after its last notice (REOPEN, loop 4) is read from that resume onward: a reply written before it
            # answers the earlier run, never the one the resume started (Astra loop 3, N3).
            if (w and reopen != LAST_RUN_UNREADABLE and transcript_finished(w)
                    and finish_gap(last_assistant_message(w, reopen)) is None):
                pass   # the notification was not seen (window closed first) but the transcript ended on its final reply
            else:
                inflight += 1; continue   # no result yet, or an async launch whose task-notification has not arrived
        w = os.path.join(subdir, f"agent-{aid}.jsonl")
        if not os.path.isfile(w):
            bad.append((aid[:14], "tagged launch but no transcript on disk")); continue
        p = profile_claude(w)
        if not p:
            bad.append((aid[:14], "tagged transcript with no assistant turn")); continue
        workers.append((aid[:14], p))
        turn_rt[aid[:14]] = claude_turn_runtimes(w)   # EVERY turn, not the majority — the gate judges these
        # FINISHED BEFORE JUDGED (v6.26 loops 1 and 2): the turns above are only the ones on disk. NOTICE is the parent's
        # word on how the worker ended, None for a quiet worker let through above; completion_gap is the one judgement.
        gap[aid[:14]] = completion_gap(w, notice, reopen)
    exec_evidence = ("executor effort unreadable" if exec_eff == "?" else
                     "executor model unreadable" if exec_model == "unknown" else None)   # no evidence = never PURE
    for name, (m, e, out, tools, turns) in workers:
        # Judged PER TURN: the printed m/e are profile_claude's MAJORITY, which is a summary, not the gate. A worker whose
        # majority is pinned can still hold an off-runtime turn (Astra R2), and that turn cost money on the wrong model.
        unreadable, offturns = turn_verdict(turn_rt.get(name, []), exec_model, exec_eff)
        unfinished = gap.get(name)
        missing = (e == "?" or m == "unknown") or bool(unreadable) or bool(unfinished)
        ok = not missing and not offturns and exec_evidence is None and m == exec_model and e == exec_eff
        mark = "EVIDENCE-MISSING" if (missing or exec_evidence) else ("ok" if ok else "MIXED")
        print(f"  worker {name:<16} {m:<18} {e:<7} out={out:>7} tools={tools:>3} turns={turns:>3}  {mark}")
        if not ok:
            bad.append((name, exec_evidence or unfinished or ((unreadable or offturns) and turn_why(unreadable, offturns)) or f"{m} {e}"))
    for name, why in bad:
        # A worker that did not finish is invisible on its worker line — that line profiles the turns on disk — so it
        # gets its own reason line (`worker killed by parent`, `transcript incomplete (…)`), like one never profiled.
        if not any(name == n for n, _ in workers) or why == gap.get(name):
            print(f"  MIXED  {name:<16} {why}")
    if bad:   # a MIXED verdict is never masked by workers still running
        wc0 = Counter((m, e) for _, (m, e, *_r) in workers)
        wdesc0 = " + ".join(f"{n} × {m} {e}" for (m, e), n in wc0.most_common()) or "0"
        print(f"PURITY: MIXED · executor {exec_model} {exec_eff} · workers {wdesc0} · offenders: " + ", ".join(f"{n}={w}" for n, w in bad) + (f" · {inflight} still running" if inflight else "")); return 1
    if inflight:
        print(f"PURITY: NOTHING-TO-CHECK · {inflight} tagged worker(s) still running (no result recorded yet) — wait for them to finish and re-run"); return 2
    if not workers and not bad:
    # UNTAGGED LAUNCHES DECIDE THIS. This tool already counted them and printed the count, then returned
    # NOTHING-TO-CHECK regardless — so an inline day (0 launches, genuinely nothing to check) and a bulk day whose
    # workers were launched WITHOUT the tag (every extraction unverifiable) got the same fail-open verdict, and the
    # only thing standing between them was a line in the run instructions asking a reviewer to notice (/kun M5). A launch that
    # happened but cannot be checked is now MIXED, and it names the count.
        if untagged:
            named = ", ".join(f"{tid}{'' if not aid else ' (agent ' + aid + ')'}" for tid, aid in untagged)
            print(f"PURITY: MIXED · executor {exec_model} {exec_eff} · workers 0 · {len(untagged)} launch(es) without "
                  f"the {WORKER_TAG!r} tag and no tagged worker at all — their model and effort cannot be read, so no "
                  f"extraction in this run is verified: {named}. Re-run the batches as tagged subagents and re-check "
                  f"with --after."); return 1
        print("PURITY: NOTHING-TO-CHECK · no subagent launches at all in the window (an inline day — there is no "
              "worker whose purity could be in question)"); return 2
    wc = Counter((m, e) for _, (m, e, *_r) in workers)
    wdesc = " + ".join(f"{n} × {m} {e}" for (m, e), n in wc.most_common()) or "0"
    print(f"PURITY: PURE · executor {exec_model} {exec_eff} · workers {wdesc}"); return 0


# ---------------------------------------------------------------- Codex
def _meta_fields(payload, record):
    """The `session_meta` fields every caller wants, derived in ONE place. `codex_meta` (which reads a whole rollout
    for model / effort / usage) and `first_session_meta` / `head_meta` (which read only its head) must produce the
    same dict, or the head-only fast path would silently answer a different question from the full read."""
    p = payload if isinstance(payload, dict) else {}
    spawn = ((p.get("source") or {}).get("subagent") or {}).get("thread_spawn") if isinstance(p.get("source"), dict) else None
    return {"id": p.get("id"), "cwd": p.get("cwd"), "originator": p.get("originator"),
            "start": p.get("timestamp") or (record or {}).get("timestamp"),
            "parent": (spawn or {}).get("parent_thread_id"),
            "task": os.path.basename((spawn or {}).get("agent_path") or "")}


def _first_session_meta_record(path):
    """The rollout's FIRST `session_meta` record, or None. Lazy: `records()` is a generator, so this stops at that
    record instead of walking a multi-megabyte rollout to EOF. A forked child replays its parent's session_meta
    later in the file, so only the FIRST one answers "whose thread is this".

    READ WITHOUT VALIDATING TIMESTAMPS — ownership is decided from this, and the timestamp rule is applied AFTER
    (Astra loop 1, R1). v6.25 read it through `scan_records`, which bails at the first unreadable stamp: an OWNED
    worker whose head stamp was malformed returned {} here, failed the `parent == exec_id` test, and was counted as
    an unrelated stranger. The gate then printed PURE over a set with that worker missing — and Astra's control
    proved it hides a real offender: the same worker running Sol reported MIXED with a good head and PURE with a bad
    one. Ownership can be read from a record whose stamp cannot be ordered; `codex_run_files` decides which files
    are ours, and only then does the strict rule bite."""
    for o in records(path):
        if o.get("type") == "session_meta":
            return o
    return None


def first_session_meta(path):
    """The rollout's own `session_meta` PAYLOAD, raw, or None when the file holds none. Moved here from
    `runtime_check.py` in v6.23 so the two tools share one head-only reader — runtime_check imports it back, and its
    callers (which read `source`, `cwd`, `id`, `timestamp`) see exactly the payload they saw before."""
    o = _first_session_meta_record(path)
    p = o.get("payload") if o else None
    return p if isinstance(p, dict) else None


def head_meta(path):
    """`codex_meta(path)[0]` WITHOUT reading the rollout to EOF — the derived session_meta dict, from the head only.

    `codex_run_files` used `codex_meta(f)[0]` to read one first-record field (`parent`) off every rollout in the
    tree, which walked all 1,004 of them — 2 GB — to their last byte: 4.0 s warm, against 0.1 s for the head, and
    the tree grows by about 300 rollouts a month. Nothing else about those files was wanted at that point, so only
    the candidates that pass the parent filter are now read in full (code-review run 1, finding 3)."""
    o = _first_session_meta_record(path)
    return _meta_fields(o.get("payload"), o) if o else {}


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
    at = require_bound(at, "codex_meta(at=)")
    since = require_bound(since, "codex_meta(since=)")
    meta, model, eff, first_prompt, out, base = {}, None, "?", None, 0, None
    for o in codex_records(path):
        p = o.get("payload")
        if not isinstance(p, dict):
            continue
        raw = o.get("timestamp") or ""
        if at and raw > at and (p.get("model") or p.get("reasoning_effort") or p.get("effort")):
            continue   # a later model/effort switch does not belong to this run
        cycle = not (since and raw < since) and not (at and raw > at)
        if o.get("type") == "session_meta" and not meta:   # a forked child carries the parent's session_meta too — only the FIRST is its own
            meta = _meta_fields(p, o)   # one home, shared with head_meta()
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


ASSISTANT_WORK = ("message", "function_call", "custom_tool_call")   # see is_assistant_work


def is_assistant_work(p):
    """True when this record payload is a turn the ASSISTANT took — the one home of "evidenced assistant work" on the Codex
    side. Three shapes count: an assistant `message`, a `function_call`, and a `custom_tool_call`. Tool RESULTS do not: a
    `*_output` record is the environment answering, not the model working, and counting it would attribute the runtime in
    force at the answer rather than at the request.

    Text messages alone are not enough, and that is not hypothetical. In a real production worker's
    rollout, record 24 is a `custom_tool_call` (name
    `exec`) at 15:54:54.140Z with its own `token_count` at record 27, record 30 another at 15:55:01.269Z with its
    `token_count` at 34 — and that worker's whole selected cycle carries exactly ONE assistant text message (record 138).
    Across the seven workers of the 2026-09-05 run the message-only rule saw 12 turns; this predicate sees 125 (113 tool
    calls + 12 messages). A worker could therefore do all its extraction on a cheap runtime through tool calls and emit one
    pinned final line, and the gate would report PURE (GPT-6 Astra, v6.22 loop 1, finding N5, repro Appendix D).

    Matching is on the PAYLOAD type, not the record's outer `type`: Codex writes these as `response_item` on disk, and the
    same payload shape also appears wrapped in `event_msg`."""
    t = p.get("type")
    return t in ASSISTANT_WORK and (p.get("role") == "assistant" if t == "message" else True)


def codex_turn_runtimes(path, cs, ce):
    """(ts, model, effort) for every record of EVIDENCED ASSISTANT WORK inside the cycle (CS, CE] — assistant messages,
    function calls and custom tool calls, per `is_assistant_work` — each carrying the pair IN FORCE at that turn.
    Model/effort are tracked from the START of the file, never only from CS, so a turn inherits a switch made before the
    cycle opened: that is codex_meta's rule, and a cycle carrying no turn_context of its own must not read `unknown`.
    codex_meta returns the LAST pair in force, which is the right summary for the printed line but the wrong thing to gate
    on: a cycle that ran on Luna/low and then switched back to the pinned runtime before completing has a pinned LAST value
    and is not pure (GPT-6 Astra full pass, finding 1, repro R1). The gate reads this list; the printed line still shows the
    last pair. codex_meta's own return contract is untouched — runtime_check.py imports it for exactly that last-in-force
    reading and its selftest gates the behaviour."""
    cs = require_bound(cs, "codex_turn_runtimes(cs=)")
    ce = require_bound(ce, "codex_turn_runtimes(ce=)")
    model, eff, out = None, "?", []
    for o in codex_records(path):
        p = o.get("payload")
        if not isinstance(p, dict):
            continue
        raw = o.get("timestamp") or ""
        if raw > ce:
            break   # records are oldest-first, so nothing after the cycle end can matter
        if p.get("model"):
            model = p["model"]
        if p.get("reasoning_effort") or p.get("effort"):
            eff = p.get("reasoning_effort") or p.get("effort")
        if cs < raw <= ce and is_assistant_work(p):
            out.append((raw, norm(model), eff))
    return out


def codex_task_events(path):
    """[(ts, type)] for every task_started / task_complete / turn_aborted event of a thread — one cycle per task it was driven with."""
    out = []
    for o in codex_records(path):
        p = o.get("payload") or {}
        if isinstance(p, dict) and p.get("type") in ("task_started", "task_complete", "turn_aborted"):
            out.append((o.get("timestamp") or "", p["type"]))   # already validated by codex_records
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


def codex_cycles_all(path):
    """Every task cycle in the WHOLE rollout — `codex_cycles` with no run window. Timestamps are compared as strings, so
    "" sorts before every ISO stamp and "~" (0x7E, above every digit and letter) after every one. session_cost uses this
    when it is given no token window (`--codex`, bare paths): the per-cycle completeness test must not depend on the
    invocation form (GPT-6 Astra full pass, finding 5, repro R3)."""
    return codex_cycles(path, "", "~")


def codex_has_assistant_turn(path, cs, ce):
    """True when the thread recorded at least one piece of EVIDENCED ASSISTANT WORK inside the cycle (CS, CE] — the same
    `is_assistant_work` predicate the per-turn gate uses, so the two cannot disagree about what a turn is. A cycle that
    reached task_complete with no such record produced nothing that can be checked against the executor's model + effort,
    so the purity gate must report it as an offender rather than count it as a clean worker.
    Widened from "an assistant message" in v6.22 loop 2: a cycle whose whole output was tool calls IS checkable work, and
    calling it empty was the same message-only assumption as finding N5."""
    cs = require_bound(cs, "codex_has_assistant_turn(cs=)")
    ce = require_bound(ce, "codex_has_assistant_turn(ce=)")
    for o in codex_records(path):
        raw = o.get("timestamp") or ""
        if not (cs < raw <= ce):
            continue
        p = o.get("payload")
        if isinstance(p, dict) and is_assistant_work(p):
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


def run_codex(files, after, untagged=(), at=None, windows=None):
    if not files:
        print("--codex needs the executor rollout and at least one worker rollout"); return EXIT_LOOKUP
    main = files[0]
    meta, em, ee, fp, _ = codex_meta(main, at=at)
    print(f"executor rollout: {os.path.basename(main)[8:27]} · {em} · {ee} · cwd={tilde(meta.get('cwd'))}")
    untagged = list(untagged) if not isinstance(untagged, int) else []
    if untagged:
        # Named, and not called "ignored": with no tagged thread this same list is the MIXED verdict below.
        print(f"  ({len(untagged)} child thread(s) whose task_name does not start with {CODEX_WORKER_TAG!r} — "
              f"helpers / reviewers; not counted as workers)")
        for u in untagged:
            print(f"      untagged thread {os.path.basename(u)}")
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
        if state != "done":
            inflight += 1; print(f"  worker {name} still running"); continue   # no task_complete for its last task
        # INFLIGHT IS DECIDED BY THE CYCLE STATE ALONE. Until v6.23 an unreadable model (`wm == "unknown"`) was also
        # routed here, so a worker that had COMPLETED but whose `turn_context` could not be read was reported as
        # still running — for ever, since nothing further would be written to it. The whole batch then read
        # NOTHING-TO-CHECK, exit 2, which is a fail-OPEN: the Claude path and this file's own docstring both make
        # unreadable evidence an EVIDENCE-MISSING offender and MIXED (code-review run 1, finding 1).
        if cyc and not codex_has_assistant_turn(w, cyc[0], cyc[1]):
            bad.append((name, "no assistant turn in its task cycle")); continue   # completed with nothing to check = never PURE
        missing = (wm == "unknown" or we == "?")   # a DONE cycle with an unreadable model or effort has no evidence to check
        # Judged PER TURN: the printed wm/we are codex_meta's LAST pair in force, which is a summary, not the gate. A cycle
        # that ran on the wrong runtime and switched back before completing has a pinned last value (Astra R1), and the
        # turns it took on the wrong model still cost money and still broke the pin.
        unreadable, offturns = turn_verdict(codex_turn_runtimes(w, cyc[0], cyc[1]) if cyc else [], em, ee)
        missing = missing or bool(unreadable)
        ok = not missing and not offturns and exec_evidence is None and wm == em and we == ee
        mark = "EVIDENCE-MISSING" if (missing or exec_evidence) else ("ok" if ok else "MIXED")
        print(f"  worker {name} {wm:<14} {we:<7} out={out:>7}  {mark}")
        workers.append((name, (wm, we)))
        if not ok:
            bad.append((name, exec_evidence or ((unreadable or offturns) and turn_why(unreadable, offturns)) or f"{wm} {we}"))
    if bad:
        wc0 = Counter(v for _, v in workers); wdesc0 = " + ".join(f"{n} × {m} {e}" for (m, e), n in wc0.most_common()) or "0"
        print(f"PURITY: MIXED · executor {em} {ee} · workers {wdesc0} · offenders: " + ", ".join(f"{n}={w}" for n, w in bad) + (f" · {inflight} still running" if inflight else "")); return 1
    if inflight:
        print(f"PURITY: NOTHING-TO-CHECK · {inflight} tagged worker thread(s) still running — wait for them to finish and re-run"); return 2
    if not workers:
    # UNTAGGED LAUNCHES DECIDE THIS. This tool already counted them and printed the count, then returned
    # NOTHING-TO-CHECK regardless — so an inline day (0 launches, genuinely nothing to check) and a bulk day whose
    # workers were launched WITHOUT the tag (every extraction unverifiable) got the same fail-open verdict, and the
    # only thing standing between them was a line in the run instructions asking a reviewer to notice (/kun M5). A launch that
    # happened but cannot be checked is now MIXED, and it names the count.
        if untagged:
            print(f"PURITY: MIXED · executor {em} {ee} · workers 0 · {len(untagged)} child thread(s) whose task_name "
                  f"does not start with {CODEX_WORKER_TAG!r} and no tagged thread at all — their model and effort "
                  f"cannot be read, so no extraction in this run is verified: "
                  + ", ".join(os.path.basename(u) for u in untagged)
                  + ". Re-spawn the batches as tagged threads and re-check with --after."); return 1
        print(f"PURITY: NOTHING-TO-CHECK · no child thread spawned by the executor inside the run window (an inline "
              f"day — there is no worker whose purity could be in question)"); return 2
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
    exec_id = head_meta(mainf).get("id")
    if not exec_id:
        # `parent == exec_id` with exec_id None matches every top-level rollout — none of which records a parent —
        # INCLUDING the executor itself, so the executor was handed a child's cycle LIST and `codex_meta` raised a
        # TypeError on it. A lookup that cannot identify the executor is a lookup error, never a match-all
        # (code-review run 1, finding 2).
        print(f"--codex-run: the executor rollout {os.path.basename(mainf)} has no readable session id in its "
              f"session_meta, so its child threads cannot be identified. Nothing checked.")
        sys.exit(EXIT_LOOKUP)
    def driven_in_window(f):   # spawned OR re-driven (followup_task) inside the window — a re-used thread has an old first record
        return any(start < t <= end for t, k in codex_task_events(f) if k == "task_started")

    def head_ts_readable(f):
        """Is this rollout's FIRST record stamped in the canonical form? Head only, no exit — the caller decides."""
        for o in records(f):
            return ts_ok(o.get("timestamp") or "")
        return True        # an empty file has no head stamp to be wrong about; it simply owns nothing

    # OWNERSHIP FIRST, THE TIMESTAMP RULE SECOND (Astra loop 1, R1). Three states, in this order:
    #   not ours          — an unreadable head is NOTED and skipped. The scan reads every rollout on the machine and
    #                       one stranger's malformed stamp must never end a digest lookup.
    #   ours, unreadable  — EXIT 3 naming the file, via the strict `first_ts` below. A known child whose evidence
    #                       cannot be ordered is unreadable evidence, not a non-candidate: dropping it silently is
    #                       how a Sol worker disappeared behind PURE 7 in Astra's control.
    #   ours, readable    — the ordinary window and task-event filters decide.
    # head_meta, not codex_meta: only `parent` is wanted here, and it is in the first record — see head_meta's note.
    children = []
    for f in files:
        m = head_meta(f)                                    # raw head read: no stamp validation, no skip
        if m.get("parent") != exec_id:
            if not head_ts_readable(f):
                SKIPPED_HEADS.append(os.path.basename(f))   # a stranger — named once in the note below
            continue
        if (first_ts(f) or "") > end:                       # STRICT: this is one of ours, so a bad stamp is exit 3
            continue
        if driven_in_window(f):
            children.append((f, m))
    workers = [f for f, m in children if (m.get("task") or "").startswith(CODEX_WORKER_TAG)]
    others = [f for f, m in children if f not in workers]
    windows = {mainf: (start, end)}
    for f, _m in children:
        cycles = codex_cycles(f, start, end)
        if cycles:
            windows[f] = cycles
    if SKIPPED_HEADS:
        # ONE note, not one per file: the scan reads every rollout on the machine and most of them belong to other
        # work entirely. Named so a real problem in a real digest rollout is still findable.
        uniq = sorted(set(SKIPPED_HEADS))
        shown = ", ".join(uniq[:4]) + (f", +{len(uniq) - 4} more" if len(uniq) > 4 else "")
        print(f"note: {len(uniq)} rollout(s) skipped: unreadable head timestamp ({shown})", file=sys.stderr)
    return [mainf] + workers, others, windows   # (executor + tagged workers, untagged children — helpers/reviewers: ignored by purity, billed by cost)


def first_ts(path, reader=None):
    """The rollout's first stamped record. STRICT BY DEFAULT — the DISCOVERY scan opts into leniency explicitly.

    Both bounds below fall back into a cycle the gate then judges, so an unorderable stamp on a rollout we have
    already SELECTED must exit 3 rather than be quietly skipped. `codex_run_files`, which reads every rollout on
    disk looking for candidates, passes `scan_records` — that is the whole of the leniency v6.25 added (/kun #2, F3)."""
    for o in (reader or codex_records)(path):
        if o.get("timestamp"):
            return o["timestamp"]
    return None


def last_ts(path, reader=None):
    """The timestamp of the rollout's last stamped record — the upper bound of a cycle that never recorded a closing
    event. Strict by default, for the same reason as `first_ts`."""
    last = None
    for o in (reader or codex_records)(path):
        if o.get("timestamp"):
            last = o["timestamp"]
    return last


def codex_window_end(path, token, start):
    """The run window in a Codex rollout: from the printed token to the next different complete token printed by the
    executor, else the rollout's last record. Worker rollouts must have STARTED inside it."""
    start = require_bound(start, "codex_window_end(start=)")
    last = start
    seen = set()
    for o in codex_records(path):
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


# ---------------------------------------------------------------- selftest (v6.26)
# Self-contained: every transcript below is written to a temp folder and read back through main(), so the checks run the
# same code path an executor's check 8 does. Nothing under ~/.claude or ~/.codex is read.
def _st_ts(i):
    return f"2026-09-11T10:{i // 60:02d}:{i % 60:02d}.000Z"


def _st_write(path, recs, final_newline=True, tail=""):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in recs) + ("\n" if final_newline else "") + tail)


def _st_asst(i, mid, blocks, stop):
    return {"type": "assistant", "uuid": f"u{i}", "timestamp": _st_ts(i), "effort": "xhigh",
            "message": {"role": "assistant", "id": mid, "model": "claude-opus-5", "content": blocks,
                        "stop_reason": stop, "usage": {"output_tokens": 10}}}


def _st_worker(shape):
    """A worker transcript: one answered tool call, then a last message shaped by SHAPE."""
    recs = [{"type": "user", "uuid": "w0", "timestamp": _st_ts(0), "message": {"role": "user", "content": "DIGEST-WORKER batch A"}},
            _st_asst(1, "m1", [{"type": "tool_use", "id": "tu1", "name": "Read", "input": {}}], "tool_use"),
            {"type": "user", "uuid": "w2", "timestamp": _st_ts(2),
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "ok"}]}}]
    think = _st_asst(3, "m2", [{"type": "thinking", "thinking": "…"}], None)
    return recs + {
        "whole":        [_st_asst(3, "m2", [{"type": "text", "text": "done"}], "end_turn")],
        "null_text":    [think, _st_asst(4, "m2", [{"type": "text", "text": "done"}], None)],   # how Claude Code writes a final reply today
        "mid_tool":     [think, _st_asst(4, "m2", [{"type": "tool_use", "id": "tu2", "name": "Read", "input": {}}], "tool_use")],
        "before_reply": [think],
        "after_answer": [],   # Astra's H1 repro: the first three records of "whole" — a cut right after the tool result
    }[shape]


def _st_launch(aid, text="Async agent launched successfully."):
    """The parent's first three records: a text turn, the tagged Agent launch, and its launch result carrying TEXT."""
    return [_st_asst(0, "p0", [{"type": "text", "text": "starting"}], "end_turn"),
            _st_asst(1, "p1", [{"type": "tool_use", "id": "toolu_w1", "name": "Agent",
                                "input": {"prompt": WORKER_TAG + " batch A"}}], "tool_use"),
            {"type": "user", "uuid": "p2", "timestamp": _st_ts(2), "toolUseResult": {"agentId": aid},
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_w1",
                                                      "content": [{"type": "text", "text": text}]}]}}]


def _st_claude(tmp, name, shape, newline=True, notice=True, age=None, statuses=("completed",), calls=None,
               launch_text="Async agent launched successfully."):
    """A parent session with ONE tagged async launch, and that worker's transcript. With NOTICE, the parent holds one
    task-notification per entry of STATUSES, in that order (a resumed worker notifies again); CALLS, when given, is the
    `<tool_uses>` count each carries. LAUNCH_TEXT is the launch result's wording. Returns (parent path, worker name)."""
    import hashlib, time
    aid = hashlib.sha1(name.encode()).hexdigest()[:17]
    sid = "sess-" + name
    os.makedirs(os.path.join(tmp, name, sid, "subagents"))
    parent = os.path.join(tmp, name, sid + ".jsonl")
    recs = _st_launch(aid, launch_text)
    for status in (statuses if notice else ()):
        usage = f"<usage><tool_uses>{calls}</tool_uses></usage>\n" if calls is not None else ""
        recs.append({"type": "queue-operation", "operation": "enqueue", "timestamp": _st_ts(3),
                     "content": f"<task-notification>\n<task-id>{aid}</task-id>\n<status>{status}</status>\n{usage}</task-notification>"})
    recs.append(_st_asst(4, "p4", [{"type": "text", "text": "all batches back"}], "end_turn"))
    _st_write(parent, recs)
    w = os.path.join(tmp, name, sid, "subagents", f"agent-{aid}.jsonl")
    _st_write(w, _st_worker(shape), newline)
    if age is not None:
        os.utime(w, (time.time() - age, time.time() - age))
    return parent, aid[:14]


def _st_resumed(tmp, name, runs, keep=None, cut_text=None):
    """A worker the parent re-drove after it finished, one entry of RUNS per run (v6.26 loop 3): (model, tool calls,
    the notice's status, the notice's `<tool_uses>` or None). Each run opens on its message (the tagged prompt, then the
    re-drive), makes that many answered tool calls, and ends on a final text reply — a run the parent killed or failed
    ends after its last tool result. The parent writes each run's notice twice, byte for byte (the queue record and the
    delivered message, as real parents do), and re-drives the worker with a SendMessage between runs. KEEP cuts the
    worker file to its first KEEP runs while the parent keeps every notice; CUT_TEXT = k ends the last kept run after k
    answered calls on the TEXT block of a message whose tool call was never written. Returns (parent path, worker name)."""
    import hashlib
    aid = hashlib.sha1(name.encode()).hexdigest()[:17]
    sid = "sess-" + name
    os.makedirs(os.path.join(tmp, name, sid, "subagents"))
    prec, wrec, t = _st_launch(aid), [], 10
    kept = runs[:keep] if keep else runs

    def asst(i, mid, blocks, stop, model):
        r = _st_asst(i, mid, blocks, stop)
        r["message"]["model"] = model
        return r

    for r, (model, calls, status, counted) in enumerate(runs):
        prompt = (WORKER_TAG + " batch A" if r == 0 else
                  "The coordinator sent a message while you were working:\nRe-emit the cards with raw HTML markup.")
        run = [{"type": "user", "uuid": f"w{r}", "timestamp": _st_ts(t), "message": {"role": "user", "content": prompt}}]
        stop_after = cut_text if (cut_text is not None and r == len(kept) - 1) else None
        for c in range(calls):
            if stop_after is not None and c == stop_after:
                run.append(asst(t + 1, f"r{r}m{c}", [{"type": "text", "text": "Now the next file."}], None, model))
                break
            run += [asst(t + 1, f"r{r}m{c}", [{"type": "tool_use", "id": f"r{r}tu{c}", "name": "Read", "input": {}}],
                         "tool_use", model),
                    {"type": "user", "uuid": f"w{r}r{c}", "timestamp": _st_ts(t + 2), "message": {
                        "role": "user", "content": [{"type": "tool_result", "tool_use_id": f"r{r}tu{c}", "content": "ok"}]}}]
            t += 2
        if status == "completed" and stop_after is None:
            run.append(asst(t + 1, f"r{r}fin", [{"type": "text", "text": f"run {r + 1} done"}], None, model))
        t += 2
        if r < len(kept):
            wrec += run
        usage = f"<usage><tool_uses>{counted}</tool_uses></usage>\n" if counted is not None else ""
        env = (f"<task-notification>\n<task-id>{aid}</task-id>\n<status>{status}</status>\n"
               f"<result>run {r + 1} ended</result>\n{usage}</task-notification>")
        prec += [{"type": "queue-operation", "operation": "enqueue", "timestamp": _st_ts(t), "content": env},
                 {"type": "user", "uuid": f"n{r}", "timestamp": _st_ts(t), "message": {"role": "user", "content": env}}]
        if r < len(runs) - 1:
            prec += [asst(t + 1, f"s{r}", [{"type": "tool_use", "id": f"send{r}", "name": "SendMessage",
                                            "input": {"to": aid, "message": "Re-emit the cards with raw HTML markup."}}],
                          "tool_use", "claude-opus-5"),
                     {"type": "user", "uuid": f"s{r}r", "timestamp": _st_ts(t + 2), "message": {
                         "role": "user", "content": [{"type": "tool_result", "tool_use_id": f"send{r}", "content": "Message sent"}]}}]
        t += 4
    prec.append(_st_asst(t, "pz", [{"type": "text", "text": "all batches back"}], "end_turn"))
    parent = os.path.join(tmp, name, sid + ".jsonl")
    _st_write(parent, prec)
    _st_write(os.path.join(tmp, name, sid, "subagents", f"agent-{aid}.jsonl"), wrec)
    return parent, aid[:14]


def _st_aid(name):
    import hashlib
    return hashlib.sha1(name.encode()).hexdigest()[:17]


def _st_tsf(x):
    """_st_ts to the millisecond, for timings that fall inside one second."""
    ms = int(round(x * 1000))
    return f"2026-09-11T10:{ms // 60000:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}Z"


def _st_at(stamp, mid, blocks, stop):
    """_st_asst at the timestamp STAMP."""
    r = _st_asst(0, mid, blocks, stop)
    r.update(uuid=f"u-{mid}-{stamp}", timestamp=stamp)
    return r


def _st_files(tmp, name, prec, wrec, age=None):
    """Write parent records PREC and worker records WREC in a session's layout (v6.26 loop 4). AGE backdates the worker
    file. Returns (parent path, worker name)."""
    import time
    aid, sid = _st_aid(name), "sess-" + name
    os.makedirs(os.path.join(tmp, name, sid, "subagents"))
    parent = os.path.join(tmp, name, sid + ".jsonl")
    _st_write(parent, prec)
    w = os.path.join(tmp, name, sid, "subagents", f"agent-{aid}.jsonl")
    _st_write(w, wrec)
    if age is not None:
        os.utime(w, (time.time() - age, time.time() - age))
    return parent, aid[:14]


def _st_notice(aid, stamp, run, calls):
    """One notice as the parent writes it: a queue record and the delivered message, byte for byte."""
    env = (f"<task-notification>\n<task-id>{aid}</task-id>\n<status>completed</status>\n<result>run {run} ended</result>\n"
           f"<usage><tool_uses>{calls}</tool_uses></usage>\n</task-notification>")
    return [{"type": "queue-operation", "operation": "enqueue", "timestamp": stamp, "content": env},
            {"type": "user", "uuid": f"n{run}", "timestamp": stamp, "message": {"role": "user", "content": env}}]


def _st_redrive(tmp, name, result, structured=True, request=True, run2=None, age=None,
                ask="Re-emit the cards with raw HTML markup; do not escape tags."):
    """A worker the parent re-drove with a SendMessage after its first run (v6.26 loop 4; Astra loop 3, N3), on the
    timing of a real worker the parent re-drove. Run 1 makes two answered tool calls and ends on an end_turn
    reply; the parent writes its completed notice (`<tool_uses>2`) 3 s later, then sends ASK; the worker records the
    request (REQUEST) 3 ms before the parent records the result, whose JSON is RESULT — written as the tool result's text
    and, when STRUCTURED, as `toolUseResult` too, as Claude Code writes both. RUN2 = k lets the resumed run make k answered
    calls and end on a final reply; RUN2 = (k, n) also has the parent write that run's notice, counting n. AGE backdates
    the worker file (quiet). Returns (parent path, worker name)."""
    aid = _st_aid(name)
    wrec = [{"type": "user", "uuid": "w0", "timestamp": _st_ts(10), "message": {"role": "user", "content": WORKER_TAG + " batch A"}}]
    for c in range(2):
        wrec += [_st_asst(11 + 2 * c, f"m{c}", [{"type": "tool_use", "id": f"tu{c}", "name": "Read", "input": {}}], "tool_use"),
                 {"type": "user", "uuid": f"w{c}r", "timestamp": _st_ts(12 + 2 * c),
                  "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"tu{c}", "content": "ok"}]}}]
    wrec.append(_st_asst(15, "fin1", [{"type": "text", "text": "run 1 done"}], "end_turn"))
    prec = _st_launch(aid) + _st_notice(aid, _st_ts(18), 1, 2)
    prec.append(_st_asst(25, "s1", [{"type": "tool_use", "id": "send1", "name": "SendMessage",
                                     "input": {"to": aid, "summary": "Re-emit the cards", "message": ask}}], "tool_use"))
    if request:
        wrec.append({"type": "user", "uuid": "w-ask", "timestamp": _st_tsf(27.979), "message": {
            "role": "user", "content": "The coordinator sent a message while you were working:\n" + ask}})
    res = {"type": "user", "uuid": "s1r", "timestamp": _st_tsf(27.982), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "send1", "content": [{"type": "text", "text": json.dumps(result)}]}]}}
    if structured:
        res["toolUseResult"] = result
    prec.append(res)
    t = 32
    if run2 is not None:
        k, n = run2 if isinstance(run2, tuple) else (run2, None)
        for c in range(k):
            wrec += [_st_asst(t, f"r2m{c}", [{"type": "tool_use", "id": f"r2tu{c}", "name": "Read", "input": {}}], "tool_use"),
                     {"type": "user", "uuid": f"w2{c}r", "timestamp": _st_ts(t + 1), "message": {
                         "role": "user", "content": [{"type": "tool_result", "tool_use_id": f"r2tu{c}", "content": "ok"}]}}]
            t += 2
        wrec.append(_st_asst(t, "fin2", [{"type": "text", "text": "run 2 done"}], None))
        if n is not None:
            prec += _st_notice(aid, _st_ts(t + 3), 2, n)
        t += 4
    prec.append(_st_asst(t + 1, "pz", [{"type": "text", "text": "all batches back"}], "end_turn"))
    return _st_files(tmp, name, prec, wrec, age)


def _st_codex(tmp, name, complete):
    """An executor rollout and ONE digest_worker child. COMPLETE=False cuts the child mid-write of the task_complete
    record that would have closed its cycle: the file ends in half a line, with no newline."""
    d = os.path.join(tmp, name)
    os.makedirs(d)
    ex = os.path.join(d, "rollout-2026-09-11T10-00-00-exec.jsonl")
    ch = os.path.join(d, "rollout-2026-09-11T10-00-05-child.jsonl")
    ctx = lambda t: {"timestamp": t, "type": "turn_context", "payload": {"model": "gpt-5.6-sol", "effort": "xhigh"}}
    say = lambda t: {"timestamp": t, "type": "response_item",
                     "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "ok"}]}}
    _st_write(ex, [{"timestamp": "2026-09-11T10:00:00.000Z", "type": "session_meta",
                    "payload": {"id": "exec-1", "cwd": "/selftest", "timestamp": "2026-09-11T10:00:00.000Z"}},
                   ctx("2026-09-11T10:00:01.000Z"), say("2026-09-11T10:00:02.000Z")])
    close = {"timestamp": "2026-09-11T10:00:13.000Z", "type": "event_msg", "payload": {"type": "task_complete"}}
    recs = [{"timestamp": "2026-09-11T10:00:05.000Z", "type": "session_meta",
             "payload": {"id": "child-1", "timestamp": "2026-09-11T10:00:05.000Z",
                         "source": {"subagent": {"thread_spawn": {"parent_thread_id": "exec-1", "agent_path": "digest_worker_a"}}}}},
            ctx("2026-09-11T10:00:06.000Z"),
            {"timestamp": "2026-09-11T10:00:11.000Z", "type": "event_msg", "payload": {"type": "task_started"}},
            say("2026-09-11T10:00:12.000Z")]
    if complete:
        _st_write(ch, recs + [close])
    else:
        _st_write(ch, recs, tail=json.dumps(close)[:40])
    return ex, ch


def _st_main(argv):
    import contextlib, io
    out, errb = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errb):
        try:
            rc = main(list(argv))
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue()


def selftest(census=False):
    """v6.26 — a worker is judged only when its transcript shows it finished. Loop 1: each cut indicator on its own
    worker (T1–T3) and the GATE 4 fixture's shape (T4); the complete shapes that must stay PURE, including the one Claude
    Code writes for a normal final reply (G1–G3); the Codex side, which judges by task-cycle state (C1–C2). Loop 2 —
    Astra's three repros as she built them (H1 cut right after an answered tool call, H2 a killed worker ending on text,
    H3 no notice + a thinking-only tail); the parent's other status word (S1 failed) and its LAST-in-file-order rule for a
    resumed worker (R1, R2); the tool-call count check, both directions (D1, D2). Loop 3 — a worker the parent re-drove
    is judged on its LAST run (RS1 whole and on the executor's runtime; RS2 Astra's N1 control, a second run on another
    model; RS3 her N1 cut, the file ending after the first run with both notices kept; RS4 a cut inside the last run
    that only the pair of counts shows; RS5 a run counted on top of the previous count, which must stay PURE), and the
    fork launch wording (F1, Astra's N2). Loop 4 — an accepted resume reopens the worker (RD1 a real re-driven worker's shape
    at the moment of its resume; RD2 the same worker whole; RD3 a failed attempt, which changes nothing; RD4 the no-notice
    rule on the resumed run; RD5 Astra's digest-shaped probe, the result only in text; RD6 the older resume wording), and
    the last-run boundary follows messages (MB1 Astra's boundary-split; MB2 a real worker's boundary, which must stay
    PURE). Dual-review execute mode, step 8 — the reviewer's `DUAL-REVIEW-GEN <G>` token is a family of its own (K1).
    CENSUS adds census() — real transcripts, including every real resume."""
    import tempfile
    allok = True

    def check(label, rc, out, want_rc, want_lines=(), absent=(), contains=()):
        nonlocal allok
        lines = out.splitlines()
        ok = (rc == want_rc and all(w in lines for w in want_lines) and not any(a in out for a in absent)
              and all(c in out for c in contains))
        allok &= ok
        print(f"selftest {label}: exit={rc} (expected {want_rc}) — {'PASS' if ok else 'FAIL'}")
        if not ok:
            print("    missing: " + repr([w for w in want_lines if w not in lines] + [c for c in contains if c not in out])
                  + "  unwanted: " + repr([a for a in absent if a in out]))
            print("    " + out.replace("\n", "\n    "))

    def worker_line(name, tools, mark, turns=2):   # every synthetic message carries 10 output tokens
        return f"  worker {name:<16} {'claude-opus-5':<18} {'xhigh':<7} out={10 * turns:>7} tools={tools:>3} turns={turns:>3}  {mark}"

    def mixed(name, reason, tools, turns=2):   # the three lines a worker that did not finish prints
        return [worker_line(name, tools, "EVIDENCE-MISSING", turns), f"  MIXED  {name:<16} {reason}",
                f"PURITY: MIXED · executor claude-opus-5 xhigh · workers 1 × claude-opus-5 xhigh · offenders: {name}={reason}"]

    with tempfile.TemporaryDirectory(prefix="purity-selftest-") as tmp:
        cases = (("T1 ends mid tool_use (answer never recorded)", "t1", "mid_tool", True, "ends mid tool_use"),
                 ("T2 notice present, file ends before the finishing turn (last block thinking)", "t2", "before_reply", True,
                  "ends before its finishing turn"),
                 ("T3 otherwise whole file with no trailing newline", "t3", "whole", False, "no trailing newline"),
                 ("T4 the GATE 4 fixture's shape (mid tool_use AND no trailing newline)", "t4", "mid_tool", False,
                  "ends mid tool_use; no trailing newline"))
        for label, key, shape, newline, why in cases:
            parent, name = _st_claude(tmp, key, shape, newline=newline)
            rc, out = _st_main(["--claude", parent])
            check(label, rc, out, 1, mixed(name, f"transcript incomplete ({why})", 2 if shape == "mid_tool" else 1))
        pure = "PURITY: PURE · executor claude-opus-5 xhigh · workers 1 × claude-opus-5 xhigh"
        guards = (("G1 null stop_reason, no tool call, NO notice, quiet 3600 s (beh-null-stop)", "g1", dict(notice=False, age=3600)),
                  ("G2 null stop_reason on a final text reply WITH a notice (beh-queue-notification; how 528 completed workers here end)", "g2", {}),
                  ("G3 end_turn final reply with a notice (control)", "g3", {}))
        for label, key, kw in guards:
            parent, name = _st_claude(tmp, key, "whole" if key == "g3" else "null_text", **kw)
            rc, out = _st_main(["--claude", parent])
            check(label, rc, out, 0, [worker_line(name, 1, "ok"), pure], absent=("transcript incomplete", "EVIDENCE-MISSING"))
        # ---- loop 2: completion needs positive evidence
        parent, name = _st_claude(tmp, "h1", "after_answer")
        rc, out = _st_main(["--claude", parent])
        check("H1 completed notice, file cut right after an ANSWERED tool call, newline kept (Astra H1 cut-after-answer)",
              rc, out, 1, mixed(name, "transcript incomplete (no finishing reply after the last tool call)", 1, turns=1))
        parent, name = _st_claude(tmp, "h2", "null_text", statuses=("killed",))
        rc, out = _st_main(["--claude", parent])
        check("H2 killed notice, the worker ends on an ordinary text reply (Astra H2 killed-text; a real worker's shape)",
              rc, out, 1, mixed(name, "worker killed by parent", 1))
        parent, name = _st_claude(tmp, "h3", "before_reply", notice=False, age=3600)
        rc, out = _st_main(["--claude", parent])
        check("H3 no notice, thinking-only tail, quiet 3600 s: still running, never PURE (Astra H3 cut-thinking-no-notice)",
              rc, out, 2, ["PURITY: NOTHING-TO-CHECK · 1 tagged worker(s) still running (no result recorded yet) — wait for them to finish and re-run"],
              absent=("PURITY: PURE", "  worker "))
        parent, name = _st_claude(tmp, "s1", "whole", statuses=("failed",))
        rc, out = _st_main(["--claude", parent])
        check("S1 failed notice on a whole transcript: any status but completed is the verdict", rc, out, 1,
              mixed(name, "worker failed by parent", 1))
        # R1 is built on real run timing since loop 3: a resumed worker's last run comes after its first notice
        parent, name = _st_resumed(tmp, "r1", [("claude-opus-5", 1, "killed", None), ("claude-opus-5", 1, "completed", 1)])
        rc, out = _st_main(["--claude", parent])
        check("R1 resumed worker, killed then completed: the LAST notice rules, and its last run is judged",
              rc, out, 0, [worker_line(name, 2, "ok", turns=3), pure], absent=("by parent", "EVIDENCE-MISSING"))
        parent, name = _st_claude(tmp, "r2", "whole", statuses=("completed", "killed"))
        rc, out = _st_main(["--claude", parent])
        check("R2 resumed worker, completed then killed: the LAST notice rules", rc, out, 1,
              mixed(name, "worker killed by parent", 1))
        parent, name = _st_claude(tmp, "d1", "null_text", calls=2)
        rc, out = _st_main(["--claude", parent])
        check("D1 completed notice counts 2 tool calls, the file holds 1 and ends on text (a cut between a text block and "
              "its tool call)", rc, out, 1, mixed(name, "transcript incomplete (notice counts 2 tool calls, file holds 1)", 1))
        parent, name = _st_claude(tmp, "d2", "null_text", calls=0)
        rc, out = _st_main(["--claude", parent])
        check("D2 completed notice counts FEWER tool calls than the file holds (a fork's inherited history): PURE",
              rc, out, 0, [worker_line(name, 1, "ok"), pure], absent=("transcript incomplete", "EVIDENCE-MISSING"))
        # ---- loop 3: a re-driven worker is judged on its LAST run
        opus, sonnet = "claude-opus-5", "claude-sonnet-5"
        parent, name = _st_resumed(tmp, "rs1", [(opus, 2, "completed", 2), (opus, 1, "completed", 1)])
        rc, out = _st_main(["--claude", parent])
        check("RS1 resumed worker, whole, both runs on the executor's runtime (notices 2 then 1): PURE", rc, out, 0,
              [worker_line(name, 3, "ok", turns=5), pure], absent=("transcript incomplete", "EVIDENCE-MISSING"))
        parent, name = _st_resumed(tmp, "rs2", [(opus, 1, "completed", 1), (sonnet, 1, "completed", 1)])
        rc, out = _st_main(["--claude", parent])
        check("RS2 Astra's N1 control: the same worker whole, its re-driven second run on Sonnet: MIXED on the runtime",
              rc, out, 1, [worker_line(name, 2, "MIXED", turns=4)],
              contains=(f"offenders: {name}=claude-sonnet-5 xhigh at 2026-09-11T10:00:",
                        "(+1 more off-runtime turn(s))"), absent=("transcript incomplete",))
        parent, name = _st_resumed(tmp, "rs3", [(opus, 1, "completed", 1), (sonnet, 1, "completed", 1)], keep=1)
        rc, out = _st_main(["--claude", parent])
        check("RS3 Astra's N1 cut: the file ends after the first run, the parent keeps both notices: MIXED, not PURE",
              rc, out, 1, mixed(name, "transcript incomplete (last run: no assistant message)", 1))
        parent, name = _st_resumed(tmp, "rs4", [(opus, 3, "completed", 3), (opus, 2, "completed", 2)], cut_text=1)
        rc, out = _st_main(["--claude", parent])
        check("RS4 notices 3 then 2 (the run counted alone); the file ends inside the last run on a text block whose tool "
              "call was never written — the whole file still holds 4 calls", rc, out, 1,
              mixed(name, "transcript incomplete (last run: notices count 3 then 2 tool calls, last run holds 1)", 4, turns=6))
        parent, name = _st_resumed(tmp, "rs5", [(opus, 2, "completed", 2), (opus, 3, "completed", 5)])
        rc, out = _st_main(["--claude", parent])
        check("RS5 notices 2 then 5 (the run counted on top of the previous count), whole: PURE — a last run held to "
              "the full 5 would flag 22 of the 67 real resumed workers here", rc, out, 0,
              [worker_line(name, 5, "ok", turns=7), pure], absent=("transcript incomplete", "EVIDENCE-MISSING"))
        parent, name = _st_claude(tmp, "f1", "null_text", notice=False, age=0,
                                  launch_text="Fork started — processing in background")
        rc, out = _st_main(["--claude", parent])
        check("F1 fork launch wording, no notice, fresh text tail: still running, never PURE (Astra N2 fork-fresh-text)",
              rc, out, 2, ["PURITY: NOTHING-TO-CHECK · 1 tagged worker(s) still running (no result recorded yet) — wait for them to finish and re-run"],
              absent=("PURITY: PURE", "  worker "))
        # ---- loop 4: an accepted re-drive reopens the worker; the last-run boundary follows messages.
        #      The same checks on REAL transcripts run in the census.
        running = ["PURITY: NOTHING-TO-CHECK · 1 tagged worker(s) still running (no result recorded yet) — wait for them to finish and re-run"]
        resumed = lambda a: {"success": True, "message": f"Resuming agent {a[:7]}", "resumedAgentId": a,
                             "pin": {"id": a, "name": a, "ref": "2813fe"}}
        parent, name = _st_redrive(tmp, "rd1", resumed(_st_aid("rd1")), age=3600)
        rc, out = _st_main(["--claude", parent])
        check("RD1 the shape of a real re-driven worker at its resume: its completed notice, then an ACCEPTED resume "
              "and the worker's copy of the request, no new reply yet, file quiet: still running, never PURE (Astra N3; "
              "loop 3 read PURE)", rc, out, 2, running, absent=("PURITY: PURE", "  worker "))
        parent, name = _st_redrive(tmp, "rd2", resumed(_st_aid("rd2")), run2=(1, 1))
        rc, out = _st_main(["--claude", parent])
        check("RD2 the same worker whole: the resumed run made its call, replied, and the parent's notice for it arrived: PURE",
              rc, out, 0, [worker_line(name, 3, "ok", turns=5), pure], absent=("transcript incomplete", "EVIDENCE-MISSING"))
        a = _st_aid("rd3")
        parent, name = _st_redrive(tmp, "rd3", {"success": False, "message": f'Agent "{a}" could not be resumed: No '
                                                f'transcript found for agent ID: {a}'}, request=False, age=3600)
        rc, out = _st_main(["--claude", parent])
        check("RD3 a FAILED resume attempt (`success:false`, No transcript found) resumed nothing: the verdict is the "
              "worker's own, PURE", rc, out, 0, [worker_line(name, 2, "ok", turns=3), pure], absent=("still running",))
        parent, name = _st_redrive(tmp, "rd4", resumed(_st_aid("rd4")), run2=1, age=3600)
        rc, out = _st_main(["--claude", parent])
        check("RD4 an accepted resume, no notice since, a quiet file whose run from the resume onward ends on a finishing "
              "reply: judged by the no-notice rule, PURE", rc, out, 0, [worker_line(name, 3, "ok", turns=5), pure],
              absent=("transcript incomplete", "still running"))
        a = _st_aid("rd5")
        parent, name = _st_redrive(tmp, "rd5", {"success": True, "message": f"Resuming agent {a[:7]}", "resumedAgentId": a},
                                   structured=False, request=False, age=3600)
        rc, out = _st_main(["--claude", parent])
        check("RD5 Astra's digest-shaped correction probe (`Re-emit the cards with raw HTML markup; do not escape tags`, the "
              "result only in the tool result's text), before any new reply: still running, never PURE", rc, out, 2,
              running, absent=("PURITY: PURE", "  worker "))
        a = _st_aid("rd6")
        parent, name = _st_redrive(tmp, "rd6", {"success": True, "message": f'Agent "{a}" was stopped (completed); resumed '
                                                f"it in the background with your message. You'll be notified when it "
                                                f"finishes.", "resumedAgentId": a}, age=3600)
        rc, out = _st_main(["--claude", parent])
        check("RD6 the older accepted-resume wording (`was stopped (completed); resumed it in the background`, 2 real "
              "cases): still running, never PURE", rc, out, 2, running, absent=("PURITY: PURE", "  worker "))
        a = _st_aid("mb1")   # Astra's boundary-split, record for record
        send = lambda stamp, text: _st_at(stamp, "s1", [{"type": "tool_use", "id": "send1", "name": "SendMessage",
                                                         "input": {"to": a, "message": text}}], "tool_use")
        sent = lambda stamp, content: {"type": "user", "uuid": "s1r", "timestamp": stamp, "message": {
            "role": "user", "content": [{"type": "tool_result", "tool_use_id": "send1", "content": content}]}}
        head = lambda: [{"type": "user", "uuid": "w0", "timestamp": _st_ts(10), "message": {"role": "user", "content": WORKER_TAG + " batch A"}},
                        _st_asst(11, "r0m0", [{"type": "tool_use", "id": "r0tu0", "name": "Read", "input": {}}], "tool_use"),
                        {"type": "user", "uuid": "w0r0", "timestamp": _st_ts(12), "message": {
                            "role": "user", "content": [{"type": "tool_result", "tool_use_id": "r0tu0", "content": "ok"}]}},
                        _st_asst(13, "r0fin", [{"type": "text", "text": "run 1 done"}], None)]
        prec = (_st_launch(a) + [send(_st_tsf(13.2), "Re-emit the cards with raw HTML markup."), sent(_st_tsf(13.3), "Message sent")]
                + _st_notice(a, _st_ts(14), 1, 1) + _st_notice(a, _st_ts(22), 2, 1)
                + [_st_asst(26, "pz", [{"type": "text", "text": "all batches back"}], "end_turn")])
        wrec = head() + [_st_at(_st_tsf(13.5), "split", [{"type": "tool_use", "id": "gap-tool", "name": "Read", "input": {}}], None),
                         _st_at(_st_ts(15), "split", [{"type": "text", "text": "I will inspect that result."}], None)]
        parent, name = _st_files(tmp, "mb1", prec, wrec)
        rc, out = _st_main(["--claude", parent])
        check("MB1 Astra's boundary-split: a message's tool call written before the previous notice, its text after, no "
              "result: the message is read whole — the tool call is unanswered (Astra N4; loop 3 read PURE)", rc, out, 1,
              mixed(name, "transcript incomplete (last run: ends mid tool_use)", 2, turns=3))
        a = _st_aid("mb2")   # a real worker's boundary, on its real timing
        queued = {"success": True, "message": f"Message queued for delivery to {a} at its next tool round.",
                  "pin": {"id": a, "name": a, "ref": "0a1b2c"}}
        prec = (_st_launch(a) + [send(_st_tsf(12.5), "Also check the footer."),
                                 dict(sent(_st_tsf(12.6), [{"type": "text", "text": json.dumps(queued)}]), toolUseResult=queued)]
                + _st_notice(a, _st_tsf(16.751), 1, 1) + _st_notice(a, _st_ts(23), 2, 2)
                + [_st_asst(26, "pz", [{"type": "text", "text": "all batches back"}], "end_turn")])
        wrec = head() + [{"type": "user", "uuid": "w-ask", "timestamp": _st_tsf(13.077), "message": {
                             "role": "user", "content": "The coordinator sent a message while you were working:\nAlso check the footer."}},
                         _st_at(_st_tsf(15.188), "x", [{"type": "thinking", "thinking": "…"}], None),
                         _st_at(_st_tsf(17.06), "x", [{"type": "tool_use", "id": "xtu", "name": "Read", "input": {}}], "tool_use"),
                         {"type": "user", "uuid": "wxr", "timestamp": _st_tsf(17.109), "message": {
                             "role": "user", "content": [{"type": "tool_result", "tool_use_id": "xtu", "content": "ok"}]}},
                         _st_at(_st_ts(20), "y", [{"type": "text", "text": "footer checked"}], None)]
        parent, name = _st_files(tmp, "mb2", prec, wrec)
        rc, out = _st_main(["--claude", parent])
        check("MB2 a real worker's boundary: its second run's first message thinks before the previous notice and calls "
              "a tool after it; notices 1 then 2 (on top), whole: PURE — giving that message to the EARLIER run, as the "
              "brief worded it, would leave the run 0 of its 1 call and flag a whole real worker",
              rc, out, 0, [worker_line(name, 2, "ok", turns=4), pure], absent=("transcript incomplete", "EVIDENCE-MISSING"))
        ex, ch = _st_codex(tmp, "c1", complete=False)
        rc, out = _st_main(["--codex", ex, ch])
        check("C1 Codex child cut mid-write of its task_complete (no newline): not PURE — the cycle never closed, "
              "so the existing rule reads it still running", rc, out, 2,
              ["  worker 2026-09-11T10-00-05 still running",
               "PURITY: NOTHING-TO-CHECK · 1 tagged worker thread(s) still running — wait for them to finish and re-run"],
              absent=("PURITY: PURE",))
        ex, ch = _st_codex(tmp, "c2", complete=True)
        rc, out = _st_main(["--codex", ex, ch])
        check("C2 the same child with its task_complete whole (control)", rc, out, 0,
              ["PURITY: PURE · executor gpt-5.6-sol xhigh · workers 1 × gpt-5.6-sol xhigh"])
        # K1 (dual-review execute mode, step 8): the reviewer's window token is a family of its own — printed alone on a
        # line it is a token; quoted mid-sentence or malformed it is not; it never closes a digest window
        g = "DUAL-REVIEW-GEN-20000101-000000"
        k1 = {"standalone line": standalone_tokens(f"DUAL-REVIEW-GEN {g}") == [f"DUAL-REVIEW-GEN {g}"],
              "in backticks, then more text": standalone_tokens(f"`DUAL-REVIEW-GEN {g}`\nnext") == [f"DUAL-REVIEW-GEN {g}"],
              "quoted mid-sentence": standalone_tokens(f"I will print DUAL-REVIEW-GEN {g} first") == [],
              "malformed id": standalone_tokens("DUAL-REVIEW-GEN DUAL-REVIEW-GEN-2026091-09776c") == [],
              "its own family": token_family(f"DUAL-REVIEW-GEN {g}") == "DUAL-REVIEW-GEN",
              "never closes a DIGEST-RUN window": not closes_window(f"DUAL-REVIEW-GEN {g}", "DIGEST-RUN-2000-01-01-0000"),
              "a new generation closes its own family's window":
                  closes_window("DUAL-REVIEW-GEN DUAL-REVIEW-GEN-20260914-abcdef", f"DUAL-REVIEW-GEN {g}"),
              "the old family unchanged": token_family("DIGEST-RUN-2000-01-01-0000") == "DIGEST-RUN"}
        allok &= all(k1.values())
        print(f"selftest K1 the DUAL-REVIEW-GEN token family (dual-review execute mode): "
              f"{sum(k1.values())}/{len(k1)} — {'PASS' if all(k1.values()) else 'FAIL ' + repr([k for k, v in k1.items() if not v])}")
    if census:
        allok &= run_census()
    print("selftest: PASS" if allok else "selftest: FAIL")
    return 0 if allok else 1


# ---------------------------------------------------------------- census (v6.26 loop 2, `--selftest --census`)
CENSUS_MIN_AGE = 1800   # a worker written in the last 30 minutes may still be running, so the census leaves it out


def _census_file_notices(path, cache):
    """{agent id: [(status, tool calls, envelope, timestamp), …]} in file order, for every notice in the file at PATH —
    record_notices, the same reader parse_parent uses, applied to every record that holds an envelope (the substring
    test only skips the json.loads of lines that cannot hold one); last_notice folds each list, as parse_parent does."""
    if path not in cache:
        found = {}
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            fh = None
        if fh:
            with fh:
                for line in fh:
                    if "<task-notification>" not in line:
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(o, dict):
                        for aid, status, calls, env in record_notices(o):
                            found.setdefault(aid, []).append((status, calls, env, o.get("timestamp")))
        cache[path] = found
    return cache[path]


def _loop1_flagged(path):
    """THE LOOP-1 RULE, as Astra reviewed it (sha256 df934103…), kept only so the census can show that every file it
    flagged is still flagged: the last message calls a tool no later record answers; or a null stop_reason and a last
    block that is not text; or no final newline. It reads the one grouper — this is not a second one."""
    last_id, blocks, stop, answered, _calls = last_assistant_message(path)
    if last_id is not None:
        if any(b.get("id") not in answered for b in blocks if b.get("type") == "tool_use"):
            return True
        if stop is None and not (blocks and blocks[-1].get("type") == "text"):
            return True
    return ends_in_newline(path) is not True


def _census_gate(tmp, worker, aid, notice_records):
    """Run the REAL gate (main) on a real worker: its transcript copied byte for byte beside a synthetic tagged parent
    whose executor runs on the worker's own majority runtime (so the runtime comparison cannot be what flags it), and
    whose completion evidence is the real parent's own notice records for this worker, verbatim. Astra's real-repro
    method, loop 1 appendix. Returns main's (exit, stdout). The copy keeps the worker file's times: a worker the parent
    resumed after its last notice is read by the no-notice rule, whose quiet test reads them (v6.26 loop 4)."""
    import shutil
    sid = "census-" + aid
    os.makedirs(os.path.join(tmp, sid, "subagents"))
    shutil.copy2(worker, os.path.join(tmp, sid, "subagents", f"agent-{aid}.jsonl"))
    p = profile_claude(worker)
    m, e = (p[0], p[1]) if p and p[0] != "unknown" and p[1] != "?" else ("claude-opus-5", "xhigh")
    ex = lambda i, blocks, stop: {"type": "assistant", "uuid": f"c{i}", "timestamp": _st_ts(i), "effort": e,
                                  "message": {"role": "assistant", "id": f"c{i}", "model": m, "content": blocks,
                                              "stop_reason": stop, "usage": {"output_tokens": 1}}}
    recs = [ex(0, [{"type": "text", "text": "starting"}], "end_turn"),
            ex(1, [{"type": "tool_use", "id": "toolu_census", "name": "Agent", "input": {"prompt": WORKER_TAG + " census"}}], "tool_use"),
            {"type": "user", "uuid": "c2", "timestamp": _st_ts(2), "toolUseResult": {"agentId": aid},
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_census",
                                                      "content": [{"type": "text", "text": "Async agent launched successfully."}]}]}}]
    recs += notice_records + [ex(9, [{"type": "text", "text": "back"}], "end_turn")]
    parent = os.path.join(tmp, sid + ".jsonl")
    _st_write(parent, recs)
    return _st_main(["--claude", parent])


def run_census():
    """The finish rule over every real subagent transcript on this machine whose parent holds a notice for it. Root:
    CLAUDE_PROJECTS_ROOT (default ~/.claude/projects). Byte-identical
    copies of one worker count once; files newer than CENSUS_MIN_AGE are left out. A worker's notices are read from the
    candidate file holding the LONGEST sequence of them — its parent session, or a sibling agent file for a worker a
    subagent launched; a fork sibling holds only a copy of the parent's context up to the fork, so it never has more.
    Assertions, never fixed totals (cleanup changes them): every worker whose last status is not `completed` flags
    through the real gate on its real notice records; every file the loop-1 rule flagged still flags; a sample of 20
    completed workers ending on a null-stop text reply (the ordinary ending) does not flag; and (loop 3) every completed
    worker the parent notified more than once flags through the real gate once its file is cut back to the moment of
    the parent's previous notice — Astra's N1 cut, on every real re-driven worker. Everything else is printed."""
    import hashlib, tempfile, time
    roots = []
    for r in [CLAUDE_PROJECTS_ROOT]:
        rp = os.path.realpath(r)
        if os.path.isdir(rp) and rp not in roots:
            roots.append(rp)
    now, copies = time.time(), {}
    for root in roots:
        for f in sorted(glob.glob(os.path.join(root, "*", "*", "subagents", "agent-*.jsonl"))):
            aid = agent_file_id(f)
            try:
                if not aid or now - os.path.getmtime(f) < CENSUS_MIN_AGE:
                    continue
                with open(f, "rb") as fh:
                    sha = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                continue
            copies.setdefault((aid, sha), []).append(f)
    cache, pop = {}, []
    for (aid, _sha), paths in sorted(copies.items()):
        # One worker can sit in two session folders — Claude Code links it into a later session that resumes it
        # (one real worker failed in the first session and completed in the one that resumed it) — so the candidates
        # are every copy's parent session and sibling agent files, and the longest notice sequence is the worker's history.
        cands = []
        for f in paths:
            d = os.path.dirname(f)
            top = os.path.join(os.path.dirname(os.path.dirname(d)), os.path.basename(os.path.dirname(d)) + ".jsonl")
            cands += ([top] if os.path.isfile(top) else []) + sorted(g for g in glob.glob(os.path.join(d, "agent-*.jsonl"))
                                                                    if g not in paths)
        best = max(((len(_census_file_notices(c, cache).get(aid, [])), -k, c) for k, c in enumerate(cands)), default=(0, 0, None))
        if best[0]:
            pop.append((aid, paths[0], best[2], _census_file_notices(best[2], cache)[aid]))
    ok = True
    status_n = Counter(seq[-1][0] for _a, _f, _p, seq in pop)
    print(f"census: {len(pop)} worker transcripts with a parent notice (roots: {', '.join(tilde(r) for r in roots)}; "
          f"older than {CENSUS_MIN_AGE // 60} min; byte-identical copies counted once)")
    print("census: last notice status — " + " · ".join(f"{s or 'no status'} {n}" for s, n in status_n.most_common()))
    nonc = [(a, f, p, seq) for a, f, p, seq in pop if seq[-1][0] != "completed"]
    with tempfile.TemporaryDirectory(prefix="purity-census-") as tmp:
        for status in sorted({seq[-1][0] or "" for _a, _f, _p, seq in nonc}):
            group = [(a, f, p, seq) for a, f, p, seq in nonc if (seq[-1][0] or "") == status]
            flagged, alone, missed = 0, 0, []
            for a, f, p, seq in group:
                rc, out = _census_gate(tmp, f, a, _census_notice_records(p, a))
                # the gate names the parent's status — or, for a worker with no assistant turn to profile, says that first
                want = completion_gap(f, last_notice(seq)) if profile_claude(f) else "tagged transcript with no assistant turn"
                if rc == 1 and f"  MIXED  {a[:14]:<16} {want}" in out.splitlines():
                    flagged += 1
                else:
                    missed.append(a)
                alone += completion_gap(f, ("completed",) + last_notice(seq)[1:]) is not None
            ok &= not missed
            print(f"census: {status or 'no status'} — {flagged}/{len(group)} flagged by the real gate on their real notice "
                  f"records" + (f" · MISSED {missed}" if missed else "") + f" · the transcript alone (status ignored) "
                  f"would flag {alone}/{len(group)}")
            if status == "killed":
                print("census:   killed workers — " + ", ".join(f"{a} ({os.path.basename(p)})" for a, _f, p, _s in group))
        loop1 = [(a, f, seq) for a, f, _p, seq in pop if _loop1_flagged(f)]
        still = [a for a, f, seq in loop1 if completion_gap(f, last_notice(seq)) is not None]
        ok &= len(still) == len(loop1)
        print(f"census: loop-1 flags — {len(still)}/{len(loop1)} still flagged"
              + ("" if len(still) == len(loop1) else f" · NO LONGER FLAGGED {sorted({a for a, _f, _s in loop1} - set(still))}"))
        comp = [(a, f, p, seq) for a, f, p, seq in pop if seq[-1][0] == "completed"]
        ordinary = []
        for a, f, p, seq in comp:
            last_id, blocks, stop, _ans, _n = last_assistant_message(f)
            if last_id is not None and stop is None and blocks and blocks[-1].get("type") == "text":
                ordinary.append((a, f, p, seq))
        sample = [ordinary[i * len(ordinary) // 20] for i in range(20)] if len(ordinary) >= 20 else ordinary
        false_pos = []
        for a, f, p, seq in sample:
            rc, out = _census_gate(tmp, f, a, _census_notice_records(p, a))
            # the runtime comparison may still call a real worker MIXED (the executor is synthetic) — only a FINISH verdict counts
            if completion_gap(f, last_notice(seq)) is not None or "by parent" in out or "transcript incomplete" in out or "still running" in out:
                false_pos.append(a)
        ok &= not false_pos and len(sample) == 20
        print(f"census: sample — {len(false_pos)}/{len(sample)} completed workers ending on a null-stop text reply flagged "
              f"(every {max(len(ordinary) // 20, 1)}th of {len(ordinary)} by agent id; the real gate run on each)"
              + (f" · FALSE POSITIVES {false_pos}" if false_pos else ""))
        flagged_comp = [(a, why) for a, why in ((a, completion_gap(f, last_notice(seq))) for a, f, _p, seq in comp) if why]
        print(f"census: all {len(comp)} completed workers — {len(flagged_comp)} flagged by the cut indicators"
              + "".join(f"\ncensus:   {a} {why}" for a, why in flagged_comp))
        resumed = [(a, f, seq) for a, f, _p, seq in pop if len({x[0] for x in seq}) > 1]
        for a, f, seq in resumed:
            order = [x[0] for i, x in enumerate(seq) if i == 0 or x[0] != seq[i - 1][0]]
            print(f"census: resumed {a} notices {' → '.join(str(s) for s in order)} → "
                  f"{completion_gap(f, last_notice(seq)) or 'judged on its transcript: finished'}")
        # Loop 3 (Astra loop 2, N1): each completed worker the parent notified more than once, cut back to the file as it
        # stood when the parent's previous notice was written — every line before the first record stamped after it —
        # and run through the real gate on its real notice records. Its earlier run's reply and calls are all on disk;
        # the last run is not, and that must flag.
        multi = [(a, f, p, seq) for a, f, p, seq in comp if last_notice(seq)[2] is not None]
        whole_flag = [a for a, _f, _p, _s in multi if a in {x for x, _w in flagged_comp}]
        cut_ok, cut_missed = 0, []
        for a, f, p, seq in multi:
            cut = os.path.join(tmp, "last-run-cuts", a, f"agent-{a}.jsonl")
            _census_cut(f, last_notice(seq)[2], cut)
            rc, out = _census_gate(os.path.join(tmp, "last-run-gates"), cut, a, _census_notice_records(p, a))
            if rc == 1 and any(l.startswith(f"  MIXED  {a[:14]:<16} transcript incomplete (last run: ") for l in out.splitlines()):
                cut_ok += 1
            else:
                cut_missed.append(a)
        ok &= not cut_missed
        print(f"census: re-driven — {len(multi)} completed workers the parent notified more than once: whole, "
              f"{len(whole_flag)} flagged; cut back to the parent's previous notice, {cut_ok}/{len(multi)} flagged "
              f"`transcript incomplete (last run: …)` by the real gate on their real notice records"
              + (f" · MISSED {cut_missed}" if cut_missed else ""))
        # Loop 4 (Astra loop 3, N3): every resume a parent's SendMessage got accepted, read as parent and worker stood the
        # moment it was accepted — the parent's own notice records for the worker before it, then the SendMessage call
        # and its result, all verbatim; the worker's file cut after its last record stamped at or before the result, with
        # its own times — must read still running through the real gate. No notice has closed the run the resume
        # started, and the worker's earlier reply cannot stand in for it. The same snapshot without the call and the
        # result is loop 3's reading. Every failed attempt must leave the verdict exactly as it was. A copy of a
        # session that continued another holds the same resume (same tool_use id): it counts once, and the copy kept
        # is one whose worker file sits beside it when there is one.
        worker_of = lambda parent, a: next((w for w in [os.path.join(worker_dir(parent), f"agent-{a}.jsonl")]
                                            if os.path.isfile(w) and now - os.path.getmtime(w) >= CENSUS_MIN_AGE), None)
        found, uniq, seen_r = _census_sends(roots), [], set()
        for x in sorted(found, key=lambda x: worker_of(x[0], x[5]) is None):   # stable: file order within each group
            if (x[5], x[6], x[7]) not in seen_r:
                seen_r.add((x[5], x[6], x[7])); uniq.append(x)
        acc, fails = [x for x in uniq if x[7] == "accepted"], [x for x in uniq if x[7] == "failed"]
        still = "PURITY: NOTHING-TO-CHECK · 1 tagged worker(s) still running (no result recorded yet) — wait for them to finish and re-run"
        verdict = lambda rc: {0: "PURE", 1: "MIXED", 2: "still running"}.get(rc, f"exit {rc}")
        pname = lambda p: os.path.basename(p)[:14 if os.path.basename(p).startswith("agent-") else 8] + "…"
        snaps, snap_miss, loop3_read, absent = 0, [], Counter(), []
        for k, (parent, cpos, call, rpos, res, a, tid, _kind) in enumerate(acc):
            w = worker_of(parent, a)
            if not w:
                absent.append(f"{a} ({pname(parent)}:{rpos + 1})")
                continue
            snaps += 1
            before = [(i, o) for i, o in _census_notice_lines(parent, a) if i < rpos]
            cut = os.path.join(tmp, "resume-cuts", str(k), f"agent-{a}.jsonl")
            _census_cut(w, _stamp(res.get("timestamp")), cut)
            rc, out = _census_gate(os.path.join(tmp, "resume-gates", str(k)), cut, a,
                                   [o for _i, o in sorted(before + [(cpos, call), (rpos, res)], key=lambda x: x[0])])
            rc3, _out3 = _census_gate(os.path.join(tmp, "resume-gates-loop3", str(k)), cut, a, [o for _i, o in before])
            loop3_read[verdict(rc3)] += 1
            if not (rc == 2 and still in out.splitlines()):
                snap_miss.append(f"{a} ({pname(parent)}:{rpos + 1})")
        ok &= snaps > 0 and not snap_miss
        print(f"census: accepted resumes — {len(acc)} on this machine ({len(found) - len(uniq)} more records are copies "
              f"in a session that continued another); {snaps} with the worker's file beside its parent, read as they "
              f"stood the moment each was accepted: {snaps - len(snap_miss)}/{snaps} still running through the real gate"
              + (f" · MISSED {snap_miss}" if snap_miss else "") + " · the same snapshots without the call and its result "
              f"(loop 3's reading): " + " · ".join(f"{v} {n}" for v, n in loop3_read.most_common())
              + (f" · no worker file beside the parent: {', '.join(absent)}" if absent else ""))
        same, changed = 0, []
        for k, (parent, cpos, call, rpos, res, a, tid, _kind) in enumerate(fails):
            w = worker_of(parent, a)
            if not w:
                continue
            notes = _census_notice_lines(parent, a)
            with_try = _census_gate(os.path.join(tmp, "failed-try", str(k)), w, a,
                                    [o for _i, o in sorted(notes + [(cpos, call), (rpos, res)], key=lambda x: x[0])])
            without = _census_gate(os.path.join(tmp, "failed-try-none", str(k)), w, a, [o for _i, o in notes])
            if with_try == without:
                same += 1
            else:
                changed.append(a)
        ok &= not changed
        print(f"census: failed resume attempts — {len(fails)} in {len({x[0] for x in fails})} parent files: "
              f"{same}/{len(fails)} verdicts unchanged by the attempt through the real gate"
              + (f" · CHANGED {changed}" if changed else ""))
        # A resume no notice in its parent follows: the whole worker, the parent's notices and every resume of it there,
        # through the real gate — what the tool reads once the worker has stopped writing. Shown, not asserted.
        shown = []
        for parent, _cp, _c, _rp, _r, a, _t, kind in found:
            if kind != "accepted" or (parent, a) in shown:
                continue
            mine = [x for x in found if x[0] == parent and x[5] == a and x[7] == "accepted"]
            notes = _census_notice_lines(parent, a)
            closed = any(i > max(x[3] for x in mine) for i, _o in notes)
            if closed:
                continue
            shown.append((parent, a))
            w = worker_of(parent, a)
            if w:
                recs = notes + [(p2, o2) for x in mine for p2, o2 in ((x[1], x[2]), (x[3], x[4]))]
                rc, out = _census_gate(os.path.join(tmp, "resume-whole", str(len(shown))), w, a,
                                       [o for _i, o in sorted(recs, key=lambda x: x[0])])
                last = next((l for l in reversed(out.splitlines()) if l.startswith("PURITY:")), f"exit {rc}")
            else:
                last = "no worker file beside this parent"
            said = ("notices " + " then ".join(dict.fromkeys(x[1] or "no status" for _i, o in notes
                                                             for x in record_notices(o) if x[0] == a))) if notes else "no notice"
            print(f"census:   resumed {a} in {pname(parent)} ({said}; "
                  f"no notice after its last resume): {last}")
    print(f"census: {'PASS' if ok else 'FAIL'}")
    return ok


def _census_notice_records(parent, aid):
    """The records of PARENT that carry a notice for AID, verbatim and in file order — the completion evidence
    _census_gate hands the real gate."""
    return [o for _i, o in _census_notice_lines(parent, aid)]


def _census_notice_lines(parent, aid):
    """[(line index, record)] for every record of PARENT that carries a notice for AID, verbatim and in file order. Only
    a line holding both the envelope marker and the id is parsed at all."""
    out = []
    with open(parent, encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if aid in line and "<task-notification>" in line:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if isinstance(o, dict) and any(x[0] == aid for x in record_notices(o)):
                    out.append((i, o))
    return out


def _census_sends(roots):
    """Every SendMessage result that resumed a worker or failed to, in every session and agent file under ROOTS (v6.26
    loop 4): [(file, line of the call, call record, line of the result, result record, agent id, tool_use id, 'accepted'
    | 'failed')], read by send_results and judged by resumed_agent, as the gate reads them. A file that never names
    SendMessage is not parsed. Lines are numbered as _census_notice_lines numbers them — the file's own lines, never
    str.splitlines(), which also breaks at a U+2028 a record's text can hold."""
    out = []
    for root in roots:
        for f in sorted(glob.glob(os.path.join(root, "*", "*.jsonl")) + glob.glob(os.path.join(root, "*", "*", "subagents", "agent-*.jsonl"))):
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    if "SendMessage" not in fh.read():
                        continue
                    fh.seek(0)
                    lines = list(fh)
            except OSError:
                continue
            sends, calls = {}, {}
            for i, line in enumerate(lines):
                if "SendMessage" not in line and not (sends and "tool_result" in line):
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(o, dict):
                    continue
                m = o.get("message")
                if isinstance(m, dict) and m.get("role") == "assistant":
                    for b in m.get("content") or []:
                        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "SendMessage":
                            sends[b.get("id")] = str((b.get("input") or {}).get("to") or "")
                            calls[b.get("id")] = (i, o)
                    continue
                for tid, r in send_results(o, sends):
                    # a failed attempt is told by its own words, not by resumed_agent, so a gate that wrongly
                    # accepted one would still be caught by the failed-attempt assertion
                    failed = isinstance(r, dict) and r.get("success") is False and "could not be resumed" in str(r.get("message") or "")
                    aid = None if failed else resumed_agent(r, sends[tid])
                    if failed or aid:
                        out.append((f, calls[tid][0], calls[tid][1], i, o, aid or sends[tid], tid, "failed" if failed else "accepted"))
    return out


def _census_cut(src, since, dst):
    """Write to DST the lines of worker file SRC that come before its first record stamped after SINCE — the file as it
    stood at SINCE — with SRC's own times. Returns the number of lines kept."""
    with open(src, "rb") as fh:
        lines = fh.read().splitlines(keepends=True)
    keep = len(lines)
    for i, raw in enumerate(lines):
        try:
            o = json.loads(raw)
        except Exception:
            continue
        t = _stamp(o.get("timestamp")) if isinstance(o, dict) else None
        if t is not None and since not in (None, LAST_RUN_UNREADABLE) and t > since:
            keep = i
            break
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(b"".join(lines[:keep]))
    os.utime(dst, (os.path.getmtime(src), os.path.getmtime(src)))
    return keep


def main(argv):
    global WORKER_TAG
    if argv and argv[0] == "--selftest":
        if argv[1:] not in ([], ["--census"]):   # a mode, not a filter: anything else would be silently ignored
            print(f"--selftest takes no other argument but --census; got {argv[1:]}"); return EXIT_LOOKUP
        return selftest(census=argv[1:] == ["--census"])
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
        return run_codex(files, after, others, at=windows[files[0]][0], windows=windows)   # the EXECUTOR's entry is a bare (start, end) tuple, so [0] is the run-window start (children hold cycle LISTS)
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
