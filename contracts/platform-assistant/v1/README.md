# Platform Assistant contract v1

This directory is the wire and policy contract for 开小花. It is intentionally
separate from `contracts/agent/v1` and `backend/app/capabilities`: those assets
describe StaffDeck Agent/provider capabilities, while this contract describes
versioned platform business workflows, trusted page context, structured UI
blocks and risk-gated tools.

Rules:

- The server owns workflow state, block versions, entity authorization and deep-link generation.
- The browser only reports route identifiers and candidate entity references.
- Model output is untrusted until it passes these schemas and business validation.
- R3 and R4 actions are never executable by the first release of 开小花.
- Unknown block types degrade to a safe notice; they are not rendered as HTML.

`manifest.json` is the closure used by contract tests. Schema or instance changes
must update the manifest and retain protocol compatibility.
