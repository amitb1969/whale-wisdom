# Fund Letter Top Recommendations Frontend

Simple Vite UI to extract top stock/ETF recommendations from fund-letter text files.

## Local run

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

## How to use

1. Upload one or more `.txt` files (for example from `output/playwright/fund-letters/latest-quarter-content/text/`).
2. Set `Top N`.
3. Click **Extract Recommendations**.
4. (Optional) Click **Save report to Vercel Blob**.

## Deploy to Vercel

1. Push this repo to GitHub.
2. Import project in Vercel.
3. Deploy.

Vercel auto-detects Vite via `vercel.json`.

## Blob note

`/api/save-report` is intentionally a small placeholder endpoint returning setup guidance. If you want live Blob persistence, add `@vercel/blob` and wire `put()` in that route with `BLOB_READ_WRITE_TOKEN`.
