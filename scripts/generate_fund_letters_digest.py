#!/usr/bin/env python3
"""
Generate Fund Letters Digest -- Cannibal Strategy

Reads extracted fund letter text, analyzes each via Claude API,
and generates an HTML digest page.

Usage:
    python scripts/generate_fund_letters_digest.py
    python scripts/generate_fund_letters_digest.py --from-cache
    python scripts/generate_fund_letters_digest.py --concurrency 3
    python scripts/generate_fund_letters_digest.py --filter "greenlight,pershing"
    python scripts/generate_fund_letters_digest.py --model claude-sonnet-4-6

Environment:
    ANTHROPIC_API_KEY   Required for LLM analysis (not needed with --from-cache)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
CONTENT_DIR = BASE_DIR / "output" / "playwright" / "fund-letters" / "latest-quarter-content"
TEXT_DIR = CONTENT_DIR / "text"
META_JSON = CONTENT_DIR / "latest-quarter-fund-letters-with-content.json"
DIGEST_DIR = CONTENT_DIR / "digest"
CACHE_DIR = DIGEST_DIR / "cache"

MIN_WORD_COUNT = 150  # skip very thin letters

# ---------------------------------------------------------------------------
# Analyst prompt  (user-provided, verbatim)
# ---------------------------------------------------------------------------
ANALYST_PROMPT = r"""
You are a senior investment analyst working for a CIO at a family office / long-short equity fund. Your job is to read quarterly hedge fund investor letters and extract actionable investment ideas -- nothing else.

## ROLE

You are pitching ideas to a CIO who has one minute per idea. The CIO wants to know:
- Is the stock cheap? (Value)
- What makes it move? (Catalyst)
- What could go wrong and what's the payoff? (Risk/Reward)
- What is the investment theme / framework?
- Does momentum support or contradict the thesis?

You are NOT summarizing the letter. You are NOT reporting performance. You are distilling ideas the way Mohnish Pabrai runs his cannibal strategy: find the company, understand why it's cheap, understand the specific bet, and state it plainly in under 90 seconds.

## OUTPUT FORMAT

IMPORTANT: Begin your response with exactly these three lines:

