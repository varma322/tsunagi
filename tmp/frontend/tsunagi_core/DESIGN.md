---
name: Tsunagi Core
colors:
  surface: '#131315'
  surface-dim: '#131315'
  surface-bright: '#39393b'
  surface-container-lowest: '#0e0e10'
  surface-container-low: '#1c1b1d'
  surface-container: '#201f22'
  surface-container-high: '#2a2a2c'
  surface-container-highest: '#353437'
  on-surface: '#e5e1e4'
  on-surface-variant: '#c7c4d7'
  inverse-surface: '#e5e1e4'
  inverse-on-surface: '#313032'
  outline: '#908fa0'
  outline-variant: '#464554'
  surface-tint: '#c0c1ff'
  primary: '#c0c1ff'
  on-primary: '#1000a9'
  primary-container: '#8083ff'
  on-primary-container: '#0d0096'
  inverse-primary: '#494bd6'
  secondary: '#b9c8de'
  on-secondary: '#233143'
  secondary-container: '#39485a'
  on-secondary-container: '#a7b6cc'
  tertiary: '#4edea3'
  on-tertiary: '#003824'
  tertiary-container: '#00885d'
  on-tertiary-container: '#000703'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e1e0ff'
  primary-fixed-dim: '#c0c1ff'
  on-primary-fixed: '#07006c'
  on-primary-fixed-variant: '#2f2ebe'
  secondary-fixed: '#d4e4fa'
  secondary-fixed-dim: '#b9c8de'
  on-secondary-fixed: '#0d1c2d'
  on-secondary-fixed-variant: '#39485a'
  tertiary-fixed: '#6ffbbe'
  tertiary-fixed-dim: '#4edea3'
  on-tertiary-fixed: '#002113'
  on-tertiary-fixed-variant: '#005236'
  background: '#131315'
  on-background: '#e5e1e4'
  surface-variant: '#353437'
typography:
  display:
    fontFamily: Geist
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Geist
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-md:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  gutter: 24px
  margin-safe: 32px
---

## Brand & Style

The design system is engineered for technical precision, reliability, and developer-centric efficiency. It adopts a **Modern Corporate** aesthetic with **Minimalist** and **Glassmorphic** influences, prioritizing information density and structural clarity.

The interface should feel like a high-performance tool: calm, focused, and unobtrusive. It utilizes deep charcoal tones to reduce eye strain during long sessions, punctuated by vibrant functional accents that guide the user's attention to critical actions and system statuses.

**Key Visual Principles:**
- **Subtlety over Ornamentation:** Use borders and tonal shifts instead of heavy shadows to define structure.
- **Intentional Friction:** Use vibrant indigo only for primary actions and state changes.
- **Technical Rigor:** Alignment and spacing must follow a strict mathematical rhythm to reflect the platform's reliability.

## Colors

The palette is optimized for a sophisticated dark-mode experience. The primary background uses a near-black neutral to provide maximum contrast for text while maintaining a premium feel.

- **Primary (Indigo):** Reserved for primary buttons, active navigation states, and key progress indicators.
- **Neutrals (Zinc/Slate):** Used for the structural framework. Surface levels are defined by shifting from `#09090b` (base) to `#18181b` (cards/modals).
- **Functional Accents:** Emerald is used exclusively for "Connected" or "Synced" states. Amber is used for "Rate Limited" or "Pending" syncs.
- **Borders:** Use low-contrast zinc borders (`#27272a`) to define regions without creating visual noise.

## Typography

This design system uses a dual-font strategy to balance character and legibility. **Geist** provides a technical, sharp edge for headings and UI labels, while **Inter** ensures that long-form data (like SMS logs and API documentation) remains highly readable.

**Usage Guidelines:**
- **Headlines:** Use Geist with tighter letter spacing for a compact, modern look.
- **Data Display:** Use `body-md` for standard table cells. 
- **Monospace:** Use JetBrains Mono for API keys, phone numbers, and log snippets to ensure character distinction (e.g., 0 vs O).
- **Contrast:** Maintain a minimum 4.5:1 contrast ratio. Secondary text should use the Slate (`#94a3b8`) color.

## Layout & Spacing

The layout follows a **Fluid Grid** model with fixed maximum widths for content readability. The system is built on a 4px baseline grid to ensure all elements align perfectly.

- **Desktop:** 12-column grid with 24px gutters. Sidebars should be fixed-width (240px-280px) with a glassmorphic background blur (20px).
- **Tablet:** 8-column grid with 16px gutters. Sidebars collapse into an overlay.
- **Mobile:** 4-column grid with 16px margins.
- **Density:** Use `md` (16px) spacing for general layout padding, but drop to `sm` (8px) for dense data tables and property lists.

## Elevation & Depth

Depth is conveyed through **Tonal Layering** and **Glassmorphism** rather than traditional shadows. This creates a sophisticated, "stacked" interface feel.

- **Level 0 (Base):** Deepest layer (`#09090b`). Used for the main application background.
- **Level 1 (Surface):** Raised layer (`#121214`). Used for sidebar backgrounds and secondary panels.
- **Level 2 (Container):** Primary interactive layer (`#18181b`). Used for cards, table headers, and input fields.
- **Glassmorphism:** Apply to sidebars and navigation headers using `backdrop-filter: blur(20px)` and a 10% opacity white border to simulate light catching the edge of a pane.
- **Shadows:** Only used for floating elements (modals, dropdowns). Use a 3-layer diffused shadow: `0 10px 15px -3px rgba(0, 0, 0, 0.5), 0 4px 6px -2px rgba(0, 0, 0, 0.25)`.

## Shapes

The shape language is "Soft-Modern." It avoids the playfulness of fully rounded pills while providing more approachability than sharp 0px corners.

- **Standard Radius (8px):** Applied to buttons, input fields, and small cards.
- **Large Radius (16px):** Applied to main dashboard containers and modals.
- **Interactive States:** On hover, interactive elements do not change radius; they only shift in background luminosity or border color brightness.

## Components

### Buttons
- **Primary:** Solid Indigo (`#6366f1`) with white text. 8px radius.
- **Secondary:** Transparent background with a Zinc border (`#27272a`). Subtle white hover state.
- **Ghost:** No border or background. Used for navigation items and low-priority actions.

### Data Tables
- **Header:** Zinc (`#18181b`) background, Geist medium weight labels, bottom border only.
- **Rows:** Subtle hover highlight (`#1c1c1f`). SMS logs should use a monospaced font for the "From/To" columns.
- **Status Indicators:** 8px solid circles (Emerald/Amber/Red) followed by a Geist label.

### Input Fields
- **Default:** Dark background (`#09090b`), Zinc border, 8px radius. 
- **Focus:** Primary Indigo border with a subtle 2px indigo outer glow (low opacity).
- **Labels:** Always positioned above the field in `label-md` Geist.

### Chips/Badges
- **Status Badges:** Low-opacity background of the status color (e.g., 10% Emerald) with a full-opacity text color for the label. Rounded-full (pill) style.

### Cards
- **Construction:** Surface background (`#18181b`), 1px solid Zinc border (`#27272a`), 12px-16px padding. 
- **Header:** Integrated title with an optional "More" icon menu in the top right.