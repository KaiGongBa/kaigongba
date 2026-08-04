# Platform Assistant Adaptive Interview Protocol v2

Version 2 adds an adaptive interview state to the frozen Platform Assistant v1
contract. It is an additive transport version: all seven v1 blocks remain valid
inside a v2 turn response without being rewritten. Adaptive `question_group`
and `interview_state` blocks use `schema_version: "2.0"`.

## Compatibility rules

- Existing files under `contracts/platform-assistant/v1` are immutable and are
  not replaced by this package.
- A v1 client continues to send and parse `protocol_version: "1.0"` exactly as
  before.
- A v2 client sends `protocol_version: "2.0"` and can parse frozen v1 blocks,
  v2 adaptive question groups, and v2 interview state blocks.
- Unknown or malformed blocks fail closed in clients and must never be treated
  as executable UI.
- An adaptive question group contains one to three questions. Free-text
  conversation remains available through `allow_free_text`; the block is not a
  replacement for the complete business form.

## Fact safety

`interview_state.facts` distinguishes candidate, confirmed, conflicting and
superseded facts. `hard_fact` records which facts must not be silently invented
or overwritten by the model. `classification` may remain unmatched, and
`readiness` is false whenever `blocking_fields` is non-empty.
