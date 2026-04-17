# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in Goblin, please report it
responsibly:

1. **Do not** open a public GitHub issue.
2. Email the maintainer directly or use GitHub's private vulnerability
   reporting feature on this repository.
3. Include a description of the vulnerability, steps to reproduce, and any
   potential impact.

We will acknowledge receipt within 72 hours and aim to provide a fix or
mitigation within 14 days.

## Credential Hygiene

Goblin resolves secrets at runtime via environment variables and the Windows
Credential Manager. **No API keys, tokens, or account identifiers should ever
be committed to this repository.**

If you find a committed secret, please report it immediately using the process
above.

## Automated Trading Disclaimer

Goblin is a **research platform**. Real-money automated trading is explicitly
forbidden by repository governance (`AGENTS.md`). The platform may interact
with broker demo accounts for observability and parity validation only.

**Do not use this software to execute real-money trades without independent
risk assessment and explicit authorization outside of this repository's
governance.**
