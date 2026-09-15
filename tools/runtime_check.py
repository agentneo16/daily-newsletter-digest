#!/usr/bin/env python3
"""runtime_check.py — what model and effort is THIS Codex session on? Answered from the rollout on disk, never self-report.

Why it exists: a Codex session cannot see its own TUI status line. Asked to self-report its model and effort, Sol
answered `WRONG RUNTIME — GPT-5/unknown` twice on 2026-09-06 while its own rollout's `turn_context` said
`model: gpt-5.6-sol, effort: xhigh` (Session 191). The rollout knows; the model does not. This tool
reads the rollout, so the SELF-CHECK is a shell command with an exit code instead of a question the model has to guess at.

Usage:
  python3 tools/runtime_check.py --codex                          # this session's runtime, checked against the pinned default
  python3 tools/runtime_check.py --codex --expect gpt-5.6-sol/xhigh   # the default expectation, stated explicitly
  python3 tools/runtime_check.py --codex --within-minutes 1440    # widen the candidate window (default 30 minutes)
  python3 tools/runtime_check.py --codex --session-id <id>        # name the calling session explicitly (overrides the env)
  python3 tools/runtime_check.py --selftest

Output — ONE line on stdout, always the same shape, so a paste prompt can quote it:
  RUNTIME: gpt-5.6-sol/xhigh · rollout rollout-2000-01-01T00-00-00-00000000-….jsonl · started 2000-01-01T00:00:00Z · selector id

Exit codes:
  0  the runtime matches --expect (default gpt-5.6-sol/xhigh)
  2  a rollout was found but its model/effort differ — stdout still prints the RUNTIME line, stderr says what was needed
  3  no candidate rollout, or one that cannot be read for a model/effort — stderr says why (nothing is printed on stdout)
  4  usage error

Which rollout is "this session" — in this order (v6.21 loop 2; loop 1 sorted by start time alone, which handed a Codex
review session the runtime of a DIFFERENT session started later, reproduced live 2026-09-06 23:0x):
  1. EXACT ID. `--session-id`, else the environment's `CODEX_SESSION_ID`, else `CODEX_THREAD_ID` — Codex exports both to
     every command it runs, and their value is the calling rollout's first `session_meta.payload.id`. The eligible
     rollout carrying that id is the answer. No eligible rollout carries it → exit 3, never a guess at a neighbour.
  2. MTIME, only when no id is available. The most recently WRITTEN eligible rollout (`st_mtime_ns`), because Codex
     appends to its own rollout immediately before running the command; `session_meta.timestamp` breaks a tie. This
     still races a second session writing in the same instant, so it announces itself on stderr.
Eligible means: `session_meta.source` is a TOP-LEVEL session — the string "cli" (a REPL) or "exec" (a `codex exec`
run, the form recommended for non-interactive production) — `session_meta.cwd` is the hub root,
and the file was modified inside the --within-minutes window. A spawned worker carries `source: {"subagent":
{"thread_spawn": …}}`, a dict rather than a string, so forks are skipped and a `run news` executor never reads a
worker's runtime as its own. Model and effort are the LAST ones in force in the chosen rollout — exactly what
`worker_purity_check.codex_meta(path)` returns with `at=None`.

Configuration: HUB and CODEX_DIR come from `worker_purity_check` — the one home of the rollout-lookup rules — so the
`DIGEST_HUB` and `CODEX_SESSIONS_DIR` overrides work here identically. No machine-specific path is hardcoded.
"""
import glob, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worker_purity_check as wpc   # the one home of the rollout / record-walking rules AND of the path derivation

HUB = wpc.HUB
CODEX_DIR = wpc.CODEX_DIR
DEFAULT_EXPECT = "gpt-5.6-sol/xhigh"
DEFAULT_WITHIN_MINUTES = 30
SESSION_ID_VARS = ("CODEX_SESSION_ID", "CODEX_THREAD_ID")   # Codex exports both; first non-empty wins
TOP_LEVEL_SOURCES = ("cli", "exec")   # a REPL and a `codex exec` run; a spawned worker's source is a dict, never a string

EXIT_OK = 0
EXIT_MISMATCH = 2      # a rollout was found, its runtime is not the expected one
EXIT_LOOKUP = 3        # no candidate rollout, no readable model/effort, or a named id nothing eligible carries
EXIT_USAGE = 4


