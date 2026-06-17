#!/usr/bin/env python3
"""
🤖 SARAH AI — Your AI Operations Assistant
============================================
Lead scraping + website analysis + outreach generation — all in one command.

Usage:
  python3 sarah_ai.py "Coiffeur" "Bern"              # Scrape + analyze + generate outreach
  python3 sarah_ai.py "Restaurant" "Zürich" --max 10  # Limit results
  python3 sarah_ai.py "Maler" "Bern" --skip-ai        # Scrape only, no AI analysis
  python3 sarah_ai.py --research "https://example.com" # Analyze a single website
  python3 sarah_ai.py --demo                           # Demo mode with mock data

Author: Michael Sezer (MSStrategies)
"""

import os, sys, json, time, csv, re, argparse
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime
from html.parser import HTMLParser

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
OUTPUT_DIR = ROOT / "outputs" / "sarah-ai"
TIMESTAMP = datetime.now().strftime("%Y-%m-%d_%H%M")

def load_env():
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

load_env()

APIFY_KEY = os.environ.get("APIFY_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

class TextExtractor(HTMLParser):
    """Extract visible text from HTML"""
    def __init__(self):
        super().__init__()
        self.text = []
        self._skip = False
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self._skip = True
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self._skip = False
    def handle_data(self, data):
        if not self._skip:
            t = data.strip()
            if t:
                self.text.append(t)
    def get_text(self):
        return " ".join(self.text)

def http_request(method, url, data=None, headers=None, timeout=30):
    """Generic HTTP request"""
    headers = headers or {}
    if data and isinstance(data, dict):
        data = json.dumps(data).encode()
        headers.setdefault("Content-Type", "application/json")
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except HTTPError as e:
        body = e.read().decode()[:300]
        print(f"  ❌ HTTP {e.code}: {body}")
        return None
    except (URLError, Exception) as e:
        print(f"  ❌ Error: {e}")
        return None

def fetch_page_text(url, max_chars=5000):
    """Fetch a webpage and extract visible text"""
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
        with urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
        parser = TextExtractor()
        parser.feed(html)
        text = parser.get_text()
        return text[:max_chars]
    except Exception as e:
        return f"[Could not fetch: {e}]"

def banner(text, char="═"):
    w = 60
    print(f"\n{char * w}")
    print(f"  {text}")
    print(f"{char * w}")

# ══════════════════════════════════════════════════════════════════════════════
# APIFY — GOOGLE MAPS SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

APIFY_BASE = "https://api.apify.com/v2"
GOOGLE_ACTOR = "compass/crawler-google-places"

def apify_call(method, path, data=None):
    sep = "&" if "?" in path else "?"
    url = f"{APIFY_BASE}{path}{sep}token={APIFY_KEY}"
    return http_request(method, url, data, timeout=180)

def scrape_leads(query, location, max_results=25):
    """Scrape Google Maps for businesses"""
    banner(f"🔍 SCRAPING: '{query}' in {location}")

    if not APIFY_KEY:
        print("  ❌ APIFY_API_KEY not set — using demo data")
        return _demo_leads(query, location)

    actor_id = GOOGLE_ACTOR.replace("/", "~")
    resp = apify_call("POST", f"/acts/{actor_id}/runs?memory=512", {
        "searchStringsArray": [query],
        "locationQuery": location,
        "maxCrawledPlacesPerSearch": max_results,
        "language": "de",
        "includeWebResults": False,
    })

    if not resp:
        print("  ❌ Failed to start scraper — using demo data")
        return _demo_leads(query, location)

    run_id = resp["data"]["id"]
    print(f"  🚀 Apify Run: {run_id}")

    # Poll for completion
    for i in range(60):
        time.sleep(5)
        st = apify_call("GET", f"/actor-runs/{run_id}")
        if not st:
            continue
        status = st["data"]["status"]
        if status == "SUCCEEDED":
            ds_id = st["data"]["defaultDatasetId"]
            print(f"  ✅ Done in {(i+1)*5}s")
            break
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            print(f"  ❌ {status}")
            return _demo_leads(query, location)
        print(f"  ⏳ {status}... ({(i+1)*5}s)", end="\r")
    else:
        print("  ⏰ Timeout")
        return _demo_leads(query, location)

    # Fetch results
    items = apify_call("GET", f"/datasets/{ds_id}/items?limit={max_results}&clean=true")
    if not items:
        return []

    if isinstance(items, dict):
        items = items.get("items", items.get("data", []))

    leads = []
    for item in items:
        leads.append({
            "name": item.get("title", ""),
            "address": item.get("address", ""),
            "city": item.get("city", location),
            "phone": item.get("phone", "") or item.get("phoneUnformatted", ""),
            "website": item.get("website", ""),
            "email": item.get("email", ""),
            "google_maps": item.get("url", ""),
            "rating": item.get("totalScore", ""),
            "reviews": item.get("reviewsCount", 0),
            "category": item.get("categoryName", query),
        })
    
    print(f"  📊 Found {len(leads)} leads")
    return leads

def _demo_leads(query, location):
    """Demo data for testing without Apify"""
    return [
        {"name": f"Demo {query} 1", "address": f"Hauptstrasse 1, {location}", "city": location,
         "phone": "+41 31 123 45 67", "website": "https://example.com", "email": "",
         "google_maps": "", "rating": "4.5", "reviews": 23, "category": query},
        {"name": f"Demo {query} 2", "address": f"Bundesgasse 10, {location}", "city": location,
         "phone": "+41 31 987 65 43", "website": "", "email": "",
         "google_maps": "", "rating": "3.8", "reviews": 8, "category": query},
    ]

# ══════════════════════════════════════════════════════════════════════════════
# AI — WEBSITE ANALYSIS + OUTREACH GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def ai_call(prompt, system="Du bist Sarah, eine AI Marketing-Expertin. Antworte auf Deutsch, knapp und direkt.", max_tokens=1500):
    """Call AI via OpenRouter (falls back to Anthropic)"""
    
    # Try OpenRouter first (cheapest)
    if OPENROUTER_KEY:
        resp = http_request("POST", "https://openrouter.ai/api/v1/chat/completions", {
            "model": "anthropic/claude-3.5-haiku",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
        }, headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
        })
        if resp and "choices" in resp:
            return resp["choices"][0]["message"]["content"]
    
    # Fallback: Anthropic direct
    if ANTHROPIC_KEY:
        resp = http_request("POST", "https://api.anthropic.com/v1/messages", {
            "model": "claude-3-5-haiku-20241022",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }, headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        })
        if resp and "content" in resp:
            return resp["content"][0]["text"]
    
    return "[AI unavailable — no API key]"