FUND_NAME: [name of the fund]
MANAGER: [name of the portfolio manager / author]
REGIME: [one sentence on the manager's current macro stance]

Then for each named investment idea, output:

===

TICKER: [symbol or asset name]
TAGLINE: [15 words or less -- the setup in plain English]
DIRECTION: [Long / Short / Macro / Special Situation]

PITCH:
3-5 sentences. No jargon. No hedge fund speak. Explain what the manager is actually betting on, why the stock is mispriced, and what the specific mechanism is. Use plain declarative sentences. If the manager isn't saying it's cheap -- say why they own it anyway. Avoid phrases like "compelling opportunity" or "attractive risk/reward."

VALUE: [What makes it cheap or mispriced -- specific to this idea only]
CATALYST: [What specifically causes the stock to move -- named event, trigger, or mechanism]
RISK_REWARD: [Upside target or logic if given. Specific downside risk. No vague "macro headwinds."]
THEME: [One of: Buyback cannibal / Hated sector / M&A / Real assets / Tariff beneficiary / AI infrastructure / Special sit / Deep value / Quality on dislocation / Macro hedge / Other]
MOMENTUM: [Price action in the letter period if stated]

## CRITICAL RULES

1. Use ONLY information stated in the letter. Do not add context from your training.
2. If the manager does not give a price target, do not invent one.
3. If the manager did not explain the rationale -- say so, do not fabricate a thesis.
4. Skip any idea where the manager only mentions performance without explaining the position.
5. Skip boilerplate macro commentary unless it directly explains a position.
6. The pitch must sound like a person talking, not a report being written.
7. No bullet points inside the pitch. Write in sentences.
8. Mark each idea with its direction badge: Long / Short / Macro / Special Sit.
9. Do not include fund performance, AUM, inception returns, or fee structures.
10. If there are NO actionable ideas in the letter (only performance commentary, no thesis), respond with:

FUND_NAME: [name]
MANAGER: [name]
REGIME: [stance]
NO_IDEAS: true

## WHAT TO SKIP

- Performance commentary ("the fund returned X%")
- General market observations not tied to a specific position
- Positions exited where no thesis is explained
- Political commentary not tied to an investment implication
- Any position where the manager only names the stock without explaining why they own it
""".strip()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_letters() -> list[dict]:
    """Load fund letter metadata + text from the consolidated JSON."""
    if not META_JSON.exists():
        print(f"ERROR: {META_JSON} not found. Run extract_latest_quarter_fund_letters_content.py first.")
        sys.exit(1)

    with open(META_JSON) as f:
        data = json.load(f)

    letters = []
    for entry in data.get("letters", []):
        text = entry.get("full_text", "").strip()
        word_count = entry.get("wordCount", len(text.split()))
        if word_count < MIN_WORD_COUNT:
            continue
        letters.append({
            "title": entry.get("title", "Unknown Fund"),
            "text": text,
            "word_count": word_count,
            "link": entry.get("link", ""),
            "quarter": entry.get("quarter", ""),
            "year": entry.get("year", ""),
        })

    period = data.get("latestQuarter", {})
    return letters, f"{period.get('quarter', 'Q?')} {period.get('year', '????')}"


# ---------------------------------------------------------------------------
# LLM analysis
# ---------------------------------------------------------------------------

def analyze_letter(client: anthropic.Anthropic, title: str, text: str, model: str) -> str:
    """Send a fund letter to Claude for analysis. Returns raw text response."""
    user_msg = f"Analyze this quarterly investor letter and extract actionable ideas.\n\nFUND: {title}\n\n--- BEGIN LETTER ---\n{text}\n--- END LETTER ---"

    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=4096,
                system=ANALYST_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            return resp.content[0].text
        except anthropic.RateLimitError:
            wait = 2 ** (attempt + 1)
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait)
        except anthropic.APIError as e:
            print(f"  API error for {title}: {e}")
            if attempt == 2:
                raise
            time.sleep(2)
    return ""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _extract_field(text: str, field: str) -> str:
    """Extract a single-line field value like 'TICKER: AAPL'."""
    pattern = rf"^{re.escape(field)}:\s*(.+)$"
    m = re.search(pattern, text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _extract_pitch(text: str) -> str:
    """Extract multi-line PITCH block."""
    m = re.search(r"PITCH.*?:\s*\n(.*?)(?=\n(?:VALUE|CATALYST|RISK|THEME|MOMENTUM|===|\Z))", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # fallback: single-line PITCH
    m = re.search(r"PITCH.*?:\s*(.+?)(?=\n(?:VALUE|CATALYST|RISK|THEME|MOMENTUM|===|\Z))", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def parse_analysis(raw: str) -> dict:
    """Parse the structured LLM response into a dict."""
    result = {
        "fund_name": _extract_field(raw, "FUND_NAME"),
        "manager": _extract_field(raw, "MANAGER"),
        "regime": _extract_field(raw, "REGIME"),
        "no_ideas": bool(re.search(r"NO_IDEAS:\s*true", raw, re.IGNORECASE)),
        "ideas": [],
    }

    # Split on === to get individual ideas
    idea_blocks = re.split(r"\n===+\n", raw)

    for block in idea_blocks:
        ticker = _extract_field(block, "TICKER")
        if not ticker:
            continue

        idea = {
            "ticker": ticker,
            "tagline": _extract_field(block, "TAGLINE"),
            "direction": _extract_field(block, "DIRECTION"),
            "pitch": _extract_pitch(block),
            "value": _extract_field(block, "VALUE"),
            "catalyst": _extract_field(block, "CATALYST"),
            "risk_reward": _extract_field(block, "RISK_REWARD") or _extract_field(block, "RISK/REWARD"),
            "theme": _extract_field(block, "THEME"),
            "momentum": _extract_field(block, "MOMENTUM"),
        }
        result["ideas"].append(idea)

    return result


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def _badge_class(direction: str) -> str:
    d = direction.lower().strip()
    if "long" in d:
        return "badge-long"
    if "short" in d:
        return "badge-short"
    if "macro" in d:
        return "badge-macro"
    return "badge-special"


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate_html(digest: dict) -> str:
    """Generate the full self-contained HTML digest page."""
    period = _esc(digest["period"])
    generated = digest["generated_at"]

    fund_sections = []
    for fund in digest["funds"]:
        fund_name = _esc(fund["fund_name"])
        manager = _esc(fund.get("manager", ""))
        regime = _esc(fund.get("regime", ""))
        link = fund.get("source_link", "")

        idea_rows = []
        for idea in fund.get("ideas", []):
            ticker = _esc(idea["ticker"])
            tagline = _esc(idea["tagline"])
            direction = _esc(idea["direction"])
            badge = _badge_class(idea["direction"])
            pitch = _esc(idea.get("pitch", ""))
            value = _esc(idea.get("value", ""))
            catalyst = _esc(idea.get("catalyst", ""))
            risk_reward = _esc(idea.get("risk_reward", ""))
            theme = _esc(idea.get("theme", ""))
            momentum = _esc(idea.get("momentum", ""))

            detail_html = ""
            if pitch or value or catalyst:
                detail_html = f"""<div class="idea-detail" style="display:none">
              <div class="pitch"><strong>Pitch:</strong> {pitch}</div>
              <div class="meta-grid">
                <div><strong>Value:</strong> {value}</div>
                <div><strong>Catalyst:</strong> {catalyst}</div>
                <div><strong>Risk/Reward:</strong> {risk_reward}</div>
                <div><strong>Theme:</strong> {theme}</div>
                <div><strong>Momentum:</strong> {momentum}</div>
              </div>
            </div>"""

            idea_rows.append(f"""
          <div class="idea-row" onclick="toggleDetail(this)">
            <div class="idea-summary">
              <span class="ticker">{ticker}</span>
              <span class="tagline">{tagline}</span>
              <span class="badge {badge}">{direction.upper()}</span>
              {f'<a class="source-link" href="{_esc(link)}" target="_blank" title="Source letter" onclick="event.stopPropagation()">&#x1F517;</a>' if link else ''}
            </div>
            {detail_html}
          </div>""")

        ideas_html = "\n".join(idea_rows) if idea_rows else '<div class="no-ideas">No actionable ideas extracted from this letter.</div>'

        regime_html = f'<div class="regime"><strong>Regime:</strong> {regime}</div>' if regime else ""

        fund_sections.append(f"""
      <section class="fund-card">
        <div class="fund-header">
          <h2 class="fund-name">{fund_name}</h2>
          <span class="manager">{manager}</span>
        </div>
        {regime_html}
        <div class="ideas">
          {ideas_html}
        </div>
      </section>""")

    funds_html = "\n".join(fund_sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fund Letters Digest &ndash; Cannibal Strategy | {period}</title>
<style>
:root {{
  --bg: #f7f8fa;
  --card-bg: #ffffff;
  --border: #e5e7eb;
  --text: #1a1a2e;
  --text-secondary: #6b7280;
  --accent: #0d1117;
  --regime-bg: #ecfdf5;
  --regime-border: #a7f3d0;
  --regime-text: #065f46;
  --long-bg: #dcfce7;
  --long-text: #166534;
  --short-bg: #fef2f2;
  --short-text: #991b1b;
  --macro-bg: #eff6ff;
  --macro-text: #1e40af;
  --special-bg: #fefce8;
  --special-text: #854d0e;
  --detail-bg: #f9fafb;
}}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
}}

/* --- Header Bar --- */
.header {{
  background: var(--accent);
  color: #fff;
  padding: 14px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}}
.header-left {{
  display: flex;
  align-items: center;
  gap: 16px;
}}
.logo {{
  font-weight: 800;
  font-size: 0.85rem;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  background: linear-gradient(135deg, #22c55e, #10b981);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}
.header-title {{
  font-size: 1rem;
  font-weight: 600;
  color: #e5e7eb;
}}
.header-right {{
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  font-size: 0.78rem;
  color: #9ca3af;
  gap: 2px;
}}
.header-right .period {{
  font-weight: 600;
  color: #d1d5db;
}}

/* --- Copy Button --- */
.copy-btn {{
  position: fixed;
  top: 60px;
  right: 24px;
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 0.8rem;
  cursor: pointer;
  color: var(--text-secondary);
  z-index: 100;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  transition: all 0.15s;
}}
.copy-btn:hover {{
  background: var(--bg);
  color: var(--text);
}}

/* --- Container --- */
.container {{
  max-width: 960px;
  margin: 0 auto;
  padding: 24px 20px;
}}

/* --- Fund Card --- */
.fund-card {{
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}}
.fund-header {{
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 12px;
}}
.fund-name {{
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text);
}}
.manager {{
  font-size: 0.9rem;
  color: var(--text-secondary);
  font-weight: 400;
}}

/* --- Regime Box --- */
.regime {{
  background: var(--regime-bg);
  border: 1px solid var(--regime-border);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 0.88rem;
  color: var(--regime-text);
  margin-bottom: 16px;
  line-height: 1.5;
}}

/* --- Idea Rows --- */
.ideas {{
  display: flex;
  flex-direction: column;
  gap: 0;
}}
.idea-row {{
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.1s;
}}
.idea-row:last-child {{
  border-bottom: none;
}}
.idea-row:hover {{
  background: #fafbfc;
}}
.idea-summary {{
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 4px;
}}
.ticker {{
  font-weight: 700;
  font-size: 0.92rem;
  min-width: 90px;
  color: var(--text);
  font-family: 'SF Mono', 'Fira Code', monospace;
}}
.tagline {{
  flex: 1;
  font-size: 0.88rem;
  color: var(--text-secondary);
}}

/* --- Direction Badges --- */
.badge {{
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  padding: 3px 10px;
  border-radius: 4px;
  white-space: nowrap;
  text-transform: uppercase;
}}
.badge-long {{
  background: var(--long-bg);
  color: var(--long-text);
}}
.badge-short {{
  background: var(--short-bg);
  color: var(--short-text);
}}
.badge-macro {{
  background: var(--macro-bg);
  color: var(--macro-text);
}}
.badge-special {{
  background: var(--special-bg);
  color: var(--special-text);
}}

.source-link {{
  font-size: 0.85rem;
  text-decoration: none;
  opacity: 0.5;
  transition: opacity 0.15s;
}}
.source-link:hover {{
  opacity: 1;
}}

/* --- Idea Detail (expandable) --- */
.idea-detail {{
  padding: 8px 4px 16px 4px;
  font-size: 0.86rem;
  color: var(--text);
  background: var(--detail-bg);
  border-radius: 0 0 8px 8px;
  margin: 0 -4px;
  padding: 12px 16px;
}}
.pitch {{
  margin-bottom: 10px;
  line-height: 1.6;
}}
.meta-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 20px;
  font-size: 0.83rem;
  color: var(--text-secondary);
}}
.meta-grid strong {{
  color: var(--text);
}}

.no-ideas {{
  padding: 12px 4px;
  font-size: 0.88rem;
  color: var(--text-secondary);
  font-style: italic;
}}

/* --- Footer --- */
.footer {{
  text-align: center;
  padding: 24px;
  font-size: 0.78rem;
  color: var(--text-secondary);
}}

/* --- Print --- */
@media print {{
  .copy-btn {{ display: none; }}
  .idea-detail {{ display: block !important; }}
  .header {{ background: #333; }}
  .fund-card {{ break-inside: avoid; }}
}}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <span class="logo">DL INTEL</span>
    <span class="header-title">Fund Letters Digest &ndash; Cannibal Strategy</span>
  </div>
  <div class="header-right">
    <span class="period">Period: {period}</span>
    <span>Source: Fiscal.ai / Primary Letters / Front CSO Brief &mdash; One Minute Pitch</span>
  </div>
</div>

<button class="copy-btn" onclick="copyDigest()">&#128203; Copy</button>

<div class="container">
{funds_html}
</div>

<div class="footer">
  Generated {_esc(generated)} &middot; Cannibal Strategy Digest &middot; For internal use only
</div>

<script>
function toggleDetail(row) {{
  const detail = row.querySelector('.idea-detail');
  if (!detail) return;
  detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
}}

function copyDigest() {{
  const lines = [];
  document.querySelectorAll('.fund-card').forEach(card => {{
    const name = card.querySelector('.fund-name')?.textContent || '';
    const manager = card.querySelector('.manager')?.textContent || '';
    const regime = card.querySelector('.regime')?.textContent || '';
    lines.push('\\n## ' + name + (manager ? ' (' + manager + ')' : ''));
    if (regime) lines.push(regime);
    card.querySelectorAll('.idea-row').forEach(row => {{
      const ticker = row.querySelector('.ticker')?.textContent || '';
      const tagline = row.querySelector('.tagline')?.textContent || '';
      const badge = row.querySelector('.badge')?.textContent || '';
      lines.push('  ' + ticker + ' | ' + tagline + ' [' + badge + ']');
    }});
  }});
  navigator.clipboard.writeText(lines.join('\\n')).then(() => {{
    const btn = document.querySelector('.copy-btn');
    btn.textContent = '\\u2705 Copied';
    setTimeout(() => btn.innerHTML = '&#128203; Copy', 1500);
  }});
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate Fund Letters Digest")
    parser.add_argument("--from-cache", action="store_true",
                        help="Skip LLM calls, generate HTML from cached analysis")
    parser.add_argument("--filter", type=str, default="",
                        help="Comma-separated substrings to filter fund names")
    parser.add_argument("--concurrency", type=int, default=3,
                        help="Max parallel API calls (default: 3)")
    parser.add_argument("--model", type=str, default="claude-sonnet-4-6",
                        help="Claude model to use (default: claude-sonnet-4-6)")
    args = parser.parse_args()

    # Load letters
    letters, period = load_letters()
    print(f"Loaded {len(letters)} fund letters for {period}")

    # Apply filter
    if args.filter:
        filters = [f.strip().lower() for f in args.filter.split(",")]
        letters = [l for l in letters if any(f in l["title"].lower() for f in filters)]
        print(f"Filtered to {len(letters)} letters")

    if not letters:
        print("No letters to process.")
        sys.exit(0)

    # Ensure output dirs
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Analyze each letter (or load from cache)
    funds_data = []

    if args.from_cache:
        # Load all cached analyses
        print("Loading from cache...")
        for cache_file in sorted(CACHE_DIR.glob("*.json")):
            with open(cache_file) as f:
                funds_data.append(json.load(f))
        print(f"Loaded {len(funds_data)} cached analyses")
    else:
        # Verify API key
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("ERROR: ANTHROPIC_API_KEY not set.")
            print("Set it with: export ANTHROPIC_API_KEY=sk-ant-...")
            print("Or use --from-cache to generate HTML from previously cached results.")
            sys.exit(1)

        client = anthropic.Anthropic(api_key=api_key)

        def process_letter(letter):
            title = letter["title"]
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            cache_path = CACHE_DIR / f"{slug}.json"

            # Check cache
            if cache_path.exists():
                print(f"  [cached] {title}")
                with open(cache_path) as f:
                    return json.load(f)

            print(f"  [analyzing] {title} ({letter['word_count']} words)...")
            raw = analyze_letter(client, title, letter["text"], args.model)

            parsed = parse_analysis(raw)
            parsed["source_link"] = letter.get("link", "")
            parsed["raw_response"] = raw

            # Cache result
            with open(cache_path, "w") as f:
                json.dump(parsed, f, indent=2)

            return parsed

        print(f"\nAnalyzing {len(letters)} letters (concurrency={args.concurrency}, model={args.model})...\n")

        if args.concurrency <= 1:
            for letter in letters:
                funds_data.append(process_letter(letter))
        else:
            # Parallel processing
            with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                future_map = {executor.submit(process_letter, l): l for l in letters}
                for future in as_completed(future_map):
                    letter = future_map[future]
                    try:
                        result = future.result()
                        funds_data.append(result)
                    except Exception as e:
                        print(f"  [ERROR] {letter['title']}: {e}")

        # Sort by original order (letter title)
        title_order = {l["title"].lower(): i for i, l in enumerate(letters)}
        funds_data.sort(key=lambda f: title_order.get(f.get("fund_name", "").lower(), 999))

    # Build digest
    digest = {
        "period": period,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "fund_count": len(funds_data),
        "total_ideas": sum(len(f.get("ideas", [])) for f in funds_data),
        "funds": funds_data,
    }

    # Save JSON (without raw_response to keep it clean)
    digest_clean = json.loads(json.dumps(digest))
    for f in digest_clean["funds"]:
        f.pop("raw_response", None)

    json_path = DIGEST_DIR / "fund-letters-digest.json"
    with open(json_path, "w") as f:
        json.dump(digest_clean, f, indent=2)
    print(f"\nJSON saved: {json_path}")

    # Generate and save HTML
    html = generate_html(digest_clean)
    html_path = DIGEST_DIR / "fund-letters-digest.html"
    with open(html_path, "w") as f:
        f.write(html)
    print(f"HTML saved: {html_path}")

    # Summary
    print(f"\n--- Digest Summary ---")
    print(f"Period: {period}")
    print(f"Funds analyzed: {digest['fund_count']}")
    print(f"Total ideas extracted: {digest['total_ideas']}")
    for fund in digest_clean["funds"]:
        n = len(fund.get("ideas", []))
        label = "no ideas" if n == 0 else f"{n} idea{'s' if n != 1 else ''}"
        print(f"  {fund['fund_name']}: {label}")


if __name__ == "__main__":
    main()
