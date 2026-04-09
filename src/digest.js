import './digest.css'

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let letters = []
let analyses = []
let isRunning = false

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------
const root = document.getElementById('root')
root.innerHTML = `
<div class="header">
  <div class="header-left">
    <span class="logo">DL INTEL</span>
    <span class="header-title">Fund Letters Digest &ndash; Cannibal Strategy</span>
  </div>
  <div class="header-right">
    <span class="period" id="period">Period: Q4 2025</span>
    <span>Source: Fiscal.ai / Primary Letters / Front CSO Brief &mdash; One Minute Pitch</span>
  </div>
</div>

<div class="toolbar">
  <a href="/" class="nav-link">&larr; Recommendations</a>
  <div class="toolbar-right">
    <label class="concurrency-label">
      Parallel
      <input id="concurrency" type="number" min="1" max="10" value="3" />
    </label>
    <button id="generateBtn" class="btn btn-primary">Generate Digest</button>
    <button id="copyBtn" class="btn btn-secondary" disabled>&#128203; Copy</button>
  </div>
</div>

<div id="progress" class="progress-bar" style="display:none">
  <div class="progress-fill" id="progressFill"></div>
  <span class="progress-text" id="progressText">0 / 0</span>
</div>

<div class="container" id="digestContainer">
  <div class="empty-state" id="emptyState">
    <p>Click <strong>Generate Digest</strong> to analyze all fund letters and extract investment ideas.</p>
    <p class="small">This calls the Claude API for each letter. The ANTHROPIC_API_KEY must be set in Vercel environment variables.</p>
  </div>
</div>

<div class="footer" id="footer" style="display:none">
  <span id="footerText"></span>
</div>
`

const generateBtn = document.getElementById('generateBtn')
const copyBtn = document.getElementById('copyBtn')
const concurrencyInput = document.getElementById('concurrency')
const progressBar = document.getElementById('progress')
const progressFill = document.getElementById('progressFill')
const progressText = document.getElementById('progressText')
const digestContainer = document.getElementById('digestContainer')
const emptyState = document.getElementById('emptyState')
const footer = document.getElementById('footer')
const footerText = document.getElementById('footerText')

// ---------------------------------------------------------------------------
// Load bundled text files
// ---------------------------------------------------------------------------
const modules = import.meta.glob(
  '../output/playwright/fund-letters/latest-quarter-content/text/*.txt',
  { query: '?raw', import: 'default' }
)

async function loadLetters() {
  const loaded = await Promise.all(
    Object.entries(modules).map(async ([path, loader]) => {
      const text = await loader()
      const name = path.split('/').pop()
      // Extract fund title from filename: "001-1-main-capital.txt" -> "1 Main Capital"
      const title = name
        .replace(/^\d+-/, '')
        .replace(/\.txt$/, '')
        .replace(/-/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase())
      return { name, title, text }
    })
  )
  return loaded.sort((a, b) => a.name.localeCompare(b.name))
}

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------
async function analyzeLetter(title, text) {
  const resp = await fetch('/api/analyze-letter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, text })
  })
  const data = await resp.json()
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`)
  return data.analysis
}

// ---------------------------------------------------------------------------
// Concurrent processing with limited parallelism
// ---------------------------------------------------------------------------
async function processAll(items, concurrency, onProgress) {
  const results = new Array(items.length)
  let nextIndex = 0
  let completed = 0

  async function worker() {
    while (nextIndex < items.length) {
      const idx = nextIndex++
      const item = items[idx]
      try {
        results[idx] = await analyzeLetter(item.title, item.text)
      } catch (err) {
        results[idx] = {
          fund_name: item.title,
          manager: '',
          regime: '',
          no_ideas: true,
          ideas: [],
          error: err.message
        }
      }
      completed++
      onProgress(completed, items.length, item.title)
    }
  }

  const workers = Array.from(
    { length: Math.min(concurrency, items.length) },
    () => worker()
  )
  await Promise.all(workers)
  return results
}

// ---------------------------------------------------------------------------
// Generate digest
// ---------------------------------------------------------------------------
generateBtn.addEventListener('click', async () => {
  if (isRunning) return
  isRunning = true
  generateBtn.disabled = true
  generateBtn.textContent = 'Analyzing...'

  try {
    if (letters.length === 0) {
      letters = await loadLetters()
    }

    // Filter out very short letters
    const validLetters = letters.filter(
      (l) => l.text.split(/\s+/).length >= 100
    )

    // Show progress
    progressBar.style.display = 'flex'
    progressFill.style.width = '0%'
    progressText.textContent = `0 / ${validLetters.length}`
    emptyState.style.display = 'none'

    const concurrency = Math.max(
      1,
      Math.min(10, Number(concurrencyInput.value) || 3)
    )

    analyses = await processAll(
      validLetters,
      concurrency,
      (done, total, title) => {
        const pct = Math.round((done / total) * 100)
        progressFill.style.width = `${pct}%`
        progressText.textContent = `${done} / ${total} — ${title}`
      }
    )

    renderDigest(analyses)
    copyBtn.disabled = false

    const totalIdeas = analyses.reduce(
      (n, a) => n + (a.ideas?.length || 0),
      0
    )
    footer.style.display = 'block'
    footerText.textContent = `Generated ${new Date().toISOString().slice(0, 16)} UTC · ${analyses.length} funds · ${totalIdeas} ideas · Cannibal Strategy Digest · For internal use only`
  } catch (err) {
    digestContainer.innerHTML = `<div class="error">Error: ${escapeHtml(err.message)}</div>`
  } finally {
    isRunning = false
    generateBtn.disabled = false
    generateBtn.textContent = 'Generate Digest'
    progressBar.style.display = 'none'
  }
})

// ---------------------------------------------------------------------------
// Copy
// ---------------------------------------------------------------------------
copyBtn.addEventListener('click', () => {
  const lines = []
  for (const fund of analyses) {
    if (!fund.fund_name) continue
    lines.push(
      `\n## ${fund.fund_name}${fund.manager ? ` (${fund.manager})` : ''}`
    )
    if (fund.regime) lines.push(`Regime: ${fund.regime}`)
    for (const idea of fund.ideas || []) {
      lines.push(
        `  ${idea.ticker} | ${idea.tagline} [${idea.direction.toUpperCase()}]`
      )
    }
  }
  navigator.clipboard.writeText(lines.join('\n')).then(() => {
    copyBtn.innerHTML = '&#10003; Copied'
    setTimeout(() => (copyBtn.innerHTML = '&#128203; Copy'), 1500)
  })
})

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------
function renderDigest(results) {
  const funds = results.filter((r) => r && r.fund_name)
  if (funds.length === 0) {
    digestContainer.innerHTML =
      '<div class="empty-state">No analyses available.</div>'
    return
  }

  digestContainer.innerHTML = funds.map((fund) => renderFundCard(fund)).join('')
}

