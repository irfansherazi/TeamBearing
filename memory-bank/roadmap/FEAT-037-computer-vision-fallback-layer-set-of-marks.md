---
legacy_id: FEAT-037
version: next
linked_tasks: [computer-vision-fallback-layer-set-of-marks]
status: complete
---

### FEAT-037: Computer Vision Fallback Layer (Set-of-Marks)
- **Version**: next
- **Status**: complete
- **Priority**: high
- **Complexity**: Level 4
- **Description**: Introduces a pure Computer Vision (CV) fallback layer that activates when DOM/ARIA resolution fails — covering PrimeNG components with obfuscated ARIA trees, dynamic Canvas rendering, and Shadow DOM elements that have no accessible locator. When the standard executor fails to resolve a target element (after the existing failure-aware recovery chain is exhausted), the agent captures a raw Playwright screenshot, overlays a Set-of-Marks (SoM) grid (numbered cells mapped to X,Y viewport coordinates), and sends the annotated image to Claude 3.5 Sonnet Vision. The model identifies the target element visually and returns the grid cell ID; the system maps it back to exact X,Y coordinates and Playwright executes a `page.mouse.click(x, y)` — completely bypassing the DOM.
- **Linked Tasks**: computer-vision-fallback-layer-set-of-marks (COMPLETE)
- **Branch**: feature/FEAT-037-cv-fallback-som
- **Created**: 2026-05-16
- **Completed**: 2026-05-17 ✅