def same_dir(a, b):
    """True when two directory paths name the same directory. Trailing slashes are normalised away, and the comparison is
    ALSO case-insensitive: macOS mounts the hub on a case-insensitive filesystem, so a Codex session opened through
    a differently-cased path records a cwd that differs from HUB only in case and is nonetheless the same directory. A rollout
    whose session_meta carries no `cwd` at all compares as "" and is therefore never a match."""
    a, b = os.path.normpath(a or ""), os.path.normpath(b or "")
    return bool(a) and bool(b) and (a == b or a.lower() == b.lower())


# The rollout's OWN `session_meta` payload — the first one in the file; None when it holds none. A forked child
# replays its parent's session_meta later in the file, so only the first record answers "whose thread is this".
# Lazy: it reads the head of a multi-megabyte rollout, not all of it. The body MOVED to `worker_purity_check` in
# v6.23, where `codex_run_files` needed the same head-only read (code-review run 1, finding 3); this module keeps
# the name because it is the one that named the rule, and one home means one copy of the body.
first_session_meta = wpc.first_session_meta


def env_session_id():
    """(id, which-variable) from the environment Codex exports to every command it runs, or (None, None)."""
    for var in SESSION_ID_VARS:
        val = (os.environ.get(var) or "").strip()
        if val:
            return val, var
    return None, None


def candidates(within_minutes, sessions_dir=None, hub=None):
    """Every rollout that could be the calling session: modified inside the window, `cwd` the hub root, and `source` one
    of the TOP_LEVEL_SOURCES strings — "cli" or "exec" (a spawned worker's source is a dict, so forks never
    qualify). Each entry is a dict with `path`, `id`, `stamp` (session_meta.timestamp), `mtime` (st_mtime_ns)
    and `meta`. Returned in no meaningful order — the caller selects by
    exact id first and by `mtime` only as a fallback (see the module docstring); neither reads the list order."""
    root = sessions_dir if sessions_dir is not None else CODEX_DIR
    hub = hub if hub is not None else HUB
    cutoff = time.time() - within_minutes * 60
    out = []
    for f in glob.glob(os.path.join(root, "*", "*", "*", "rollout-*.jsonl")):
        try:   # a rollout that vanishes between the glob and the stat is skipped, never a traceback
            st = os.stat(f)
        except OSError:
            continue
        if st.st_mtime < cutoff:
            continue
        meta = first_session_meta(f)
        if not meta or meta.get("source") not in TOP_LEVEL_SOURCES or not same_dir(meta.get("cwd"), hub):
            continue
        out.append({"path": f, "id": meta.get("id"), "stamp": meta.get("timestamp") or "",
                    "mtime": st.st_mtime_ns, "meta": meta})
    return out


def why_excluded(session_id, within_minutes, sessions_dir=None, hub=None):
    """A named id matched nothing eligible — say WHY if that id is on disk at all, so the operator is not left guessing.
    Only ever called on the error path: it reads the first record of every rollout in the tree, which is cheap per file
    but not free across a thousand of them, and the happy path must never pay for it."""
    root = sessions_dir if sessions_dir is not None else CODEX_DIR
    hub = hub if hub is not None else HUB
    cutoff = time.time() - within_minutes * 60
    for f in glob.glob(os.path.join(root, "*", "*", "*", "rollout-*.jsonl")):
        try:
            st = os.stat(f)
        except OSError:
            continue
        meta = first_session_meta(f)
        if not meta or meta.get("id") != session_id:
            continue
        src = meta.get("source")
        if not isinstance(src, str):
            return "its rollout is a spawned worker thread (source is a thread_spawn record), not a top-level session"
        if src not in TOP_LEVEL_SOURCES:
            return (f"its rollout records source {src!r}, and only top-level sessions are eligible "
                    f"({', '.join(repr(s) for s in TOP_LEVEL_SOURCES)})")
        if not same_dir(meta.get("cwd"), hub):
            return f"its rollout was opened at cwd {meta.get('cwd')!r}, not the hub root {wpc.tilde(hub)}"
        if st.st_mtime < cutoff:
            return f"its rollout was last written more than {within_minutes:g} minutes ago (widen --within-minutes)"
        return "its rollout became ineligible between the two scans"
    return None


def started(meta):
    """The session's start stamp at second precision, keeping whatever zone suffix it carried — `2026-09-06T07:45:51.652Z`
    prints as `2026-09-06T07:45:51Z`. The fractional digits are dropped and the suffix after them (`Z`, `+05:30`, or
    nothing) is kept as recorded; a stamp carrying no fraction is printed unchanged rather than reshaped."""
    raw = str(meta.get("timestamp") or meta.get("start") or "")
    head, dot, tail = raw.partition(".")
    if not dot:
        return raw
    return head + tail.lstrip("0123456789")


