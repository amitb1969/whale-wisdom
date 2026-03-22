import { asMarkdown, runExtraction } from './lib/extractor.js'
import { filterRecentLetters, buildLetterBrief, parseLetterDate } from './lib/summarizer.js'
import './styles.css'

/* ── metadata (bundled at build time) ── */
import metaJson from '../output/playwright/fund-letters/latest-quarter-fund-letters.json'

const app = document.querySelector('#root')

app.innerHTML = `
  <main class="container">
    <header class="app-header">
      <h1>Whale Wisdom</h1>
      <nav class="tabs">
        <button class="tab active" data-tab="brief">CIO Brief</button>
        <button class="tab" data-tab="extract">Detailed Extraction</button>
      </nav>
    </header>

    <!-- ═══════ CIO BRIEF TAB ═══════ -->
    <div id="tab-brief" class="tab-content active">
      <section class="brief-controls panel">
        <div class="brief-header">
          <div>
            <h2 class="brief-title">Latest Fund Letter Insights</h2>
            <p class="sub">Quick-scan summaries from recent fund letters — a curated source of ideas.</p>
          </div>
          <div class="brief-options">
            <label class="inline-label">
              Window
              <select id="dayWindow">
                <option value="7">7 days</option>
                <option value="15" selected>15 days</option>
                <option value="30">30 days</option>
                <option value="60">60 days</option>
                <option value="0">All letters</option>
              </select>
            </label>
          </div>
        </div>
        <p id="briefStatus" class="small"></p>
      </section>

      <section id="briefOverview"></section>
      <section id="briefCards"></section>
    </div>

    <!-- ═══════ DETAILED EXTRACTION TAB ═══════ -->
    <div id="tab-extract" class="tab-content">
      <section class="panel">
        <p class="small">Using bundled text files from <code>output/playwright/fund-letters/latest-quarter-content/text</code>.</p>

        <label>
          Top N
          <input id="topN" type="number" min="1" max="25" value="5" />
        </label>

        <div class="actions">
          <button id="extractBtn" disabled>Extract Recommendations</button>
          <button id="saveBtn" disabled>Save report to Vercel Blob</button>
        </div>

        <p id="status" class="small"></p>
      </section>

      <section id="results"></section>
    </div>
  </main>
`

/* ── state ── */
let loadedFiles = []
let currentResult = null
let letterMeta = metaJson.letters || []

/* ── DOM refs ── */
const topNInput = document.getElementById('topN')
const extractBtn = document.getElementById('extractBtn')
const saveBtn = document.getElementById('saveBtn')
const status = document.getElementById('status')
const results = document.getElementById('results')
const briefStatus = document.getElementById('briefStatus')
const briefOverview = document.getElementById('briefOverview')
const briefCards = document.getElementById('briefCards')
const dayWindow = document.getElementById('dayWindow')

/* ── tabs ── */
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'))
    document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'))
    btn.classList.add('active')
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active')
  })
})

/* ── initialize ── */
initializeFiles()

dayWindow.addEventListener('change', () => renderBrief())

/* ── extraction tab ── */
extractBtn.addEventListener('click', () => {
  const topN = Math.max(1, Number(topNInput.value) || 5)
  currentResult = runExtraction(loadedFiles, topN)
  saveBtn.disabled = false
  renderResults(currentResult, topN)
})

saveBtn.addEventListener('click', async () => {
  if (!currentResult) return
  const topN = Math.max(1, Number(topNInput.value) || 5)
  const markdown = asMarkdown(currentResult, topN)

  status.textContent = 'Saving report…'
  try {
    const response = await fetch('/api/save-report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ result: currentResult, markdown, topN })
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.error || 'Save failed')
    status.textContent = `Saved. JSON: ${payload.jsonUrl} | Markdown: ${payload.markdownUrl}`
  } catch (error) {
    status.textContent = `Unable to save to Blob: ${error.message}`
  }
})

/* ── load files ── */
async function initializeFiles() {
  status.textContent = 'Loading bundled fund letter text files…'
  briefStatus.textContent = 'Loading…'

  const modules = import.meta.glob('../output/playwright/fund-letters/latest-quarter-content/text/*.txt', {
    query: '?raw',
    import: 'default'
  })

  const loaded = await Promise.all(
    Object.entries(modules).map(async ([path, loader]) => {
      const text = await loader()
      const name = path.split('/').pop()
      return { name, text }
    })
  )

  loadedFiles = loaded.sort((a, b) => a.name.localeCompare(b.name))
  extractBtn.disabled = loadedFiles.length === 0
  saveBtn.disabled = true
  status.textContent = loadedFiles.length
    ? `Loaded ${loadedFiles.length} bundled file(s).`
    : 'No bundled text files found.'

  renderBrief()
}

/* ══════════════════════════════════════════════
   CIO BRIEF RENDERING
   ══════════════════════════════════════════════ */

