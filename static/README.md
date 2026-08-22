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

The production default backend is `https://td-admin-api.tradingagent.cc`, set in
`static/index.html`. Do not change the Pages build to call an IP address directly.

## Production route

Cloudflare Pages hosts the static console. The configured HTTPS endpoint removes
the HTTPS-page-to-HTTP-origin mixed-content failure without making an origin IP
the browser API target. Its tunnel, connector/service, listener and credential
placement are runtime-delivery concerns: verify them from the target environment
before claiming them; this repository does not define or prove those details.

Never commit route credentials, copy them into Pages, or place them in browser
storage.

To verify the published boundary, `GET /admin/` must return 200 over HTTPS and
an unauthenticated `GET /admin/api/...` must return 401. Those are distinct
checks; use an authenticated readback separately when an admin token is in
scope.

## Data Browser

The console includes a Data Browser tab: filter `/v1/catalog`, click a dataset to page through its stored rows via `POST /v1/query` (forward-only cursor).

## CORS Requirements

Your backend must return a successful unauthenticated preflight for
`OPTIONS /admin/api/*`; browsers send it before cross-origin requests that use
the `Authorization` header. The preflight grants no API access—the subsequent
request still requires the admin token.

The current policy intentionally returns `Access-Control-Allow-Origin: *` for a
bearer-token-only API with no cookie/session authentication. If cookie or browser
credentials are added, replace the wildcard with an explicit origin allowlist.

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
