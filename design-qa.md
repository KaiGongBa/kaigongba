# Design QA — AI 需求解析 UI（方案 3）

## Comparison target

- Source visual truth: `/Users/albert/.codex/generated_images/019fd4f1-02eb-7e90-afd1-12a0c6ff337b/exec-fb95ca29-8b54-476c-ab56-f3335a3258a9.png`
- Browser-rendered implementation: `/Users/albert/Documents/开工吧复刻/kaigongba/.artifacts/design-qa/option3-implementation-final.png`
- Responsive evidence: `/Users/albert/Documents/开工吧复刻/kaigongba/.artifacts/design-qa/option3-responsive-1180.png`
- Route: `http://127.0.0.1:5173/enterprise/demands/new?draftId=reqdraft_6c31163470374eed`
- Viewport: 1672 × 941 CSS px; responsive check at 1180 × 900 CSS px
- Pixel dimensions: source 1672 × 941; implementation 1672 × 941
- Density normalization: 1:1 pixel comparison at the same viewport; no scaling or density conversion was required.
- State: authenticated enterprise demand creation page, reviewing AI draft v5, AI composer populated, result ribbon ready, assistant drawer open.

## Full-view comparison evidence

The source and final browser capture were opened together in the same comparison input at identical pixel dimensions. The requested top experience preserves the source hierarchy and composition: compact white AI composer, left sparkle affordance, black analysis CTA, four-part result ribbon, red state labels, editable recognized facts, amber hard-information confirmation, red review CTA, and the real editable requirement form immediately below.

The surrounding production shell is intentionally retained. Its navigation rail, header, form component density, and assistant drawer differ slightly from the generated concept because the requested scope was the upper AI parsing UI, not a replacement of the application shell or assistant conversation.

## Focused region comparison evidence

The top composer and result ribbon were inspected at readable scale in both images. Typography hierarchy, one-pixel borders, 7–10 px corner radii, cell separators, chip treatment, CTA contrast, spacing, and the transition into the form are visibly aligned. No additional crop was required because the full-resolution 1672 × 941 comparison keeps every label and control in the target region legible.

## Required fidelity surfaces

- Fonts and typography: production sans-serif stack is retained; weights, sizes, line heights, wrapping, truncation, and red/neutral hierarchy match the compact enterprise target. No overflow or illegible small text was found.
- Spacing and layout rhythm: composer height, ribbon density, padding, borders, cell divisions, and vertical handoff to the form match the source pattern. The 1180 px check correctly reflows the ribbon to two columns without horizontal overflow.
- Colors and visual tokens: white/gray surfaces, neutral black CTA, product red labels/action, amber confirmation, and subtle blue-purple sparkle reuse the application's existing palette and preserve source contrast.
- Image and icon fidelity: existing production logo/avatar assets remain intact. Standard UI glyphs use the project's Lucide Sparkles and PencilLine icons; no placeholder, CSS drawing, emoji, or fake asset was introduced.
- Copy and content: labels follow the approved design (`AI 已识别`, `AI 已扩写`, `仍需确认`). The action copy intentionally says `已自动填入` and `检查已填表单`, because the product now auto-fills immediately instead of making the user click a second gate.

## Findings

- No actionable P0, P1, or P2 visual or interaction findings remain.
- Accepted contextual difference: the generated source shows a simplified success summary in the assistant drawer, while the implementation keeps the real production drawer and existing conversation state. This is outside the requested upper-input redesign scope.
- Accepted contextual difference: the exact number of filled fields and pending facts is data-driven; the inspected draft reports six filled fields and one relative-time confirmation.

## Comparison history

1. Initial implementation capture: `.artifacts/design-qa/option3-implementation-v1.png`.
   - [P2] `AI 已识别` favored long acceptance text and internal values over the source's concise title/category/audience/time facts.
   - [P2] the pending area could say `无需补充` while the real form still required a concrete delivery date, and a raw `desired_delivery_at` blocker leaked into the note row.
   - Fixes: reordered recognized facts to title/category/audience/time; merged warning and handoff fields into a clickable user-facing pending item; mapped the internal delivery field to `期望完成时间`; removed raw handoff validation text; corrected responsive cell borders to target semantic classes instead of fragile child indices.
2. Post-fix browser capture: `.artifacts/design-qa/option3-implementation-final.png`.
   - Evidence: four concise editable facts are visible; `期望完成时间` is the only amber confirmation; internal field names are absent; 1672 px and 1180 px layouts have no horizontal overflow; no P0/P1/P2 differences remain in the requested region.

## Primary interactions tested

- Composer accepts natural-language input and enables `AI 解析`.
- Clicking a recognized AI fact focuses the corresponding real form field.
- Clicking `检查已填表单` focuses the first populated field for review.
- Pending `期望完成时间` is rendered as an actionable control leading to the deadline field.
- Responsive layout tested at 1180 × 900 with `scrollWidth === clientWidth`.

## Runtime checks

- Browser console errors/warnings after the final render: none.
- Focused tests: 33 passed.
- Production TypeScript/Vite build: passed.

## Follow-up polish

- No required P3 follow-up for the approved upper-input scope.

final result: passed