def analyze_company(lead):
    """Analyze a company's website and generate insights"""
    name = lead.get("name", "Unknown")
    website = lead.get("website", "")
    category = lead.get("category", "")
    city = lead.get("city", "")
    rating = lead.get("rating", "")
    reviews = lead.get("reviews", 0)

    print(f"  🔬 Analyzing: {name}...", end=" ", flush=True)

    # Fetch website content
    website_text = ""
    if website:
        website_text = fetch_page_text(website, max_chars=3000)

    prompt = f"""Analysiere dieses Unternehmen für Cold Outreach:

**Name:** {name}
**Kategorie:** {category}
**Stadt:** {city}
**Website:** {website or 'Keine Website'}
**Google Rating:** {rating} ({reviews} Bewertungen)

**Website-Inhalt (gekürzt):**
{website_text[:2000] if website_text else 'Nicht verfügbar'}

Gib mir in diesem EXAKTEN Format:

PAIN_POINTS:
- [Pain Point 1]
- [Pain Point 2]  
- [Pain Point 3]

OPPORTUNITY:
[1-2 Sätze: Was ist die grösste Wachstumschance für dieses Unternehmen?]

HOOK:
[1 personalisierter Satz der zeigt dass du das Business recherchiert hast — für den Outreach-Opener]

PRIORITY: [HIGH/MEDIUM/LOW] — basierend auf wie wahrscheinlich sie Hilfe brauchen"""

    result = ai_call(prompt)
    print("✅")
    return result

def generate_outreach(lead, analysis):
    """Generate personalized cold email + IG DM based on analysis"""
    name = lead.get("name", "Unknown")
    city = lead.get("city", "")
    website = lead.get("website", "")
    category = lead.get("category", "")

    prompt = f"""Schreibe Cold Outreach für dieses Unternehmen. Nutze die Analyse.

**Unternehmen:** {name} ({category}, {city})
**Website:** {website or 'Keine'}

**Analyse:**
{analysis}

Schreibe in diesem EXAKTEN Format:

---EMAIL---
Betreff: [Betreffzeile]

[Email-Body — max 5 Zeilen, persönlich, kein Sales-Pitch. Endet mit CTA für kurzes Gespräch]

[Dein Name]
---/EMAIL---

---IGDM---
[Instagram DM — max 3 Zeilen, casual, wie ein Nachbar der hilft. Kein Pitch.]
---/IGDM---

---LOOM_HOOK---
[1 Satz: Worüber würdest du im Loom-Video sprechen?]
---/LOOM_HOOK---"""

    result = ai_call(prompt, max_tokens=800)
    return result

