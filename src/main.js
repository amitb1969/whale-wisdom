import { asMarkdown, runExtraction } from './lib/extractor.js'
import './styles.css'

const app = document.querySelector('#root')

app.innerHTML = `
  <main class="dashboard">
    <header class="dash-header">
      <div>
        <h1>Whale Wisdom</h1>
        <p class="sub">Investment Ideas from Latest Fund Letters</p>
      </div>
      <div class="controls">
        <label>Show top
          <input id="topN" type="number" min="1" max="25" value="10" />
          ideas
        </label>
        <button id="extractBtn" disabled>Extract</button>
        <button id="saveBtn" class="btn-secondary" disabled>Export</button>
      </div>
    </header>

    <p id="status" class="status-bar"></p>

    <section id="results"></section>
  </main>
`

let loadedFiles = []
let currentResult = null

const topNInput = document.getElementById('topN')
const extractBtn = document.getElementById('extractBtn')
const saveBtn = document.getElementById('saveBtn')
const status = document.getElementById('status')
const results = document.getElementById('results')

initializeFiles()

extractBtn.addEventListener('click', () => {
  const topN = Math.max(1, Number(topNInput.value) || 10)
  currentResult = runExtraction(loadedFiles, topN)
  saveBtn.disabled = false
  renderResults(currentResult, topN)
})

saveBtn.addEventListener('click', async () => {
  if (!currentResult) return
  const topN = Math.max(1, Number(topNInput.value) || 10)
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
    status.textContent = `Unable to save: ${error.message}`
  }
})

async function initializeFiles() {
  status.textContent = 'Loading fund letters…'
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

  if (loadedFiles.length) {
    status.textContent = `${loadedFiles.length} fund letters loaded.`
    extractBtn.click()
  } else {
    status.textContent = 'No fund letter files found.'
  }
}

function renderResults(result, topN) {
  const top = result.aggregate.slice(0, topN)
  const totalMentions = result.aggregate.reduce((sum, r) => sum + r.mentions, 0)

  let html = ''

  // Summary stats
  html += `
    <div class="stats-row">
      <div class="stat-card">
        <span class="stat-value">${result.filesProcessed}</span>
        <span class="stat-label">Fund Letters</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">${result.aggregate.length}</span>
        <span class="stat-label">Assets Found</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">${totalMentions}</span>
        <span class="stat-label">Total Mentions</span>
      </div>
    </div>
  `

  // Idea cards
  html += '<div class="ideas-grid">'
  top.forEach((row, i) => {
    const convictionClass = row.conviction === 'High' ? 'badge-high' : row.conviction === 'Medium' ? 'badge-med' : 'badge-low'

    const quotesHtml = row.examples
      .map((ex) => `
        <blockquote class="rationale-quote">
          <p>${escapeHtml(truncate(ex.text, 200))}</p>
          <cite>${escapeHtml(ex.source)}</cite>
        </blockquote>
      `)
      .join('')

    const sourcesHtml = row.sources
      .map((s) => `<span class="source-tag">${escapeHtml(s)}</span>`)
      .join('')

    html += `
      <article class="idea-card">
        <div class="idea-header">
          <span class="idea-rank">#${i + 1}</span>
          <span class="idea-asset">${escapeHtml(row.asset)}</span>
          <span class="badge ${convictionClass}">${row.conviction} Conviction</span>
        </div>
        <div class="idea-meta">
          <span>Score: <strong>${row.score}</strong></span>
          <span>Mentions: <strong>${row.mentions}</strong></span>
        </div>
        <div class="idea-sources">${sourcesHtml}</div>
        <div class="idea-rationale">
          <h4>Key Rationale</h4>
          ${quotesHtml || '<p class="muted">No rationale excerpts captured.</p>'}
        </div>
      </article>
    `
  })
  html += '</div>'

  // Per-fund breakdown (collapsed)
  html += '<details class="fund-details"><summary>View by Fund</summary>'
  for (const fileResult of result.files) {
    if (!fileResult.top.length) continue
    html += `<div class="fund-section"><h3>${escapeHtml(fileResult.fundName)}</h3>`
    html += renderCompactTable(fileResult.top.slice(0, topN))
    html += '</div>'
  }
  html += '</details>'

  results.innerHTML = html
}

function renderCompactTable(rows) {
  const body = rows
    .map(
      (row, idx) =>
        `<tr>
          <td>${idx + 1}</td>
          <td><strong>${escapeHtml(row.asset)}</strong></td>
          <td>${row.conviction}</td>
          <td>${row.score}</td>
          <td>${row.mentions}</td>
          <td class="rationale-cell">${row.examples.length ? escapeHtml(truncate(row.examples[0].text, 120)) : '—'}</td>
        </tr>`
    )
    .join('')

  return `
    <table>
      <thead><tr><th>#</th><th>Asset</th><th>Conviction</th><th>Score</th><th>Mentions</th><th>Top Rationale</th></tr></thead>
      <tbody>${body}</tbody>
    </table>
  `
}

function truncate(str, max) {
  if (str.length <= max) return str
  return str.slice(0, max).replace(/\s+\S*$/, '') + '…'
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
}
