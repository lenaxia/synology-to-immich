You are writing or improving tests for the synology-to-immich repository.

**Read README.md first** — TDD is mandatory (Rule 1).

Rules:
1. Follow the project's testing requirements exactly:
   - Multiple happy-path tests
   - Multiple unhappy-path tests (errors, invalid inputs, boundary failures, dependency failures)
   - Edge case coverage
   - Integration tests that exercise real wiring (handler → hook event → bot layer) — unit tests alone are not sufficient
2. Use table-driven tests following existing patterns in the codebase.
3. All tests must pass with `-race` flag: `go test -timeout 30s -race ./...`
4. For handler tests, feed synthetic frames through `ms.Feed(...)` to test the full decode → callback → hook event path (see README.md Testing Requirements). For test fixtures that assert specific packet field layouts/semantics, derive the expected layout from rAthena source, not intuition: `git clone --depth 1 https://github.com/rathena/rathena.git /tmp/rathena` and cross-reference `src/map/packets_struct.hpp` / `clif.cpp` (Rule 11). A test that encodes a wrong field mapping and asserts it against itself proves nothing about correctness.
5. Run `go build ./...` and `go test ./...` before pushing — zero failures required (full repo).
6. For new test files, follow the naming convention: `*_test.go` in the same package.
7. Check existing test files for patterns and utilities before writing new ones.
8. Create a work log in `docs/07_WORK_LOG/` (Rule 0).
