# Career Agentic AI Client UI Spec

This README defines the required UI pages for the student experience. The flow is:

1. Landing Page
2. Evidence and Resume Upload
3. Student Constraints Input
4. Agent Loading
5. Explanation Page (Career and Pathway Plan)

## Global Visual Direction

- Style: modern EdTech, minimalist, professional, high-fidelity mockup quality
- Palette: deep navy + electric blue accents, white base surfaces, soft gray shadows
- Typography: sleek sans-serif with strong headline hierarchy
- Components: rounded cards, subtle gradients, clean vector illustration style
- Spacing: uncluttered, generous whitespace, clear visual grouping
- Motion: subtle glow, fade, and progress transitions only

## 1) Landing Page

### Required Content

- Hero headline: "Map Your Career Blueprint"
- One primary CTA button: "Get Started"
- Supporting visual: clean vector illustration of a glowing neural network

### Layout and Behavior

- Single-page hero layout only
- No header, no navigation bar, no login screen, no signup screen
- White background with soft gray shadowed elements
- Navy and electric blue visual accents
- 4K-ready composition and scalable responsive behavior

### Design Notes

- Keep message-first hierarchy: headline, short subtext, CTA
- Use strong contrast for accessibility on CTA and headline
- Keep visual balance between text block and neural illustration

## 2) Evidence and Resume Upload Page

### Required Content

- Top progress indicator showing step progress
- Split-screen layout:
	- Left: "Drag and Drop" PDF resume upload zone
	- Right: form fields for "Project Links" and "Certifications"

### Layout and Behavior

- Left panel should clearly communicate PDF-only support
- Right panel supports multiple links and certification entries
- Include iOS-style toggles for optional metadata/preferences
- Keep the experience professional, clean, and uncluttered

### Design Notes

- Subtle card elevation and restrained color usage
- Modern sans-serif body text and concise helper labels
- Prefer clear status feedback for upload success/failure

## 3) Student Constraints Input Page

### Required Content

- Segmented control for Academic Level:
	- Undergrad
	- Grad
	- Professional
- Interactive slider for "Hours per Week on training"

### Layout and Behavior

- Card-based dashboard layout
- Soft blue accents and modern data-entry patterns
- High-quality glassmorphism effects on key cards
- Inputs should feel interactive and precise (show current values)

### Design Notes

- Keep controls grouped logically: profile context then time constraints
- Ensure sliders are keyboard-accessible and labeled clearly
- Preserve readability despite glass effects

## 4) Agent Loading Page

### Required Content

- Loading screen representing AI processing of submitted student data
- Centered glowing orbital loader as the focal element

### Layout and Behavior

- Minimal screen with consistent style from previous pages
- Subtle animated glow and orbital movement
- Optional short status line (for example: "Analyzing your pathway...")

### Design Notes

- Avoid clutter and keep animation smooth, not distracting
- Maintain deep navy/electric blue accent identity
- Preserve visual continuity with earlier pages

## 5) Explanation Page (Career and Pathway Plan)

### Required Content

- Complex dashboard UI with two major sections:
	- Left column: "Gap Analysis"
		- "Skills Found"
		- "Skills Needed"
	- Right column: timeline-based "Pathway Plan" based on user constraints

### Layout and Behavior

- Reporting-style professional dashboard
- Clean data visualizations for progress and milestones
- Use small green and orange status indicators for state clarity
- Surface clear milestones, dependencies, and estimated durations

### Design Notes

- Emphasize actionable insights over decorative elements
- Ensure the timeline is scannable and easy to follow
- Keep contrast and spacing high for dense information

## Scope Guardrails

- This phase covers only the pages above.
- Do not add authentication flows (no login/signup screens).
- Landing page must remain headerless and focused on a single CTA.

## Suggested Build Order

1. Build Landing Page hero and CTA
2. Build Upload split-screen and progress bar
3. Build Constraints controls and card layout
4. Build Loading state animation screen
5. Build Explanation dashboard and timeline

## Acceptance Checklist

- Landing page contains only headline + CTA + neural illustration
- No header/login/signup in landing experience
- Upload page uses split-screen with drag-drop and form inputs
- Constraints page includes segmented control and both sliders
- Loading page includes centered glowing orbital loader
- Explanation page includes gap analysis + timeline pathway plan
- Visual system is consistent across all pages
