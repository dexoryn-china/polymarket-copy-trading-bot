# Security Policy

## Supported versions

Security fixes are applied to the latest release on the `main` branch.

| Version | Supported |
|---------|-----------|
| Latest on `main` | Yes |
| Older tags | Best effort |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report privately via:

- **Telegram**: [@dexoryn](https://t.me/dexoryn) (preferred)
- **GitHub**: [Private vulnerability report](https://github.com/dexoryn-china/polymarket-copy-trading-bot/security/advisories/new) if you have access

Include steps to reproduce, affected versions, and impact when possible. We aim to acknowledge reports within a few business days.

## User security practices

This bot handles wallets and can place real trades. Please:

- Never commit `config.yaml`, `targets.yaml`, or `settings.yaml` with live secrets
- Use `mode: dry_run` until behavior is verified
- Set `web.token` before exposing the dashboard beyond localhost
- Use a dedicated wallet with limited funds for automation
- Rotate API keys if they may have been exposed

## Disclaimer

Dexoryn Labs is not responsible for losses from misuse, misconfiguration, or
third-party platform changes. You are responsible for securing your keys and
capital.
