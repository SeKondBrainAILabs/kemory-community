# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities privately to
**security@kemory.s9n.ai**. Do NOT open a public issue.

We aim to:
- Acknowledge receipt within 2 business days.
- Provide an initial assessment within 5 business days.
- Disclose publicly within 90 days of report, or sooner if a fix ships first.

We follow [coordinated disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure).
If you'd like CVE assignment, mention it in your report.

## Supported versions

Only the latest minor release receives security fixes. Older versions
are best-effort.

## Scope

In scope: the kemory-community Python backend, its CLI, its packaging,
and the dashboard shipped in this repo. Out of scope: third-party
dependencies (report upstream), the hosted Kemory service (report via
hosted security channel), or vulnerabilities requiring physical
access to the user's machine.
