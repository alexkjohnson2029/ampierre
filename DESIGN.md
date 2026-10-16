---
name: AMPierre
description: Schematic in, breadboard out.
colors:
  indigo: "#2f3061"
  indigo-deep: "#23244a"
  indigo-raised: "#3d3e78"
  gold: "#ffe66d"
  gold-soft: "#fff4bf"
  copper: "#b87333"
  copper-deep: "#8a5420"
  silk: "#ffffff"
  silk-muted: "#c9cae6"
  bg: "#f3f3f8"
  card: "#ffffff"
  panel: "#f0f0f7"
  hover-soft: "#e8e8f3"
  board-backdrop: "#dedfeb"
  ink: "#1f2033"
  body-ink: "#3a3c55"
  muted: "#565873"
  line: "#dcdce8"
  line-strong: "#b9bacf"
  control-line: "#8b8ca6"
  warn: "#6e5a00"
  error: "#b3261e"
  area-accent: "#a8601f"
  area-ink: "#1f1d1a"
  area-muted: "#6c675e"
  area-line: "#c6bfb1"
typography:
  display:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", sans-serif"
    fontSize: "34px"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", sans-serif"
    fontSize: "23px"
    fontWeight: 700
    letterSpacing: "-0.015em"
  title:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", sans-serif"
    fontSize: "16px"
    fontWeight: 700
  body:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", sans-serif"
    fontSize: "12px"
    fontWeight: 700
    letterSpacing: "0.07em"
  mono:
    fontFamily: "ui-monospace, Menlo, monospace"
    fontSize: "13px"
    fontWeight: 400
rounded:
  none: "0px"
spacing:
  page-gutter: "32px"
  page-gutter-narrow: "16px"
  card-padding: "20px 22px"
  stack: "18px"
  gap: "10px"
  gap-wide: "14px"
components:
  button:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "8px 14px"
  button-primary:
    backgroundColor: "{colors.indigo}"
    textColor: "{colors.silk}"
    rounded: "{rounded.none}"
    padding: "8px 14px"
  button-primary-hover:
    backgroundColor: "{colors.indigo-deep}"
    textColor: "{colors.silk}"
  button-shell:
    backgroundColor: "{colors.indigo}"
    textColor: "{colors.silk}"
    rounded: "{rounded.none}"
    padding: "5px 10px"
  button-shell-hover:
    backgroundColor: "{colors.indigo-raised}"
    textColor: "{colors.silk}"
  chip:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "5px 10px"
  input:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "9px 11px"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "20px 22px"
  option-selected:
    backgroundColor: "{colors.gold-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "9px 11px"
  tab:
    backgroundColor: "{colors.indigo}"
    textColor: "{colors.silk-muted}"
    rounded: "{rounded.none}"
    padding: "14px 10px"
  tab-active:
    backgroundColor: "{colors.indigo}"
    textColor: "{colors.silk}"
  timeline-pad:
    backgroundColor: "{colors.indigo-deep}"
    textColor: "{colors.silk-muted}"
    rounded: "{rounded.none}"
    padding: "5px 10px"
  timeline-pad-done:
    backgroundColor: "{colors.copper-deep}"
    textColor: "{colors.silk}"
  timeline-pad-active:
    backgroundColor: "{colors.gold}"
    textColor: "{colors.indigo}"
  tooltip:
    backgroundColor: "{colors.indigo-deep}"
    textColor: "{colors.silk}"
    rounded: "{rounded.none}"
    padding: "10px 12px"
---

# Design System: AMPierre

## Overview

**Creative North Star: "The Purple Circuit Board"**

The app is a finished circuit board built around the student's work. The shell (header, build timeline, tab bar) is indigo solder mask carrying white silkscreen type; whatever is active or selected is a gold pad; copper is the trace that rules sections off and that the build steps travel along. Inside the shell, work happens on calm, faintly lavender-grey ground with white cards, so the breadboard drawing and the parts lists read without competition.

The density is a working tool's: compact controls, 13 to 15px text, tight 10 to 18px gaps, everything square. The palette is tinted from the logo's indigo, so neutrals are cool and faintly violet rather than flat grey. It refuses the grey SaaS page with one accent: colour carries meaning (where you are, what is done, what needs attention), not decoration.

Two drawing surfaces sit inside the world but keep their own palettes: the breadboard renderer draws a realistic white board with red and blue rails, real resistor bands and wire colours, and the schematic canvas uses conventional schematic inks. The world frames them; it never recolours them.

**Key Characteristics:**
- Indigo solder-mask shell, white silkscreen type, copper rule along its edge.
- Gold is a pad: active tab, current build step, selected option, focus on the shell.
- Copper is a trace: section rules, the timeline track, done steps, featured emphasis.
- Light lavender-grey work ground with white, square, thin-bordered cards.
- Square corners everywhere; depth from colour and rules, not shadows.

## Colors

A two-register palette: a dark indigo shell and a light cool work area, joined by gold for state-of-attention and copper for structure.

