/**
 * Summarizer – extracts quick CIO-ready insights from fund letter text.
 */

const INSIGHT_KEYWORDS = [
  'largest position', 'top position', 'core holding', 'high conviction',
  'best idea', 'overweight', 'initiated', 'added to', 'new position',
  'biggest winner', 'top contributor', 'key driver', 'top five winner',
  'significant position', 'meaningful position', 'concentrated',
  'compelling', 'undervalued', 'attractive valuation', 'buy',
  'bullish', 'upside', 'thesis', 'catalyst', 'opportunity'
]

const THEME_KEYWORDS = {
  'AI / Technology': ['artificial intelligence', 'machine learning', 'ai ', 'semiconductor', 'cloud', 'software', 'technology', 'data center'],
  'Energy': ['energy', 'oil', 'gas', 'renewable', 'solar', 'nuclear', 'utility', 'power'],
  'Healthcare': ['healthcare', 'pharma', 'biotech', 'drug', 'medical', 'fda'],
  'Financials': ['bank', 'insurance', 'financial', 'fintech', 'credit', 'lending'],
  'Consumer': ['consumer', 'retail', 'brand', 'e-commerce', 'restaurant'],
  'Real Estate': ['real estate', 'reit', 'property', 'housing'],
  'Crypto / Digital': ['crypto', 'bitcoin', 'blockchain', 'digital asset', 'defi', 'token'],
  'Macro / Rates': ['interest rate', 'inflation', 'fed ', 'monetary policy', 'macro', 'tariff', 'trade war'],
  'Value Investing': ['value', 'margin of safety', 'intrinsic value', 'discount', 'cheap', 'undervalued'],
  'International': ['international', 'emerging market', 'europe', 'asia', 'china', 'india', 'latin america']
}

const SENTENCE_SPLIT = /(?<=[.!?])\s+|\n+/g

/**
 * Parse a date string like "January 26" with a year into a Date object.
 */
export function parseLetterDate(dateStr, year) {
  if (!dateStr || !year) return null
  const d = new Date(`${dateStr}, ${year}`)
  // Fund letters dated in year X with Q4 are published early next year
  // The dates like "January 26" with year 2025 Q4 actually mean January 2026
  const parsed = new Date(`${dateStr}, ${Number(year) + 1}`)
  return isNaN(parsed.getTime()) ? null : parsed
}

/**
 * Filter letters to those published within the last N days from a reference date.
 */
export function filterRecentLetters(letters, days = 15, referenceDate = null) {
  const ref = referenceDate || new Date()
  const cutoff = new Date(ref)
  cutoff.setDate(cutoff.getDate() - days)

  return letters.filter(letter => {
    const d = parseLetterDate(letter.date, letter.year)
    return d && d >= cutoff && d <= ref
  })
}

/**
 * Extract key insight sentences from letter text.
 */
export function extractInsights(text, maxInsights = 4) {
  const sentences = text.split(SENTENCE_SPLIT).map(s => s.trim()).filter(s => s.length > 30)
  const scored = []

  for (const sentence of sentences) {
    const lower = sentence.toLowerCase()
    let score = 0
    for (const kw of INSIGHT_KEYWORDS) {
      if (lower.includes(kw)) score += 1
    }
    // Boost sentences that mention tickers
    if (/\$[A-Z]{1,5}\b/.test(sentence) || /\((?:NYSE|NASDAQ)\s*:\s*[A-Z]+\)/i.test(sentence)) {
      score += 2
    }
    if (/\([A-Z]{1,5}\)/.test(sentence)) {
      score += 1
    }
    if (score > 0) {
      scored.push({ sentence, score })
    }
  }

  scored.sort((a, b) => b.score - a.score)
  return scored.slice(0, maxInsights).map(s => s.sentence)
}

/**
 * Detect which themes are present in the letter text.
 */
export function detectThemes(text) {
  const lower = text.toLowerCase()
  const found = []
  for (const [theme, keywords] of Object.entries(THEME_KEYWORDS)) {
    const hits = keywords.filter(kw => lower.includes(kw)).length
    if (hits >= 1) found.push({ theme, strength: hits })
  }
  found.sort((a, b) => b.strength - a.strength)
  return found.slice(0, 4).map(t => t.theme)
}

/**
 * Extract performance return if mentioned in first ~500 chars.
 */
export function extractPerformance(text) {
  const header = text.slice(0, 1500)
  // Look for patterns like "returned X.X%" or "returned X%"
  const match = header.match(/returned\s+([+-]?\d+\.?\d*)\s*%/i)
    || header.match(/(\d+\.?\d*)\s*%\s*(?:net|gross|in 2025|for (?:the|full))/i)
  return match ? match[1] + '%' : null
}

/**
 * Build a CIO brief for a single fund letter.
 */
export function buildLetterBrief(letter, fileText) {
  return {
    fund: letter.title,
    date: letter.date,
    year: letter.year,
    parsedDate: parseLetterDate(letter.date, letter.year),
    performance: extractPerformance(fileText),
    themes: detectThemes(fileText),
    insights: extractInsights(fileText, 4),
    wordCount: fileText.split(/\s+/).length
  }
}
