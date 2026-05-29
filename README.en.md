# Polymarket Bot | Polymarket Trading Bot | Polymarket Copy Trading Bot  

**Languages:** [English](README.en.md) · [中文](README.md) · [Русский](README.ru.md)

> **Automated Polymarket copy trading bot that mirrors active traders in real time**  
> **Live tested • Real on-chain execution • Swap targets anytime**

> **Need help or an updated build?**  
> 📱 **Telegram**: [t.me/dexoryn777](https://t.me/dexoryn777) | 🎮 **Discord**: `dexoryn777`

---

## 🎥 Live Profit Videos (Historical — Gabagool22)

These sessions were recorded while **@gabagool22** was actively trading. They show the bot executing real copy trades on-chain—not a simulation.

**Wallet (historical target):** `0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d`

> **Note:** Gabagool22 is no longer a reliable copy target. The videos remain proof that the bot worked in production; you should point `USER_ADDRESSES` at traders who are **active today**. See [Story 3](#story-3--bot-still-running-after-gabagool22-stopped) below.

### Video 1 — Live Copy Trading Run

https://github.com/user-attachments/assets/2194ef92-b0f7-40e1-9835-4d2965e85e81

- **+$80 profit in ~15 minutes**
- Bot ran unattended during this session
- Real on-chain execution, not simulation

### Video 2 — Second run (confirmation)

https://github.com/user-attachments/assets/df3a6791-89b5-4230-ae40-fb7130dcadc4

- **Additional +$230 profit in the next ~15 minutes**
- Same bot, same logic, separate run
- Fully automated copy trading

---

## 📖 Live Test Stories (Real Usage)

### Story 1 — Unattended session (Gabagool22 era)

After updating the bot, I ran it to test the new logic and left it running while I went out to play billiards with friends.

About one hour later, when I returned:

- ✅ The bot was running normally
- ✅ It was copy trading accurately
- ✅ Trades matched the target trader's transactions
- ✅ The bot had already generated profit

This was a fully unattended live run, not a simulation or backtest.

---

### Story 2 — Repeatable performance (video runs)

The two videos above are from **separate live sessions** on different days. Same codebase, same monitoring and execution pipeline—no manual clicking through Polymarket. That repeatability is what we optimize for: stable automation, not a one-off lucky trade.

---

### Story 3 — Bot still running after Gabagool22 stopped

<a id="story-3--bot-still-running-after-gabagool22-stopped"></a>

Gabagool22 eventually **slowed down and stopped being a practical copy target**—fewer trades, different behavior, or simply going inactive. A lot of copy traders hit the same wall: the wallet that worked last month goes quiet, and their bot looks "broken" when the real issue is an **empty signal**, not broken software.

What we did:

- Kept the **same bot** running—no rewrite, no new product
- Updated `USER_ADDRESSES` to **other active Polymarket wallets** (use the research scripts under `src/scripts/research/` or your own due diligence)
- Confirmed the full pipeline still works: trade detection → sizing → order posting → logging

What we saw:

- ✅ Process stayed up and healthy
- ✅ New target trades were detected and mirrored correctly
- ✅ Logs and MongoDB history updated as expected
- ✅ Failures were isolated to market/order edge cases, not "bot died when Gabagool22 left"

#### Perfect copy-trading result — mirroring **securebet**

After switching targets, we copied [**securebet**](https://polymarket.com/@securebet) and captured this side-by-side:

<p align="center">
  <img src="Realtradehistory/securebet.jpg" alt="Copy trading PnL: bot wallet vs securebet target — matching chart shape" width="100%"/>
</p>

**This is what ideal copy trading looks like.** Your bot wallet (left) and the target trader (right) show the **same PnL chart shape** for the day—the same flat period, dip, and recovery spike at the end. Dollar amounts differ because of your sizing (`COPY_SIZE`, multipliers, and balance), but the **curve tracks the leader**, which means trades are being detected and mirrored in sync—not lagging behind or fighting the strategy.

Same session, same markets in the activity/history tabs (e.g. the temperature markets visible in the screenshot). That alignment is the proof traders care about: **follow the wallet, get the same equity curve pattern.**

**Takeaway for traders:** This bot is built to follow **whoever you configure**, not one celebrity wallet. When a trader stops working for you, **change the address—not the bot.** Past Gabagool22 results do not guarantee future results on any target.

---

## ⭐ Why This Bot

### 🎯 Real proof, not just claims

Other Polymarket bots often stop at screenshots. This repo includes **video proof** of live execution plus the stories above—including running correctly **after** the original star trader went inactive.

### 🚀 Architecture & performance

- **Centralized `data/` layout** — logs, cache, and simulation results in one place
- **Async-first** — built on Python `asyncio` for low-latency monitoring
- **Smart caching** — fewer redundant API calls

### 💡 Features traders actually use

- **Trade aggregation** — combine small fills into executable size (helps gas and Polymarket minimums)
- **Tiered multipliers** — size positions by the leader's trade size (`TIERED_MULTIPLIERS` in `.env.example`)
- **Copy strategies** — `PERCENTAGE`, `FIXED`, or `ADAPTIVE` sizing
- **Simulation & audit tools** — backtest and validate before going live
- **Multi-trader support** — copy several wallets at once
- **1-second polling** — configurable via `FETCH_INTERVAL`

### 📈 Comparison

| Feature | This Bot | Typical alternatives |
|---------|----------|----------------------|
| **Live execution proof** | ✅ Videos + real stories | ❌ Claims only |
| **Survives target going inactive** | ✅ Change `USER_ADDRESSES` | ⚠️ Tied to one influencer |
| **Trade aggregation** | ✅ | ❌ |
| **Tiered multipliers** | ✅ | ❌ Fixed multiplier only |
| **Simulation / audit** | ✅ | ❌ |
| **Multi-trader** | ✅ | ⚠️ Limited |

---

## 🎯 Who This Is For

**Good fit:**

- Traders who want **passive exposure** to wallets they trust
- Users comfortable running **Python 3.10+** and a `.env` file
- People who understand **on-chain risk**, gas, and that leaders change over time

**Not a fit:**

- Anyone expecting **guaranteed** profits or a forever hands-off money printer
- Complete beginners who will not monitor logs or rotate targets when activity drops

---

## Quick Start

### Prerequisites

- **Python 3.10+**
- **MongoDB** — [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register) free tier is fine
- **Polygon wallet** — USDC for trading, POL/MATIC for gas
- **RPC URL** — [Infura](https://infura.io) or [Alchemy](https://www.alchemy.com)

### Installation

```bash
git clone https://github.com/dexorynLabs/polymarket-copy-trading-bot-v2.0.git
cd polymarket-copy-trading-bot-v2.0

pip install -r requirements.txt

python -m src.scripts.setup.setup
python -m src.scripts.setup.system_status
python -m src.main
```

Optional: `pip install -e .` then run `polymarket-bot` (see `pyproject.toml`).

**Help:** [@dexoryn777](https://t.me/dexoryn777) on Telegram.

---

## Configuration

Copy `.env.example` to `.env` and fill in secrets. The setup wizard writes most fields for you.

### Essential variables

| Variable | Description | Example |
|----------|-------------|---------|
| `USER_ADDRESSES` | Wallets to copy (comma-separated or JSON array) | `'0xABC..., 0xDEF...'` |
| `PROXY_WALLET` | Your Polygon trading wallet | `'0x123...'` |
| `PRIVATE_KEY` | Private key (**no** `0x` prefix) | `'abc...'` |
| `MONGO_URI` | MongoDB connection string | `'mongodb+srv://...'` |
| `RPC_URL` | Polygon RPC | `'https://polygon-mainnet...'` |
| `USDC_CONTRACT_ADDRESS` | USDC on Polygon (default in example) | `'0x2791...'` |
| `CLOB_HTTP_URL` | Polymarket CLOB API | `'https://clob.polymarket.com'` |
| `COPY_STRATEGY` | `PERCENTAGE`, `FIXED`, or `ADAPTIVE` | `PERCENTAGE` |
| `COPY_SIZE` | % or USD depending on strategy | `10.0` |
| `FETCH_INTERVAL` | Poll interval in seconds (default `1`) | `1` |
| `PREVIEW_MODE` | `true` = monitor only, no orders | `false` |
| `TRADE_AGGREGATION_ENABLED` | Batch small trades (default `false`) | `true` |
| `TRADE_AGGREGATION_WINDOW_SECONDS` | Wait time before batching (default `300`) | `300` |

For `TIERED_MULTIPLIERS`, safety caps, and legacy `TRADE_MULTIPLIER`, see **`.env.example`**.

### Find active traders to copy

```bash
python -m src.scripts.research.find_best_traders
python -m src.scripts.research.scan_best_traders
```

Always verify wallet activity and risk before copying.

---

## Safety & Risk Management

⚠️ **This bot places real trades with real funds.**

- Start small; use `PREVIEW_MODE=true` first
- **Rotate targets** when a trader goes quiet—Gabagool22 is a lesson, not a permanent setting
- Copy **multiple** wallets when possible; don't rely on one address
- Check logs daily; run `python -m src.scripts.setup.system_status` before live runs
- Past performance (including the videos) **does not** guarantee future results

1. Use a dedicated wallet with limited balance  
2. Never commit `.env` or share `PRIVATE_KEY`  
3. Know how to stop the bot (`Ctrl+C`)  
4. Research wallets before adding them to `USER_ADDRESSES`

---

## FAQ

**Can I still copy Gabagool22?**  
You can set any address, but Gabagool22 is **not recommended** anymore—activity dropped. Use research scripts or your own list of **currently active** traders.

**What if my target stops trading?**  
The bot keeps running; you won't see new copies until you point `USER_ADDRESSES` at active wallets. That's expected—not a bot failure.

**Does this work on all Polymarket markets?**  
Standard markets are supported; exotic or illiquid cases may fail individually and get logged/retried.

**Is this open source?**  
Yes. A maintained premium build with extra support is also available via Telegram.

---

## Author & Contact

**Dexoryn Labs** — Polymarket copy-trading automation

- **Telegram**: [@dexoryn777](https://t.me/dexoryn777) (fastest)
- **Discord**: `dexoryn777`
- **Twitter**: [@dexoryn](https://x.com/dexoryn)
- **GitHub**: [@dexorynLabs](https://github.com/dexorynLabs)
- **WeChat**: scan to add **DexorynWe**

<p align="center">
  <img src="wechat.png" alt="WeChat QR code — scan to add DexorynWe as a friend" width="280"/>
</p>

---

## Contributing

1. Fork the repo  
2. `git checkout -b feature/your-feature`  
3. Commit and push  
4. Open a Pull Request  

---

## Legal Disclaimer

Trading on Polymarket involves **substantial risk of loss**. Dexoryn is not responsible for losses from using this software. You are solely responsible for wallet security, target selection, and capital at risk.

**Only trade with funds you can afford to lose.**

---

If this project helps you, consider ⭐ starring the repo or opening issues/PRs. Questions: [@dexoryn777](https://t.me/dexoryn777).
