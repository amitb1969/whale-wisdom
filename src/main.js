import { asMarkdown, runExtraction } from './lib/extractor.js'
import './styles.css'

const app = document.querySelector('#root')

app.innerHTML = `
  <main class="container">
    <h1>Fund Letter Top Recommendations</h1>
    <p class="sub">Upload fund letter text files and extract top stock/ETF recommendations.</p>

    <section class="panel">
      <label>
        Upload .txt files
        <input id="fileInput" type="file" multiple accept=".txt" />
      </label>

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
  </main>
`

let loadedFiles = []
let currentResult = null

const fileInput = document.getElementById('fileInput')
const topNInput = document.getElementById('topN')
const extractBtn = document.getElementById('extractBtn')
const saveBtn = document.getElementById('saveBtn')
const status = document.getElementById('status')
const results = document.getElementById('results')

fileInput.addEventListener('change', async (event) => {
  const selected = [...event.target.files]
  loadedFiles = await Promise.all(
    selected.map(async (file) => ({ name: file.name, text: await file.text() }))
  )
  currentResult = null
  extractBtn.disabled = loadedFiles.length === 0
  saveBtn.disabled = true
  results.innerHTML = ''
  status.textContent = loadedFiles.length
    ? `Loaded ${loadedFiles.length} file(s): ${loadedFiles.map((f) => f.name).join(', ')}`
    : ''
})

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

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
}
