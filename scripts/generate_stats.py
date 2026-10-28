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

W, PAD, LH, FS = 760, 26, 21, 13.5
CW = FS * 0.6  # monospace char width estimate
BG, FG, DIM, MUTED = "#141413", "#e8e6dc", "#6f6d66", "#a3a199"
ACCENT, GREEN = "#d97757", "#5fb36b"


class Session:
    """Static render of a Claude Code-like terminal session."""

    def __init__(self):
        self.out, self.y = [], 0

    def _text(self, x, parts):
        spans = "".join(f'<tspan class="{c}">{escape(t)}</tspan>' for c, t in parts)
        return f'<text x="{x:.1f}" y="{self.y:.1f}" xml:space="preserve">{spans}</text>'

    def gap(self, n=1):
        self.y += LH * n

    def welcome(self, cwd):
        top, h = self.y, LH * 3 + 16
        self.out.append(f'<rect x="{PAD}" y="{top}" width="{W - 2 * PAD}" height="{h}" rx="7" fill="none" stroke="{ACCENT}"/>')
        self.y = top + LH + 6
        self.out.append(self._text(PAD + 16, [("a", "✻ "), ("b", "Welcome to Claude Code")]))
        self.y += LH + 2
        self.out.append(self._text(PAD + 16 + 2 * CW, [("m", "/help for help, /status for your current setup")]))
        self.y += LH - 4
        self.out.append(self._text(PAD + 16 + 2 * CW, [("m", f"cwd: {cwd}")]))
        self.y = top + h + LH

    def prompt(self, text):
        self.y += LH
        self.out.append(self._text(PAD, [("m", "> "), ("f", text)]))

    def tool(self, name, arg, result_lines):
        self.y += LH
        self.out.append(f'<circle cx="{PAD + 4}" cy="{self.y - 4.5}" r="4" fill="{GREEN}"/>')
        self.out.append(self._text(PAD + 2 * CW, [("b", name), ("m", f"({arg})")]))
        for i, parts in enumerate(result_lines):
            self.y += LH
            if i == 0:
                ex = PAD + 2 * CW + 4
                self.out.append(f'<path d="M{ex:.1f} {self.y - 13} V{self.y - 5} H{ex + 8:.1f}" fill="none" stroke="{DIM}" stroke-width="1.2"/>')
            self.out.append(self._text(PAD + 5 * CW, parts))

    def say(self, lines):
        self.y += LH
        self.out.append(f'<circle cx="{PAD + 4}" cy="{self.y - 4.5}" r="4" fill="{FG}"/>')
        for i, parts in enumerate(lines):
            if i:
                self.y += LH
            self.out.append(self._text(PAD + 2 * CW, parts))

    def bars(self, rows):
        for name, pct in rows:
            self.y += LH
            bx, cells = PAD + 14 * CW, 30
            filled = pct / 100 * cells
            self.out.append(self._text(PAD + 2 * CW, [("f", name)]))
            for i in range(cells):
                fill = ACCENT if i + 1 <= filled else ("#7a4434" if i < filled else "#2a2a28")
                self.out.append(f'<rect x="{bx + i * 10:.1f}" y="{self.y - 10}" width="7" height="10" rx="1" fill="{fill}"/>')
            self.out.append(self._text(bx + cells * 10 + 10, [("f", f"{pct:5.1f}%")]))

    def input_box(self, model):
        self.y += LH
        top = self.y
        self.out.append(f'<rect x="{PAD}" y="{top}" width="{W - 2 * PAD}" height="{LH + 14}" rx="7" fill="none" stroke="{DIM}"/>')
        self.y = top + LH + 1
        self.out.append(self._text(PAD + 14, [("m", ">")]))
        self.out.append(f'<rect x="{PAD + 14 + 2 * CW:.1f}" y="{self.y - FS + 1}" width="{CW:.1f}" height="{FS + 2}" fill="{FG}" opacity="0.85"/>')
        self.y = top + LH + 14 + LH
        self.out.append(self._text(PAD + 14, [("m", "? for shortcuts")]))
        self.out.append(f'<text x="{W - PAD - 14}" y="{self.y}" text-anchor="end"><tspan class="a">● </tspan><tspan class="m">{escape(model)}</tspan></text>')

    def render(self):
        h = self.y + 22
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h:.0f}" viewBox="0 0 {W} {h:.0f}">
<style>
  text {{ font-family: 'JetBrains Mono','SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace; font-size:{FS}px; fill:{FG}; }}
  .f {{ fill:{FG}; }}
  .b {{ fill:{FG}; font-weight:700; }}
  .m {{ fill:{MUTED}; }}
  .d {{ fill:{DIM}; }}
  .a {{ fill:{ACCENT}; }}
  .g {{ fill:{GREEN}; }}
  .tt {{ font-size:12px; fill:{DIM}; }}
</style>
<rect width="{W}" height="{h:.0f}" rx="10" fill="{BG}"/>
<rect x="0.5" y="0.5" width="{W - 1}" height="{h - 1:.0f}" rx="10" fill="none" stroke="#2c2c2a"/>
<path d="M0.5 34 V10.5 a10 10 0 0 1 10 -10 H{W - 10.5} a10 10 0 0 1 10 10 V34 Z" fill="#1c1c1b"/>
<line x1="0" y1="34" x2="{W}" y2="34" stroke="#2c2c2a"/>
<circle cx="20" cy="17" r="5.5" fill="#3a3a38"/><circle cx="38" cy="17" r="5.5" fill="#3a3a38"/><circle cx="56" cy="17" r="5.5" fill="#3a3a38"/>
<text x="{W / 2}" y="21.5" text-anchor="middle" class="tt">mrtsknn — claude — 100×32</text>
{chr(10).join(self.out)}
</svg>
"""


def terminal_svg(s, langs, repo_count):
    ses = Session()
    ses.y = 34 + 22
    ses.welcome("~/mrtsknn")
    ses.prompt("who is murat?")
    ses.tool("Read", "profile.md", [[("m", "Read "), ("f", "24"), ("m", " lines")]])
    ses.y += 6
    ses.say(
        [[("b", "murat"), ("m", " — full stack developer @ vakifbank, istanbul")]]
        + [[("a", f"{k:<10}"), ("f", v)] for k, v in STACK]
    )
    ses.y += 6
    ses.prompt("scan every repo, private ones too — don't leak names")
    ses.tool(
        "Bash",
        "gh api graphql --paginate",
        [
            [("f", f"{repo_count}"), ("m", " repos · "), ("f", f"{s['total']:,}"), ("m", " contributions · "), ("f", f"{s['commits']:,}"), ("m", " commits")],
            [("m", "last 365d "), ("f", f"{s['last_year']:,}"), ("m", " · streak "), ("f", f"{s['current_streak']}d"), ("m", f" (max {s['longest_streak']}d)")],
            [("m", "private repo names "), ("a", "[redacted]")],
        ],
    )
    ses.y += 6
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]
    ses.say([[("f", "Language breakdown"), ("m", " (public + private, by bytes)")]])
    ses.bars([(n.lower(), size / total * 100) for n, size in top])
    ses.y += 8
    ses.input_box("opus · auto mode")
    return ses.render()


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
