You are performing a deep analysis of the synology-to-immich codebase. This is a READ-ONLY task — do not make any code changes.

**Read README.md first** for full architectural context.

Rules:
1. Read README.md for the four-layer architecture, critical rules, and handler workflow.
2. Read relevant design documents from `docs/02_ARCHITECTURE/` or `docs/08_BACKLOG/` as needed.
3. Be specific — reference file paths, function names, type names, and data flows. Do NOT reference line numbers (they drift).
4. If you find bugs or design flaws, describe them precisely with reproduction steps or code references.
5. Do not create branches, PRs, or make any file changes.
6. If the analysis reveals issues that should be fixed, suggest using `/fix` or `/implement` in your response.
7. For packet-behaviour analysis, ground every claim in rAthena source: `git clone --depth 1 https://github.com/rathena/rathena.git /tmp/rathena`, then cite specific structs in `src/map/packets_struct.hpp` (primary), `packets.hpp`, or `clif.cpp`. Never analyse packet semantics from memory. If analysis suggests a rathena-client decode gap, say so and recommend a cited bug report (Rule 18).

Output format:
## Analysis

### Topic
[What was analyzed]

### Findings
[Detailed findings with code references]

### Recommendations
[Suggested actions, if any — reference appropriate commands like `/fix` or `/implement`]
