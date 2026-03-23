# GreenWatt — GHL Nurture Sequences (Lead Magnet Funnel)

**Version:** 1.0 | **Date:** March 23, 2026
**Platform:** GoHighLevel (GHL)
**Trigger:** Form submit on greenwattconsultingresults.com (benchmark report download)
**Configures:** Shehar (triggers + delivery)
**Copy:** Below

---

## Placeholders

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `{{FIRST_NAME}}` | Contact's first name | "Mike" |
| `{{VERTICAL}}` | Their vertical/industry | "Roofing", "Mortgage", "Solar" |
| `{{CPL}}` | Cost per lead for their vertical | "35", "85" |

## Links

| Link | URL |
|------|-----|
| Thank-you page (VSL) | greenwattconsultingresults.com/thank-you |
| Score 10 Free tool | greenwattconsultingresults.com/score |
| Calendly (Gold Program) | https://calendly.com/d/cxsg-ydm-kqc/gold-program-greenwatt |

---

## EMAIL 1 — Immediate (on form submit)

**Subject:** Your {{VERTICAL}} Lead Quality Report

{{FIRST_NAME}} —

Your report is in your inbox. Before you read it, here's what to pay attention to.

Most lead buyers we talk to are spending between 30-50% of their budget on leads that were dead before they hit the CRM. Disconnected phones, renters, known TCPA litigators, bot submissions. Your reps call them anyway because nobody flagged them.

The report breaks down the five scoring pillars we use to catch those leads before delivery — and shows you what "Gold-tier" quality actually looks like in {{VERTICAL}}.

Two things to look for:
1. The contactability breakdown. This is where most of the waste hides.
2. The fraud and legal section. One litigator in your pipeline costs more than a month of lead spend.

I recorded a quick walkthrough showing how this works in practice — two minutes, no pitch: greenwattconsultingresults.com/thank-you

Jackson Doyle
GreenWatt Consulting

---

## EMAIL 2 — Day 2

**Subject:** Score 10 of your {{VERTICAL}} leads — free

{{FIRST_NAME}} —

The report shows what to look for. Now see it on YOUR data.

We built a free tool that scores 10 of your leads — any source, any age — across all five pillars. Upload them, get scores back in about two minutes. Each lead gets a 0-100 composite score and a tier: Gold, Silver, Bronze, or Block.

You'll see exactly which leads your reps should be calling first and which ones should never have made it into the CRM.

greenwattconsultingresults.com/score

Quick FAQ:
- No commitment. No credit card. No sales call required.
- Your data stays private — scored and displayed, never stored or shared.
- Works for any {{VERTICAL}} lead source: your own gen, aggregators, whatever you're buying.

10 leads. Two minutes. You'll know if lead scoring is worth exploring further.

Jackson Doyle
GreenWatt Consulting

---

## EMAIL 3 — Day 5

**Subject:** The real cost of shared leads

{{FIRST_NAME}} —

Quick math on what most {{VERTICAL}} buyers are actually paying per job.

Shared leads at ${{CPL}} each, sold to 3-4 buyers. Each buyer fights for the same appointment. Industry average close rate on shared leads is 5-8%.

At ${{CPL}} per lead and a 6% close rate, you're paying roughly ${{CPL}} x 17 leads = real cost per closed job. That doesn't include your reps' time on the ones that never pick up.

Now flip it.

Scored exclusive leads. One buyer. Phone verified, homeowner confirmed, fraud-checked, behavioral signals validated. Contact rates go up. Close rates go up. Cost per job comes down — not because the CPL is lower, but because you stop paying for leads that were never going to close.

That's the difference between buying leads and buying scored leads.

Want to see the difference on your own data? Score 10 free: greenwattconsultingresults.com/score

Jackson Doyle
GreenWatt Consulting

---

## EMAIL 4 — Day 8

**Subject:** Quick question about your {{VERTICAL}} leads

{{FIRST_NAME}} —

Want to see what Gold-only leads look like for {{VERTICAL}}? 15 minutes — I'll plug in your CPL and close rate and we'll see if the numbers work.

If they don't, I'll tell you.

https://calendly.com/d/cxsg-ydm-kqc/gold-program-greenwatt

Jackson Doyle
GreenWatt Consulting

---

## SMS 1 — Immediate (on form submit)

```
Your {{VERTICAL}} lead quality report is in your inbox. Quick video walkthrough here: greenwattconsultingresults.com/thank-you — Jackson, GreenWatt
```

---

## SMS 2 — Day 3

```
Hey {{FIRST_NAME}} — ready to see your own lead scores? Score 10 free, takes 2 min: greenwattconsultingresults.com/score — Jackson
```

---

## GHL Setup Notes

- Trigger: Form submission on greenwattconsultingresults.com report download
- Email 1 + SMS 1: Immediate (0 delay)
- Email 2: +2 days
- SMS 2: +3 days
- Email 3: +5 days
- Email 4: +8 days
- Sender name: Jackson Doyle
- Sender email: jackson@ (GreenWatt domain)
- Subject lines are sentence case intentionally (report context, not cold outreach)
- All links should have UTM parameters for tracking: `?utm_source=ghl&utm_medium=email&utm_campaign=nurture&utm_content=email_X`
- SMS character counts are under 160 (verify after link shortening)

---

## Claims Compliance

- No CPA guarantees or specific improvement percentages
- "5-8% close rate" is stated as industry average, not a GreenWatt claim
- No specific multipliers or projected results
- "Roughly" and "about" used for directional numbers
- Score 10 Free framed as diagnostic, not a sales commitment
- Consistent with GreenWatt Messaging Starter Pack guardrails