function renderBrief() {
  const days = Number(dayWindow.value)
  // Reference date: use the pull date from metadata, or today
  const refDate = metaJson.pulledAtUtc ? new Date(metaJson.pulledAtUtc) : new Date()

  const recentLetters = days === 0
    ? letterMeta
    : filterRecentLetters(letterMeta, days, refDate)

  // Match each letter to its loaded text file
  const briefs = []
  for (const letter of recentLetters) {
    const fileMatch = loadedFiles.find(f => {
      const clean = letter.title.toLowerCase().replace(/[^a-z0-9]+/g, '-')
      return f.name.toLowerCase().includes(clean) ||
             f.name.toLowerCase().includes(clean.split('-').slice(0, 2).join('-'))
    })
    if (fileMatch) {
      briefs.push(buildLetterBrief(letter, fileMatch.text))
    }
  }

  // Sort by date descending
  briefs.sort((a, b) => (b.parsedDate || 0) - (a.parsedDate || 0))

  briefStatus.textContent = days === 0
    ? `Showing all ${briefs.length} fund letters.`
    : `${briefs.length} letter(s) published in the last ${days} days (as of ${refDate.toLocaleDateString()}).`

  renderBriefOverview(briefs)
  renderBriefCards(briefs)
}

function renderBriefOverview(briefs) {
  if (!briefs.length) {
    briefOverview.innerHTML = `<section class="panel brief-empty">
      <p>No letters found in this window. Try expanding the date range.</p>
    </section>`
    briefCards.innerHTML = ''
    return
  }

  // Aggregate top tickers across recent briefs
  const tickerMap = new Map()
  for (const b of briefs) {
    for (const insight of b.insights) {
      const tickers = insight.match(/\$([A-Z]{1,5})\b/g)
        || insight.match(/\(([A-Z]{1,5})\)/g)
        || []
      for (let raw of tickers) {
        const t = raw.replace(/[$()]/g, '')
        if (t.length < 2) continue
        tickerMap.set(t, (tickerMap.get(t) || 0) + 1)
      }
    }
  }
  const topTickers = [...tickerMap.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)

  // Aggregate themes
  const themeMap = new Map()
  for (const b of briefs) {
    for (const th of b.themes) {
      themeMap.set(th, (themeMap.get(th) || 0) + 1)
    }
  }
  const topThemes = [...themeMap.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)

  briefOverview.innerHTML = `
    <div class="overview-grid">
      <div class="overview-card">
        <div class="overview-number">${briefs.length}</div>
        <div class="overview-label">Letters Reviewed</div>
      </div>
      <div class="overview-card">
        <div class="overview-number">${tickerMap.size}</div>
        <div class="overview-label">Unique Tickers Mentioned</div>
      </div>
      <div class="overview-card themes-card">
        <div class="overview-label">Top Themes</div>
        <div class="theme-tags">${topThemes.map(([t, c]) =>
          `<span class="theme-tag">${escapeHtml(t)} <small>(${c})</small></span>`
        ).join('')}</div>
      </div>
      <div class="overview-card tickers-card">
        <div class="overview-label">Most Mentioned Tickers</div>
        <div class="ticker-tags">${topTickers.map(([t, c]) =>
          `<span class="ticker-tag">${escapeHtml(t)} <small>&times;${c}</small></span>`
        ).join('')}</div>
      </div>
    </div>
  `
}

function renderBriefCards(briefs) {
  if (!briefs.length) { briefCards.innerHTML = ''; return }

  briefCards.innerHTML = briefs.map(b => `
    <article class="brief-card panel">
      <div class="brief-card-header">
        <div>
          <h3 class="fund-name">${escapeHtml(b.fund)}</h3>
          <span class="fund-date">${escapeHtml(b.date)}, ${Number(b.year) + 1}</span>
        </div>
        ${b.performance ? `<div class="perf-badge">${escapeHtml(b.performance)} return</div>` : ''}
      </div>
      ${b.themes.length ? `<div class="theme-tags">${b.themes.map(t =>
        `<span class="theme-tag">${escapeHtml(t)}</span>`
      ).join('')}</div>` : ''}
      ${b.insights.length ? `
        <ul class="insight-list">
          ${b.insights.map(ins => `<li>${escapeHtml(truncate(ins, 220))}</li>`).join('')}
        </ul>
      ` : '<p class="small">No strong actionable signals detected in this letter.</p>'}
    </article>
  `).join('')
}

/* ══════════════════════════════════════════════
   EXTRACTION TAB RENDERING  (unchanged logic)
   ══════════════════════════════════════════════ */

function renderResults(result, topN) {
  const aggregateRows = result.aggregate.slice(0, topN)

  let html = `<section class="panel"><h2>Aggregate Top Ideas</h2>${renderTable(aggregateRows)}</section>`

  for (const fileResult of result.files) {
    html += `<section class="panel"><h2>${fileResult.file}</h2>${renderTable(fileResult.top.slice(0, topN))}</section>`
  }

  html += `<section class="panel"><h2>Markdown Preview</h2><pre>${escapeHtml(asMarkdown(result, topN))}</pre></section>`
  results.innerHTML = html
}

function renderTable(rows) {
  const body = rows
    .map(
      (row, idx) =>
        `<tr><td>${idx + 1}</td><td>${escapeHtml(row.asset)}</td><td>${row.score}</td><td>${row.mentions}</td></tr>`
    )
    .join('')

  return `
    <table>
      <thead><tr><th>Rank</th><th>Asset</th><th>Score</th><th>Mentions</th></tr></thead>
      <tbody>${body}</tbody>
    </table>
  `
}

/* ── helpers ── */
function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
}

function truncate(str, max) {
  if (str.length <= max) return str
  return str.slice(0, max).replace(/\s+\S*$/, '') + '…'
}
