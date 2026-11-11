# BedSynth AI Design System

**Status:** Proposed visual and interaction specification. Tokens are design starting points and should be checked in rendered interfaces for contrast and accessibility before release.

## Design direction

Clinical Modern: calm, precise, and approachable, with white or deep navy foundations, restrained teal actions, cyan information accents, clear data hierarchy, and minimal decorative chrome. Use Inter for interface text and JetBrains Mono for identifiers, seeds, timestamps, and technical values.

## Color tokens

Hex values are initial targets. Text/background pairs must be measured and adjusted to meet WCAG 2.2 AA, including hover, focus, disabled, and chart states.

| Token | Light | Dark | Use |
|---|---:|---:|---|
| `background` | `#FFFFFF` | `#0B1220` | Main page |
| `foreground` | `#0F172A` | `#F8FAFC` | Primary text |
| `surface` | `#FFFFFF` | `#111C2E` | Cards and dialogs |
| `surface-muted` | `#F1F5F9` | `#172438` | Secondary panels |
| `surface-hover` | `#E2E8F0` | `#22324A` | Interactive muted surfaces |
| `border` | `#CBD5E1` | `#334155` | Dividers and outlines |
| `muted` | `#475569` | `#A7B4C6` | Secondary copy |
| `primary` | `#0F766E` | `#5EEAD4` | Primary action/accent |
| `primary-hover` | `#115E59` | `#99F6E4` | Hover action |
| `primary-foreground` | `#FFFFFF` | `#062C2B` | Text on primary |
| `secondary` | `#0891B2` | `#67E8F9` | Secondary accent/data series |
| `focus` | `#0E7490` | `#67E8F9` | Focus ring |
| `success` | `#15803D` | `#4ADE80` | Success state |
| `warning` | `#A16207` | `#FACC15` | Warning state |
| `danger` | `#B91C1C` | `#F87171` | Error/destructive state |
| `info` | `#0369A1` | `#7DD3FC` | Informational state |
| `chart-1` | `#0F766E` | `#5EEAD4` | Occupancy/current |
| `chart-2` | `#0891B2` | `#67E8F9` | Capacity/secondary |
| `chart-3` | `#4F46E5` | `#A5B4FC` | Additional series |
| `chart-4` | `#C2410C` | `#FDBA74` | Additional series |
| `chart-5` | `#7C3AED` | `#C4B5FD` | Additional series |

Semantic status must use both text/icon/shape and color; color alone cannot communicate validity or urgency. Avoid using success green as a general decorative series.

## Typography

- **UI family:** Inter with system sans-serif fallback.
- **Technical family:** JetBrains Mono with monospace fallback.
- **Scale:** 12/16 px caption; 14/20 body-small; 16/24 body; 18/28 lead; 20/28 section title; 24/32 page section; 30/36 page title. Use a consistent weight ladder: 400 regular, 500 medium, 600 semibold, 700 bold.
- Body text should remain readable at browser zoom; avoid long all-caps labels. Numeric data should use tabular numerals where available.

## Spacing, shape, and elevation

- Base spacing unit: 4 px. Common steps: 4, 8, 12, 16, 24, 32, 40, 48, 64 px.
- Control heights: compact 32 px, default 40 px, touch-oriented 44 px minimum target where practical.
- Radius: small 6 px, control 8 px, card 12 px, modal 16 px, pill fully rounded only for short status chips.
- Borders carry most structure. Use subtle elevation for overlays; avoid stacked shadows on every card.
- Content width should suit the task: forms and reading views use a constrained measure; analytics and tables can use the available viewport.

## Components

### Buttons

- Primary: solid teal, one dominant action per region; clear verb label.
- Secondary: neutral surface with border; tertiary: text/ghost for lower emphasis.
- Destructive: danger styling and confirmation for irreversible deletion.
- Include disabled, loading, hover, focus-visible, and pressed states. Loading preserves label context and prevents duplicate submission.

### Cards

- Use cards to group related configuration, status, and summary information, not as decoration around every element.
- Provide a concise heading, optional helper text, and clear action placement. Maintain consistent padding (16–24 px) and border contrast.

### Forms

- Persistent labels above fields; helper/error text associated programmatically with each control.
- Mark required fields and explain units, formats, and defaults. Avoid placeholder-only labels.
- Validate on submit and, where useful, after field completion; preserve entered values on recoverable errors.
- Group related constraints and provide a review summary before generation.

### Tables

- Use semantic column headers, row focus/selection patterns, aligned numeric values, and stable units.
- Provide pagination, visible result count, empty/error states, and clear horizontal overflow behavior on mobile.
- Do not rely on zebra striping alone; maintain adequate row and column boundaries. Keep identifiers monospace only where it helps scanning.

### Modals and dialogs

- Use for focused confirmation or short decision flows, not long configuration pages.
- Trap focus while open, provide accessible name/description, close with Escape when safe, and return focus to the invoking control.
- For destructive actions, name the affected resource and provide a clear cancel path.

### Feedback states

- Loading: describe the active operation and show progress only when known; do not imply percentage accuracy without measurable progress.
- Empty: explain why there is no data and offer the next relevant action.
- Error: state what failed, what input is affected, and a safe next action; provide a correlation reference only when useful.
- Success: confirm saved/generated/exported result and provide a route to inspect it.

## Navigation

Use a persistent primary navigation for Hospitals, Generate, Datasets/History, and Settings as those areas exist. Keep the active location visually and programmatically clear. On narrow screens, use a compact menu with accessible name, expanded state, and keyboard behavior. Avoid exposing advanced features as enabled navigation before they are implemented.

## Responsive breakpoints

Suggested breakpoints: small mobile `<640 px`; tablet `640–1023 px`; desktop `1024–1279 px`; wide desktop `>=1280 px`. These are layout thresholds, not supported-device guarantees. Reflow forms to one column on narrow widths, prioritize core actions, and define table overflow or card-row alternatives. Verify at 320 px width and browser zoom.

## Accessibility standards

- Target WCAG 2.2 AA. Use semantic HTML, logical headings, keyboard-accessible controls, visible focus, sufficient contrast, and no keyboard traps.
- Include skip navigation, clear labels, live announcements for job status, and reduced-motion support.
- Charts require text summaries or data-table alternatives, keyboard discoverability where interactive, readable legends, and non-color encodings where feasible.
- Provide focus order consistent with visual flow and preserve focus through dialogs and route transitions.
- Test manually with keyboard and screen reader plus automated accessibility checks; automated results alone do not establish conformance.

## Chart styling

- Use Recharts for planned web charts with shared theme tokens, explicit units, meaningful axis labels, and clear tooltips.
- Occupancy charts should show occupied and eligible capacity distinctly, with thresholds and exceptional values labeled rather than implied by color alone.
- Keep gridlines low contrast; use direct labels or legends for multiple series. Avoid 3D, excessive gradients, and truncated axes that distort interpretation.
- Include the date range, aggregation cadence, denominator/definition, and synthetic data label near the chart.
- Supply a text summary and table view. In dark theme, verify grid and series contrast independently.

## Motion guidelines

- Use motion only to communicate state changes, hierarchy, or continuity; transitions should be brief and nonessential.
- Honor `prefers-reduced-motion`; avoid pulsing, parallax, and animated chart changes that impede reading.
- Skeletons may indicate layout while loading, but also announce loading status accessibly. Never make animation the only signal of progress or completion.
