---
name: Obsidian Keynote
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#3a3939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1c1b1b'
  surface-container: '#201f1f'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353534'
  on-surface: '#e5e2e1'
  on-surface-variant: '#c4c7c8'
  inverse-surface: '#e5e2e1'
  inverse-on-surface: '#313030'
  outline: '#8e9192'
  outline-variant: '#444748'
  surface-tint: '#c6c6c7'
  primary: '#ffffff'
  on-primary: '#2f3131'
  primary-container: '#e2e2e2'
  on-primary-container: '#636565'
  inverse-primary: '#5d5f5f'
  secondary: '#c8c6c5'
  on-secondary: '#303030'
  secondary-container: '#474746'
  on-secondary-container: '#b7b5b4'
  tertiary: '#ffffff'
  on-tertiary: '#2f3131'
  tertiary-container: '#e2e2e2'
  on-tertiary-container: '#636565'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e2e2e2'
  primary-fixed-dim: '#c6c6c7'
  on-primary-fixed: '#1a1c1c'
  on-primary-fixed-variant: '#454747'
  secondary-fixed: '#e4e2e1'
  secondary-fixed-dim: '#c8c6c5'
  on-secondary-fixed: '#1b1c1c'
  on-secondary-fixed-variant: '#474746'
  tertiary-fixed: '#e2e2e2'
  tertiary-fixed-dim: '#c6c6c7'
  on-tertiary-fixed: '#1a1c1c'
  on-tertiary-fixed-variant: '#454747'
  background: '#131313'
  on-background: '#e5e2e1'
  surface-variant: '#353534'
typography:
  display-xl:
    fontFamily: Inter
    fontSize: 72px
    fontWeight: '600'
    lineHeight: 76px
    letterSpacing: -0.025em
  display-xl-mobile:
    fontFamily: Inter
    fontSize: 40px
    fontWeight: '600'
    lineHeight: 44px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 56px
    fontWeight: '600'
    lineHeight: 60px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '500'
    lineHeight: 34px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '500'
    lineHeight: 26px
    letterSpacing: -0.01em
  body-md:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: 0em
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0em
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.12em
  data-mono:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0.02em
rounded:
  sm: 0.5rem
  DEFAULT: 1rem
  md: 1.5rem
  lg: 2rem
  xl: 3rem
  full: 9999px
spacing:
  stage-gutter: 2rem
  stage-margin: 3rem
  card-padding: 1.5rem
  dock-padding: 0.75rem
  element-gap: 1rem
  factor-gap: 0.5rem
---

## Brand & Style

The design system projects the gravitas and cinematic reverence of an elite flagship keynote presentation staged in total darkness. Designed for high-velocity, precision AI video editing, the interface eliminates all extraneous digital noise to evoke supreme technological confidence, mystery, and optical craftsmanship.

The visual direction merges **Monochrome Glassmorphism** with **Atmospheric Keynote Stage Minimal**. The canvas exists in an infinite void of deep black `#050505`, punctuated only by sheets of monolithic frosted glass and an immense, slowly breathing silver-white radial aurora. The interaction language feels tactile yet weightless: floating glass sheets, pristine hair-thin light refractions, and stark optical contrast where stark white emerges from absolute darkness.

## Colors

The palette adheres to an uncompromising, strictly achromatic gamut. Absolutely zero chroma or saturated hue is permitted. Visual depth, hierarchy, and affordance are produced entirely through luminosity and progressive opacity stops.

- **Base Void (`#050505`)**: The core canvas tone, absorbing ambient light.
- **Stage Tier 1 (`#0d0d0d`)**: Recessed canvas wells, timeline tracks, and drawer tracks.
- **Stage Tier 2 (`#141414`)**: Secondary card backgrounds and inactive panels.
- **Border / Structure (`#262626`)**: Hairline dividers, inactive tracks, and structural bounds.
- **Pure Peak (`#ffffff`)**: Highest emphasis, primary typography, high-potency action states.
- **Liquid Glass Fill (`rgba(255, 255, 255, 0.05)`)**: The standard refractive card body.
- **Glass Specular Border (`rgba(255, 255, 255, 0.10)`)**: Top-lit hairline specular highlights.
- **Atmospheric Bloom (`radial-gradient(ellipse at 50% 0%, rgba(255, 255, 255, 0.08) 0%, rgba(255, 255, 255, 0) 70%)`)**: An expansive monochrome silver field positioned deep behind glass layers, pulsing with subtle breathing cycles.

## Typography

Typography utilizes geometric, optical precision set in Inter, with numbers, counters, and timeline readouts set in a crisp monospace variant.

