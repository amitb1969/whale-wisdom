const POSITIVE_KEYWORDS = [
  'buy', 'bought', 'adding', 'added', 'accumulate', 'initiated', 'initiate',
  'long', 'bullish', 'favorite', 'high conviction', 'recommend'
]

const HIGH_CONVICTION_KEYWORDS = [
  'largest position', 'top position', 'core holding', 'high conviction', 'best idea', 'overweight'
]

const STOP_TICKERS = new Set([
  'THE', 'AND', 'FOR', 'WITH', 'THIS', 'THAT', 'WAS', 'ARE', 'NOT', 'FROM',
  'WERE', 'WILL', 'ETF', 'USD', 'Q1', 'Q2', 'Q3', 'Q4'
])

const SENTENCE_SPLIT = /(?<=[.!?])\s+|\n+/g
const TICKER_PATTERNS = [
  /\$([A-Z]{1,5})\b/g,
  /\((?:NYSE|NASDAQ|AMEX|TSX|LSE)\s*[:\-]\s*([A-Z]{1,5})\)/gi,
  /\(([A-Z]{1,5})\)/g
]
const ETF_PATTERN = /\b([A-Z][A-Za-z0-9&'\-. ]{1,50}? ETF)\b/g

function scoreSentence(sentence) {
  const s = sentence.toLowerCase()
  let score = 1
  if (POSITIVE_KEYWORDS.some((k) => s.includes(k))) score += 2
  if (HIGH_CONVICTION_KEYWORDS.some((k) => s.includes(k))) score += 3
  return score
}

function extractAssets(sentence) {
  const assets = new Set()

  for (const pattern of TICKER_PATTERNS) {
    let match
    pattern.lastIndex = 0
    while ((match = pattern.exec(sentence)) !== null) {
      const ticker = String(match[1]).toUpperCase()
      if (!STOP_TICKERS.has(ticker)) assets.add(ticker)
    }
  }

  let etf
  ETF_PATTERN.lastIndex = 0
  while ((etf = ETF_PATTERN.exec(sentence)) !== null) {
    assets.add(etf[1].trim().replace(/\s+/g, ' '))
  }

  return [...assets]
}

function rankMentions(mentions) {
  const aggregate = new Map()
  for (const mention of mentions) {
    const existing = aggregate.get(mention.asset) || {
      asset: mention.asset,
      score: 0,
      mentions: 0,
      examples: []
    }
    existing.score += mention.score
    existing.mentions += 1
    if (existing.examples.length < 3) existing.examples.push(mention.sentence)
    aggregate.set(mention.asset, existing)
  }

  return [...aggregate.values()].sort((a, b) => (b.score - a.score) || (b.mentions - a.mentions))
}

function extractMentions(text) {
  const mentions = []
  for (const raw of text.split(SENTENCE_SPLIT)) {
    const sentence = raw.trim()
    if (sentence.length < 20) continue
    const assets = extractAssets(sentence)
    if (!assets.length) continue
    const baseScore = scoreSentence(sentence)
    for (const asset of assets) {
      mentions.push({ asset, score: baseScore, sentence })
    }
  }
  return mentions
}

export function runExtraction(files, topN = 5) {
  const perFile = []
  const allMentions = []

  for (const file of files) {
    const mentions = extractMentions(file.text)
    allMentions.push(...mentions)
    perFile.push({
      file: file.name,
      top: rankMentions(mentions).slice(0, topN),
      mentionCount: mentions.length
    })
  }

  return {
    filesProcessed: files.length,
    aggregate: rankMentions(allMentions),
    files: perFile
  }
}

export function asMarkdown(result, topN = 5) {
  const lines = ['# Fund Letter Top Stock/ETF Recommendations', '']
  lines.push('## Aggregate Top Ideas', '')
  lines.push('| Rank | Asset | Score | Mentions |')
  lines.push('|---:|---|---:|---:|')
  result.aggregate.slice(0, topN).forEach((row, i) => {
    lines.push(`| ${i + 1} | ${row.asset} | ${row.score} | ${row.mentions} |`)
  })

  for (const fileResult of result.files) {
    lines.push('', `## ${fileResult.file}`, '')
    lines.push('| Rank | Asset | Score | Mentions |')
    lines.push('|---:|---|---:|---:|')
    fileResult.top.slice(0, topN).forEach((row, i) => {
      lines.push(`| ${i + 1} | ${row.asset} | ${row.score} | ${row.mentions} |`)
    })
  }

  lines.push('', '_Heuristic extraction only; verify against source letters._')
  return lines.join('\n')
}
