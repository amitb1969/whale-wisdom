import Anthropic from '@anthropic-ai/sdk'

const ANALYST_SYSTEM_PROMPT = `You are a senior investment analyst working for a CIO at a family office / long-short equity fund. Your job is to read quarterly hedge fund investor letters and extract actionable investment ideas — nothing else.

## ROLE

You are pitching ideas to a CIO who has one minute per idea. The CIO wants to know:
- Is the stock cheap? (Value)
- What makes it move? (Catalyst)
- What could go wrong and what's the payoff? (Risk/Reward)
- What is the investment theme / framework?
- Does momentum support or contradict the thesis?

You are NOT summarizing the letter. You are NOT reporting performance. You are distilling ideas the way Mohnish Pabrai runs his cannibal strategy: find the company, understand why it's cheap, understand the specific bet, and state it plainly in under 90 seconds.

## CRITICAL RULES

1. Use ONLY information stated in the letter. Do not add context from your training.
2. If the manager does not give a price target, do not invent one.
3. If the manager did not explain the rationale — say so, do not fabricate a thesis.
4. Skip any idea where the manager only mentions performance without explaining the position.
5. Skip boilerplate macro commentary unless it directly explains a position.
6. The pitch must sound like a person talking, not a report being written.
7. No bullet points inside the pitch. Write in sentences.
8. Do not include fund performance, AUM, inception returns, or fee structures.

## WHAT TO SKIP

- Performance commentary ("the fund returned X%")
- General market observations not tied to a specific position
- Positions exited where no thesis is explained
- Political commentary not tied to an investment implication
- Any position where the manager only names the stock without explaining why they own it

## STYLE

- Short sentences. Active voice.
- Dinner-party expert tone — someone who knows the idea well and is explaining it to a smart generalist.
- Flag ideas that are "tariff-immune" — in the current environment this is meaningful differentiation.
- Flag any idea where the manager explicitly states a price target with upside percentage.

Call the submit_fund_analysis tool with your structured analysis. If the letter contains no actionable ideas (only performance commentary, no thesis), set no_ideas to true and leave the ideas array empty.`

const ANALYSIS_TOOL = {
  name: 'submit_fund_analysis',
  description:
    'Submit the structured analysis extracted from a fund investor letter',
  input_schema: {
    type: 'object',
    properties: {
      fund_name: {
        type: 'string',
        description: 'Name of the fund'
      },
      manager: {
        type: 'string',
        description: 'Name of the portfolio manager or letter author'
      },
      regime: {
        type: 'string',
        description:
          "One sentence on the manager's current macro stance (bullish / bearish / neutral + why)"
      },
      no_ideas: {
        type: 'boolean',
        description:
          'True if the letter contains no actionable investment ideas'
      },
      ideas: {
        type: 'array',
        description: 'List of extracted investment ideas',
        items: {
          type: 'object',
          properties: {
            ticker: {
              type: 'string',
              description: 'Stock ticker symbol or asset name'
            },
            tagline: {
              type: 'string',
              description: '15 words or less — the setup in plain English'
            },
            direction: {
              type: 'string',
              enum: ['Long', 'Short', 'Macro', 'Special Situation'],
              description: 'Investment direction'
            },
            pitch: {
              type: 'string',
              description:
                '3-5 sentences. No jargon. Plain declarative sentences explaining the bet, why mispriced, and the mechanism.'
            },
            value: {
              type: 'string',
              description:
                'What makes it cheap or mispriced — specific to this idea only'
            },
            catalyst: {
              type: 'string',
              description:
                'What specifically causes the stock to move — named event, trigger, or mechanism'
            },
            risk_reward: {
              type: 'string',
              description:
                'Upside target or logic if given. Specific downside risk.'
            },
            theme: {
              type: 'string',
              enum: [
                'Buyback cannibal',
                'Hated sector',
                'M&A',
                'Real assets',
                'Tariff beneficiary',
                'AI infrastructure',
                'Special sit',
                'Deep value',
                'Quality on dislocation',
                'Macro hedge',
                'Other'
              ],
              description: 'Investment theme category'
            },
            momentum: {
              type: 'string',
              description:
                'Price action in the letter period if stated — e.g. "+20.7% Q1" or "fell on macro fear, not fundamentals"'
            }
          },
          required: [
            'ticker',
            'tagline',
            'direction',
            'pitch',
            'value',
            'catalyst',
            'risk_reward',
            'theme',
            'momentum'
          ]
        }
      }
    },
    required: ['fund_name', 'manager', 'regime', 'no_ideas', 'ideas']
  }
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  const apiKey = process.env.ANTHROPIC_API_KEY
  if (!apiKey) {
    return res.status(500).json({
      error:
        'ANTHROPIC_API_KEY is not configured. Set it in Vercel environment variables.'
    })
  }

  const { title, text } = req.body || {}
  if (!title || !text) {
    return res
      .status(400)
      .json({ error: 'Missing required fields: title, text' })
  }

  if (text.split(/\s+/).length < 100) {
    return res.status(400).json({ error: 'Letter text too short for analysis' })
  }

  try {
    const client = new Anthropic({ apiKey })
    const model = process.env.ANTHROPIC_MODEL || 'claude-sonnet-4-6'

    const response = await client.messages.create({
      model,
      max_tokens: 4096,
      system: ANALYST_SYSTEM_PROMPT,
      tools: [ANALYSIS_TOOL],
      tool_choice: { type: 'tool', name: 'submit_fund_analysis' },
      messages: [
        {
          role: 'user',
          content: `Analyze this quarterly investor letter and extract actionable ideas.\n\nFUND: ${title}\n\n--- BEGIN LETTER ---\n${text}\n--- END LETTER ---`
        }
      ]
    })

    // Extract the tool use result
    const toolBlock = response.content.find((b) => b.type === 'tool_use')
    if (!toolBlock) {
      return res
        .status(500)
        .json({ error: 'No structured analysis returned from model' })
    }

    return res.status(200).json({ analysis: toolBlock.input })
  } catch (err) {
    console.error('Analysis error:', err)
    const status = err.status || 500
    return res
      .status(status)
      .json({ error: err.message || 'Analysis failed' })
  }
}
