You are implementing a feature or user story for the synology-to-immich repository.

**Read README.md first** — it contains 18 critical rules.

Rules:
1. Read README.md before making any changes — it contains hard rules for TDD, type safety, architecture, hook events, builders, and rathena-client integration.
2. Read the relevant design document(s) from `docs/02_ARCHITECTURE/` or `docs/08_BACKLOG/USER_STORIES/` before starting.
3. Follow TDD (Rule 1): write tests FIRST — they must fail, then implement, then pass. Multiple happy-path + unhappy-path + edge cases + integration tests.
4. Use hook package events (`internal/hook/events.go`) — never local event types (Rule 4). Map rathena-client wire fields to hook event fields with explicit conversions. For non-obvious field semantics, clone rAthena (`git clone --depth 1 https://github.com/rathena/rathena.git /tmp/rathena`) and confirm what each wire field means against `src/map/packets_struct.hpp` / `clif.cpp` so the hook event carries correct semantics (Rule 11).
5. Use builders (`internal/network/send/builders/`) for send packets — never manual byte construction (Rule 5).
6. Register new handlers via `session.RegisterSemanticHandler` in the sub-package's `Register(ms, d, ...)` function (Rule 7).
7. NEVER edit or work around rathena-client. If rathena-client has a bug, file a report and mark the story blocked (Rule 18).
8. Do not add goroutines or channels inside bot instances (Rule 16).
9. Run `go build ./...` and `go test ./...` before pushing — zero failures required (full repo).
10. Create a work log in `docs/07_WORK_LOG/` (Rule 0).
11. Leave the codebase in zero-error state — fix any pre-existing errors you encounter.