- **Scale & Impact**: Headlines command the viewport at 56px to 72px with negative letter tracking (`-0.02em` to `-0.025em`) to create dense, theatrical authority reminiscent of keynote projection slides.
- **Reading Layer**: Body text is fixed at 15px with `rgba(255, 255, 255, 0.6)` for smooth legibility against dark glassy surfaces without introducing glare.
- **Metadata Layer**: Technical labels, factor meters, and status cues are rendered in strictly uppercase 11px with expansive `0.12em` tracking at `rgba(255, 255, 255, 0.4)`.

## Layout & Spacing

The layout is built upon an expansive fluid stage architecture that leaves ample breathing room around floating tool clusters and video viewports.

- **Desktop (1440px+)**: 12-column dynamic fluid grid flanked by 48px keynote stage margins. Panels float as independent glassy sheets over the background radiance bloom.
- **Tablet (768px - 1439px)**: Tool docks collapse into floating bottom bars; side utility panels transition into sliding glass overlay drawers.
- **Mobile (below 768px)**: Viewports scale to full-width; floating glass panels pin to screen edges with 16px lateral safety margins, reducing vertical padding to maintain spatial density.

## Elevation & Depth

Depth in the design system is produced via optical transparency and refraction rather than opaque shadow stacking.

- **The Deep Void (Level 0)**: Background `#050505` anchored with a massive radial silver gradient simulating an overhead theatre spotlight or breathing aurora (`filter: blur(120px)`).
- **Recessed Insets (Level 1)**: `#0d0d0d` background, inset border `1px solid rgba(255,255,255,0.03)` for waveform wells and clip timelines.
- **Floating Sheets (Level 2)**: The primary keynote panels. 
  - Fill: `rgba(255, 255, 255, 0.05)`
  - Filter: `backdrop-filter: blur(32px) saturate(140%)`
  - Border: `1px solid rgba(255, 255, 255, 0.10)`
  - Hover Transition: An inner glow blooms smoothly into `box-shadow: inset 0 0 24px rgba(255, 255, 255, 0.08), 0 20px 40px rgba(0, 0, 0, 0.6)`.
- **Top Overlays & Modals (Level 3)**: Fill `rgba(255, 255, 255, 0.08)`, blur `48px`, border `1px solid rgba(255, 255, 255, 0.18)`.

## Shapes

The design balances generous structural panel radiuses with strict pill-shaped interactive components.

- **Glass Cards and Viewports**: Large structural sheets utilize a consistent 24px (`1.5rem`) border radius, giving them the presence of heavy, precision-milled glass slabs.
- **Interactive Controls**: Buttons, badges, factor chips, and tool selection pills adopt complete pill curvature (`border-radius: 9999px`).
- **Data Visualizers**: Audio waveforms, factor track bars, and progress nodes retain rounded caps to sustain an organic, fluid tone.

## Components

### Buttons
- **Primary Action**: Solid pure white (`#ffffff`) pill with stark `#050505` text (weight 600). Hover produces a subtle outer silver haze (`box-shadow: 0 0 20px rgba(255, 255, 255, 0.35)`). Active scales down slightly (`transform: scale(0.98)`).
- **Ghost Glass Pill**: Background `rgba(255, 255, 255, 0.05)`, backdrop blur 16px, border `1px solid rgba(255, 255, 255, 0.12)`, text `#ffffff`. Hover elevates background to `rgba(255, 255, 255, 0.10)`.

### Factor Meters & Score Rings
- **Factor Meter**: Horizontal track in `#141414` with a 4px height; active fill is a gradient from `rgba(255, 255, 255, 0.4)` to pure `#ffffff`. Accompanying indicator is an 11px uppercase label with trailing monospace numeric readout.
- **Score Ring**: Circular SVG meter with background ring `rgba(255, 255, 255, 0.08)` and foreground stroke `#ffffff` with a subtle drop-glow. Center metric is rendered in bold 24px Inter.

### Audio Waveforms
- Displayed as a continuous array of 2px wide vertical bars spaced by 2px. Non-active amplitude renders at `rgba(255, 255, 255, 0.15)`; played amplitude reflects solid `#ffffff`. Scrub line is an ultra-fine 1px `#ffffff` vertical line with a 4px glowing halo.

### Input Fields & Search Bars
- Glass pill or 16px rounded shell with fill `rgba(255, 255, 255, 0.03)` and border `1px solid rgba(255, 255, 255, 0.08)`. Focus states trigger an expansive white inner-reflection line and soft silver outer glow without color tinting.

### Timeline & Floating Dock
- Floating glass dock anchored above the bottom stage edge. Houses playback buttons, clipping tools, and keyframe selectors encased in a singular 32px-blur floating glass capsule.