# ══════════════════════════════════════════════════════════════════════════════
# RESEARCH SINGLE WEBSITE
# ══════════════════════════════════════════════════════════════════════════════

def research_website(url):
    """Deep-research a single website"""
    banner(f"🔬 DEEP RESEARCH: {url}")
    
    text = fetch_page_text(url, max_chars=5000)
    
    prompt = f"""Analysiere diese Website im Detail für einen Marketing/Growth-Service-Anbieter:

URL: {url}

Website-Inhalt:
{text}

Erstelle eine detaillierte Analyse:

## 1. Unternehmen
- Name, Branche, Standort
- Was sie verkaufen/anbieten
- Zielgruppe

## 2. Website-Qualität (1-10)
- Design / UX
- Mobile-Ready?
- SEO-Basics (Title, Meta, H1)?
- Call-to-Action vorhanden?
- Kontaktmöglichkeiten?

## 3. Marketing-Analyse
- Laufen Google/Facebook Ads? (basierend auf Website-Signale)
- Social Media Links vorhanden?
- Blog/Content vorhanden?
- Bewertungen/Testimonials?

## 4. Schwächen (Pain Points)
- Was fehlt?
- Was ist schlecht gemacht?
- Wo verlieren sie Kunden?

## 5. Outreach-Empfehlung
- Welchen Service könntest DU ihnen verkaufen?
- Wie würdest du sie ansprechen?
- Priority: HIGH/MEDIUM/LOW"""

    result = ai_call(prompt, max_tokens=2000)
    print(result)
    
    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r'[^a-z0-9]', '-', url.lower().replace('https://', '').replace('http://', ''))[:40]
    out_path = OUTPUT_DIR / f"research_{slug}_{TIMESTAMP}.md"
    out_path.write_text(f"# Website Research: {url}\n\n_Generated by Sarah AI — {TIMESTAMP}_\n\n{result}")
    print(f"\n💾 Saved: {out_path}")
    return result

# ══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(niche, location, max_results=25, skip_ai=False):
    """Full pipeline: Scrape → Analyze → Generate Outreach → Save"""
    
    banner(f"🤖 SARAH AI — Lead Generation Pipeline", "═")
    print(f"  Niche:    {niche}")
    print(f"  Location: {location}")
    print(f"  Max:      {max_results}")
    print(f"  AI:       {'OFF' if skip_ai else 'ON'}")
    print(f"  Output:   {OUTPUT_DIR}")
    
    # ── Step 1: Scrape ──
    leads = scrape_leads(niche, location, max_results)
    
    if not leads:
        print("\n❌ No leads found. Try a different search.")
        return
    
    # ── Step 2: AI Analysis (optional) ──
    results = []
    
    if not skip_ai:
        banner("🧠 AI ANALYSIS + OUTREACH GENERATION")
        
        for i, lead in enumerate(leads):
            print(f"\n  [{i+1}/{len(leads)}] {lead['name']}")
            
            # Analyze
            analysis = analyze_company(lead)
            
            # Generate outreach
            print(f"  ✍️  Generating outreach...", end=" ", flush=True)
            outreach = generate_outreach(lead, analysis)
            print("✅")
            
            results.append({
                **lead,
                "analysis": analysis,
                "outreach": outreach,
            })
            
            # Rate limit protection
            if i < len(leads) - 1:
                time.sleep(1)
    else:
        results = [{**lead, "analysis": "", "outreach": ""} for lead in leads]
    
    # ── Step 3: Save ──
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = f"{niche.lower().replace(' ', '-')}_{location.lower().replace(' ', '-').replace(',', '')}"
    
    # Save markdown report
    md_path = OUTPUT_DIR / f"{slug}_{TIMESTAMP}.md"
    md_content = generate_report(niche, location, results)
    md_path.write_text(md_content)
    
    # Save CSV
    csv_path = OUTPUT_DIR / f"{slug}_{TIMESTAMP}.csv"
    save_leads_csv(results, csv_path)
    
    # Save JSON (raw data)
    json_path = OUTPUT_DIR / f"{slug}_{TIMESTAMP}.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    
    # ── Summary ──
    banner("📊 RESULTS")
    print(f"  Total Leads:  {len(results)}")
    print(f"  With AI:      {'Yes' if not skip_ai else 'No'}")
    print(f"  Report:       {md_path}")
    print(f"  CSV:          {csv_path}")  
    print(f"  JSON:         {json_path}")
    print(f"\n  ✅ Done! Open the report to see personalized outreach for each lead.\n")
    
    return results

