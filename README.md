# Polymarket 机器人 | Polymarket 交易机器人 | Polymarket 跟单机器人

**语言：** [English](public/README.en.md) · [中文](README.md) · [Русский](public/README.ru.md)

> **实时镜像活跃交易者的 Polymarket 自动跟单机器人**  
> **预测市场 & 永续 • 多钱包 • Web 仪表盘 • 实盘验证 • 真实链上执行**

> **需要帮助或更新版本？**  
> 📱 **Telegram**：[t.me/dexoryn](https://t.me/dexoryn) | 🎮 **Discord**：`dexoryn_`

---

## 🎥 实盘盈利视频（历史记录 - Gabagool22）

这些录像拍摄于 **@gabagool22** 仍活跃交易期间，展示机器人在链上执行真实跟单，而非模拟。

**钱包（历史跟单目标）：** `0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d`

> **说明：** Gabagool22 已不再是可靠的跟单对象。视频仍可证明实盘生产环境运行--见下方 [故事 3](#story-3--bot-still-running-after-gabagool22-stopped) 了解如何更换活跃领头。

### 视频 1 - 实盘跟单运行

https://github.com/user-attachments/assets/2194ef92-b0f7-40e1-9835-4d2965e85e81

- **约 15 分钟内 +$80 盈利**
- 本次会话全程无人值守
- 真实链上执行，非模拟

### 视频 2 - 第二次运行（验证）

https://github.com/user-attachments/assets/df3a6791-89b5-4230-ae40-fb7130dcadc4

- **随后约 15 分钟再 +$230**
- 同一机器人、同一逻辑、独立运行
- 全自动跟单

---

## 📖 实盘故事（真实使用）

### 故事 1 - 无人值守会话（Gabagool22 时期）

更新机器人逻辑后，我启动测试并出门和朋友打台球，机器人持续运行。

约一小时后返回：

- ✅ 机器人运行正常
- ✅ 跟单准确
- ✅ 成交与目标交易者一致
- ✅ 已产生盈利

这是完全无人值守的实盘运行，不是模拟或回测。

---

### 故事 2 - 可重复的表现（视频运行）

上方两段视频来自**不同日期**的两次实盘会话。同一套代码、同一监控与执行流水线--无需在 Polymarket 上手动点击。我们追求的是**稳定自动化**，而非单次运气。

---

### 故事 3 - Gabagool22 停更后机器人仍正常运行

<a id="story-3--bot-still-running-after-gabagool22-stopped"></a>

Gabagool22 最终**交易减少，不再适合作为跟单目标**--成交变少、策略变化或已不再活跃。很多跟单者会遇到同样问题：上个月好用的钱包安静下来，机器人看起来像「坏了」，但真正原因往往是**没有信号**，而不是软件故障。

我们做了什么：

- **同一套机器人**继续运行--无需重写或换产品
- 在仪表盘中添加**新的活跃钱包**作为目标（保存至 `targets.yaml`）
- 确认完整流程仍正常：检测交易 → 计算仓位 → 下单 → 日志记录

我们观察到：

- ✅ 进程稳定健康
- ✅ 新目标的交易被正确检测并镜像
- ✅ 活动历史与 `state.json` 按预期更新
- ✅ 失败仅出现在个别市场/订单边界情况，而非「Gabagool22 一走机器人就挂了」

#### 完美跟单结果 - 镜像 **securebet**

更换目标后，我们跟单 [**securebet**](https://polymarket.com/@securebet)，并拍下这张对比图：

<p align="center">
  <img src="public/Realtradehistory/securebet.jpg" alt="跟单盈亏：机器人钱包 vs securebet 目标 - 曲线形状一致" width="100%"/>
</p>

**这就是理想跟单应有的样子。** 左侧为你的机器人钱包，右侧为目标交易者，当日 **盈亏曲线形状一致**--相同的横盘、回撤与末尾反弹。美元金额因你的仓位设置与余额而不同，但**曲线跟随领头钱包**，说明交易被及时检测并同步镜像，而非滞后或偏离策略。

同一时段、活动/历史标签页中的市场也一致（例如截图中的温度类市场）。这种对齐才是交易者真正关心的证明：**跟随钱包，获得相同的权益曲线形态。**

**给交易者的结论：** 本机器人跟单**你配置的任何地址**，而非绑定某个「明星钱包」。当某位交易者不再适合你时，**换地址，不要换机器人。** Gabagool22 的过往表现不保证任何目标未来的结果。

---

## ⭐ 功能概览

上方视频与故事来自**预测市场**流水线。本版本在此基础上提供完整平台：

- **多钱包跟单** - 多个领头，各自 sizing 与上限
- **Web 仪表盘** `http://127.0.0.1:8787` - 目标、活动、持仓、设置
- **预测 + 永续** - 同一时间仅一个 venue，在仪表盘中切换
- **WebSocket 检测**、份额批处理、可选退出镜像（`copy_closes`）、Telegram 提醒
- **模拟模式**与持久化状态（`state.json`、`history.db`）

| 功能 | 本机器人 | 常见替代 |
|------|----------|----------|
| 实盘执行证明 | ✅ 上方视频与故事 | ❌ 仅宣传 |
| 多钱包 + 仪表盘 | ✅ | ❌ 单地址 / CLI |
| 永续 + 退出镜像 | ✅ | ❌ 仅预测 / 仅入场 |
| 领头停更后换目标 | ✅ 仪表盘 | ⚠️ 绑定单一钱包 |
| WebSocket + 模拟模式 | ✅ | ⚠️ 轮询 / 无模拟 |

**适合：** 使用 **Python 3.10+** 并会查看 **活动** 的被动跟单者。**不适合：** 保证盈利、同时跟单预测+永续、或未设 `web.token` 就公开仪表盘。

---

**跳转：** [快速开始](#-快速开始) · [仪表盘](#-仪表盘) · [配置](#配置) · [常见问题](#常见问题)

## 🚀 快速开始

### 环境要求

- **Python 3.10+**
- **Polygon 钱包** - 预测市场用 USDC，gas 用 POL/MATIC（`mode: real`）
- **Polymarket CLOB API 凭证** - 预测市场实盘下单
- **已充值的永续账户** - 仅在 `real` 模式下跟单永续时需要
- **Node.js 18+** - 仅在你自行构建仪表盘 UI 时需要

### 安装

```bash
git clone https://github.com/dexoryn-china/polymarket-copy-trading-bot.git
cd polymarket-copy-trading-bot

pip install -r requirements.txt

cp config.yaml.example config.yaml
# 编辑 config.yaml：mode、web 设置、polymarket 密钥（real 模式）

python -m app.main
```

### 首次运行

1. 在 `config.yaml` 中保持 **`mode: dry_run`**
2. 打开 **http://127.0.0.1:8787** → **目标** → 添加钱包、venue、sizing → **Start**
3. 在 **活动** 中确认成交后，设 **`mode: real`**，重启，小仓位再次 **Start**

UI 重建（可选）：`cd ui && npm install && npm run build` · 见 [`ui/README.md`](../ui/README.md)

**帮助：** Telegram [@dexoryn](https://t.me/dexoryn)

---

## 🖥 仪表盘

完成一次性 `config.yaml` 配置后，通过仪表盘运行机器人。目标保存至 `targets.yaml`，调参保存至 `settings.yaml`。旧版单 `target_wallet` 首次启动自动迁移。

| 页面 | 用途 |
|------|------|
| **概览** | 跟单状态、活跃 venue、延迟快照 |
| **目标** | 添加、编辑、启用或暂停领头钱包 |
| **活动** | 检测到的成交与跟单结果实时流 |
| **持仓** | 当前敞口与剩余额度 |
| **设置** | sizing、滑点、通知 |

**永续：** 目标 `venue: perps`，在 [polymarket.com](https://polymarket.com) 充值。轮询领头公开资料检测组合变化；订单为 mark ± 滑点的 IOC 限价单。

> **同一时间仅一个 venue** - 预测或永续，不能同时。除非设置了 `web.token`，请保持 `web.host: 127.0.0.1`。

---

## 配置

| 层级 | 文件 | 用途 |
|------|------|------|
| 启动 | `config.yaml` | `mode`、API 密钥、web/Telegram、全局默认 |
| 运行 | `targets.yaml` | 领头钱包（在 **目标** 页管理） |
| 运行 | `settings.yaml` | 交易调参（在 **设置** 页管理） |

仪表盘值会覆盖 `config.yaml` 中的对应项。

### `config.yaml` 核心项

| 设置 | 说明 | 示例 |
|------|------|------|
| `mode` | `dry_run` 模拟；`real` 提交订单 | `dry_run` |
| `copy.venue` | 开始跟单时的初始 venue | `predictions` |
| `web.enabled` | 启用仪表盘 | `true` |
| `web.host` / `web.port` | 绑定地址 | `127.0.0.1` / `8787` |
| `web.token` | 可选仪表盘认证 | `""` |
| `risk.max_open_usd_total` | 预测目标总敞口上限（可选） | `null` |
| `execution.order_type` | `taker`（FAK）或 `maker`（GTC） | `taker` |
| `slippage.entry_bps_max` | BUY 最大滑点（bps） | `1000` |

`mode: real` 时填写 `polymarket:`。每目标字段（`wallet`、`venue`、`enabled`、`copy_closes`、`sizing.*`）在仪表盘中设置。完整说明见 **`config.yaml.example`**。

---

## 安全与风险

⚠️ **`mode: real` 使用真实资金。** 请使用余额有限的专用钱包、设置保守的单目标上限、查看 `logs/copybot.log`、切勿提交密钥。过往表现不保证未来结果。

---

## 常见问题

**用了仪表盘还需要 `config.yaml` 吗？**  
需要 - 用于 `mode`、API 密钥与 web/Telegram。目标与日常调参在仪表盘中管理。

**日志与状态存在哪里？**  
`logs/copybot.log`、`history.db`、`state.json`、`settings.yaml`（均已 gitignore，示例配置除外）。

**是否开源？**  
是。另有维护中的高级版本，可通过 Telegram 获取额外支持。

---

## 作者与联系

**Dexoryn Labs** - Polymarket 跟单自动化

- **Telegram**：[@dexoryn](https://t.me/dexoryn)（回复最快）
- **Discord**：`dexoryn_`
- **Twitter**：[@dexoryn](https://x.com/dexoryn)
- **GitHub**：[@dexorynLabs](https://github.com/dexorynLabs)
- **微信**：扫码添加 **DexorynWe**

<p align="center">
  <img src="public/dexoryn_tg.jpg" alt="Telegram 二维码 - @dexoryn" height="260"/>
  &nbsp;&nbsp;
  <img src="public/dexoryn_wechat.png" alt="微信二维码 - DexorynWe" height="260"/>
</p>

---

## 贡献

详见 [CONTRIBUTING.md](.github/CONTRIBUTING.md)。简要：Fork → 分支 → `pytest` → PR。

社区：[行为准则](.github/CODE_OF_CONDUCT.md) · [安全](.github/SECURITY.md) · [MIT 许可证](LICENSE)

---

## 法律声明

在 Polymarket 交易存在**重大亏损风险**。Dexoryn 不对使用本软件造成的损失负责。钱包安全、目标选择与资金风险由您自行承担。

**请仅使用您能承受损失的资金进行交易。**

问题咨询：Telegram [@dexoryn](https://t.me/dexoryn) · 有帮助请 ⭐ Star。
