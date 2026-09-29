# Polymarket Bot | Polymarket Trading Bot | Polymarket Copy Trading Bot  

**Languages:** [English](README.en.md) · [中文](../README.md) · [Русский](README.ru.md)

> **Automated Polymarket copy trading bot that mirrors active traders in real time**  
> **Predictions & Perps • Multi-wallet • Web dashboard • Live tested • Real on-chain execution**

> **Need help or an updated build?**  
> 📱 **Telegram**: [t.me/dexoryn](https://t.me/dexoryn) | 🎮 **Discord**: `dexoryn_`

---

## 🎥 Live Profit Videos (Historical - Gabagool22)

These sessions were recorded while **@gabagool22** was actively trading. They show the bot executing real copy trades on-chain-not a simulation.

**Wallet (historical target):** `0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d`

> **Note:** Gabagool22 is no longer a reliable copy target. The videos remain proof of live production use-see [Story 3](#story-3--bot-still-running-after-gabagool22-stopped) for how we switched to active leaders.

### Video 1 - Live Copy Trading Run

https://github.com/user-attachments/assets/2194ef92-b0f7-40e1-9835-4d2965e85e81

- **+$80 profit in ~15 minutes**
- Bot ran unattended during this session
- Real on-chain execution, not simulation

### Video 2 - Second run (confirmation)

https://github.com/user-attachments/assets/df3a6791-89b5-4230-ae40-fb7130dcadc4

- **Additional +$230 profit in the next ~15 minutes**
- Same bot, same logic, separate run
- Fully automated copy trading

---

## 📖 Live Test Stories (Real Usage)

### Story 1 - Unattended session (Gabagool22 era)

After updating the bot, I ran it to test the new logic and left it running while I went out to play billiards with friends.

About one hour later, when I returned:

- ✅ The bot was running normally
- ✅ It was copy trading accurately
- ✅ Trades matched the target trader's transactions
- ✅ The bot had already generated profit

This was a fully unattended live run, not a simulation or backtest.

---

### Story 2 - Repeatable performance (video runs)

The two videos above are from **separate live sessions** on different days. Same codebase, same monitoring and execution pipeline-no manual clicking through Polymarket. That repeatability is what we optimize for: stable automation, not a one-off lucky trade.

---

### Story 3 - Bot still running after Gabagool22 stopped

<a id="story-3--bot-still-running-after-gabagool22-stopped"></a>

Gabagool22 eventually **slowed down and stopped being a practical copy target**-fewer trades, different behavior, or simply going inactive. A lot of copy traders hit the same wall: the wallet that worked last month goes quiet, and their bot looks "broken" when the real issue is an **empty signal**, not broken software.

What we did:

- Kept the **same bot** running-no rewrite, no new product
- Added **new active wallets** as targets in the dashboard (saved to `targets.yaml`)
- Confirmed the full pipeline still works: trade detection → sizing → order posting → logging

What we saw:

- ✅ Process stayed up and healthy
- ✅ New target trades were detected and mirrored correctly
- ✅ Activity history and `state.json` updated as expected
- ✅ Failures were isolated to market/order edge cases, not "bot died when Gabagool22 left"

#### Perfect copy-trading result - mirroring **securebet**

After switching targets, we copied [**securebet**](https://polymarket.com/@securebet) and captured this side-by-side:

<p align="center">
  <img src="public/Realtradehistory/securebet.jpg" alt="Copy trading PnL: bot wallet vs securebet target - matching chart shape" width="100%"/>
</p>

**This is what ideal copy trading looks like.** Your bot wallet (left) and the target trader (right) show the **same PnL chart shape** for the day-the same flat period, dip, and recovery spike at the end. Dollar amounts differ because of your sizing settings and balance, but the **curve tracks the leader**, which means trades are being detected and mirrored in sync-not lagging behind or fighting the strategy.

Same session, same markets in the activity/history tabs (e.g. the temperature markets visible in the screenshot). That alignment is the proof traders care about: **follow the wallet, get the same equity curve pattern.**

**Takeaway for traders:** This bot is built to follow **whoever you configure**, not one celebrity wallet. When a trader stops working for you, **change the target-not the bot.** Past Gabagool22 results do not guarantee future results on any target.

---

## ⭐ Features

The videos and stories above are **predictions** runs. This build adds a full platform on top of that core pipeline:

- **Multi-wallet copy** - several leaders, each with its own sizing and cap
- **Web dashboard** at `http://127.0.0.1:8787` - targets, activity, positions, settings
- **Predictions + Perps** - one active venue at a time; switch from the dashboard
- **WebSocket detection**, share batching, optional exit mirroring (`copy_closes`), Telegram alerts
- **Dry-run mode** and persistent state (`state.json`, `history.db`)

| Feature | This Bot | Typical alternatives |
|---------|----------|----------------------|
| Live execution proof | ✅ Videos + stories above | ❌ Claims only |
| Multi-wallet + dashboard | ✅ | ❌ Single address / CLI |
| Perps + exit mirroring | ✅ | ❌ Predictions / entry only |
| Swap target when leader goes quiet | ✅ In UI | ⚠️ Tied to one wallet |
| WebSocket + dry-run | ✅ | ⚠️ Polling / no simulation |

**Good fit:** passive copy traders on **Python 3.10+** who will monitor **Activity**. **Not a fit:** guaranteed profits, simultaneous predictions + perps, or a public dashboard without `web.token`.

---

**Jump to:** [Quick Start](#-quick-start) · [Dashboard](#-dashboard) · [Configuration](#configuration) · [FAQ](#faq)

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+**
- **Polygon wallet** - USDC for predictions, POL/MATIC for gas (`mode: real`)
- **Polymarket CLOB API credentials** - for live prediction-market orders
- **Funded Perps account** - only when copying Perps in `real` mode
- **Node.js 18+** - only if you rebuild the dashboard UI yourself

### Install

```bash
git clone https://github.com/dexorynlabs/polymarket-trading-bot-python.git
cd polymarket-trading-bot-python

pip install -r requirements.txt

cp config.yaml.example config.yaml
# Edit config.yaml: mode, web settings, polymarket secrets (real mode)

python -m app.main
```

### First run

1. Keep **`mode: dry_run`** in `config.yaml`
2. Open **http://127.0.0.1:8787** → **Targets** → add wallet, venue, sizing → **Start**
3. Confirm fills in **Activity**, then set **`mode: real`**, restart, and **Start** with small size

Build the UI from source (optional): `cd ui && npm install && npm run build` · see [`ui/README.md`](ui/README.md)

**Help:** [@dexoryn](https://t.me/dexoryn) on Telegram.

---

## 🖥 Dashboard

Run the bot from the dashboard after the one-time `config.yaml` setup. Target edits save to `targets.yaml`; tuning saves to `settings.yaml`. Legacy single `target_wallet` configs auto-migrate on first launch.

| Page | What you do there |
|------|-------------------|
| **Overview** | Copy status, active venue, latency snapshot |
| **Targets** | Add, edit, enable, or pause leader wallets |
| **Activity** | Live feed of detected fills and copy results |
| **Positions** | Open exposure and remaining headroom |
| **Settings** | Sizing, slippage, notifications |

**Perps:** set target `venue: perps`, fund on [polymarket.com](https://polymarket.com). Portfolio changes are polled from the leader's public profile; orders are IOC limits at mark ± slippage.

> **One venue at a time** - predictions or perps, not both. Keep `web.host: 127.0.0.1` unless you set `web.token`.

---

## Configuration

| Layer | File | Use for |
|-------|------|---------|
| Bootstrap | `config.yaml` | `mode`, API secrets, web/Telegram, global defaults |
| Runtime | `targets.yaml` | Leader wallets (managed in **Targets**) |
| Runtime | `settings.yaml` | Trading tuning (managed in **Settings**) |

Dashboard values override matching keys in `config.yaml`.

### Essential `config.yaml`

| Setting | Description | Example |
|---------|-------------|---------|
| `mode` | `dry_run` simulates; `real` posts orders | `dry_run` |
| `copy.venue` | Initial venue when copying starts | `predictions` |
| `web.enabled` | Serve the dashboard | `true` |
| `web.host` / `web.port` | Bind address | `127.0.0.1` / `8787` |
| `web.token` | Optional dashboard auth | `""` |
| `risk.max_open_usd_total` | Optional cap across prediction targets | `null` |
| `execution.order_type` | `taker` (FAK) or `maker` (GTC) | `taker` |
| `slippage.entry_bps_max` | Max slippage on BUY copies (bps) | `1000` |

For `mode: real`, fill `polymarket:` (`private_key`, `wallet_address`, `api_key`, `api_secret`, `passphrase`). Per-target fields (`wallet`, `venue`, `enabled`, `copy_closes`, `sizing.*`) are set in the dashboard. Full reference: **`config.yaml.example`**.

---

## Safety & Risk

⚠️ **`mode: real` uses real funds.** Use a dedicated wallet with limited balance, set conservative per-target caps, check `logs/copybot.log`, never commit secrets, and remember past performance does not guarantee future results.

---

## FAQ

**Do I still need `config.yaml` if I use the dashboard?**  
Yes - for `mode`, API secrets, and web/Telegram. Targets and day-to-day tuning live in the dashboard.

**Where are logs and state stored?**  
`logs/copybot.log`, `history.db`, `state.json`, and `settings.yaml` (gitignored except the example config).

**Is this open source?**  
Yes. A maintained premium build with extra support is also available via Telegram.

---

## Author & Contact

**Dexoryn Labs** - Polymarket copy-trading automation

- **Telegram**: [@dexoryn](https://t.me/dexoryn) (fastest)
- **Discord**: `dexoryn_`
- **Twitter**: [@dexoryn](https://x.com/dexoryn)
- **GitHub**: [@dexorynLabs](https://github.com/dexorynLabs)
- **WeChat**: scan to add **DexorynWe**

<p align="center">
  <img src="public/dexoryn_tg.jpg" alt="Telegram QR code - @dexoryn" height="260"/>
  &nbsp;&nbsp;
  <img src="public/dexoryn_wechat.png" alt="WeChat QR code - DexorynWe" height="260"/>
</p>

---

## Contributing

See [CONTRIBUTING.md](.github/CONTRIBUTING.md). Quick start: fork → branch → `pytest` → PR.

Community: [Code of Conduct](.github/CODE_OF_CONDUCT.md) · [Security](.github/SECURITY.md) · [MIT License](LICENSE)

---

## Legal Disclaimer

Trading on Polymarket involves **substantial risk of loss**. Dexoryn is not responsible for losses from using this software. You are solely responsible for wallet security, target selection, and capital at risk.

**Only trade with funds you can afford to lose.**

Questions: [@dexoryn](https://t.me/dexoryn) · ⭐ star the repo if it helps.
