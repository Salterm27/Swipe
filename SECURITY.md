# Security policy

## Reporting a vulnerability

Please report security issues **privately** through GitHub:
**Security → Report a vulnerability** on this repository. Please don't open
a public issue.

Include what you found, how to reproduce it, and what an attacker could do
with it. Expect a first reply within a week. This is a personal project
maintained in spare time.

## Supported versions

Only `main` is supported. The Pi auto-deploys it, so fixes ship as soon as
they merge.

## What Swipe is designed for

Swipe is a **self-hosted, single-household app**. It is meant to run on a
home network, behind your router, for people you trust.

- **No accounts or login.** Anyone who can reach the port can read, change
  and delete every project. Don't expose it to the internet as it is (no
  port forwarding, no public tunnel). If you want remote access, put it
  behind something that authenticates, such as a VPN like Tailscale or
  WireGuard, or a reverse proxy with auth.
- **Your data stays on the Pi.** The server makes no outbound requests, and
  the fonts are self-hosted. The only third-party traffic is your own
  browser loading the image URLs that are in your lists.
- **List data is treated as untrusted.** Imported lists are rendered as
  text, never as HTML. Links and images are limited to http(s) (and `data:`
  images). A Content-Security-Policy only allows the page's own script and
  style, by hash.

## What's in place

- **Static analysis:** CodeQL (security-extended) on the Python backend, the
  frontend JavaScript and the GitHub Actions workflows, on every PR and
  weekly. ruff with bandit rules, and ESLint, which bans `innerHTML`.
- **Dependencies:** pinned exactly. Dependabot proposes weekly updates for
  pip, npm and GitHub Actions, and each one runs the full test suite.
- **Workflows:** run with a read-only `GITHUB_TOKEN`. Jobs that need more
  ask for it explicitly.
- **Headers:** CSP, `nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer` and a restrictive `Permissions-Policy`.
- **Error handling:** API errors return fixed messages, never exception text.
