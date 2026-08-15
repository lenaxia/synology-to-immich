## Core Rules

These rules apply to every response. They are non-negotiable.

### 1. Test-Driven Development (TDD)

Write tests BEFORE writing functional code. Always.

1. Write test
2. Run test (must fail)
3. Write minimal code to pass
4. Run test (must pass)
5. Refactor if needed

Every code change must include: multiple happy-path tests, multiple unhappy-path tests, edge cases, and integration tests that exercise real wiring. Unit tests alone are not sufficient.

### 2. Assumptions: State, Then Validate

Every non-trivial claim rests on assumptions. Unstated, unvalidated assumptions cause most bugs.

**Mandatory protocol:**

- State every assumption explicitly before relying on it.
- Validate every assumption — read the source code, run a test, check git history, or query the system. Do not proceed on an assumption you have not verified.
- If you cannot validate an assumption, do not rely on it. Redesign so it is unnecessary, or ask the user.
- Record what proved each assumption (file path, test name, command output).

**Red flag words — these signal an unvalidated assumption. When you catch yourself using them, stop and verify:**

- "probably", "likely", "should be", "should work", "I believe", "I assume", "appears to", "seems like", "I think", "presumably", "in theory", "ought to", "most likely", "chances are", "it's safe to assume", "I'm fairly confident", "as expected", "the expectation is", "normally", "typically", "by convention", "standard practice is", "the intent is", "this is meant to", "designed to", "supposed to"

When any of these appear in your reasoning or output, replace them with verified evidence or explicitly flag them as unvalidated assumptions that need proof.

**Never claim what the code does without reading it.** Do not describe behavior from memory, convention, or inference. Read the actual source, trace the actual path, confirm the actual behavior. "I haven't verified this" is an honest answer. An unverified claim presented as fact is worse.


### Zero Technical Debt

- No TODOs, FIXMEs, or commented-out code
- No adapters for backwards compatibility — implement the final solution
- Never hack tests to pass — fix the root cause
- Pre-existing errors are not acceptable — fix them when encountered

