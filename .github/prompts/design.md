You are iterating on a **design document** for the synology-to-immich repository — the step that comes *before* `/implement` or `/fix`. The goal is a reviewed, approved design, not code.

Output target: a design document under `docs/02_ARCHITECTURE/` (for cross-cutting/architectural work) or `docs/08_BACKLOG/USER_STORIES/EPIC_XX/` (for story- or epic-scoped work), following the repository's existing conventions.

Rules:
1. Read README.md first — especially the architecture section (four-layer system), the critical rules, and the handler workflow. Read any existing doc that touches the same area before writing.
2. Decide where the design lives:
   - Cross-cutting / architectural → a new file in `docs/02_ARCHITECTURE/` named descriptively (e.g. `SOMETHING_ARCHITECTURE.md`).
   - Story- or epic-scoped → the relevant `docs/08_BACKLOG/USER_STORIES/EPIC_XX/` directory (often a `README.md` or a story file).
   - Updating an existing design → edit it in place; do not silently duplicate.
3. Scope the design to the request text from the collaborator. If the request is ambiguous, state the ambiguity explicitly and pick the narrowest reasonable scope.
4. A design doc must cover at minimum: problem statement, goals/non-goals, proposed design, alternatives considered, data-flow / component interactions, failure-mode analysis, and open questions. Trace every claim to source (file:function) where the codebase is referenced — do not describe behaviour from memory. For any packet-behaviour claim, clone rAthena (`git clone --depth 1 https://github.com/rathena/rathena.git /tmp/rathena`) and cite the actual struct in `src/map/packets_struct.hpp` (primary) or `clif.cpp`. If the design depends on packet behaviour rathena-client doesn't currently expose, call it out as a rathena-client dependency/blocker (Rule 18) — do not assume goKore can work around it.
5. State assumptions up front and validate each one against source/tests before relying on it.
6. Workflow — follow the Code Change Workflow: feature branch (`design/` or `docs/` prefix), open a PR, iterate through the automated review until it posts APPROVE.
7. **MERGE HOLD — this command never auto-merges.** After the automated review posts APPROVE, STOP. Do not merge. Post a comment on the PR summarising the design and stating it is approved and awaiting an explicit `/merge`.
8. Do not write production code in this step — only the design document and supporting diagrams/tables.
