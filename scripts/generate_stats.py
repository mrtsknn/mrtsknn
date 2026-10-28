"""Generate profile stat cards (SVG) from public AND private repos.

Only aggregate numbers are written out: no repository names, descriptions
or URLs ever end up in the SVGs, so private repos stay hidden.

Env:
  GH_TOKEN      token with access to private repos (classic PAT: repo, read:user)
  EXCLUDE_LANGS comma separated languages to skip (optional)
"""
import datetime as dt
import json
import os
import urllib.request
from html import escape

TOKEN = os.environ["GH_TOKEN"]
EXCLUDE = {s.strip().lower() for s in os.environ.get("EXCLUDE_LANGS", "").split(",") if s.strip()}
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
TOP_N = 8


def gql(query, variables=None):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        body = json.load(r)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


def fetch_repos():
    repos, cursor = [], None
    while True:
        data = gql(
            """query($cursor: String) {
              viewer {
                repositories(ownerAffiliations: OWNER, isFork: false, first: 100, after: $cursor) {
                  totalCount
                  pageInfo { hasNextPage endCursor }
                  nodes {
                    stargazerCount
                    languages(first: 30, orderBy: {field: SIZE, direction: DESC}) {
                      edges { size node { name color } }
                    }
                  }
                }
              }
            }""",
            {"cursor": cursor},
        )["viewer"]["repositories"]
        repos += data["nodes"]
        if not data["pageInfo"]["hasNextPage"]:
            return repos, data["totalCount"]
        cursor = data["pageInfo"]["endCursor"]


def fetch_contributions():
    viewer = gql("query { viewer { login name createdAt contributionsCollection { contributionYears } } }")["viewer"]
    total = commits = prs = 0
    for year in viewer["contributionsCollection"]["contributionYears"]:
        c = gql(
            """query($from: DateTime!, $to: DateTime!) {
              viewer { contributionsCollection(from: $from, to: $to) {
                totalCommitContributions restrictedContributionsCount totalPullRequestContributions
                contributionCalendar { totalContributions }
              } }
            }""",
            {"from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"},
        )["viewer"]["contributionsCollection"]
        total += c["contributionCalendar"]["totalContributions"]
        commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        prs += c["totalPullRequestContributions"]

    days = gql(
        """query { viewer { contributionsCollection {
          contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
        } } }"""
    )["viewer"]["contributionsCollection"]["contributionCalendar"]
    counts = [d["contributionCount"] for w in days["weeks"] for d in w["contributionDays"]]
    longest = run = 0
    for n in counts:
        run = run + 1 if n else 0
        longest = max(longest, run)
    current = 0
    # today may not have activity yet; don't break the streak for it
    for i, n in enumerate(reversed(counts)):
        if n:
            current += 1
        elif i:
            break
    return {
        "name": viewer["name"] or viewer["login"],
        "total": total,
        "commits": commits,
        "prs": prs,
        "last_year": days["totalContributions"],
        "current_streak": current,
        "longest_streak": longest,
    }



STACK = [
    ("backend", "c# · .net · java · spring"),
    ("frontend", "typescript · react · javascript"),
    ("mobile", "kotlin · android tv"),
    ("data", "postgresql · mssql · python"),
]

W, PAD, LH, FS = 700, 26, 21, 14
CW = FS * 0.61  # monospace char width estimate
BG, RED = "#0a0a0a", "#e0262b"
PROMPT = "root@mrtsknn:~#"


class Term:
    def __init__(self):
        self.rows, self.t = [], 0.4

    def cmd(self, text):
        dur = max(0.4, len(text) * 0.045)
        self.rows.append(("cmd", text, self.t, dur))
        self.t += dur + 0.35

    def out(self, parts, step=0.07):
        self.rows.append(("out", parts, self.t, 0))
        self.t += step

    def bar(self, name, pct):
        self.rows.append(("bar", (name, pct), self.t, 0))
        self.t += 0.09

    def gap(self):
        self.rows.append(("gap", None, self.t, 0))

    def render(self):
        top = 44
        h = top + 4 + LH * (len(self.rows) + 1) + 18
        body, y = [], top + 4
        for kind, data, t, dur in self.rows:
            y += LH
            if kind == "gap":
                continue
            show = f'style="animation-delay:{t:.2f}s"'
            if kind == "cmd":
                px = PAD + (len(PROMPT) + 1) * CW
                n = len(data)
                body.append(
                    f'<g class="show" {show}><text x="{PAD}" y="{y}"><tspan class="p">{PROMPT}</tspan> '
                    f'<tspan class="c">{escape(data)}</tspan></text>'
                    f'<rect class="type" x="{px:.1f}" y="{y - FS}" width="{n * CW + 12:.1f}" height="{LH}" fill="{BG}" '
                    f'style="--d:{n * CW + 12:.1f}px;animation:type {dur:.2f}s steps({n}) {t:.2f}s forwards"/></g>'
                )
            elif kind == "out":
                spans = "".join(f'<tspan class="{c}">{escape(s)}</tspan>' for c, s in data)
                body.append(f'<text class="show" {show} x="{PAD}" y="{y}" xml:space="preserve">{spans}</text>')
            elif kind == "bar":
                name, pct = data
                cells, filled = 32, round(pct / 100 * 32 * 2) / 2
                bx = PAD + 14 * CW
                rects = []
                for i in range(cells):
                    fill = RED if i + 1 <= filled else ("#7a1416" if i < filled else "#1c1c1c")
                    rects.append(f'<rect x="{bx + i * 11:.1f}" y="{y - 11}" width="8" height="11" fill="{fill}"/>')
                body.append(
                    f'<g class="show" {show}><text x="{PAD}" y="{y}" class="o">{escape(name)}</text>{"".join(rects)}'
                    f'<text x="{bx + cells * 11 + 14:.1f}" y="{y}" class="h">{pct:5.1f}%</text></g>'
                )
        cy = y + LH
        body.append(
            f'<g class="show" style="animation-delay:{self.t:.2f}s"><text x="{PAD}" y="{cy}" class="p">{PROMPT}</text>'
            f'<rect class="blink" x="{PAD + (len(PROMPT) + 1) * CW:.1f}" y="{cy - FS + 2}" width="{CW:.1f}" height="{FS + 2}" fill="#d8d8d8"/></g>'
        )
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}">
<defs>
  <pattern id="scan" width="4" height="3" patternUnits="userSpaceOnUse"><rect width="4" height="1" fill="#ffffff" opacity="0.035"/></pattern>
  <radialGradient id="vignette" cx="50%" cy="45%" r="75%"><stop offset="60%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity="0.55"/></radialGradient>
