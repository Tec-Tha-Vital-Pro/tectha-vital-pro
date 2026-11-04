# Tec Tha Vital — Hospital OS · Lovable demo

An interactive demo of **Tec Tha Vital** by Tec Tha Consultancy Services. It is one file, `src/App.tsx`, with sample data only: no backend and no real patients.

**What it includes:**
- Public landing page
- 8 hospital modules, plus AI agents, Compliance and Settings
- Patient app view
- Light, dark and system themes
- 9 languages: English, Hindi, Tamil, Telugu, Malayalam, Kannada, Marathi, Arabic and Urdu (Arabic and Urdu run right-to-left)
- 6 currencies: INR, USD, EUR, GBP, AED and SAR, converted at fixed demo rates
- 6 demo roles, a guided tour, and undo on actions

## 1. Put it into Lovable

1. Create a new Lovable project (React + Vite + TypeScript + Tailwind, Lovable's default).
2. Paste this prompt into the Lovable chat:

   > Replace the entire contents of `src/App.tsx` with the code I paste next, exactly as given. Do not add or change any other component. Make sure `tailwind.config.ts` has `darkMode: ["class"]` and that `src/main.tsx` renders `<App />`. lucide-react is already installed.

3. Paste the whole of `src/App.tsx` from this folder.
4. Upload the Tec Tha logo PNG to Lovable's **`public/`** folder as **`tectha-logo.png`**. Until it is uploaded, the app shows the text wordmark "Tec Tha" instead.
5. Open the preview. The landing page appears first; **Try the demo** opens the app at `/#demo`.

**If Lovable asks about `index.css`:** keep its three Tailwind lines (`@tailwind base; @tailwind components; @tailwind utilities;`). If Lovable's default theme colours show through on `body`, add this to `src/index.css`:

```css
html, body, #root { min-height: 100%; background: #F5F5F7; }
html.dark, html.dark body { background: #121214; }
```

**If Lovable says `darkMode` is missing:** in `tailwind.config.ts`, set `darkMode: ["class"],` at the top level of the exported config.

## 2. SEO: paste into `index.html` `<head>`

Only the landing page should be indexed. The app sets `<meta name="robots">` to `index, follow` on the landing page and `noindex, nofollow` inside the demo (`/#demo`). It also sets `<html lang>`, `<html dir>` and `document.title` per screen. Replace the `<head>` content with:

```html
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
<title>Tec Tha Vital — Hospital OS by Tec Tha</title>
<meta name="description" content="Tec Tha Vital connects your hospital ERP, CRM and WhatsApp: smart OPD queue, billing, TPA claims, pharmacy and one view of every branch." />
<link rel="canonical" href="https://www.tectha.com/" />
<meta name="robots" content="index, follow" />
<meta name="theme-color" content="#121214" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="Tec Tha Consultancy Services" />
<meta property="og:title" content="Tec Tha Vital — Hospital OS by Tec Tha" />
<meta property="og:description" content="One connected system for your hospital, from OPD queue to insurance claim. Built for Indian healthcare rules." />
<meta property="og:url" content="https://www.tectha.com/" />
<meta property="og:image" content="https://www.tectha.com/og-image.png" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="Tec Tha Vital — Hospital OS by Tec Tha" />
<meta name="twitter:description" content="One connected system for your hospital, from OPD queue to insurance claim." />
<meta name="twitter:image" content="https://www.tectha.com/og-image.png" />
<link rel="icon" type="image/png" href="/tectha-logo.png" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    { "@type": "Organization", "name": "Tec Tha Consultancy Services", "url": "https://www.tectha.com", "email": "team@tectha.com",
      "logo": "https://www.tectha.com/tectha-logo.png", "slogan": "Technology That Shapes the Future." },
    { "@type": "SoftwareApplication", "name": "Tec Tha Vital", "alternateName": "Tec Tha Vital — Hospital OS",
      "applicationCategory": "HealthApplication", "operatingSystem": "Web",
      "publisher": { "@type": "Organization", "name": "Tec Tha Consultancy Services", "url": "https://www.tectha.com" },
      "description": "Hospital ERP and CRM layer: OPD queue, clinical decision support, operations, billing, diagnostics, pharmacy, patient engagement and TPA claims." }
  ]
}
</script>
```

Change the canonical and `og:url` to the address the site actually lives on, and create a 1200×630 `public/og-image.png`.

**`public/robots.txt`**

```
User-agent: *
Allow: /
Sitemap: https://www.tectha.com/sitemap.xml
```

**`public/sitemap.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.tectha.com/</loc><changefreq>monthly</changefreq><priority>1.0</priority></url>
</urlset>
```

The demo lives at `/#demo`. Search engines don't index hash fragments, and the page also marks itself `noindex` there.

## 3. Showing it to a doctor (5 minutes)

1. Landing page: pick the doctor's language with the globe selector, then press **Try the demo**.
2. In the dark sidebar, press **Guided tour**. It walks through Owner dashboard → OPD queue → Clinical → Billing → Insurance claims in 5 steps.
3. **Clinical Care** (role Doctor):
   - Change the vitals; the early-warning score updates live.
   - The AI triage list explains its reasoning under **Why** and needs **Mark doctor reviewed**. It is labelled decision support, never a diagnosis.
4. **TPA & Insurance:** claim timers count live against the IRDAI 1-hour and 3-hour limits.
5. **Role → Patient:** the patient's own phone view, with appointment ticket, booking, demo payment and sample report.
6. **Settings → Reset demo data** puts everything back before the next meeting.

## 4. What every control does

| Control | Effect |
|---|---|
| Role select | Changes the menu and home screen (Owner, Doctor, Front desk, Billing, Pharmacist, Patient) |
| Branch select | Filters the queue, beds, bills, stock and roster by Main Hospital / City Branch |
| Language select | Translates the interface; Arabic and Urdu switch to right-to-left |
| Currency select | Converts every amount from INR with fixed demo rates (shown in Settings) |
| Sun / moon / screen | Light, dark or follow the device |
| Patient search | Finds sample patients by name, UHID (TT-…) or ABHA number |
| Undo (in toasts) | Reverts the last action |
| Confirm dialog | Appears before discharge, dismissing a revenue finding, withdrawing consent and resetting data |

## 5. Before any real use

- All data is synthetic. Real deployment needs the Tec Tha Vital backend, consent capture, an audit trail and hosting in India.
- Translations were written for this demo. Have native speakers review them.
- Exchange rates are fixed demo values, not live.
- AI features are illustrative decision support, never diagnosis.

## 6. Preview without Lovable

- `preview.html`: a single self-contained file of the same build. Open it in any browser.
- `preview/`: the same build as a static folder (`index.html` plus `assets/`), for any static host.
