export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  return res.status(501).json({
    error:
      'Blob save endpoint is not enabled in this environment. To enable on Vercel, add @vercel/blob and BLOB_READ_WRITE_TOKEN.'
  })
}