### Primary
- **Solder-Mask Indigo** (indigo): the logo ground and the shell: header, timeline band, tab bar, primary buttons, step numbers, the default focus ring on light ground. Fixed by the logo; not to be retuned.
- **Mask in Shadow** (indigo-deep): pressed and hover state of primary buttons, unreached timeline pads, the tooltip body.
- **Mask Catching Light** (indigo-raised): hover on shell controls and tabs, dividers between tabs and above the timeline strip.

### Secondary
- **ENIG Gold** (gold): the logo glyph and the active/selected signal on the shell: active tab bar and number, the current timeline pad, the scrubber thumb, the bottom bar of an active segmented button, focus rings and hover borders on indigo, text selection. Fixed by the logo.
- **Pad Glow** (gold-soft): the light-ground version of selected: a chosen part option, the active schematic tool. Also the warning panel's fill.

### Tertiary
- **Copper Trace** (copper): non-text structure only: the 3px rule under the header and above the tab bar and timeline, the timeline track and pad outlines, section rules on the About page, the outline of featured chips and badges.
- **Soldered Copper** (copper-deep): build steps already done; text on the featured badge.

### Neutral
- **Silkscreen White** (silk): primary type on indigo.
- **Faded Silkscreen** (silk-muted): secondary type on indigo (7.8:1), idle tabs and pads.
- **Lavender Work Ground** (bg): page background under the work.
- **Card White** (card): cards, inputs, buttons, the schematic canvas.
- **Tool Panel** (panel): schematic tool and property panels, project cards.
- **Hover Wash** (hover-soft): row and list hover on light ground.
- **Board Backdrop** (board-backdrop): the well the white breadboard sits in, so it reads as an object.
- **Ink** (ink), **Body Ink** (body-ink), **Muted Ink** (muted, 6.9:1 on white): heading, long-form and secondary text.
- **Hairline** (line), **Strong Hairline** (line-strong), **Control Edge** (control-line, 3.3:1 on white): dividers, card and button borders, form-control edges.

### State
- **Amber Warn** (warn) on Pad Glow with a gold border: the "Check these" panel and pinout warnings.
- **Fault Red** (error): errors and unconnected-pin problems.

