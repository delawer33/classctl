# ADR 0002: Docker SSH containers for integration testing

## Status
Accepted

## Context
The tool SSHes into up to 35 real Linux machines to execute long-running scripts. The developer has no access to the real classroom hardware. The classroom tester can only be asked to validate infrequently, so regressions must be caught before release.

The alternative was mocking the SSH layer entirely (faster, no Docker dependency).

## Decision
Integration tests spin up real SSH-enabled Docker containers as fake workstations. The containers run parameterizable shell scripts (`fake_script.sh --sleep N --exit-code N --output-pattern X`) that simulate success, error output, hangs, and mid-run disconnects. The real asyncssh code connects to these containers — no SSH mocking.

WoL packet sending is stubbed (it's a one-liner with nothing to test). The post-WoL SSH polling and timeout logic is tested against containers by controlling when SSH becomes available.

Test framework: pytest + pytest-asyncio + docker-py fixtures.

## Consequences
- All non-happy paths (timeouts, partial failures, mid-step disconnects, retry flows) are reproducible and automated.
- Tests run locally; no CI for now.
- Docker must be available on the development machine.
- The SSH code is exercised end-to-end; a mock would not catch asyncssh-specific issues.
