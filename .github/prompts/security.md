You are performing a security-focused review of the synology-to-immich codebase.

**Read README.md first** for security-relevant coding standards.

Rules:
1. Check every one of these areas:
   - **Credentials:** Are bot passwords, usernames, or auth tokens exposed in logs, error messages, or API responses? Bot credentials live in config files — verify they are never logged unredacted (Rule 17).
   - **Input validation:** Is all user/network input validated at the boundary (packet field lengths, types, ranges)?
   - **Packet handling:** Are there any manual byte-construction paths bypassing the builder pattern? (Rule 5 — builders enforce validation; raw bytes bypass it.)
   - **rathena-client:** Is any code trying to edit or work around rathena-client? That is forbidden (Rule 18) — it could introduce wire-protocol bugs or security issues.
   - **Network:** Are there any unauthenticated or unprotected network paths? Could a malicious server packet cause a crash, buffer overflow, or resource exhaustion?
   - **Concurrency:** Are there goroutine leaks or race conditions that could be exploited for DoS? (Rule 16 — single-threaded bot instances.)
   - **LLM integration:** Could the LLM cognitive layer be manipulated via in-game chat to execute unintended actions? Are LLM prompts/responses sanitized?
   - **Packet length / field authority:** When a finding hinges on a packet's declared length or field layout, cross-reference rAthena (`git clone --depth 1 https://github.com/rathena/rathena.git /tmp/rathena`; check `src/map/packets.hpp` for declared lengths and `src/map/packets_struct.hpp` for the struct). A handler that assumes a different length/layout than rAthena declares is relying on a rathena-client gap — file a report citing rAthena (Rule 18), do not work around it.
   - **Secrets in config:** Are there hardcoded secrets, API keys, or credentials in the diff?
2. If code changes are needed to fix security issues, create a branch, open a PR, and follow the code change workflow. **For every security vulnerability you fix, write a regression test that proves the fix** — a test that fails against the vulnerable code (exercises the exploit path) and passes after the fix. A security fix without a regression test is incomplete.
3. Never handle or create secrets.
4. For read-only security analysis, post findings as a comment.

Output format:
## Security Review

### Scope
[What was reviewed]

### Findings
| # | Severity | Description | Location | Remediation |
|---|----------|-------------|----------|-------------|
| 1 | Critical/High/Medium/Low | [description] | file:line | [fix] |

### Threat Surface Impact
[How this affects the overall threat surface]

### Verdict
[SAFE / CONCERNS FOUND] — [one sentence summary]
