#!/usr/bin/env python3
"""questlog: score your engineering work. GitHub data comes from `gh`. Stdlib only, Python 3.9+."""
from __future__ import annotations

import argparse, base64, http.client, json, math, os, re, subprocess, sys, urllib.error, urllib.parse, urllib.request  # noqa: E401
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

# ---- Tune these ---------------------------------------------------------------------------------
XP_MERGED, XP_CLEAN, XP_TESTED, XP_REVIEWED = 10, 5, 5, 10   # per PR
XP_CARD, XP_CHECK_POINT = 3, 2        # per card; per point of check score
XP_OWNED = 10                         # bonus for a merged PR whose own check scored full marks
CLEAN_MIN, CLEAN_MAX = 10, 400        # effective changed lines of a clean slice
MAX_FILES = 100                       # above this many files, count the PR totals
XP_PER_STEP = 25                      # level = 1 + isqrt(xp // XP_PER_STEP)
TITLES = {1: "Apprentice", 3: "Journeyman", 5: "Artisan", 7: "Expert", 9: "Master", 11: "Legend"}
SKIP_RE = re.compile(                 # paths that do not count as changed lines
    r"(^|/)(package-lock\.json|pnpm-lock\.yaml|go\.sum|Package\.resolved)$"
    r"|\.lock$|\.snap$|\.min\.(js|css)$|\.generated\.|\.pb\.go$|_pb2\.py$"
    r"|(^|/)(dist|vendor|node_modules|generated|__generated__|__snapshots__)/")
TEST_RE = re.compile(                 # paths that make a PR "tested"
    r"(^|/)(?i:tests?|spec|__tests__)/|(^|/)test_|_test\.|\.test\.|\.spec\.|Tests?\.")
ACHIEVEMENTS = [                      # (name, what it counts, goal)
    ("Clean Slicer", "clean", 10), ("Test Pilot", "tested", 10), ("Second Pair of Eyes", "review", 20),
    ("Scholar", "card", 15), ("Deep Diver", "perfect", 5), ("Cartographer", "areas", 25), ("Iron Streak", "best", 10),
    ("Owner", "owned", 10)]
GQL = ("query($q:String!,$type:SearchType!,$after:String){search(query:$q,type:$type,first:100,after:$after)"
       "{pageInfo{hasNextPage endCursor}nodes{...on PullRequest{%s}}}}")
WARNED = []                           # warn once about partial GitHub errors
PR = "number title url headRefName repository{nameWithOwner} "
PR_REF = re.compile(r"^(?:https?://[^/\s]+/)?([\w.-]+/[\w.-]+)(?:#|/pull/)(\d+)(?:[/?#].*)?$")
FILES = "additions deletions changedFiles files(first:100){nodes{path additions deletions}}"
KEY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+-[0-9]+")    # a Jira key such as ABC-12
CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff]")    # C0, DEL, C1 and lone surrogates

