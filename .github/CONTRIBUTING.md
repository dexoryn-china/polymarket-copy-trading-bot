# Contributing

Thanks for helping improve this project. Issues and pull requests are welcome.

## Before you start

- Read the [README](../README.md) for setup and safety notes.
- **Never commit secrets** - `config.yaml`, `targets.yaml`, `settings.yaml`, wallet keys, or API credentials.
- Trading bots carry financial risk. Test in `dry_run` before suggesting changes that affect live execution.

## Development setup

```bash
git clone https://github.com/dexoryn-china/polymarket-copy-trading-bot.git
cd polymarket-copy-trading-bot

pip install -r requirements.txt
pip install -r requirements-dev.txt

cp config.yaml.example config.yaml
pytest
```

Optional UI work: see [`ui/README.md`](../ui/README.md).

## Pull requests

1. Fork the repo and create a branch from `main` (e.g. `feature/short-description`).
2. Keep changes focused - one logical change per PR when possible.
3. Run tests: `pytest`
4. Open a PR with a clear summary and test notes.

Commit messages in this repo typically use prefixes like `feat:`, `fix:`, `docs:`, `test:`, or `perf:`.

## Code of conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). Be respectful in issues and reviews.

## Questions

- **Telegram**: [@dexoryn](https://t.me/dexoryn)
- **GitHub Issues**: for bugs and feature requests (no secrets in issue text)