### Drawing surfaces (outside the shell palette)
- **Schematic canvas**: parts in schematic blue (#1f3c88), wires and junctions green (#2e7d32), net labels plum (#8a2a5a), loose pins red (#c62828), selection in Schematic Copper (area-accent) with area-ink and area-muted for reference and value text, grid dots #c3c4d8.
- **Breadboard renderer** (`static/breadboard.js`): its own realistic colours (off-white board, red and blue rails, true resistor bands, wire colours). The About page primer reuses that board palette. Do not map these to shell tokens.

### Named Rules
**The Gold Pad Rule.** Gold means active or selected, nothing else. If an element is not the current tab, step, choice or focus, it is not gold.

**The Copper Trace Rule.** Featured or emphasised content uses copper, never gold. Copper is structure and emphasis; it is never body text on light ground.

**The Mint Is Retired Rule.** No mint or green tints in the UI chrome. Green exists only as schematic wire ink and in the realistic board.

## Typography

**Display Font:** system UI stack (ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif)
**Body Font:** the same stack
**Label/Mono Font:** ui-monospace, Menlo, monospace for netlists, hole coordinates, pin numbers, key bindings and wire steps

**Character:** Plain, legible, bench-practical. Hierarchy comes from weight and size, not a second family.

**Open decision:** a sourced silkscreen-style display face for the wordmark and headings is proposed but not decided; it awaits the owner's approval to download a font. Until then the system stack is the system, and no surface should introduce a display face on its own.

### Hierarchy
- **Display** (700, 34px, 1.15, -0.02em; 27px under 860px): About page hero only.
- **Headline** (700, 23px, -0.015em): the wordmark in the header; About credit heading at 22px.
- **Title** (700, 16px): card headings, paired with a square indigo step number in gold.
- **Body** (400, 15px/1.55): default. Long-form About text 14.5 to 17px, held to 64ch.
- **Label** (700, 12px, 0.07em, uppercase, muted): headings of panels inside a card (Parts, Build order, Check these). On the About page h3 drops the uppercase and becomes a 19px section heading.
- **Mono** (13px): netlist textarea, hole lists, pin tables.

### Named Rules
**The Silkscreen Weight Rule.** On the shell, white is for the current thing and headings; secondary text drops to silk-muted, never to a lower weight or smaller size alone.

## Layout

A single centred column (max 1480px; About 1080px) with 32px gutters (16px under 900px), framed by a full-width indigo header at the top and a fixed indigo tab bar at the bottom (body reserves 76px for it). Content stacks in cards 18px apart with 20px by 22px padding. Inside the Board card: the board in its backdrop well, the indigo timeline band directly beneath, then a two-column parts/build-order grid (1fr / 1.4fr) that stacks under 900px. The schematic editor is a three-column tool / canvas / properties grid (190px / fluid / 240px), dropping to two columns at 1100px and one at 700px. Readable text is held to 60 to 68ch.

## Elevation & Depth

Flat. Depth comes from the two registers (indigo shell against light work) and from copper rules, not from shadows. Two exceptions are functional: the floating tooltip, which must lift off the board, and inset bars used as pad marks.

### Shadow Vocabulary
- **Tooltip lift** (`box-shadow: 0 12px 30px rgba(0, 0, 0, 0.3)`): the hover tooltip only.
- **Pad bar** (`box-shadow: inset 0 -4px 0 #ffe66d` on tabs, `inset 0 -3px 0` on segmented buttons): marks the active tab or segment as a gold pad.
- **Hairline badge** (`box-shadow: inset 0 0 0 1px` copper): the featured-example badge outline.

### Named Rules
**The Flat Board Rule.** Cards and panels never take drop shadows. Something floats only if it literally floats over the work (the tooltip).

## Shapes

Square everywhere: a global zero radius is enforced on every element. Edges are 1px hairlines in line or line-strong; structural boundaries are 3px copper rules (header bottom, tab bar top, timeline top, About section tops). Number badges are 20px squares. The one sanctioned curve is the busy spinner ring, which is round because it rotates; the breadboard drawing's own holes and leads follow the physical board.

## Components

### Buttons
Compact and square, like labelled switches.
- **Shape:** square (0px), 1px border.
- **Default:** white with a strong-hairline border, 14px text, 8px by 14px; hover turns the border indigo.
- **Primary:** indigo fill, white 600-weight text; hover deepens to indigo-deep.
- **On the shell:** transparent with a 40% white border and white text; hover fills indigo-raised with a gold border. Focus rings turn gold on indigo.
- **Link:** borderless, indigo underlined text at 13px.
- **Disabled:** 45% opacity.

### Chips
- **Style:** a small default button (5px by 10px, 13px) used for example circuits.
- **Featured:** copper border and 600-weight ink text; may carry an uppercase copper "Example" badge with a 1px copper inset outline.

### Segmented control
Joined square buttons in a strong-hairline frame. Idle segments are muted text on white; the active segment is indigo with white text and a 3px gold bottom bar.

### Cards / Containers
- **Corner Style:** square.
- **Background:** card white on the lavender ground; tool panels and project cards use panel.
- **Shadow Strategy:** none (see Elevation).
- **Border:** 1px line-strong; project and featured blocks use a 2 to 3px copper top rule instead.
- **Internal Padding:** 20px by 22px.

### Inputs / Fields
- **Style:** white, 1px control-line border, 9px by 11px, 14px text; label above in 13px muted.
- **Focus:** 2px indigo outline inset by 2px.
- **Error:** message below in error red at 13px.

### Part options
List rows with a hairline border; hover turns the border indigo; the selected option takes an indigo border and gold-soft fill.

### Navigation (tab bar)
Fixed to the bottom, full width, indigo with a 3px copper top rule. Tabs share the width equally, 15px 600-weight in silk-muted with an outlined copper number square. Hover lifts to indigo-raised. The active tab goes white with a 4px gold bottom bar and a solid gold number square. Subtitles hide under 900px.

### Build timeline (signature)
An indigo band under the board with a 3px copper top rule. The build is a copper trace: a 2px copper line runs through a scrolling strip of square pads. Unreached pads are indigo-deep with a copper outline and muted text; done pads are solid copper-deep with white text; the current pad is solid gold with indigo text. The scrubber is a 3px copper track with a square gold thumb. Shell buttons sit in its header.

### Tooltip
Indigo-deep panel with a 2px gold top edge, white title, silk-muted secondary rows, 13px text, max 340px; carries a white inset for pinout drawings.

## Do's and Don'ts

### Do:
- **Do** put the shell (header, timeline, tab bar) on indigo (#2f3061) with white silkscreen text and a 3px copper rule on its inner edge.
- **Do** mark the current tab, step, selection and shell focus in gold (#ffe66d), and use gold-soft (#fff4bf) for selection on light ground.
- **Do** use copper (#b87333) for rules, tracks, outlines and featured emphasis.
- **Do** keep every corner square and every card border a 1px hairline.
- **Do** let the breadboard and schematic drawings keep their own realistic colours inside the light work area.
- **Do** keep secondary text on indigo at silk-muted (#c9cae6) and on light ground at muted (#565873) to hold contrast.

### Don't:
- **Don't** use gold for anything that is not active or selected; featured and emphasised content is copper.
- **Don't** reintroduce mint or any green tint into the interface chrome.
- **Don't** retune the logo indigo or gold.
- **Don't** round corners on controls, cards or panels.
- **Don't** add drop shadows to cards or panels; only the floating tooltip lifts.
- **Don't** use copper as text colour on light ground; it is for non-text structure (copper-deep carries text).
- **Don't** recolour the breadboard rails, resistor bands or wire colours to match the shell.
- **Don't** introduce a display typeface until the owner approves the silkscreen font decision.