function renderFundCard(fund) {
  const ideasHtml =
    fund.ideas && fund.ideas.length > 0
      ? fund.ideas.map((idea) => renderIdeaRow(idea, fund.source_link)).join('')
      : '<div class="no-ideas">No actionable ideas extracted from this letter.</div>'

  const regimeHtml = fund.regime
    ? `<div class="regime"><strong>Regime:</strong> ${escapeHtml(fund.regime)}</div>`
    : ''

  const errorHtml = fund.error
    ? `<div class="error-note">Analysis error: ${escapeHtml(fund.error)}</div>`
    : ''

  return `
    <section class="fund-card">
      <div class="fund-header">
        <h2 class="fund-name">${escapeHtml(fund.fund_name)}</h2>
        <span class="manager">${escapeHtml(fund.manager || '')}</span>
      </div>
      ${regimeHtml}
      ${errorHtml}
      <div class="ideas">${ideasHtml}</div>
    </section>`
}

function renderIdeaRow(idea) {
  const badgeClass = getBadgeClass(idea.direction)
  const detailHtml =
    idea.pitch || idea.value || idea.catalyst
      ? `<div class="idea-detail" style="display:none">
      <div class="pitch"><strong>Pitch:</strong> ${escapeHtml(idea.pitch || '')}</div>
      <div class="meta-grid">
        <div><strong>Value:</strong> ${escapeHtml(idea.value || '')}</div>
        <div><strong>Catalyst:</strong> ${escapeHtml(idea.catalyst || '')}</div>
        <div><strong>Risk/Reward:</strong> ${escapeHtml(idea.risk_reward || '')}</div>
        <div><strong>Theme:</strong> ${escapeHtml(idea.theme || '')}</div>
        <div><strong>Momentum:</strong> ${escapeHtml(idea.momentum || '')}</div>
      </div>
    </div>`
      : ''

  return `
    <div class="idea-row" onclick="window.__toggleDetail(this)">
      <div class="idea-summary">
        <span class="ticker">${escapeHtml(idea.ticker)}</span>
        <span class="tagline">${escapeHtml(idea.tagline)}</span>
        <span class="badge ${badgeClass}">${escapeHtml(idea.direction.toUpperCase())}</span>
      </div>
      ${detailHtml}
    </div>`
}

// Expose toggle to onclick handlers
window.__toggleDetail = function (row) {
  const detail = row.querySelector('.idea-detail')
  if (!detail) return
  detail.style.display = detail.style.display === 'none' ? 'block' : 'none'
}

function getBadgeClass(direction) {
  const d = (direction || '').toLowerCase()
  if (d.includes('long')) return 'badge-long'
  if (d.includes('short')) return 'badge-short'
  if (d.includes('macro')) return 'badge-macro'
  return 'badge-special'
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}
