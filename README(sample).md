# Polymarket 机器人 | Polymarket 交易机器人 | Polymarket 跟单机器人

**语言：** [English](README.en.md) · [中文](README.md) · [Русский](README.ru.md)

> **实时镜像活跃交易者的 Polymarket 自动跟单机器人**  
> **实盘验证 • 真实链上执行 • 随时更换跟单目标**

> **需要帮助或更新版本？**  
> 📱 **Telegram**：[t.me/dexoryn](https://t.me/dexoryn) | 🎮 **Discord**：`dexoryn777`

---

## 🎥 实盘盈利视频（历史记录 — Gabagool22）

这些录像拍摄于 **@gabagool22** 仍活跃交易期间，展示机器人在链上执行真实跟单，而非模拟。

**钱包（历史跟单目标）：** `0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d`

> **说明：** Gabagool22 已不再是可靠的跟单对象。视频仍可证明机器人曾在生产环境正常运行；请将 `USER_ADDRESSES` 指向**当前仍活跃**的交易者。见下方 [故事 3](#story-3--bot-still-running-after-gabagool22-stopped)。

### 视频 1 — 实盘跟单运行

https://github.com/user-attachments/assets/2194ef92-b0f7-40e1-9835-4d2965e85e81

- **约 15 分钟内 +$80 盈利**
- 本次会话全程无人值守
- 真实链上执行，非模拟

### 视频 2 — 第二次运行（验证）

https://github.com/user-attachments/assets/df3a6791-89b5-4230-ae40-fb7130dcadc4

- **随后约 15 分钟再 +$230**
- 同一机器人、同一逻辑、独立运行
- 全自动跟单

---

## 📖 实盘故事（真实使用）

### 故事 1 — 无人值守会话（Gabagool22 时期）

更新机器人逻辑后，我启动测试并出门和朋友打台球，机器人持续运行。

约一小时后返回：

- ✅ 机器人运行正常
- ✅ 跟单准确
- ✅ 成交与目标交易者一致
- ✅ 已产生盈利

这是完全无人值守的实盘运行，不是模拟或回测。

---

### 故事 2 — 可重复的表现（视频运行）

上方两段视频来自**不同日期**的两次实盘会话。同一套代码、同一监控与执行流水线——无需在 Polymarket 上手动点击。我们追求的是**稳定自动化**，而非单次运气。

---

### 故事 3 — Gabagool22 停更后机器人仍正常运行

<a id="story-3--bot-still-running-after-gabagool22-stopped"></a>

Gabagool22 最终**交易减少，不再适合作为跟单目标**——成交变少、策略变化或已不再活跃。很多跟单者会遇到同样问题：上个月好用的钱包安静下来，机器人看起来像「坏了」，但真正原因往往是**没有信号**，而不是软件故障。

我们做了什么：

- **同一套机器人**继续运行——无需重写或换产品
- 将 `USER_ADDRESSES` 更新为**其他活跃的 Polymarket 钱包**（可使用 `src/scripts/research/` 下的研究脚本，或自行尽调）
- 确认完整流程仍正常：检测交易 → 计算仓位 → 下单 → 日志记录

我们观察到：

- ✅ 进程稳定健康
- ✅ 新目标的交易被正确检测并镜像
- ✅ 日志与 MongoDB 历史按预期更新
- ✅ 失败仅出现在个别市场/订单边界情况，而非「Gabagool22 一走机器人就挂了」

#### 完美跟单结果 — 镜像 **securebet**

更换目标后，我们跟单 [**securebet**](https://polymarket.com/@securebet)，并拍下这张对比图：

<p align="center">
  <img src="Realtradehistory/securebet.jpg" alt="跟单盈亏：机器人钱包 vs securebet 目标 — 曲线形状一致" width="100%"/>
</p>

**这就是理想跟单应有的样子。** 左侧为你的机器人钱包，右侧为目标交易者，当日 **盈亏曲线形状一致**——相同的横盘、回撤与末尾反弹。美元金额因你的仓位设置（`COPY_SIZE`、倍数与余额）而不同，但**曲线跟随领头钱包**，说明交易被及时检测并同步镜像，而非滞后或偏离策略。

同一会话中，活动/历史标签页出现相同市场（如截图中的气温类市场）。交易者最在意的证明是：**跟对钱包，就能得到相同的资金曲线形态。**

**给交易者的结论：** 本机器人跟单**你配置的任何地址**，而非绑定某个「明星钱包」。当某位交易者不再适合你时，**换地址，不要换机器人。** Gabagool22 的过往表现不保证任何目标未来的结果。

---

## ⭐ 为什么选择本机器人

### 🎯 真实证明，而非空口宣传

许多 Polymarket 机器人只有截图。本仓库提供**实盘视频**与上述故事——包括在明星交易者停更后**仍能正常运行**。

### 🚀 架构与性能

- **集中式 `data/` 目录** — 日志、缓存与模拟结果统一管理
- **异步优先** — 基于 Python `asyncio`，低延迟监控
- **智能缓存** — 减少重复 API 调用

### 💡 交易者真正会用到的功能

- **交易聚合** — 将多笔小单合并为可执行规模（节省 gas，满足 Polymarket 最低额）
- **分层倍数** — 按领头者单笔规模调整仓位（见 `.env.example` 中的 `TIERED_MULTIPLIERS`）
- **跟单策略** — `PERCENTAGE`、`FIXED` 或 `ADAPTIVE` 仓位计算
- **模拟与审计工具** — 实盘前回测与验证
- **多交易者支持** — 同时跟单多个钱包
- **1 秒轮询** — 通过 `FETCH_INTERVAL` 可配置

### 📈 对比

| 功能 | 本机器人 | 常见替代方案 |
|------|----------|----------------|
| **实盘执行证明** | ✅ 视频 + 真实故事 | ❌ 仅宣传 |
| **目标停更后仍可用** | ✅ 更换 `USER_ADDRESSES` | ⚠️ 绑定单一网红钱包 |
| **交易聚合** | ✅ | ❌ |
| **分层倍数** | ✅ | ❌ 仅固定倍数 |
| **模拟 / 审计** | ✅ | ❌ |
| **多交易者** | ✅ | ⚠️ 有限 |

---

## 🎯 适合谁

**适合：**

- 希望**被动跟随**信任钱包的交易者
- 能运行 **Python 3.10+** 并配置 `.env` 的用户
- 理解**链上风险**、gas，以及领头者会随时间变化的人

**不适合：**

- 期望**保证盈利**或永远无需盯盘的「印钞机」心态
- 完全不查看日志、不在活跃度下降时更换目标的新手

---

## 快速开始

### 环境要求

- **Python 3.10+**
- **MongoDB** — [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register) 免费套餐即可
- **Polygon 钱包** — 交易用 USDC，gas 用 POL/MATIC
- **RPC URL** — [Infura](https://infura.io) 或 [Alchemy](https://www.alchemy.com)

### 安装

```bash
git clone https://github.com/dexorynLabs/polymarket-copy-trading-bot-v2.0.git
cd polymarket-copy-trading-bot-v2.0

pip install -r requirements.txt

python -m src.scripts.setup.setup
python -m src.scripts.setup.system_status
python -m src.main
```

可选：`pip install -e .` 后运行 `polymarket-bot`（见 `pyproject.toml`）。

**帮助：** Telegram [@dexoryn](https://t.me/dexoryn)

---

## 配置

将 `.env.example` 复制为 `.env` 并填写密钥。安装向导会写入大部分字段。

### 核心变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `USER_ADDRESSES` | 要跟单的钱包（逗号分隔或 JSON 数组） | `'0xABC..., 0xDEF...'` |
| `PROXY_WALLET` | 你的 Polygon 交易钱包 | `'0x123...'` |
| `PRIVATE_KEY` | 私钥（**不要**加 `0x` 前缀） | `'abc...'` |
| `MONGO_URI` | MongoDB 连接字符串 | `'mongodb+srv://...'` |
| `RPC_URL` | Polygon RPC | `'https://polygon-mainnet...'` |
| `USDC_CONTRACT_ADDRESS` | Polygon 上 USDC（示例中为默认值） | `'0x2791...'` |
| `CLOB_HTTP_URL` | Polymarket CLOB API | `'https://clob.polymarket.com'` |
| `COPY_STRATEGY` | `PERCENTAGE`、`FIXED` 或 `ADAPTIVE` | `PERCENTAGE` |
| `COPY_SIZE` | 依策略为 % 或 USD | `10.0` |
| `FETCH_INTERVAL` | 轮询间隔（秒），默认 `1` | `1` |
| `PREVIEW_MODE` | `true` = 仅监控不下单 | `false` |
| `TRADE_AGGREGATION_ENABLED` | 合并小单（默认 `false`） | `true` |
| `TRADE_AGGREGATION_WINDOW_SECONDS` | 合并等待时间（默认 `300`） | `300` |

`TIERED_MULTIPLIERS`、安全上限及旧版 `TRADE_MULTIPLIER` 见 **`.env.example`**。

### 寻找活跃交易者

```bash
python -m src.scripts.research.find_best_traders
python -m src.scripts.research.scan_best_traders
```

跟单前务必自行核实钱包活跃度与风险。

---

## 安全与风险管理

⚠️ **本机器人使用真实资金进行真实交易。**

- 从小资金开始；先用 `PREVIEW_MODE=true`
- 交易者不活跃时**更换目标**——Gabagool22 是教训，不是永久配置
- 尽可能**跟单多个钱包**，勿依赖单一地址
- 每日查看日志；实盘前运行 `python -m src.scripts.setup.system_status`
- 过往表现（含视频）**不保证**未来结果

1. 使用余额有限的专用钱包  
2. 切勿提交 `.env` 或泄露 `PRIVATE_KEY`  
3. 知道如何停止机器人（`Ctrl+C`）  
4. 将钱包加入 `USER_ADDRESSES` 前做好研究  

---

## 常见问题

**还能跟单 Gabagool22 吗？**  
可以设置任意地址，但 Gabagool22 **已不再推荐**——活跃度下降。请用研究脚本或自建**当前活跃**交易者列表。

**如果目标停止交易怎么办？**  
机器人会继续运行；在将 `USER_ADDRESSES` 指向活跃钱包前不会有新跟单。这是正常现象，不是机器人故障。

**支持所有 Polymarket 市场吗？**  
支持标准市场；冷门或流动性差的情况可能单笔失败并记录/重试。

**是否开源？**  
是。另有维护中的高级版本，可通过 Telegram 获取额外支持。

---

## 作者与联系

**Dexoryn Labs** — Polymarket 跟单自动化

- **Telegram**：[@dexoryn](https://t.me/dexoryn)（回复最快）
- **Discord**：`dexoryn777`
- **Twitter**：[@dexoryn](https://x.com/dexoryn)
- **GitHub**：[@dexorynLabs](https://github.com/dexorynLabs)
- **微信**：扫码添加 **DexorynWe**

<p align="center">
  <img src="dexoryn_tg.jpg" alt="Telegram 二维码 — 扫码打开 @dexoryn" height="280"/>
  &nbsp;&nbsp;
  <img src="dexoryn_wechat.png" alt="微信二维码 — 扫码添加 DexorynWe 为好友" height="280"/>
</p>

---

## 贡献

1. Fork 本仓库  
2. `git checkout -b feature/your-feature`  
3. 提交并推送  
4. 发起 Pull Request  

---

## 法律声明

在 Polymarket 交易存在**重大亏损风险**。Dexoryn 不对使用本软件造成的损失负责。钱包安全、目标选择与资金风险由您自行承担。

**请仅使用您能承受损失的资金进行交易。**

---

若本项目对您有帮助，欢迎 ⭐ Star 本仓库或提交 Issue/PR。问题咨询：Telegram [@dexoryn](https://t.me/dexoryn)。
