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


THEMES = {
    "dark": {"bg": "#0d1117", "fg": "#e6edf3", "muted": "#8b949e", "track": "#21262d", "border": "#30363d"},
    "light": {"bg": "#ffffff", "fg": "#1f2328", "muted": "#59636e", "track": "#eaeef2", "border": "#d0d7de"},
}
FONT = "font-family:'Segoe UI',Ubuntu,'Helvetica Neue',sans-serif"


def frame(t, w, h, title, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<defs>
  <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#7c3aed"/><stop offset="0.5" stop-color="#2563eb"/><stop offset="1" stop-color="#06b6d4"/>
  </linearGradient>
  <clipPath id="bar"><rect x="25" y="0" width="{w - 50}" height="{h}" rx="5"/></clipPath>
</defs>
<style>
  text {{ {FONT}; }}
  .title {{ font-size:17px; font-weight:700; fill:url(#accent); }}
  .label {{ font-size:12.5px; fill:{t['muted']}; }}
  .value {{ font-size:20px; font-weight:700; fill:{t['fg']}; }}
  .lang {{ font-size:12.5px; fill:{t['fg']}; }}
  .pct {{ font-size:12px; fill:{t['muted']}; }}
  .fade {{ opacity:0; animation: fade .6s ease-out forwards; }}
  .grow {{ transform-box: fill-box; transform-origin: left; transform: scaleX(0); animation: grow 1s cubic-bezier(.2,.8,.2,1) forwards; }}
  @keyframes fade {{ to {{ opacity:1; }} }}
  @keyframes grow {{ to {{ transform: scaleX(1); }} }}
</style>
<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="12" fill="{t['bg']}" stroke="{t['border']}"/>
<rect x="0.5" y="0.5" width="{w - 1}" height="3" rx="1.5" fill="url(#accent)"/>
<text x="25" y="38" class="title">{escape(title)}</text>
{body}
</svg>
"""


def stats_svg(t, s, stars, repo_count):
    items = [
        ("Toplam katkı", f"{s['total']:,}"),
        ("Son 1 yıl", f"{s['last_year']:,}"),
        ("Commit", f"{s['commits']:,}"),
        ("Güncel seri", f"{s['current_streak']} gün"),
        ("En uzun seri", f"{s['longest_streak']} gün"),
        ("Repo · Yıldız", f"{repo_count} · {stars}"),
    ]
    cells = []
    for i, (label, value) in enumerate(items):
        x = 25 + (i % 3) * 135
        y = 78 + (i // 3) * 62
        cells.append(
            f'<g class="fade" style="animation-delay:{i * 90}ms">'
            f'<text x="{x}" y="{y}" class="value">{escape(value)}</text>'
            f'<text x="{x}" y="{y + 20}" class="label">{escape(label)}</text></g>'
        )
    return frame(t, 440, 200, "GitHub Özeti", "\n".join(cells))


def langs_svg(t, langs):
    total = sum(size for size, _ in langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: kv[1][0], reverse=True)[:TOP_N]
    other = total - sum(v[0] for _, v in top)
    rows = [(name, size, color) for name, (size, color) in top]
    if other > 0:
        rows.append(("Diğer", other, "#6e7681"))

    w, bar_w = 440, 390
    x, segs = 25.0, []
    for i, (_, size, color) in enumerate(rows):
        seg = size / total * bar_w
        segs.append(f'<rect class="grow" style="animation-delay:{i * 60}ms" x="{x:.2f}" y="56" width="{seg:.2f}" height="10" fill="{color}"/>')
        x += seg
    bar = f'<rect x="25" y="56" width="{bar_w}" height="10" rx="5" fill="{t["track"]}"/><g clip-path="url(#bar)">{"".join(segs)}</g>'

    items = []
    half = (len(rows) + 1) // 2
    for i, (name, size, color) in enumerate(rows):
        cx = 25 + (i // half) * 200
        cy = 94 + (i % half) * 24
        items.append(
            f'<g class="fade" style="animation-delay:{300 + i * 70}ms">'
            f'<circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{color}"/>'
            f'<text x="{cx + 17}" y="{cy}" class="lang">{escape(name)}</text>'
            f'<text x="{cx + 185}" y="{cy}" class="pct" text-anchor="end">{size / total * 100:.1f}%</text></g>'
        )
    h = 94 + half * 24
    return frame(t, w, h, "En Çok Kullandığım Diller", bar + "\n" + "\n".join(items))


def main():
    repos, repo_count = fetch_repos()
    langs, stars = {}, 0
    for r in repos:
        stars += r["stargazerCount"]
        for e in r["languages"]["edges"]:
            name = e["node"]["name"]
            if name.lower() in EXCLUDE:
                continue
            size, color = langs.get(name, (0, e["node"]["color"] or "#8b949e"))
            langs[name] = (size + e["size"], color)
    s = fetch_contributions()

    os.makedirs(OUT_DIR, exist_ok=True)
    for mode, t in THEMES.items():
        with open(os.path.join(OUT_DIR, f"stats-{mode}.svg"), "w", encoding="utf-8") as f:
            f.write(stats_svg(t, s, stars, repo_count))
        with open(os.path.join(OUT_DIR, f"langs-{mode}.svg"), "w", encoding="utf-8") as f:
            f.write(langs_svg(t, langs))
    print(f"ok: {len(langs)} languages, {repo_count} repos, generated {dt.date.today()}")


if __name__ == "__main__":
    main()
