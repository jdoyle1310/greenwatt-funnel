# GreenWatt Lead Funnel — Deployment Guide

## Overview
This repo contains the complete GreenWatt lead generation funnel:
1. **Landing page** — collects lead info, delivers vertical-specific PDF report
2. **Thank you page** — VSL + Score 10 CTA
3. **13 PDF reports** — one per vertical (as HTML files, print to PDF)
4. **Score 10 Leads app** — Flask app, 5-step lead scoring wizard
5. **GHL nurture copy** — email/SMS sequences for GoHighLevel

## Domain: greenwattconsultingresults.com

### URL Routing

| URL | Serves | Type |
|-----|--------|------|
| `/` | `index.html` | Static |
| `/thank-you` | `thank-you.html` | Static |
| `/reports/[vertical].pdf` | `reports/[slug].pdf` | Static (after PDF export) |
| `/score` | Flask app (port 5050) | Reverse proxy |

### Vertical Slugs
solar, roofing, windows, hvac, siding, gutters, painting, plumbing, bath-remodel, kitchen-remodel, flooring, mortgage, insurance

## Setup

### Static Pages (Landing + Thank You + Reports)
Serve from any web server, CDN, or static hosting (Netlify, Vercel, GitHub Pages, Nginx, etc.)

No backend needed for these pages. All JS is inline.

### PDF Reports
The reports are in `reports/` as HTML files. To convert to PDF:
1. Open each `.html` file in Chrome
2. Print > Save as PDF (Letter size, no margins override — margins are set in CSS)
3. Save as `[slug].pdf` in the same `reports/` directory

Or use a headless browser script:
```bash
# Example with Puppeteer
for f in reports/*.html; do
  slug=$(basename "$f" .html)
  npx puppeteer-cli print "$f" "reports/${slug}.pdf" --format Letter
done
```

### Score 10 Leads Flask App
```bash
cd score/
pip install -r requirements.txt

# Demo mode (no API keys needed — generates fake scores)
python app.py

# Production mode (real scoring via Lambda)
LAMBDA_API_URL=https://your-lambda-url.amazonaws.com/score python app.py
```

Runs on port 5050. Set up a reverse proxy (Nginx/Caddy) to route `/score` to `localhost:5050`.

**Docker:**
```bash
cd score/
docker build -t greenwatt-score10 .
docker run -p 5050:5050 -e LAMBDA_API_URL=https://... greenwatt-score10
```

### GHL Webhook
The landing page form POSTs to a GHL webhook on submit.

**You need to:**
1. Create a GHL webhook/workflow trigger
2. Get the webhook URL from GHL
3. Replace the placeholder in `index.html`:
   - Search for `https://hooks.example.com/ghl-webhook`
   - Replace with your actual GHL webhook URL

**Payload format (JSON):**
```json
{
  "firstName": "John",
  "lastName": "Doe",
  "email": "john@company.com",
  "phone": "555-123-4567",
  "company": "ABC Roofing",
  "vertical": "Roofing",
  "source": "greenwatt-funnel",
  "timestamp": "2026-03-23T12:00:00.000Z"
}
```

### VSL Video
The thank you page has a video placeholder. Replace with actual video:

**Option 1 — Loom embed:**
In `thank-you.html`, find the `loadVideo()` function and uncomment the Loom iframe line, replacing `YOUR_LOOM_ID`.

**Option 2 — Self-hosted MP4:**
Place the video file at `assets/walkthrough.mp4`. The current code already points there.

### Calendly
All Calendly links point to: `https://calendly.com/d/cxsg-ydm-kqc/gold-program-greenwatt`

## GHL Nurture Sequences
See `nurture-copy/ghl-sequences.md` for the complete email/SMS copy. Configure in GHL with these triggers:
- **Trigger**: Webhook receives form submission
- **Email 1**: Immediate (attach PDF for their vertical)
- **Email 2**: Day 2
- **Email 3**: Day 5
- **Email 4**: Day 8
- **SMS 1**: Immediate
- **SMS 2**: Day 3

## File Structure
```
greenwatt-funnel/
├── index.html              ← Landing page
├── thank-you.html          ← VSL + Score 10 CTA
├── reports/                ← 13 vertical reports (HTML → export as PDF)
├── report-templates/       ← Master template (for future edits)
├── score/                  ← Score 10 Flask app
├── assets/                 ← Images, video
├── ad-mockups/             ← LinkedIn ad visual mockups
├── nurture-copy/           ← GHL email/SMS copy
└── README.md               ← This file
```
