#!/usr/bin/env python3
"""Collect GitHub activity (private repositories included) and draw the images.

    GH_TOKEN=... python3 scripts/stats.py assets/stats
    python3 scripts/stats.py --demo /tmp/preview   # sample data, no network

With a classic personal access token (scopes: repo, read:user) every private
repository and contribution is counted. With the default Actions token only
public data is visible.

Actions logs can be public, so this must never print the name of a
repository: log counts only.
"""

import base64
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import images

API = "https://api.github.com/graphql"
TZ = ZoneInfo("Asia/Tokyo")
MAX_COMMITS_PER_REPO = 5000


def log(msg: str) -> None:
    print(f"[stats] {msg}", flush=True)


class GraphQL:
    def __init__(self, token: str):
        self.token = token

    def __call__(self, query: str, **variables):
        body = json.dumps({"query": query, "variables": variables}).encode()
        for attempt in range(5):
            req = urllib.request.Request(
                API,
                data=body,
                headers={"Authorization": f"bearer {self.token}", "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as res:
                    payload = json.load(res)
            except (urllib.error.URLError, TimeoutError) as e:
                code = getattr(e, "code", "network")
                log(f"request failed ({code}), retry {attempt + 1}/5")
                time.sleep(2 ** attempt * 2)
                continue
            if payload.get("errors") and not payload.get("data"):
                # Error messages can contain repository names; keep them out of the log.
                types = {err.get("type", "ERROR") for err in payload["errors"]}
                log(f"graphql error ({', '.join(sorted(types))}), retry {attempt + 1}/5")
                time.sleep(2 ** attempt * 2)
                continue
            return payload["data"]
        raise RuntimeError("GitHub API request kept failing")


PROFILE_Q = """
query($login: String!) {
  user(login: $login) {
    id login name createdAt location avatarUrl(size: 160)
    followers { totalCount }
    contributionsCollection { contributionYears }
    owned: repositories(ownerAffiliations: OWNER, isFork: false) { totalCount }
    public: repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) { totalCount }
  }
}"""

YEAR_Q = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions totalPullRequestContributions
      totalIssueContributions totalPullRequestReviewContributions
      restrictedContributionsCount
      contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
    }
  }
}"""

REPOS_Q = """
query($login: String!, $id: ID!, $cursor: String) {
  user(login: $login) {
    repositories(first: 25, after: $cursor, isFork: false,
                 ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner stargazerCount forkCount isPrivate
        owner { login }
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name } } }
        defaultBranchRef { target { ... on Commit { history(author: {id: $id}) { totalCount } } } }
      }
    }
  }
}"""

HISTORY_Q = """
query($owner: String!, $name: String!, $id: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: 50, after: $cursor, author: {id: $id}) {
        pageInfo { hasNextPage endCursor }
        nodes { oid authoredDate additions deletions parents { totalCount } }
      }
    } } }
  }
}"""


def collect(gql: GraphQL, login: str) -> dict:
    user = gql(PROFILE_Q, login=login)["user"]
    uid = user["id"]
    log(f"profile ok, {user['owned']['totalCount']} owned repositories")

    # Contributions, one calendar year at a time (the API caps a range at a year).
    now = datetime.now(timezone.utc)
    years, days = {}, {}
    for year in sorted(user["contributionsCollection"]["contributionYears"]):
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = min(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc), now)
        c = gql(YEAR_Q, login=login, **{"from": start.isoformat(), "to": end.isoformat()})
        c = c["user"]["contributionsCollection"]
        years[year] = {
            "total": c["contributionCalendar"]["totalContributions"],
            "commits": c["totalCommitContributions"],
            "prs": c["totalPullRequestContributions"],
            "issues": c["totalIssueContributions"],
            "reviews": c["totalPullRequestReviewContributions"],
            "restricted": c["restrictedContributionsCount"],
        }
        for week in c["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
    log(f"contributions ok, {len(years)} years")

    # Repositories: stars, and how many commits I authored in each.
    repos, cursor = [], None
    while True:
        page = gql(REPOS_Q, login=login, id=uid, cursor=cursor)["user"]["repositories"]
        for r in page["nodes"]:
            if not r:  # e.g. an org repository behind SSO the token can't read
                continue
            ref = r["defaultBranchRef"]
            r["mine"] = ref["target"]["history"]["totalCount"] if ref and ref.get("target") else 0
            repos.append(r)
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    active = [r for r in repos if r["mine"]]
    log(f"repositories ok, {len(repos)} visible, {len(active)} with my commits")

    # Commit timestamps and line counts, deduplicated across mirrors.
    commits = {}
    for r in active:
        owner, name = r["nameWithOwner"].split("/", 1)
        cursor, seen = None, 0
        while seen < MAX_COMMITS_PER_REPO:
            try:
                data = gql(HISTORY_Q, owner=owner, name=name, id=uid, cursor=cursor)
            except RuntimeError:
                log("skipped one repository after repeated errors")
                break
            ref = (data.get("repository") or {}).get("defaultBranchRef")
            if not ref:
                break
            hist = ref["target"]["history"]
            for n in hist["nodes"]:
                commits[n["oid"]] = n
            seen += len(hist["nodes"])
            if not hist["pageInfo"]["hasNextPage"]:
                break
            cursor = hist["pageInfo"]["endCursor"]
    log(f"history ok, {len(commits)} commits")

    return {"user": user, "years": years, "days": days, "repos": repos, "commits": list(commits.values())}


# ---------------------------------------------------------------- summarise


def streaks(days: dict[str, int], today: date) -> tuple[int, int]:
    longest = run = 0
    for key in sorted(days):
        run = run + 1 if days[key] else 0
        longest = max(longest, run)
    current, d = 0, today
    if not days.get(d.isoformat()):
        d -= timedelta(days=1)  # today isn't over yet
    while days.get(d.isoformat()):
        current += 1
        d -= timedelta(days=1)
    return current, longest


def fetch_avatar(url: str) -> str:
    """The avatar as a data URI: images inside an SVG shown via <img> can't load URLs."""
    try:
        with urllib.request.urlopen(url, timeout=30) as res:
            kind = res.headers.get_content_type()
            return f"data:{kind};base64," + base64.b64encode(res.read()).decode()
    except (urllib.error.URLError, TimeoutError):
        log("avatar download failed, drawing without it")
        return ""