def level(xp): return 1 + math.isqrt(xp // XP_PER_STEP)
def title(lv): return TITLES[max(k for k in TITLES if k <= lv)]
def to_next(xp): return XP_PER_STEP * level(xp) ** 2 - xp
def local_date(ts): return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()
def ev_in(e, lo, hi): return any(lo <= d <= hi for d in e["days"])
def files(n): return (n.get("files") or {}).get("nodes") or []
def ref(n): return f"{n['repository']['nameWithOwner']}#{n['number']}"

def norm_ref(s):
    """owner/repo#n from owner/repo#n or a PR URL. None for anything else."""
    m = PR_REF.match((s or "").strip())
    return f"{m[1]}#{m[2]}" if m else None

def clean(s):
    """Text without control characters. Jira text could carry terminal escapes."""
    return CTRL_RE.sub("", str(s))

def epic_key(s):
    """The epic key in upper case. It goes into JQL and into a path, so only a plain key passes."""
    if not (isinstance(s, str) and KEY_RE.fullmatch(s)):
        die("the epic must be a Jira key like ABC-1")
    return s.upper()

def pr_keys(pr_title, branch, known):
    """Keys in `known` that a PR names in its title or branch. Other matches, such as UTF-8, link nothing."""
    return {k.upper() for k in KEY_RE.findall(pr_title + " " + branch)} & known

def season_bounds(d):
    """First and last day of the calendar quarter that holds d."""
    s = date(d.year, (d.month - 1) // 3 * 3 + 1, 1)
    return s, date(s.year + s.month // 10, (s.month + 2) % 12 + 1, 1) - timedelta(days=1)

def streaks(active, off, start, today):
    """(current, best) in workdays. Weekends and off days neither count nor break. Today may be empty."""
    run = best = 0
    d = start
    while d <= today:
        if d.weekday() < 5 and d not in off:
            if d in active:
                run += 1
            elif d != today:
                run = 0
            best = max(best, run)
        d += timedelta(days=1)
    return run, best

def week_no(d, s0): return ((d - s0).days + s0.weekday()) // 7    # weeks start on Monday

def weekly(evs, s0, today):
    """One Counter per season week up to today: xp, owned PRs and the count of each event kind. An event counts on its first day."""
    ws = [Counter() for _ in range(week_no(today, s0) + 1)]
    for e in evs:
        w = ws[week_no(min(e["days"]), s0)]
        w["xp"] += e["xp"]
        w[e["kind"]] += 1
        w["owned"] += bool(e.get("owned"))
    return ws

def spark(vals):
    """One block per value, scaled to the largest value. Zero is the lowest block."""
    top = max(vals, default=0) or 1
    return "".join("▁▂▃▄▅▆▇█"[(v * 7 + top // 2) // top] for v in vals)

def recent(active, off, s0, today, n=10):
    """■ for a workday with activity, □ for an empty one, oldest first. Off days and days before the season are skipped."""
    days, d = [], today
    while d >= s0 and len(days) < n:
        if d.weekday() < 5 and d not in off:
            days.append(d)
        d -= timedelta(days=1)
    return "".join("■" if d in active else "□" for d in reversed(days))

def areas(repo, paths):
    """Distinct repo:dir1/dir2 areas. Directories only. Generated paths are skipped."""
    return sorted({repo + ":" + "/".join(p.split("/")[:-1][:2]) for p in paths if "/" in p and not SKIP_RE.search(p)})

def pr_info(n):
    repo = n["repository"]["nameWithOwner"]
    return dict(title=n["title"], branch=n.get("headRefName") or "", url=n["url"], repo=repo, ref=ref(n),
                areas=areas(repo, [f["path"] for f in files(n)]))

def merged_event(n):
    lines = (n["additions"] + n["deletions"] if n["changedFiles"] > MAX_FILES
             else sum(f["additions"] + f["deletions"] for f in files(n) if not SKIP_RE.search(f["path"])))
    clean, tested = CLEAN_MIN <= lines <= CLEAN_MAX, any(TEST_RE.search(f["path"]) for f in files(n))
    return dict(kind="merged", days=[local_date(n["mergedAt"])], lines=lines, clean=clean, tested=tested,
                xp=XP_MERGED + XP_CLEAN * clean + XP_TESTED * tested, **pr_info(n))

def review_event(n, since):
    """One event per reviewed PR. days holds each day of my reviews since `since`."""
    days = sorted({local_date(r["submittedAt"]) for r in n["reviews"]["nodes"] if r["submittedAt"]})
    days = [d for d in days if d >= since]
    return [dict(kind="review", days=days, xp=XP_REVIEWED, **pr_info(n))] if days else []

def tally(evs):
    t, seen = Counter(), set()
    for e in evs:
        t[e["kind"]] += 1
        t["xp"] += e["xp"]
        t["clean"] += bool(e.get("clean"))
        t["tested"] += bool(e.get("tested"))
        t["owned"] += bool(e.get("owned"))
        t["perfect"] += e["kind"] == "check" and e["score"] == e["of"]
        seen.update(e.get("areas", ()))
    t["areas"] = len(seen)
    return t

def own_refs(evs):
    """Lower-case refs of PRs that have an own check with full marks."""
    return {e["pr"].lower() for e in evs if e["kind"] == "check" and e.get("own") and e.get("pr") and e["score"] == e["of"]}

def mark_owned(evs):
    """A merged PR with a full-marks own check is owned. It earns XP_OWNED on top."""
    full = own_refs(evs)
    for e in evs:
        if e["kind"] == "merged" and e["ref"].lower() in full:
            e["owned"], e["xp"] = True, e["xp"] + XP_OWNED
    return evs

def datadir():
    d = Path(os.environ.get("QUESTLOG_DIR") or "~/.claude/questlog").expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d

def read_local(path):
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            r = json.loads(ln)
            xp = {"card": XP_CARD, "check": XP_CHECK_POINT * int(r.get("score", 0)), "off": 0}[r["kind"]]
            out.append(dict(r, days=[date.fromisoformat(r["date"])], xp=xp))
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return out

def load_state():
    try:
        return json.loads((datadir() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

def die(msg):
    print("questlog: " + msg, file=sys.stderr)
    sys.exit(1)

def gh(*args):
    try:
        return subprocess.run(["gh", *args], capture_output=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        die("gh is not installed. Install GitHub CLI from https://cli.github.com, then run: gh auth login")

def whoami():
    r = gh("api", "user", "--jq", ".login")
    if r.returncode or not r.stdout.strip():
        die("gh is logged out. Run: gh auth login")
    return r.stdout.strip()

def search(q, fields, run=gh):
    """All PRs for a search query, 100 per page. Try type ISSUE first, then ISSUE_ADVANCED."""
    out, after, typ = [], None, "ISSUE"
    while True:
        r = run("api", "graphql", "-f", "query=" + GQL % fields, "-f", "q=" + q, "-f", "type=" + typ,
                *(["-f", "after=" + after] if after else []))
        try:
            s = json.loads(r.stdout)["data"]["search"]    # partial data with errors is still usable
        except (ValueError, KeyError, TypeError):
            if typ == "ISSUE" and not after:
                typ = "ISSUE_ADVANCED"
                continue
            die("GitHub search failed: " + ((r.stderr or r.stdout).strip().splitlines() or ["no detail"])[0])
        if r.returncode and not WARNED:
            WARNED.append(1)
            print("questlog: warning: GitHub reported errors, so some results may be missing", file=sys.stderr)
        out += [n for n in s["nodes"] if n]
        if not s["pageInfo"]["hasNextPage"]:
            return out
        after = s["pageInfo"]["endCursor"]

def collect(who, start):
    """Merged PRs, reviewed PRs and local events since `start`. Callers filter by day."""
    since = (start - timedelta(days=1)).isoformat()   # GitHub dates are UTC, ours are local
    merged = search(f"is:pr is:merged author:{who} merged:>={since}", PR + "mergedAt " + FILES)
    seen = search(f"is:pr reviewed-by:{who} -author:{who} updated:>={since}",
                  PR + FILES + " reviews(author:%s,first:50){nodes{submittedAt}}" % json.dumps(who))
    return mark_owned([merged_event(n) for n in merged if n.get("mergedAt")]
                      + [e for n in seen for e in review_event(n, start)] + read_local(datadir() / "log.jsonl"))

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kw):    # a redirect would carry the token to another place
        return None

def http_get(url, auth):
    """GET a URL and return the body as text. The only code that talks to Jira. It never writes."""
    hdr = {"Accept": "application/json", **({"Authorization": auth} if auth else {})}
    with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url, headers=hdr, method="GET"), timeout=20) as r:
        return r.read().decode("utf-8", "replace")

def jira_base(url):
    """The base URL without a trailing slash, or "" if unset. The token goes only over HTTPS, so any other scheme dies."""
    base = (url or "").strip().rstrip("/")
    if base and not base.startswith("https://"):
        die("QUESTLOG_JIRA_URL must start with https://")
    return base

def basic_auth(meta, token):
    """The Authorization value from the attribute list of `security` and the token, or None."""
    m = re.search(r'^\s*"acct"<blob>="(.*)"\s*$', meta, re.M)
    return "Basic " + base64.b64encode(f"{m[1]}:{token}".encode()).decode() if m and token else None

def jira_auth():
    """Basic auth from the Keychain item questlog-jira, or None for no auth. The token stays in memory."""
    def sec(*flag):
        return subprocess.run(["security", "find-generic-password", "-s", "questlog-jira", *flag],
                              capture_output=True, encoding="utf-8", errors="replace")
    try:
        meta, tok = sec(), sec("-w")
    except OSError:
        return None
    return None if meta.returncode or tok.returncode else basic_auth(meta.stdout, tok.stdout.strip())

def jira_issue(i):
    """One issue as key, summary and status category (new, indeterminate or done)."""
    f = i["fields"]
    return {"key": clean(i["key"]), "summary": clean(f["summary"]), "status": clean(f["status"]["statusCategory"]["key"])}

def key_order(k):
    proj, _, num = k.rpartition("-")
    return proj, int(num)

def jira_pull(base, epic, auth, get):
    """(the epic issue or None, its child issues by project and number). One GET for each page, 50 pages at most."""
    raw, tok = [], None
    for _ in range(50):
        q = {"jql": f"key = {epic} OR parent = {epic}", "fields": "summary,status", "maxResults": 100}
        if tok:
            q["nextPageToken"] = tok
        page = json.loads(get(f"{base}/rest/api/3/search/jql?" + urllib.parse.urlencode(q), auth))
        raw += page["issues"]
        if page["isLast"]:
            break
        tok = page["nextPageToken"]
    else:
        raise ValueError("more than 50 pages")
    rows = [jira_issue(i) for i in raw]
    kids = sorted((r for r in rows if r["key"] != epic), key=lambda r: key_order(r["key"]))
    return next((r for r in rows if r["key"] == epic), None), kids

def jira_cache(path, epic):
    """The saved jira.json as a dict, or None if it is missing or does not look right."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        date.fromisoformat(d["started"])
        ok = d["epic"] == epic and all(k in d for k in ("summary", "read_at")) and all(set(i) >= {"key", "summary", "status"} for i in d["issues"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return d if ok else None

def jira_load(path, epic, base, auth, get=http_get):
    """(data, from_cache). Read Jira and save it to `path`. If the read fails, say why and use the saved file."""
    old, why = jira_cache(path, epic), "QUESTLOG_JIRA_URL is not set, so questlog did not read Jira."
    if base:
        try:
            top, kids = jira_pull(base, epic, auth, get)
            why = None
        except urllib.error.HTTPError as e:
            why = (f"Jira refused the request (HTTP {e.code}). The token is missing, wrong or expired." if e.code in (401, 403)
                   else f"Jira answered HTTP {e.code}.")
        except OSError as e:
            why = f"Jira could not be reached ({getattr(e, 'reason', e)})."
        except (ValueError, KeyError, TypeError, http.client.HTTPException) as e:
            why = f"Jira sent an answer that questlog cannot read ({str(e) or type(e).__name__})."
    if why:
        if not old:
            die(f"{clean(why)} There is no saved copy of {epic} to use instead.")
        print("questlog: " + clean(why), file=sys.stderr)
        return old, True
    if not top:
        die(f"{epic} is not in Jira, or this account cannot see it.")
    data = {"epic": epic, "summary": top["summary"], "started": old["started"] if old else date.today().isoformat(),
            "read_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "issues": kids}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data, False

def cmd_log(a):
    today = date.today()
    try:
        d = date.fromisoformat(a.date) if a.date else today
    except ValueError:
        die("--date must look like YYYY-MM-DD")
    text, pr = " ".join((a.text or "").split()), norm_ref(a.pr)
    if a.pr and not pr:
        die("--pr must look like owner/repo#n or be a PR URL")
    if a.own and not (a.kind == "check" and pr):
        die("--own needs a check and --pr")
    if a.kind == "card" and not text:
        die("a card needs --text")
    if a.kind == "check" and not (a.score is not None and a.of and 0 <= a.score <= a.of):
        die("a check needs --score N --of M, with 0 <= N <= M and M >= 1")
    if a.kind != "off" and d > today:
        die("a card or a check cannot have a future date")
    rec = {"kind": a.kind, "date": d.isoformat(), "pr": pr, "text": text or None}
    if a.kind == "check":
        rec.update(score=a.score, of=a.of, own=a.own or None)
    with open(datadir() / "log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({k: v for k, v in rec.items() if v is not None}) + "\n")
    s0, s1 = season_bounds(today)
    xp = {"card": XP_CARD, "check": XP_CHECK_POINT * (a.score or 0), "off": 0}[a.kind]
    print(f"Logged {a.kind} for {d}: +{xp} XP" + ("" if s0 <= d <= s1 else " (outside this season, not counted)")
          + (f". Owned check saved for {pr}. Status adds the +{XP_OWNED} XP owned bonus for a PR merged this season."
             if a.own and a.score == a.of else ""))

def cmd_status(_):
    today = date.today()
    s0, s1 = season_bounds(today)
    label = f"{s0.year}-Q{(s0.month - 1) // 3 + 1}"
    who = whoami()
    evs = collect(who, s0)
    reqs = sorted(search(f"is:pr is:open review-requested:{who} archived:false", PR + "createdAt"),
                  key=lambda n: n["createdAt"])
    mine = sorted(search(f"is:pr is:open author:{who} archived:false", PR + "createdAt"), key=lambda n: n["createdAt"])
    season = [e for e in evs if ev_in(e, s0, today)]
    week = [e for e in season if ev_in(e, today - timedelta(days=today.weekday()), today)]
    active = {d for e in season if e["kind"] != "off" for d in e["days"] if d <= today}
    off = {d for e in evs if e["kind"] == "off" for d in e["days"]}
    cur, best = streaks(active, off, s0, today)
    ts, tw = tally(season), tally(week)
    ts["best"] = best
    xp, lv, st = ts["xp"], level(ts["xp"]), load_state()
    st = st if st.get("season") == label else {}      # a new season starts from zero
    have = set(st.get("unlocked", []))
    new = [n for n, k, g in ACHIEVEMENTS if ts[k] >= g and n not in have]
    out = [f"LEVEL UP: level {st.get('level', 1)} -> {lv}, {title(lv)}"] if lv > st.get("level", 1) else []
    out += [f"UNLOCKED: {n}" for n in new]
    have.update(new)
    (datadir() / "state.json").write_text(json.dumps({"season": label, "level": lv, "unlocked": sorted(have)}))

    def cells(t):
        return [f"{t['merged']} ({t['clean']} clean, {t['tested']} tested, owned {t['owned']})",
                t["review"], t["card"], t["check"], t["areas"]]
    out += [f"QUESTLOG {label} | day {(today - s0).days + 1} of {(s1 - s0).days + 1}",
            f"Level {lv} {title(lv)} | {xp} XP | {to_next(xp)} XP to level {lv + 1}",
            f"Workday streak: {cur} (best this season: {best})",
            "XP per week: " + spark([w["xp"] for w in weekly(season, s0, today)]),
            "Last 10 workdays: " + recent(active, off, s0, today), f"{'':9}{'season':<34}this week"]
    out += [f"{n:<9}{x!s:<34}{y}" for n, x, y in zip(("Merged", "Reviews", "Cards", "Checks", "Areas"), cells(ts), cells(tw))]
    out += ["Achievements"] + [f"[{'x' if n in have else ' '}] {n:<20} {min(ts[k], g)}/{g}" for n, k, g in ACHIEVEMENTS]
    others = [q for q, k in (("Ship one clean slice", "merged"), ("Write one learning card", "card"))
              if not any(e["kind"] == k and today in e["days"] for e in evs)]
    own = [f"Own it before merge: {ref(n)} {n['title'][:50]}" for n in mine if ref(n).lower() not in own_refs(evs)][:2]
    quests = (own + [f"Review {ref(n)} \"{n['title'][:50]}\" (PR is {(today - local_date(n['createdAt'])).days} days old)"
                     for n in reqs[:2]] + others)[:4]
    out += ["Today's quests" + ("" if quests else ": all done")] + [f"{i}. {q}" for i, q in enumerate(quests, 1)]
    print("\n".join(out))

def cmd_recap(a):
    today = date.today()
    lo, s0 = today - timedelta(days=max(a.days, 1) - 1), season_bounds(today)[0]
    evs = collect(whoami(), min(lo, s0))
    win, season_xp = [e for e in evs if ev_in(e, lo, today)], tally([e for e in evs if ev_in(e, s0, today)])["xp"]
    t, lv = tally(win), level(season_xp)

    def sec(head, kind, fmt):
        return ["", "## " + head] + ([fmt(e) for e in win if e["kind"] == kind] or ["- none"])

    def link(e):
        return "[%s](%s)" % (re.sub(r"([\[\]])", r"\\\1", e["title"]), e["url"])
    print("\n".join(
        [f"# Questlog recap: {lo} to {today}"]
        + sec("Shipped", "merged", lambda e: f"- {link(e)} ({e['repo']}, {e['lines']} lines{', tested' if e['tested'] else ''}{', owned' if e.get('owned') else ''})")
        + sec("Reviewed", "review", lambda e: f"- {link(e)} ({e['repo']})")
        + sec("Learned", "card", lambda e: f"- {e['text']}" + (f" ({e['pr']})" if e.get("pr") else ""))
        + ["", "## Numbers",
           f"- {t['merged']} PRs merged ({t['clean']} clean slices, {t['tested']} with tests, {t['owned']} owned), "
           f"{t['review']} PRs reviewed, {t['card']} cards, {t['check']} checks",
           f"- {t['xp']} XP in this window. Level now: {lv} {title(lv)} ({season_xp} XP this season)"]))

def chart_html(evs, today, demo=False):
    """The chart page for a season. It holds dates and numbers only."""
    import chart
    s0, s1 = season_bounds(today)
    season = [e for e in evs if ev_in(e, s0, today)]
    days, xp = Counter(), tally(season)["xp"]
    for e in season:
        days[min(e["days"])] += e["xp"]
    head = f"{s0.year}-Q{(s0.month - 1) // 3 + 1} · Level {level(xp)} {title(level(xp))} · {xp} XP" + (" · demo data" if demo else "")
    return chart.page(head, s0, s1, today, days, weekly(season, s0, today), {d for e in evs if e["kind"] == "off" for d in e["days"]},
                      [(XP_PER_STEP * (k - 1) ** 2, k) for k in range(2, 12)])

def cmd_chart(a):
    today = date.today()
    if a.demo:
        import chart
        evs, today = chart.demo()
    else:
        evs = collect(whoami(), season_bounds(today)[0])
    path = datadir() / "chart.html"
    path.write_text(chart_html(evs, today, a.demo), encoding="utf-8")
    print(f"Wrote {path}")
    if not a.no_open:
        try:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
        except OSError:
            print("questlog: could not open a browser. Open the file by hand.", file=sys.stderr)

def selftest(_=None):
    D = date
    assert [level(x) for x in (0, 24, 25, 99, 100, 2500)] == [1, 1, 2, 2, 3, 11]
    assert [title(x) for x in (1, 2, 3, 10, 11, 40)] == ["Apprentice", "Apprentice", "Journeyman", "Master", "Legend", "Legend"]
    assert (to_next(0), to_next(24), to_next(25)) == (25, 1, 75)
    skip = ("package-lock.json", "web/yarn.lock", "app/dist/a.js", "x/y.min.js", "t/__snapshots__/a.snap", "a/b.generated.ts")
    keep = ("src/app.py", "docs/guide.md", "src/block.py", "lib/vendor_utils.py")
    test = ("tests/a.py", "test/a.go", "spec/a.rb", "src/__tests__/a.js", "a_test.go", "a.test.ts", "a.spec.ts",
            "FooTest.java", "FooTests.swift", "pkg/test_a.py")
    plain = ("src/latest.py", "docs/testing.md", "src/contest.py", "src/specs.md")
    assert all(SKIP_RE.search(p) for p in skip) and not any(SKIP_RE.search(p) for p in keep)
    assert all(TEST_RE.search(p) for p in test) and not any(TEST_RE.search(p) for p in plain)

    def pr(fs, add=0, nfiles=None):
        return {"number": 123, "title": "Fix login redirect", "url": "https://github.com/acme/web/pull/123",
                "repository": {"nameWithOwner": "acme/web"}, "mergedAt": "2026-10-12T15:00:00Z", "additions": add,
                "deletions": 0, "changedFiles": nfiles or len(fs),
                "files": {"nodes": [{"path": p, "additions": x, "deletions": y} for p, x, y in fs]}}
    e = merged_event(pr([("src/a.py", 30, 10), ("tests/a_test.py", 20, 0), ("package-lock.json", 900, 0)]))
    assert (e["lines"], e["clean"], e["tested"], e["xp"]) == (60, True, True, 20)
    assert e["areas"] == ["acme/web:src", "acme/web:tests"]
    assert [merged_event(pr([("src/a.py", n, 0)]))["xp"] for n in (5, 9, 10, 400, 401)] == [10, 10, 15, 15, 10]
    big = merged_event(pr([("src/a.py", 1, 1)], add=450, nfiles=101))      # over 100 files: PR totals
    assert big["lines"] == 450 and not big["clean"]
    assert areas("r", ["a/b/c/d.py", "a/x.py", "README.md", "dist/y.js"]) == ["r:a", "r:a/b"]
    n = pr([("src/a.py", 1, 1)])
    n["reviews"] = {"nodes": [{"submittedAt": "2026-10-12T15:00:00Z"}, {"submittedAt": None}, {"submittedAt": "2026-09-01T10:00:00Z"}]}
    assert len(review_event(n, D(2026, 10, 1))) == 1 and not review_event(n, D(2026, 11, 1))
    assert abs((local_date("2026-10-12T12:00:00Z") - D(2026, 10, 12)).days) <= 1
    t = tally([dict(kind="check", days=[], xp=6, score=3, of=3), dict(kind="check", days=[], xp=4, score=2, of=3)])
    assert (t["perfect"], t["xp"], t["check"]) == (1, 10, 2)

    s0, mon, tue, wed, thu, fri = D(2026, 10, 1), D(2026, 10, 12), D(2026, 10, 13), D(2026, 10, 14), D(2026, 10, 8), D(2026, 10, 9)
    assert wed.weekday() == 2
    assert streaks({mon, tue, wed}, set(), s0, wed) == (3, 3)
    assert streaks({mon, tue}, set(), s0, wed) == (2, 2)                  # today is still empty
    assert streaks({thu, fri, mon}, set(), s0, mon) == (3, 3)             # the weekend does not break
    assert streaks({mon, wed}, {tue}, s0, wed) == (2, 2)                  # an off day does not break
    assert streaks({mon, wed}, set(), s0, wed) == (1, 1)                  # a gap breaks
    assert streaks({thu, fri}, set(), s0, wed) == (0, 2)                  # current 0, best 2
    assert streaks({D(2026, 10, 10)}, set(), s0, D(2026, 10, 11)) == (0, 0)   # Saturday work does not count
    assert [season_bounds(D(2026, m, 15)) for m in (2, 5, 8, 12)] == [
        (D(2026, 1, 1), D(2026, 3, 31)), (D(2026, 4, 1), D(2026, 6, 30)),
        (D(2026, 7, 1), D(2026, 9, 30)), (D(2026, 10, 1), D(2026, 12, 31))]

    assert spark([0, 1, 2, 4, 8]) == "▁▂▃▅█" and spark([0, 0]) == "▁▁" and spark([]) == ""
    act = {D(2026, 10, n) for n in (1, 8, 9, 12, 14)}
    assert recent(act, set(), s0, wed) == "■□□□□■■■□■"                    # 10 workdays, oldest first
    assert recent(act, {D(2026, 10, 13)}, s0, wed) == "■□□□□■■■■"         # an off day is skipped, and so is Sept 30
    w = weekly([dict(kind="merged", days=[wed], xp=20, owned=True), dict(kind="review", days=[s0, wed], xp=10)], s0, wed)
    assert [(x["xp"], x["merged"], x["review"], x["owned"]) for x in w] == [(10, 0, 1, 0), (0, 0, 0, 0), (20, 1, 0, 1)]
    assert [week_no(x, s0) for x in (s0, D(2026, 10, 4), D(2026, 10, 5), D(2026, 12, 31))] == [0, 0, 1, 13]

    refs = ("acme/web#123", " https://github.com/acme/web/pull/123/files ", "https://ghe.example.com/a-b/c.d/pull/7?x=1", "web#1", "123", "", None)
    assert [norm_ref(x) for x in refs] == ["acme/web#123", "acme/web#123", "a-b/c.d#7", None, None, None, None]
    full = dict(kind="check", own=True, pr="Acme/Web#123", score=3, of=3)             # case does not matter
    m1, m2 = merged_event(pr([("src/a.py", 20, 0)])), merged_event(dict(pr([("src/a.py", 20, 0)]), number=124))
    mark_owned([m1, m2, full, dict(full, pr="acme/web#124", score=2)])                 # #124 has only 2 of 3
    assert (m1.get("owned"), m1["xp"], m2.get("owned"), m2["xp"]) == (True, 15 + XP_OWNED, None, 15)
    m3 = mark_owned([merged_event(pr([("src/a.py", 20, 0)])), dict(full, own=False)])[0]   # not an own check
    assert not m3.get("owned") and tally([m1, m2, m3])["owned"] == 1

    import chart
    for h in (chart_html([merged_event(pr([("src/a.py", 30, 10)]))], D(2026, 10, 14)), chart_html(*chart.demo(), True)):
        assert "<polyline" in h and not any(x in h for x in ("<script", "http", "src=", "url(", "acme", "login")), "chart: dates and numbers only"

    seen = []

    def fake(*args):                                                       # ISSUE is rejected, two pages follow
        typ, page2 = next(a for a in args if a.startswith("type=")), "after=c1" in args
        seen.append(typ + ("+p2" if page2 else ""))
        if typ == "type=ISSUE":
            return subprocess.CompletedProcess(args, 1, "", "invalid SearchType")
        body = {"data": {"search": {"pageInfo": {"hasNextPage": not page2, "endCursor": "c1"}, "nodes": [{"n": 2 if page2 else 1}, {}]}}}
        return subprocess.CompletedProcess(args, 0, json.dumps(body), "")
    assert search("q", "number", run=fake) == [{"n": 1}, {"n": 2}]
    assert seen == ["type=ISSUE", "type=ISSUE_ADVANCED", "type=ISSUE_ADVANCED+p2"], seen

    import contextlib, io

    def dies(f, *args):
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                f(*args)
            except SystemExit:
                return True
        return False
    known = {"ABC-1", "ABC-2", "ABC-3"}
    assert pr_keys("Fix UTF-8 and XYZ-9", "fix-utf-8", known) == set()               # not an issue of the epic
    assert pr_keys("Export", "abc-2-export", known) == {"ABC-2"}                      # a branch links, in lower case
    assert pr_keys("[abc-3] Gate ABC-1", "main", known) == {"ABC-1", "ABC-3"}
    assert merged_event(dict(pr([("src/a.py", 20, 0)]), headRefName="abc-2-export"))["branch"] == "abc-2-export"
    assert [epic_key(x) for x in ("abc-1", "ABC_D-12")] == ["ABC-1", "ABC_D-12"]
    assert all(dies(epic_key, x) for x in ("ABC-1 OR project = X", "ABC-1\n", "", "ABC", "A-1", "ÄBC-1", None))
    assert clean("a\x1b[31mb\x07\x7f\x85c\ud800") == "a[31mbc"
    assert jira_base(None) == "" and jira_base(" https://acme.atlassian.net/ ") == "https://acme.atlassian.net"
    assert all(dies(jira_base, x) for x in ("http://acme.atlassian.net", "ftp://x", "acme.atlassian.net", "https://"))
    meta = 'attributes:\n    0x00000007 <blob>="questlog-jira"\n    "acct"<blob>="me@example.com"\n    "cdat"<timedate>=0x3230\n'
    assert basic_auth(meta, "tok") == "Basic " + base64.b64encode(b"me@example.com:tok").decode()
    assert basic_auth(meta, "") is None and basic_auth("attributes:\n", "tok") is None

    def issue(key, st="new"):
        return {"key": key, "fields": {"summary": "Issue " + key, "status": {"statusCategory": {"key": st}}}}
    pages = {None: {"issues": [issue("ABC-10"), issue("ABC-1"), issue("XYZ-3")], "isLast": False, "nextPageToken": "t2"},
             "t2": {"issues": [issue("ABC-2", "done"), issue("ABC-9")], "isLast": True}}
    urls = []

    def get_page(url, auth):                                   # two pages, like Jira
        urls.append(url)
        return json.dumps(pages[urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("nextPageToken", [None])[0]])
    top, kids = jira_pull("https://acme.example", "ABC-1", None, get_page)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(urls[0]).query)
    assert top["key"] == "ABC-1" and [k["key"] for k in kids] == ["ABC-2", "ABC-9", "ABC-10", "XYZ-3"] and kids[0]["status"] == "done"
    assert len(urls) == 2 and urls[0].startswith("https://acme.example/rest/api/3/search/jql?")
    assert q == {"jql": ["key = ABC-1 OR parent = ABC-1"], "fields": ["summary,status"], "maxResults": ["100"]}

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "c" / "jira.json"

        def fails(exc):
            def get(url, auth):
                raise exc
            return get

        def http_err(code):
            return fails(urllib.error.HTTPError("u", code, "x", {}, None))

        def no_epic(url, auth):
            return json.dumps({"issues": [issue("ABC-2")], "isLast": True})
        assert dies(jira_load, path, "ABC-1", "https://acme.example", None, http_err(401))      # no saved copy yet
        d, cached = jira_load(path, "ABC-1", "https://acme.example", None, get_page)
        assert not cached and d["started"] == date.today().isoformat() and len(d["issues"]) == 4
        path.write_text(json.dumps(dict(d, started="2026-09-01")))
        assert jira_load(path, "ABC-1", "https://acme.example", None, get_page)[0]["started"] == "2026-09-01"
        for get, msg in ((http_err(401), "Jira refused the request (HTTP 401). The token is missing, wrong or expired."),
                         (http_err(403), "Jira refused the request (HTTP 403)."), (http_err(500), "Jira answered HTTP 500."),
                         (fails(urllib.error.URLError("no route")), "Jira could not be reached (no route)."),
                         (fails(TimeoutError("timed out")), "could not be reached (timed out)"), (lambda url, auth: "<html>", "cannot read"),
                         (fails(http.client.IncompleteRead(b"")), "cannot read (IncompleteRead")):
            with contextlib.redirect_stderr(io.StringIO()) as err:                             # the saved copy is used
                d2, cached = jira_load(path, "ABC-1", "https://acme.example", None, get)
            assert cached and d2["issues"] == d["issues"] and msg in err.getvalue(), (msg, err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            assert jira_load(path, "ABC-1", "", None)[1] and "QUESTLOG_JIRA_URL" in err.getvalue()
        assert dies(jira_load, path, "ABC-1", "https://acme.example", None, no_epic)             # the saved copy stays
        assert jira_cache(path, "ABC-1")["started"] == "2026-09-01" and jira_cache(path, "ABC-2") is None
    print("ok")

def main():
    ap = argparse.ArgumentParser(prog="questlog", description="Score your engineering work.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="level, streak, counts, achievements and today's quests")
    sub.add_parser("selftest", help="check the pure functions")
    sub.add_parser("dir", help="print the data folder (QUESTLOG_DIR or ~/.claude/questlog)")
    r = sub.add_parser("recap", help="brag-doc recap in Markdown")
    r.add_argument("--days", type=int, default=7)
    c = sub.add_parser("chart", help="write chart.html: heatmap, cumulative XP and weekly bars")
    c.add_argument("--demo", action="store_true", help="draw a made-up season. Reads no GitHub data and no log")
    c.add_argument("--no-open", action="store_true", help="write the file and do not open it")
    lg = sub.add_parser("log", help="log a card, a check or an off day")
    lg.add_argument("kind", choices=["card", "check", "off"])
    lg.add_argument("--pr", help="owner/repo#n")
    lg.add_argument("--score", type=int)
    lg.add_argument("--of", type=int)
    lg.add_argument("--date", help="YYYY-MM-DD, default today")
    lg.add_argument("--text")
    lg.add_argument("--own", action="store_true", help="the check is for your own PR")
    a = ap.parse_args()
    {"status": cmd_status, "recap": cmd_recap, "chart": cmd_chart, "log": cmd_log, "selftest": selftest,
     "dir": lambda _: print(datadir())}[a.cmd](a)

if __name__ == "__main__":
    main()
