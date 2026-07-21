# Verity — Executive Pagers

Self-contained, single-file HTML collateral for **Verity** (the Enterprise Eval
Observability Framework in this repo), aimed at an executive audience. Technical
detail is kept high-level. Open any file directly in a browser — no build step;
web fonts load from Google Fonts, everything else is inline. Light + dark theme
toggle persists in `localStorage` (`aibc-theme`); no external data or tracking.

## Deliverables

| File | Format | Audience | Contents |
|---|---|---|---|
| `verity-executive.html` | **Combined one-pager** (two tabs) | Executive / leadership | Both decks below, condensed to a single screen each and switchable in-page. **Primary deliverable.** |
| `verity-executive.pptx` | **2-slide deck** | Executive / leadership | PowerPoint of the combined pager — slide 1 = Executive Brief, slide 2 = Technical Overview. Same dark aesthetic. |
| `verity-executive-narrative.html` | Slider deck (7 slides) | Executive / board | The narrative arc — problem → solution → how it works → business value → competitive landscape. |
| `verity-technical-overview.html` | Slider deck (6 slides) | Technical leadership | High-level technical view — what Verity offers, features, UX across features, benefits. |

The slider decks navigate with **← / →**, on-screen arrows, dot nav, or swipe.
The combined pager switches decks via the header tabs (or **← / →**).

## Content outline

**Slider 1 — executive narrative**
1. Problem statement — agents shipped without proof they're safe
2. Solution statement — stress-test → score → gate → monitor → self-heal
3. How it works — the five-stage pipeline (technical, high-level)
4. Business value proposition — ship faster, reduce risk, audit-ready, lower cost
5. Competitive landscape — the only closed loop (eval + observability + self-heal)

**Slider 2 — high-level technical overview**
1. What Verity offers — architecture at a glance
2. Verity features — the eight surfaces
3. User experience across all features — one journey, end to end
4. Verity benefits — provider-agnostic, immutable, idempotent, standards-native

## Design

An "audit-instrument" aesthetic: deep-ink canvas, warm-paper text, Verity's own
scoring colour language (signal-green = verified, gold = gate, coral = breach),
Fraunces display serif + Geist body. The narrative deck accents green; the
technical deck and the combined pager's Technical tab accent sky-blue.

## Versioning

These are **documentation-only** — they ship no runtime change. Land them on a
`docs/` (or `chore/`) branch so the `version-bump` workflow skips auto-tagging.