def summarise(raw: dict, login: str) -> dict:
    user, years, days = raw["user"], raw["years"], raw["days"]

    # Languages weighted by my commits: a repository I barely touched (a mirror,
    # a vendored tree) shouldn't outweigh the code I actually write.
    langs = Counter()
    for r in raw["repos"]:
        edges = (r["languages"] or {}).get("edges") or []
        total = sum(e["size"] for e in edges)
        if not total or not r["mine"]:
            continue
        for e in edges:
            langs[e["node"]["name"]] += r["mine"] * e["size"] / total

    times, added, deleted = [], 0, 0
    for c in raw["commits"]:
        times.append(datetime.fromisoformat(c["authoredDate"].replace("Z", "+00:00")).astimezone(TZ))
        if c["parents"]["totalCount"] <= 1:
            added += c["additions"]
            deleted += c["deletions"]

    owned = [r for r in raw["repos"] if r["owner"]["login"].lower() == login.lower()]
    created = datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00")).astimezone(TZ).date()

    return derive({
        "login": user["login"],
        "avatar": fetch_avatar(user["avatarUrl"]),
        "created": created,
        "followers": user["followers"]["totalCount"],
        "repos": user["owned"]["totalCount"],
        "public_repos": user["public"]["totalCount"],
        "holts": sorted((not r["isPrivate"] for r in owned), reverse=True),
        "stars": sum(r["stargazerCount"] for r in owned),
        "forks": sum(r["forkCount"] for r in owned),
        "commits": sum(y["commits"] for y in years.values()),
        "prs": sum(y["prs"] for y in years.values()),
        "issues": sum(y["issues"] for y in years.values()),
        "reviews": sum(y["reviews"] for y in years.values()),
        "added": added,
        "deleted": deleted,
        "languages": langs.most_common(),
        "commit_times": sorted(times),
        "days": days,
    })