def parse_expect(val):
    """`<model>/<effort>` → (model, effort). Split on the LAST slash, so a model name containing one still parses."""
    if "/" not in val:
        return None
    model, _, effort = val.rpartition("/")
    model, effort = model.strip(), effort.strip()
    return (model, effort) if model and effort else None


def check(expect, within_minutes, session_id=None, sessions_dir=None, hub=None, out=sys.stdout, err=sys.stderr):
    """The whole check, as a function, so the selftest can drive it without re-entering main(). SESSION_ID, when given,
    beats the environment; when neither is available the selection falls back to mtime and says so on stderr."""
    want_model, want_effort = expect
    root = sessions_dir if sessions_dir is not None else CODEX_DIR
    hub = hub if hub is not None else HUB
    eligible = candidates(within_minutes, root, hub)

    sid, sid_src = (session_id, "--session-id") if session_id else env_session_id()
    if sid:
        hit = [c for c in eligible if c["id"] == sid]
        if not hit:
            why = why_excluded(sid, within_minutes, root, hub)
            tail = f" — {why}" if why else (f" — widen --within-minutes, or the session is not at the hub root "
                                            f"({wpc.tilde(hub)})")
            print(f"{sid_src} {sid} set but no eligible rollout carries it{tail}", file=err)
            return EXIT_LOOKUP
        chosen, selector = hit[0], "id"
    else:
        if not eligible:
            print(f"no Codex rollout under {wpc.tilde(root)} was modified in the last {within_minutes:g} minutes with "
                  f"cwd {wpc.tilde(hub)} and a top-level source ({', '.join(TOP_LEVEL_SOURCES)}) — widen "
                  f"--within-minutes, or this is not a Codex session at the hub root", file=err)
            return EXIT_LOOKUP
        chosen = max(eligible, key=lambda c: (c["mtime"], c["stamp"]))
        selector = "mtime"
        # STDERR, deliberately, and worded as a GUESS. This path exits 0 like the id path, so a script that
        # checks only the exit code cannot tell "this session's own rollout" from "the most recently written
        # rollout that looked eligible". The RUNTIME line on stdout carries `selector mtime` for the same
        # reason: a caller must read that line, not just the code (/kun L13).
        print(f"selector: mtime fallback (no {SESSION_ID_VARS[0]} in env) — this is the most recently written\n"
              f"  eligible rollout, NOT a rollout proved to be this session's. Read the RUNTIME line's\n"
              f"  `selector` field before trusting the model/effort it reports.", file=err)

    path = chosen["path"]
    model, effort = wpc.codex_meta(path)[1:3]          # (meta, model, effort, first_prompt, out) — the LAST in force
    if model == "unknown" or not effort or effort == "?":
        print(f"{os.path.basename(path)} records no model/effort (model={model!r} effort={effort!r}) — nothing to check "
              f"against {want_model}/{want_effort}", file=err)
        return EXIT_LOOKUP
    print(f"RUNTIME: {model}/{effort} · rollout {os.path.basename(path)} · started {started(chosen['meta'])} "
          f"· selector {selector}", file=out)
    if model.lower() != wpc.norm(want_model).lower() or effort != want_effort:   # model case-insensitive after norm(); effort exact
        print(f"need {want_model}/{want_effort}", file=err)
        return EXIT_MISMATCH
    return EXIT_OK


