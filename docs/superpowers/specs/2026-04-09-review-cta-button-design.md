# Review CTA Button Design

## Goal

When a job is blocked on manual review in the jobs queue, the review action button should become explicit and visually urgent enough to spot immediately without overpowering the rest of the row.

## Scope

- Only change the review action button in the jobs queue table.
- Do not change overview cards, detail panels, modal entry points, or any non-review actions.
- Do not change backend review logic or status mapping beyond the button copy shown in the queue.

## UX Decisions

### Button copy

- If the blocked step is `summary_review`, the action button label becomes `需要预审核`.
- If the blocked step is `final_review`, the action button label becomes `需要最终审核`.
- For all other cases, keep the existing generic review label behavior.

### Visual treatment

- Use the "B" direction selected in chat: keep a light editorial button body instead of a solid primary button.
- Add a more prominent text color so the CTA reads as urgent at a glance.
- Add a cool RGB marquee ring animation around the button, but keep the effect constrained to the edge so the UI does not become noisy.
- Keep the button body and interior typography aligned with the existing mineral/editorial palette.

### Motion constraints

- The animated effect only applies when the queue button represents a blocked review step.
- The animation should combine:
  - a subtle lift/glow on the button body
  - a rotating RGB border/ring effect on the outside edge
- The label text itself should remain stable, not rainbow-animated.
- Respect `prefers-reduced-motion: reduce` by disabling animated motion while preserving the stronger text color and a static highlighted border.

## Implementation Boundaries

- `frontend/src/features/jobs/JobQueueTable.tsx`
  - Centralize the queue CTA label and highlight state based on the resolved pending review step.
  - Apply a dedicated review CTA class only for `summary_review` and `final_review`.
- `frontend/src/styles.css`
  - Add queue-review CTA styles and reduced-motion fallback.
- `frontend/src/features/jobs/JobQueueTable.test.tsx`
  - Cover the new explicit labels and active highlight classes for both review steps.

## Risks

- A very loud animated CTA could visually compete with the existing `重跑` button.
- Animated gradients can reduce legibility if applied directly to text instead of the ring.
- Dense queue tables can feel busy if the glow radius is too large.

## Chosen Mitigations

- Keep the animated effect on a thin outer ring instead of making the whole button solid.
- Use a strong but readable static text color for the label.
- Keep the animation footprint tight to the button outline.
- Do not animate non-review queue actions.

## Testing

- Verify `summary_review` rows render `需要预审核` and the review CTA active class.
- Verify `final_review` rows render `需要最终审核` and the review CTA active class.
- Verify non-review rows do not receive the active review CTA class.
- Verify existing row action buttons remain clickable.
