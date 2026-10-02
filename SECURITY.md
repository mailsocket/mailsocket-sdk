# Security Policy

## Supported versions

The latest published version of each package in this repo (`mailsocket` on
PyPI, `mailsocket-mcp` on PyPI, `mailsocket-sdk` on npm) is supported.
Security fixes are released as a new patch version; please upgrade rather
than pin to an old one.

## Reporting a vulnerability

Please report security vulnerabilities to **security@mailsocket.app**.

Do not open a public GitHub issue for a security report.

Include, if possible:
- The package and version affected.
- A minimal reproduction.
- The potential impact (e.g. key leakage, SSRF, injection).

We aim to acknowledge reports within a few business days and will credit
reporters (if desired) once a fix ships.

## Scope

This covers the client SDKs and MCP server in this repo. For vulnerabilities
in the mailsocket API or dashboard themselves, also use
security@mailsocket.app.