# ---------------------------------------------------------------- selftest
def _fixture(root, name, when, cwd, turns, parent=None, task=None, rid=None, mtime=None, no_cwd=False, source=None):
    """One synthetic rollout under ROOT/2026/09/06/ (the `*/*/*/` shape the glob walks). TURNS is a list of
    (model, effort) written as consecutive `turn_context` records, so a fixture can carry several switches or none at
    all. RID overrides the session id (it defaults to NAME). With PARENT the `source` becomes the
    `{"subagent": {"thread_spawn": …}}` dict a real fork records — what the top-level source filter must reject. NO_CWD omits the
    `cwd` key entirely. MTIME, in seconds, is stamped on the file afterwards so selection order is controllable."""
    day = os.path.join(root, "2026", "09", "06")
    os.makedirs(day, exist_ok=True)
    src = (source or "cli") if not parent else {"subagent": {"thread_spawn": {"parent_thread_id": parent, "depth": 1,
                                                                             "agent_path": "/root/" + (task or "digest_worker_main_a")}}}
    meta = {"id": rid or name, "session_id": parent or rid or name, "timestamp": when, "originator": "codex-tui",
            "source": src, "thread_source": "subagent" if parent else "user"}
    if not no_cwd:
        meta["cwd"] = cwd
    path = os.path.join(day, f"rollout-{name}.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"timestamp": when, "type": "session_meta", "payload": meta}) + "\n")
        for i, (model, effort) in enumerate(turns):
            fh.write(json.dumps({"timestamp": when, "type": "turn_context",
                                 "payload": {"model": model, "reasoning_effort": effort}}) + "\n")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


HUBF = "/fixture/hub"


def _run(root, expect=DEFAULT_EXPECT, within=30, session_id=None, hub=HUBF):
    """check() against a fixture root, capturing both streams: (exit code, stdout line, stderr text)."""
    import io
    o, e = io.StringIO(), io.StringIO()
    rc = check(parse_expect(expect), within, session_id=session_id, sessions_dir=root, hub=hub, out=o, err=e)
    return rc, o.getvalue().strip(), e.getvalue().strip()


def _tmp():
    import tempfile
    return tempfile.mkdtemp(prefix="runtime-check-selftest-")


def selftest():
    """Twelve assertions over five scenarios. Scenario A is the loop-1 blocker: two concurrent cli sessions at the hub,
    the CALLER started EARLIER than its competitor, plus a fork that is the newest file by every measure. Selecting by
    start time — what loop 1 did — picks the competitor every time, which is how a Codex review session was told the
    runtime of a Terra session it had nothing to do with (2026-09-06 23:0x). Every assertion here fails loudly if the id
    selector, the mtime fallback or the top-level source filter (`cli` or `exec`, never a dict) is weakened."""
    import shutil, contextlib, io
    roots, ok = [], True
    env_saved = {v: os.environ.pop(v, None) for v in SESSION_ID_VARS}   # the harness' own env must not steer the fixtures
    try:
        # ---------- Scenario A: two concurrent cli sessions + a fork that is newest by everything
        a = _tmp(); roots.append(a)
        now = time.time()
        caller = _fixture(a, "2026-09-06T22-54-36-caller", "2026-09-06T17:24:36.123Z", HUBF,
                          [("gpt-5.6-sol", "xhigh")], rid="caller-id", mtime=now - 120)
        rival = _fixture(a, "2026-09-06T22-56-56-rival", "2026-09-06T17:26:56.000Z", HUBF,
                         [("gpt-5.6-terra", "xhigh")], rid="rival-id", mtime=now - 60)
        _fixture(a, "2026-09-06T23-10-00-fork", "2026-09-06T17:40:00.000Z", HUBF, [("gpt-5.6-luna", "max")],
                 parent="caller-id", rid="fork-id", mtime=now)      # newest start AND newest mtime — must still be skipped

        rc, line, err = _run(a, session_id="caller-id")
        a1 = (rc == EXIT_OK and os.path.basename(caller) in line and "RUNTIME: gpt-5.6-sol/xhigh" in line
              and "· selector id" in line and not err)
        print(f"selftest  1 exact id beats a later-started rival: exit={rc} (expected 0) line={line!r} "
              f"(expected the CALLER rollout — the rival {os.path.basename(rival)} started later — and 'selector id', "
              f"stderr silent) — {'PASS' if a1 else 'FAIL'}")

        a2 = "started 2026-09-06T17:24:36Z" in line
        print(f"selftest  2 started stamp at second precision: line={line!r} (expected 'started "
              f"2026-09-06T17:24:36Z', not the .123 millis) — {'PASS' if a2 else 'FAIL'}")

        rc3, line3, err3 = _run(a)      # no id anywhere → mtime fallback; the caller is NOT the newest-written here
        a3 = (rc3 == EXIT_MISMATCH and os.path.basename(rival) in line3 and "RUNTIME: gpt-5.6-terra/xhigh" in line3
              and "· selector mtime" in line3 and "need gpt-5.6-sol/xhigh" in err3
              and "selector: mtime fallback" in err3)
        print(f"selftest  3 mtime fallback picks the newest-WRITTEN eligible rollout, and a wrong runtime still exits 2 "
              f"with the RUNTIME line on stdout: exit={rc3} (expected {EXIT_MISMATCH}) line={line3!r} stderr={err3!r} "
              f"(expected the rival, 'selector mtime', the fallback notice and 'need gpt-5.6-sol/xhigh') "
              f"— {'PASS' if a3 else 'FAIL'}")

        os.utime(caller, (now + 30, now + 30))      # caller now the newest-written of the two cli rollouts
        rc4, line4, err4 = _run(a)
        a4 = (rc4 == EXIT_OK and os.path.basename(caller) in line4 and "· selector mtime" in line4
              and "selector: mtime fallback" in err4)
        print(f"selftest  4 mtime fallback follows the writer, and the fork stays excluded though it is newest by start: "
              f"exit={rc4} (expected 0) line={line4!r} (expected the caller, 'selector mtime', never the fork) "
              f"— {'PASS' if a4 else 'FAIL'}")

        rc5, line5, err5 = _run(a, session_id="no-such-session")
        a5 = rc5 == EXIT_LOOKUP and line5 == "" and "no-such-session" in err5
        print(f"selftest  5 named id that nothing carries: exit={rc5} (expected {EXIT_LOOKUP}) line={line5!r} "
              f"(expected no RUNTIME line) stderr={err5!r} (expected it to name the id) — {'PASS' if a5 else 'FAIL'}")

        rc6, line6, err6 = _run(a, session_id="fork-id")
        a6 = rc6 == EXIT_LOOKUP and line6 == "" and "worker thread" in err6
        print(f"selftest  6 id of a FORK is refused, and the reason says so: exit={rc6} (expected {EXIT_LOOKUP}) "
              f"stderr={err6!r} (expected it to name the spawned-worker cause) — {'PASS' if a6 else 'FAIL'}")

        old = now - 3600
        for f in glob.glob(os.path.join(a, "*", "*", "*", "rollout-*.jsonl")):
            os.utime(f, (old, old))
        rc7, line7, err7 = _run(a)
        a7 = rc7 == EXIT_LOOKUP and line7 == "" and "modified in the last 30 minutes" in err7
        print(f"selftest  7 every rollout older than the window: exit={rc7} (expected {EXIT_LOOKUP}) line={line7!r} "
              f"(expected no RUNTIME line) stderr names the window={'modified in the last 30 minutes' in err7} "
              f"— {'PASS' if a7 else 'FAIL'}")

        # ---------- Scenario B: cwd handling — missing key skipped, different case included
        b = _tmp(); roots.append(b)
        _fixture(b, "2026-09-06T22-00-00-nocwd", "2026-09-06T16:30:00.000Z", HUBF, [("gpt-5.6-terra", "xhigh")],
                 rid="nocwd-id", mtime=now, no_cwd=True)                      # newest, and must be skipped outright
        cased = _fixture(b, "2026-09-06T21-00-00-cased", "2026-09-06T15:30:00.000Z", "/FIXTURE/Hub",
                         [("gpt-5.6-sol", "xhigh")], rid="cased-id", mtime=now - 60)
        rc8, line8, err8 = _run(b)
        a8 = rc8 == EXIT_OK and os.path.basename(cased) in line8 and "RUNTIME: gpt-5.6-sol/xhigh" in line8
        print(f"selftest  8 session_meta with no cwd is skipped; a case-different cwd is the same directory: exit={rc8} "
              f"(expected 0) line={line8!r} (expected the /FIXTURE/Hub rollout, never the newer cwd-less one) "
              f"— {'PASS' if a8 else 'FAIL'}")

        # ---------- Scenario C: several turn_context records — the LAST one in force wins
        c = _tmp(); roots.append(c)
        _fixture(c, "2026-09-06T20-00-00-switch", "2026-09-06T14:30:00.000Z", HUBF,
                 [("gpt-5.6-luna", "low"), ("gpt-5.6-sol", "xhigh"), ("gpt-5.6-sol", "xhigh")],
                 rid="switch-id", mtime=now)
        rc9, line9, err9 = _run(c)
        a9 = rc9 == EXIT_OK and "RUNTIME: gpt-5.6-sol/xhigh" in line9
        print(f"selftest  9 three turn_context records report the LAST in force: exit={rc9} (expected 0) line={line9!r} "
              f"(expected gpt-5.6-sol/xhigh, not the opening gpt-5.6-luna/low) — {'PASS' if a9 else 'FAIL'}")

        # ---------- Scenario D: an eligible rollout that records no runtime at all
        d = _tmp(); roots.append(d)
        _fixture(d, "2026-09-06T19-00-00-bare", "2026-09-06T13:30:00.000Z", HUBF, [], rid="bare-id", mtime=now)
        rc10, line10, err10 = _run(d)
        a10 = rc10 == EXIT_LOOKUP and line10 == "" and "records no model/effort" in err10
        print(f"selftest 10 eligible rollout carrying no turn_context: exit={rc10} (expected {EXIT_LOOKUP}) "
              f"line={line10!r} (expected no RUNTIME line) stderr={err10!r} (expected the 'records no model/effort' "
              f"reason) — {'PASS' if a10 else 'FAIL'}")

        # ---------- Scenario E: a `codex exec` session is top-level too, and must be eligible
        e = _tmp(); roots.append(e)
        ex = _fixture(e, "2026-09-06T23-41-41-exec", "2026-09-06T18:11:41.000Z", HUBF, [("gpt-5.6-sol", "xhigh")],
                      rid="exec-id", mtime=now - 90, source="exec")
        _fixture(e, "2026-09-06T23-50-00-execrival", "2026-09-06T18:20:00.000Z", HUBF, [("gpt-5.6-luna", "max")],
                 rid="exec-rival-id", mtime=now)          # newer cli rollout — the id must still win
        rc11, line11, err11 = _run(e, session_id="exec-id")
        a11 = (rc11 == EXIT_OK and os.path.basename(ex) in line11 and "RUNTIME: gpt-5.6-sol/xhigh" in line11
               and "· selector id" in line11)
        print(f"selftest 11 a `codex exec` session (source \"exec\") is eligible and selectable by id: exit={rc11} "
              f"(expected 0) line={line11!r} (expected the exec rollout, not the newer cli one beside it) "
              f"— {'PASS' if a11 else 'FAIL'}")

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):   # captured, so this diagnostic cannot interleave ahead of the PASS lines
            rc12 = main(["--codex", "--expect", "nonsense"])
        a12 = rc12 == EXIT_USAGE and "needs the form" in buf.getvalue()
        print(f"selftest 12 malformed --expect: exit={rc12} (expected {EXIT_USAGE}) stderr={buf.getvalue().strip()!r} "
              f"(expected it to name the required form) — {'PASS' if a12 else 'FAIL'}")

        ok = all([a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12])
    finally:
        for r in roots:
            shutil.rmtree(r, ignore_errors=True)
        for v, val in env_saved.items():
            if val is not None:
                os.environ[v] = val
    print("SELFTEST PASS" if ok else "SELFTEST FAIL")
    return EXIT_OK if ok else 1


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return EXIT_USAGE
    if argv[0] == "--selftest":
        if len(argv) > 1:   # --selftest is a mode, not a filter: trailing arguments would be silently ignored
            print(f"--selftest takes no other arguments; got {argv[1:]}", file=sys.stderr)
            return EXIT_USAGE
        return selftest()
    if argv[0] != "--codex":
        print(f"unknown mode {argv[0]!r} — use --codex or --selftest", file=sys.stderr)
        return EXIT_USAGE
    expect, within, session_id = DEFAULT_EXPECT, DEFAULT_WITHIN_MINUTES, None
    rest = argv[1:]
    while rest:
        flag = rest[0]
        if flag not in ("--expect", "--within-minutes", "--session-id"):
            print(f"unknown flag {flag!r} — --codex takes --expect, --within-minutes and --session-id", file=sys.stderr)
            return EXIT_USAGE
        if len(rest) < 2:
            print(f"{flag} needs a value", file=sys.stderr)
            return EXIT_USAGE
        if flag == "--expect":
            expect = rest[1]
        elif flag == "--session-id":
            session_id = rest[1].strip()
            if not session_id:
                print("--session-id needs a non-empty session id", file=sys.stderr)
                return EXIT_USAGE
        else:
            try:
                within = float(rest[1])
            except ValueError:
                within = -1
            if within <= 0:
                print(f"--within-minutes {rest[1]!r}: needs a positive number of minutes", file=sys.stderr)
                return EXIT_USAGE
        rest = rest[2:]
    want = parse_expect(expect)
    if not want:
        print(f"--expect {expect!r}: needs the form <model>/<effort>, e.g. {DEFAULT_EXPECT}", file=sys.stderr)
        return EXIT_USAGE
    return check(want, within, session_id=session_id)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
