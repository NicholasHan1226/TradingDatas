# TradingDatas Admin Console

This directory contains the standalone admin console frontend for deployment to Cloudflare Pages.

## Deployment to Cloudflare Pages

### Option 1: Direct Upload

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. Navigate to **Workers & Pages** → **Create** → **Pages**
3. Choose **Upload assets**
4. Upload the contents of this `static/` directory
5. Set the build output directory to `/` (root)

### Option 2: Git Integration

1. Create a GitHub repository with this `static/` directory
2. Connect it to Cloudflare Pages
3. Configure:
   - **Build command**: Leave empty (static site)
   - **Build output directory**: `static`

## Configuration

After deployment, open the admin console and:

1. **Set API URL**: Click the "API URL" button and enter your backend API URL (e.g., `https://api.yourdomain.com`)
2. **Enter Token**: Enter your API token with `admin` scope
3. **Save**: Click "Save" to store both in localStorage

The settings will persist across sessions.

## CORS Requirements

Your backend must allow CORS from the Cloudflare Pages domain:

```python
# In your backend, add:
Access-Control-Allow-Origin: https://your-site.pages.dev
Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization
```

Or use `*` for development (not recommended for production).

## Development

To test locally:

```bash
# Serve static files
python3 -m http.server 8080 --directory static

# Open http://localhost:8080
# Set API URL to your backend (e.g., http://localhost:5000)
```
