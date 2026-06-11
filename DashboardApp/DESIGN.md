# Dashboard Design System — "Egg" Theme

The monitoring dashboard (`DashboardApp/`) uses a warm, light, editorial theme called
**Egg**, inspired by the clean look of [jobs.scalefox.ai](https://jobs.scalefox.ai).
It replaced the previous dark **"Obsidian Gold"** theme.

The stylesheet is **token-driven**: every component reads CSS custom properties from
`:root` in `static/css/styles.css`, so the whole look can be retuned by editing the
token block — you rarely need to touch individual components.

---

## At a glance

| Aspect | Before (Obsidian Gold) | After (Egg) |
|---|---|---|
| Mood | Dark, glossy, techy | Light, warm, editorial / clean |
| App background | `#09080c` (near-black) | `#fafaf7` (warm off-white paper) |
| Cards | Dark `#141118` + glow | White `#ffffff` + hairline border + soft shadow |
| Accent | Gold `#c9a847` | Teal signal `#0d9488` |
| Body text | Light on dark | `#0a0a0a` ink on light |
| Body font | Syne | Inter |
| Heading font | Syne | Raleway |
| Big stat numbers | JetBrains Mono | Instrument Serif (e.g. **928 / 45,320 / 100%**) |

---

## Color tokens (`:root` in `static/css/styles.css`)

The original variable **names were kept** (e.g. `--gold`) for compatibility, but their
**values now hold the Egg palette**. `--gold` is the teal signal accent.

| Token | Value | Role |
|---|---|---|
| `--bg-primary` | `#fafaf7` | warm off-white app background (egg "ground") |
| `--bg-secondary` | `#f3f1ec` | sidebar / panels (egg "powder") |
| `--bg-card` | `#ffffff` | clean white cards |
| `--bg-card-hover` | `#f7f5f0` | card hover |
| `--bg-input` | `#ffffff` | inputs |
| `--gold` | `#0d9488` | **teal signal accent** (name kept) |
| `--gold-dim` | `#0b7d72` | darker teal |
| `--gold-bright` | `#14b8a6` | brighter teal |
| `--gold-glow` | `rgba(13,148,136,0.12)` | soft teal tint |
| `--gold-border` | `rgba(13,148,136,0.28)` | teal border |
| `--text-primary` | `#0a0a0a` | obsidian ink |
| `--text-secondary` | `#75716a` | gravel (labels) |
| `--text-muted` | `#a8a59c` | fog (subtle text) |
| `--border-color` | `#e3e1da` | hairline border |
| `--success` | `#15803d` | green |
| `--warning` | `#b45309` | amber |
| `--danger` | `#dc2626` | red |
| `--accent-blue` | `#0447ff` | secondary blue accent |

Shadows are soft and editorial (e.g. `--shadow-md: 0 8px 24px -8px rgba(10,10,10,0.12)`)
instead of heavy black glows.

---

## Typography

Loaded from Google Fonts in `templates/index.html`:

```
Inter (400–700) · Raleway (500–800) · Instrument Serif · JetBrains Mono (400–600)
```

| Token | Font | Used for |
|---|---|---|
| `--font-primary` | Inter | body text, default UI |
| `--font-display` | Raleway | page titles, section titles, card headings, logo, modal headings |
| `--font-serif` | Instrument Serif | big hero stat numbers (snapshot cards) |
| `--font-mono` | JetBrains Mono | data values, KPIs, timestamps, micro-labels |

---

## What changed in code

Only two files were touched — **no HTML structure or JS logic changed**, purely visual:

1. **`static/css/styles.css`**
   - Rewrote the `:root` token block (palette, fonts, shadows, radii) to the Egg system.
   - Softened the body film-grain overlay and added font smoothing.
   - Applied `--font-display` to `.page-title`, `.section-title`, `.card-title` area,
     `.logo-label`, and `.modal-header h2`; applied `--font-serif` to `.snapshot-number`.
   - Remapped ~70 scattered dark-theme literals to the light theme:
     - gold glows `rgba(201,168,71,*)` → teal `rgba(13,148,136,*)`
     - white-on-dark highlights `rgba(255,255,255,*)` → faint dark hairlines `rgba(10,10,10,*)`
     - old neon green `rgba(52,208,88,*)` → `rgba(21,128,61,*)`
     - old danger `rgba(224,95,95,*)` → `rgba(220,38,38,*)`
     - heavy black shadows/scrims softened to light editorial values
     - dark button text `#08070b` → `#ffffff` on teal buttons

2. **`templates/index.html`**
   - Swapped the Google Fonts link (Syne/JetBrains Mono → Inter/Raleway/Instrument Serif/JetBrains Mono).
   - Bumped the CSS/JS cache-bust version (`?v=14` → `?v=15`).

> Cache-bust note: when you change `styles.css` or `dashboard.js`, bump the `?v=` query
> string on both `<link>` and `<script>` tags in `index.html` so browsers fetch the new file.

---

## How to view it

```bash
cd DashboardApp
python app.py          # serves on http://127.0.0.1:5050  (override with DASHBOARD_PORT)
```

Then open <http://127.0.0.1:5050/>. Hard-refresh (Ctrl+Shift+R) if you still see the old
theme from cache. Credentials are loaded from `Scrapers/.env`; the dashboard reads live
data from Supabase with a local filesystem fallback.

---

## Retuning the theme later

- **Change the accent color:** edit `--gold*` tokens in `:root`.
- **Change backgrounds / paper warmth:** edit `--bg-*` tokens.
- **Change fonts:** edit `--font-*` tokens and the Google Fonts `<link>` in `index.html`.
- Then bump the `?v=` cache-bust version in `index.html`.
