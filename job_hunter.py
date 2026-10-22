#!/usr/bin/env python3
"""Job Hunter: fetch fresh jobs worldwide, score against your resume skills, alert on Telegram."""
import argparse, html, json, os, re, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests, yaml

ROOT = Path(__file__).parent
SEEN_FILE = ROOT / "seen_jobs.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (job-hunter personal use)"}
TIMEOUT = 20
RUN_SLOT = int(time.time() // 900)  # changes every 15 min; used to rotate countries/queries


# ---------- helpers ----------
def strip_html(t):
    t = html.unescape(t or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def parse_iso(s):
    if not s:
        return None
    s = re.sub(r"(\.\d{6})\d+", r"\1", str(s).strip().replace("Z", "+00:00"))
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def from_epoch(x):
    try:
        x = float(x)
        return datetime.fromtimestamp(x / 1000 if x > 1e11 else x, tz=timezone.utc)
    except Exception:
        return None

def mk(source, jid, title, company, location, url, posted, text):
    return {"id": f"{source}:{jid}", "source": source, "title": title or "", "company": company or "",
            "location": location or "", "url": url, "posted": posted, "text": strip_html(text)}

def rotate(items, n=1):
    if not items:
        return []
    return [items[(RUN_SLOT * n + i) % len(items)] for i in range(n)]


# ---------- sources ----------
def fetch_adzuna(cfg):
    app_id, key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and key):
        return []
    home = cfg["adzuna_home_country"]
    calls = [(home, q) for q in rotate(cfg["adzuna_india_queries"], cfg.get("adzuna_india_queries_per_run", 3))]
    for c in rotate(cfg["adzuna_other_countries"], 1):
        calls.append((c, cfg["adzuna_query_or"]))
    out = []
    for c, q in calls:
        try:
            params = {"app_id": app_id, "app_key": key, "results_per_page": 50,
                      "max_days_old": 1, "sort_by": "date"}
            params["what" if c == home else "what_or"] = q
            r = requests.get(f"https://api.adzuna.com/v1/api/jobs/{c}/search/1", headers=HEADERS,
                             timeout=TIMEOUT, params=params)
            r.raise_for_status()
            for j in r.json().get("results", []):
                loc = j.get("location", {}).get("display_name") or ""
                out.append(mk("adzuna", j["id"], j.get("title"), j.get("company", {}).get("display_name"),
                              f"{loc} [{c.upper()}]", j.get("redirect_url"), parse_iso(j.get("created")), j.get("description")))
        except Exception as e:
            print(f"[adzuna:{c}:{q}] {e}", file=sys.stderr)
    return out
    
def fetch_jooble(cfg):
    key = os.getenv("JOOBLE_KEY")
    if not key:
        return []
    out = []
    for q in rotate(cfg["jooble_queries"], 2):
        try:
            r = requests.post(f"https://jooble.org/api/{key}", timeout=TIMEOUT, json={"keywords": q, "location": "", "page": 1})
            r.raise_for_status()
            for j in r.json().get("jobs", []):
                out.append(mk("jooble", j["id"], j.get("title"), j.get("company"), j.get("location"),
                              j.get("link"), parse_iso(j.get("updated")), j.get("snippet")))
        except Exception as e:
            print(f"[jooble:{q}] {e}", file=sys.stderr)
    return out

def fetch_remotive(cfg):
    if not cfg.get("allow_remote"):
        return []
    out = []
    for q in ["sales", "account", "business development", "customer success"]:
        try:
            r = requests.get("https://remotive.com/api/remote-jobs", params={"search": q}, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            for j in r.json().get("jobs", []):
                loc = j.get("candidate_required_location", "")
                if not re.search(cfg["remote_location_regex"], loc.strip(), re.I):
                    continue
                out.append(mk("remotive", j["id"], j.get("title"), j.get("company_name"), f"Remote ({loc})",
                              j.get("url"), parse_iso(j.get("publication_date")), j.get("description")))
        except Exception as e:
            print(f"[remotive:{q}] {e}", file=sys.stderr)
    return out

def fetch_remoteok(cfg):
    if not cfg.get("allow_remote"):
        return []
    out = []
    try:
        r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json():
            if not isinstance(j, dict) or "position" not in j:
                continue
            loc = j.get("location") or ""
            if loc and not re.search(cfg["remote_location_regex"], loc.strip(), re.I):
                continue
            out.append(mk("remoteok", j["id"], j.get("position"), j.get("company"), f"Remote ({loc or 'Worldwide'})",
                          j.get("url"), from_epoch(j.get("epoch")), j.get("description")))
    except Exception as e:
        print(f"[remoteok] {e}", file=sys.stderr)
    return out

def fetch_arbeitnow(cfg):
    out = []
    try:
        r = requests.get("https://www.arbeitnow.com/api/job-board-api", headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("data", []):
            loc = j.get("location") or ""
            out.append(mk("arbeitnow", j["slug"], j.get("title"), j.get("company_name"),
                          ("Remote - " if j.get("remote") else "") + loc, j.get("url"),
                          from_epoch(j.get("created_at")), j.get("description")))
    except Exception as e:
        print(f"[arbeitnow] {e}", file=sys.stderr)
    return out

def fetch_greenhouse(cfg):
    out = []
    for b in cfg.get("greenhouse_boards") or []:
        try:
            r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{b}/jobs", params={"content": "true"},
                             headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            for j in r.json().get("jobs", []):
                out.append(mk("greenhouse", j["id"], j.get("title"), b, j.get("location", {}).get("name"),
                              j.get("absolute_url"), parse_iso(j.get("updated_at")), j.get("content")))
        except Exception as e:
            print(f"[greenhouse:{b}] {e}", file=sys.stderr)
    return out

def fetch_lever(cfg):
    out = []
    for b in cfg.get("lever_boards") or []:
        try:
            r = requests.get(f"https://api.lever.co/v0/postings/{b}", params={"mode": "json"}, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            for j in r.json():
                out.append(mk("lever", j["id"], j.get("text"), b, j.get("categories", {}).get("location"),
                              j.get("hostedUrl"), from_epoch(j.get("createdAt")), j.get("descriptionPlain")))
        except Exception as e:
            print(f"[lever:{b}] {e}", file=sys.stderr)
    return out

SOURCES = [fetch_adzuna, fetch_jooble, fetch_remotive, fetch_remoteok, fetch_arbeitnow, fetch_greenhouse, fetch_lever]


# ---------- scoring ----------
def has(text, phrase):
    return re.search(r"(?<![a-z])" + re.escape(phrase.lower()) + r"(?![a-z])", text) is not None

def score_job(j, cfg):
    title = j["title"].lower()
    text = f"{title} {j['text'].lower()}"
    if any(has(title, k) for k in cfg["exclude_title_keywords"]):
        return None

    # title fit 0-40
    t_score = 40 if any(t in title for t in cfg["target_titles"]) else (20 if any(k in title for k in cfg["title_keywords"]) else 0)
    if t_score == 0:
        return None

    # skills fit 0-50
    matched, total_w, got_w = [], 0, 0
    for name, s in cfg["skills"].items():
        total_w += s["w"]
        if any(has(text, p) for p in s["any"]):
            matched.append(name)
            got_w += s["w"]
    s_score = min(50, got_w / (0.35 * total_w) * 50)

    # location fit 0-10 (anywhere in the world is OK, preferred places score higher)
    loc = j["location"].lower()
    preferred = any(p in loc for p in cfg["preferred_locations"]) or (cfg["allow_remote"] and "remote" in loc)
    l_score = 10 if preferred else -cfg.get("abroad_penalty", 15)

    # experience-level sanity check for mid-level roles
    penalty = 0
    m = re.search(r"(\d{1,2})\s*(?:\+|-|to|–)?\s*(?:\d{1,2})?\s*\+?\s*(?:years|yrs)", text)
    if m:
        n = int(m.group(1))
        if n >= 9:
            penalty = 25
        elif n <= 1 and "fresher" in text:
            penalty = 20

    visa = bool(re.search(r"visa sponsorship|relocation (?:assistance|support|package)|will sponsor", text))
    needs_auth = bool(re.search(r"(?:authori[sz]ed|eligible|right) to work|work permit|citizen", text))
    gaps = [g for g in cfg["gap_skills"] if has(text, g)]
    return {"score": max(0, round(t_score + s_score + l_score - penalty)), "matched": matched, "gaps": gaps,
            "abroad": not preferred, "visa": visa, "needs_auth": needs_auth}


# ---------- alerts ----------
def ago(dt):
    m = max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 60))
    return f"{m} min ago" if m < 120 else f"{m // 60} h ago"

def format_msg(j, r):
    e = html.escape
    lines = [f"🚨 <b>{e(j['title'])}</b>",
             f"🏢 {e(j['company'])}  |  📍 {e(j['location'] or 'n/a')}",
             f"⏱ Posted {ago(j['posted'])}  |  🎯 Match <b>{r['score']}%</b>",
             f"✅ Your skills: {e(', '.join(r['matched'][:8]) or '-')}"]
    if r["gaps"]:
        lines.append(f"⚠️ JD also mentions: {e(', '.join(r['gaps']))}")
    if r["abroad"]:
        note = "visa/relocation support mentioned" if r["visa"] else ("work authorization required" if r["needs_auth"] else "check visa/work rules")
        lines.append(f"🌍 Abroad role: {note}")
    lines.append(f"👉 <a href=\"{e(j['url'])}\">Apply now</a>  ({j['source']})")
    return "\n".join(lines)

def send_telegram(msg):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("Telegram not configured; printing instead:\n" + msg + "\n")
        return
    r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=TIMEOUT,
        json={"chat_id": chat, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True})
    r.raise_for_status()
    time.sleep(0.5)


# ---------- main ----------
def load_seen():
    try:
        return json.loads(SEEN_FILE.read_text())
    except Exception:
        return {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print alerts only; don't send or save state")
    ap.add_argument("--hours", type=float, help="override window_hours")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "profile.yaml").read_text())
    window = timedelta(hours=args.hours or cfg["window_hours"])
    now = datetime.now(timezone.utc)
    seen = load_seen()

    jobs = {}
    for fn in SOURCES:
        for j in fn(cfg):
            if j["posted"] and timedelta(0) <= now - j["posted"] <= window and j["url"]:
                jobs[j["id"]] = j
    print(f"{len(jobs)} jobs posted in the last {window}")

    hits = []
    for jid, j in jobs.items():
        if jid in seen:
            continue
        r = score_job(j, cfg)
        if r and r["score"] >= cfg["min_score"]:
            hits.append((r["score"], j, r))
    hits.sort(key=lambda x: -x[0])

    for _, j, r in hits[: cfg["max_alerts_per_run"]]:
        msg = format_msg(j, r)
        if args.dry_run:
            print(msg + "\n")
        else:
            try:
                send_telegram(msg)
                seen[j["id"]] = now.isoformat()
            except Exception as e:
                print(f"telegram error: {e}", file=sys.stderr)

    if not args.dry_run:
        cutoff = now - timedelta(days=7)
        seen = {k: v for k, v in seen.items() if (parse_iso(v) or cutoff) > cutoff}
        SEEN_FILE.write_text(json.dumps(seen, indent=1))
    print(f"{len(hits)} matching jobs")

if __name__ == "__main__":
    main()
