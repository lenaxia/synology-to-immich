You are explaining code, architecture, or data flow in the synology-to-immich repository. This is a READ-ONLY task — do not make any code changes.

**Read README.md first** for the full architectural context.

Rules:
1. Read README.md for the four-layer architecture (bot → handler → connector → rathena-client) and critical rules.
2. Read relevant design documents from `docs/02_ARCHITECTURE/` as needed.
3. Be clear and specific — reference files, functions, types, and data flows. Do NOT reference line numbers (they drift).
4. If the explanation reveals issues, note them but do not fix them. Suggest `/fix` or `/analyze` for follow-up.
5. Do not create branches, PRs, or make any file changes.
6. For any packet-behaviour explanation, ground field/type/semantics claims in rAthena source: `git clone --depth 1 https://github.com/rathena/rathena.git /tmp/rathena`, then reference the actual struct in `src/map/packets_struct.hpp` (primary) or `clif.cpp` — never describe packet behaviour from memory.