def derive(s: dict) -> dict:
    """Everything the images need that follows from commit times and daily counts."""
    now = datetime.now(TZ)
    today = now.date()
    days = s["days"]

    # Pulse: for each of the last 52 weeks (Monday first), when commits
    # happened, as minutes after midnight.
    monday = today - timedelta(days=today.weekday())
    first = monday - timedelta(weeks=51)
    pulse = [[] for _ in range(52)]
    hours, weekdays = [0] * 24, [0] * 7
    for t in s["commit_times"]:
        hours[t.hour] += 1
        weekdays[t.weekday()] += 1
        if first <= t.date() <= today:
            pulse[(t.date() - first).days // 7].append(t.hour * 60 + t.minute)

    months = Counter()
    for key, n in days.items():
        months[(int(key[:4]), int(key[5:7]))] += n
    first_year = min((y for y, _ in months), default=today.year)

    last = [today - timedelta(days=i) for i in range(364, -1, -1)]
    current, longest = streaks(days, today)
    active_years = {y for (y, _), n in months.items() if n}
    return {
        **s,
        "today": today,
        "scope": os.environ.get("STATS_SCOPE", "public"),
        "pulse": pulse,
        "hours": hours,
        "weekdays": weekdays,
        "months": {k: months[k] for k in sorted(months) if k[0] >= first_year},
        "contributions": sum(days.values()),
        "years_active": len(active_years) or 1,
        "last_year": sum(days.get(d.isoformat(), 0) for d in last),
        "active_days": sum(1 for d in last if days.get(d.isoformat())),
        "streak": current,
        "longest": longest,
    }


def demo() -> dict:
    """Plausible fake activity, for previewing the images without a token."""
    rnd = random.Random(17333271)
    today = datetime.now(TZ).date()
    start = date(2016, 2, 19)
    days, times = {}, []
    d = start
    while d <= today:
        age = (d - start).days / (today - start).days
        rate = 0.4 + 9 * age ** 2.2 + (3 if d.month in (8, 9, 3) else 0)
        n = int(rnd.expovariate(1 / rate)) if rnd.random() < 0.35 + 0.5 * age else 0
        days[d.isoformat()] = n
        for _ in range(n if (today - d).days < 420 else 0):
            if rnd.random() < 0.8:
                h = int(rnd.gauss(14.5, 3.2)) % 24 if rnd.random() < 0.75 else int(rnd.gauss(23, 1.6)) % 24
                times.append(datetime(d.year, d.month, d.day, h, rnd.randrange(60), tzinfo=TZ))
        d += timedelta(days=1)
    return derive({
        "login": "1outres", "created": start, "followers": 29,
        "avatar": fetch_avatar("https://avatars.githubusercontent.com/u/17333271?s=160"),
        "repos": 180, "public_repos": 17, "holts": [True] * 17 + [False] * 163,
        "stars": 12, "forks": 2,
        "commits": 8421, "prs": 612, "issues": 188, "reviews": 97,
        "added": 1843210, "deleted": 912345,
        "languages": [("Go", 4200), ("TypeScript", 2600), ("Nix", 1500), ("Python", 900),
                      ("Rust", 420), ("TeX", 300), ("Swift", 180), ("Shell", 150), ("Ruby", 60)],
        "commit_times": sorted(times),
        "days": days,
    })


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0] if args else "assets/stats")
    if "--demo" in sys.argv:
        s = demo()
    else:
        token = os.environ.get("GH_TOKEN")
        if not token:
            sys.exit("GH_TOKEN is not set")
        login = os.environ.get("GH_USER") or "1outres"
        s = summarise(collect(GraphQL(token), login), login)
    images.write_all(s, out)
    log(f"wrote images to {out}")


if __name__ == "__main__":
    main()
