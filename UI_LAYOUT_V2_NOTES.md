# UI Layout v2 — structural redesign

This update changes page structure and navigation, not only colors.

## What changed

- Replaced the persistent left sidebar with a full-width, sticky top navigation. Primary destinations are New scan, Reports, History, and AI models; system status remains accessible from the header.
- Replaced the large marketing-style hero and orbital illustration with an operational workspace header, current local-AI health, and four real summary metrics based on API data.
- Rebuilt the scan composer into a single focused panel: URL input and launch action, clear target-policy message, four selectable testing cards, and a separate workflow strip.
- Added direct, visible detail for each pillar using the checks already represented in this project; this is explanatory UI and does not claim all checks run successfully on every target.
- Moved runtime readiness and recent scans into two practical work panels below the scan composer. Tool availability remains distinct from successful execution.
- Extended typography and spacing rules to the existing History, Reports, Progress, and AI Models pages for more consistent readability.
- Added responsive behavior for tablet/mobile navigation, pillar cards, URL entry, scan history and tool readiness.

## Files changed

- `frontend/src/App.tsx`: new horizontal top navigation and app shell.
- `frontend/src/pages/Home.tsx`: rebuilt scan workspace layout using the existing policy, job history, tools and scan-creation APIs.
- `frontend/src/styles.css`: new layout and responsive design rules. Existing scanning logic and backend contracts are unchanged by this UI-only layout pass.

## Functional behavior retained

- Scan creation continues to POST to `/api/jobs` with the URL and selected pillars.
- Exact-origin authorization is reflected in the launch state and checked again by the backend.
- Tool status is loaded from `/api/tools`; counts are described as availability, not proof of a successful scan.
- Recent runs link to a report when completed and back to progress for non-completed jobs.
- Select-all and clear controls affect the actual selected pillar state; launch is disabled when no pillar is selected.
- The Clear URL action clears the field without submitting a request.

## Validation notes

- TypeScript/TSX syntax transpilation completed with no syntax diagnostics across 13 frontend TypeScript files.
- A full `tsc -b` / Vite production build could not be completed in this environment because npm dependency installation could not fetch uncached packages from the registry. Do not interpret syntax parsing as a successful production build.
- Backend logic was not intentionally changed in this layout-only update.

## Before demo

1. Run `npm ci` in `frontend/` on the development/demo machine.
2. Run `npm run build` and resolve any environment-specific type/build issues.
3. Start the backend and frontend using the project README.
4. Check navigation on desktop and mobile widths.
5. Submit only an organizer-approved target and verify scan creation, progress, report links, history refresh, model settings, and tool readiness.
