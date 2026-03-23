# GreenWatt — Score 10 Leads

Sales demo and lead magnet tool. Prospects fill out a gate form, upload a CSV of up to 10 leads, map their columns, and get instant 3-tier scoring results (Gold / Silver / Bronze / Reject).

## Requirements

- Python 3.9+
- Flask 3.1+

## Quick Start (Local)

```bash
git clone git@github.com:jdoyle1310/greenwatt-score-10-leads.git
cd greenwatt-score-10-leads
pip install -r requirements.txt
python app.py
```

App runs at `http://localhost:5050`

Without any API keys set, the app runs in **demo mode** with deterministic fake scores — perfect for testing the UI flow.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LAMBDA_API_URL` | No | API Gateway URL for the GreenWatt Lambda scorer (e.g. `https://abc123.execute-api.us-east-1.amazonaws.com/Prod/validate`). When set, uses real Lambda scoring. |
| `TRESTLE_API_KEY` | No | Trestle Real Contact API key. Used for direct API scoring mode. |
| `BATCHDATA_API_KEY` | No | BatchData Property API key. Used for direct API scoring mode. |

## Scoring Modes

The app picks the best available mode automatically (priority order):

1. **Lambda mode** — Set `LAMBDA_API_URL`. Calls the production GreenWatt Lambda endpoint which handles all enrichment + LLM scoring. This is what you want in production.
2. **Direct API mode** — Set `TRESTLE_API_KEY` + `BATCHDATA_API_KEY`. Calls enrichment APIs directly from the Flask app.
3. **Demo mode** — No env vars needed. Generates deterministic fake scores for sales demos and UI testing.

## Tier Thresholds

| Tier | Score Range |
|------|-------------|
| Gold | 70 - 100 |
| Silver | 45 - 69 |
| Bronze | 20 - 44 |
| Reject | 0 - 19 |

## Production Deployment

### Option 1: Docker (Recommended)

```bash
# Build
docker build -t greenwatt-score10 .

# Run with Lambda scoring
docker run -d \
  --name greenwatt-score10 \
  -p 5050:5050 \
  -e LAMBDA_API_URL=https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/Prod/validate \
  --restart unless-stopped \
  greenwatt-score10
```

### Option 2: Direct Python

```bash
pip install -r requirements.txt
LAMBDA_API_URL=https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/Prod/validate python app.py
```

### Option 3: PaaS (Render / Railway)

1. Connect this repo
2. Set `LAMBDA_API_URL` env var in the dashboard
3. Auto-deploys on push

## HTTPS / Custom Domain

Put Nginx or Caddy in front of the app for HTTPS and a custom domain:

**Caddy example** (add to Caddyfile):
```
score.greenwatt.com {
    reverse_proxy localhost:5050
}
```

**Nginx example**:
```nginx
server {
    server_name score.greenwatt.com;
    location / {
        proxy_pass http://localhost:5050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Then point your DNS A record to your server IP.

## Project Structure

```
score-10-leads/
├── app.py              # Flask application (all routes + scoring logic)
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker container config
├── templates/
│   └── index.html      # Single-page app (gate form → upload → mapping → results)
└── README.md
```

## How It Works

1. **Gate Form** — Prospect enters name, email, company, vertical
2. **CSV Upload** — Upload a CSV with up to 10 leads
3. **Field Mapping** — Auto-detects columns, user confirms mapping
4. **Scoring** — Each lead is scored via the configured scoring mode
5. **Results** — Shows tier breakdown with score details and a CTA to contact GreenWatt