</defs>
<style>
  text {{ font-family: 'JetBrains Mono','Fira Code','SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace; font-size:{FS}px; fill:#bdbdbd; }}
  .p {{ fill:{RED}; font-weight:700; }}
  .c {{ fill:#f2f2f2; }}
  .o {{ fill:#9a9a9a; }}
  .d {{ fill:#5a5a5a; }}
  .h {{ fill:#f2f2f2; font-weight:700; }}
  .r {{ fill:{RED}; font-weight:700; }}
  .tt {{ font-size:12px; fill:#6a6a6a; }}
  .show {{ opacity:0; animation: show 0s linear forwards; }}
  .type {{ animation-fill-mode: forwards; }}
  .blink {{ animation: blink 1s steps(1) infinite; }}
  @keyframes show {{ to {{ opacity:1; }} }}
  @keyframes type {{ to {{ transform: translateX(var(--d)); }} }}
  @keyframes blink {{ 50% {{ opacity:0; }} }}
</style>
<rect width="{W}" height="{h}" rx="10" fill="{BG}"/>
<rect x="0.5" y="0.5" width="{W - 1}" height="{h - 1}" rx="10" fill="none" stroke="#262626"/>
<path d="M0.5 34 V10.5 a10 10 0 0 1 10 -10 H{W - 10.5} a10 10 0 0 1 10 10 V34 Z" fill="#121212"/>
<line x1="0" y1="34" x2="{W}" y2="34" stroke="#262626"/>
<circle cx="20" cy="17" r="5.5" fill="#3a3a3a"/><circle cx="38" cy="17" r="5.5" fill="#3a3a3a"/><circle cx="56" cy="17" r="5.5" fill="{RED}" opacity="0.85"/>
<text x="{W / 2}" y="21.5" text-anchor="middle" class="tt">root@mrtsknn: ~ — ssh 10.0.0.1</text>
{chr(10).join(body)}
<rect y="34" width="{W}" height="{h - 34}" fill="url(#scan)" pointer-events="none"/>
<rect width="{W}" height="{h}" rx="10" fill="url(#vignette)" pointer-events="none"/>
</svg>
"""


def terminal_svg(s, langs, repo_count):
    term = Term()
    term.cmd("whoami")
    term.out([("h", "murat"), ("d", "  // full stack developer @ vakifbank · istanbul")])
    term.out([("o", "hello, friend.")])
    term.gap()
    term.cmd("cat /etc/stack")
    for k, v in STACK:
        term.out([("r", f"{k:<10}"), ("o", v)])
    term.gap()
    term.cmd("./recon --target=self --include-private")
    term.out([("d", f"[*] scanning {repo_count} repositories ... "), ("h", "done")], step=0.35)
    rows = [
        ("contributions", f"{s['total']:,}"),
        ("last 365 days", f"{s['last_year']:,}"),
        ("commits", f"{s['commits']:,}"),
        ("streak", f"{s['current_streak']}d  (max {s['longest_streak']}d)"),
    ]
    for k, v in rows:
        term.out([("r", "[+] "), ("o", f"{k:<16}"), ("h", v)])
    term.out([("r", "[!] "), ("o", f"{'private repos':<16}"), ("d", "counted · names "), ("r", "[REDACTED]")])
    term.gap()
    term.cmd(f"./langs --top {TOP_N}")
    total = sum(langs.values()) or 1
    for name, size in sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]:
        term.bar(name.lower(), size / total * 100)
    return term.render()


def main():
    repos, repo_count = fetch_repos()
    langs = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            name = e["node"]["name"]
            if name.lower() not in EXCLUDE:
                langs[name] = langs.get(name, 0) + e["size"]
    s = fetch_contributions()

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "terminal.svg"), "w", encoding="utf-8") as f:
        f.write(terminal_svg(s, langs, repo_count))
    print(f"ok: {len(langs)} languages, {repo_count} repos, generated {dt.date.today()}")


if __name__ == "__main__":
    main()