def generate_report(niche, location, results):
    """Generate a beautiful markdown report"""
    lines = [
        f"# 🤖 Sarah AI — Lead Report",
        f"",
        f"**Niche:** {niche}  ",
        f"**Location:** {location}  ",
        f"**Leads:** {len(results)}  ",
        f"**Generated:** {TIMESTAMP}  ",
        f"",
        f"---",
        f"",
    ]
    
    for i, r in enumerate(results):
        lines.append(f"## {i+1}. {r['name']}")
        lines.append(f"")
        lines.append(f"| Field | Value |")
        lines.append(f"|-------|-------|")
        lines.append(f"| 📍 Address | {r.get('address', '-')} |")
        lines.append(f"| 📞 Phone | {r.get('phone', '-')} |")
        lines.append(f"| 🌐 Website | {r.get('website', '-')} |")
        lines.append(f"| ⭐ Rating | {r.get('rating', '-')} ({r.get('reviews', 0)} reviews) |")
        lines.append(f"| 📧 Email | {r.get('email', '-')} |")
        lines.append(f"")
        
        if r.get("analysis"):
            lines.append(f"### Analysis")
            lines.append(f"")
            lines.append(r["analysis"])
            lines.append(f"")
        
        if r.get("outreach"):
            lines.append(f"### Ready-to-Send Outreach")
            lines.append(f"")
            lines.append(r["outreach"])
            lines.append(f"")
        
        lines.append(f"---")
        lines.append(f"")
    
    lines.append(f"_Generated by Sarah AI for MSStrategies — {datetime.now().isoformat()}_")
    return "\n".join(lines)

def save_leads_csv(results, path):
    """Save leads as CSV"""
    if not results:
        return
    fields = ["name", "address", "city", "phone", "website", "email", "rating", "reviews", "category"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    print(f"  💾 CSV: {path}")

# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="🤖 Sarah AI — Lead Scraping + AI Outreach Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 sarah_ai.py "Coiffeur" "Bern"              # Full pipeline
  python3 sarah_ai.py "Restaurant" "Zürich" --max 10  # Limit to 10
  python3 sarah_ai.py "Maler" "Bern" --skip-ai        # Scrape only
  python3 sarah_ai.py --research https://example.com   # Single website
  python3 sarah_ai.py --demo                           # Demo mode
        """
    )
    
    parser.add_argument("niche", nargs="?", help="Business niche to search (e.g. 'Coiffeur', 'Restaurant')")
    parser.add_argument("location", nargs="?", help="Location to search (e.g. 'Bern', 'Zürich')")
    parser.add_argument("--max", type=int, default=25, help="Max leads to scrape (default: 25)")
    parser.add_argument("--skip-ai", action="store_true", help="Skip AI analysis (scrape only)")
    parser.add_argument("--research", type=str, help="Deep-research a single website URL")
    parser.add_argument("--demo", action="store_true", help="Run with demo data (no API calls)")
    
    args = parser.parse_args()
    
    print("""
╔══════════════════════════════════════════════════════════╗
║  🤖 SARAH AI — Your AI Operations Assistant             ║
║  Lead Scraping • Website Analysis • Outreach Generation ║
║  Michael Sezer (MSStrategies)                       ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    if args.research:
        research_website(args.research)
        return
    
    if args.demo:
        print("  🎮 Demo Mode — using mock data\n")
        run_pipeline("Coiffeur", "Bern", max_results=2, skip_ai=False)
        return
    
    if not args.niche or not args.location:
        parser.print_help()
        print("\n  💡 Quick start: python3 sarah_ai.py \"Coiffeur\" \"Bern\"")
        return
    
    run_pipeline(args.niche, args.location, max_results=args.max, skip_ai=args.skip_ai)


if __name__ == "__main__":
    main()
