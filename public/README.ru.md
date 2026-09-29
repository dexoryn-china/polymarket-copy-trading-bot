# Polymarket Bot | Торговый бот Polymarket | Бот копи-трейдинга Polymarket

**Языки:** [English](../public/README.en.md) · [中文](../README.md) · [Русский](README.ru.md)

> **Автоматический бот копи-трейдинга Polymarket - зеркалит активных трейдеров в реальном времени**  
> **Predictions & Perps • Несколько кошельков • Web-дашборд • Проверено в live • Реальное исполнение on-chain**

> **Нужна помощь или обновлённая сборка?**  
> 📱 **Telegram**: [t.me/dexoryn](https://t.me/dexoryn) | 🎮 **Discord**: `dexoryn_`

---

## 🎥 Видео с реальной прибылью (архив - Gabagool22)

Эти записи сделаны, пока **@gabagool22** активно торговал. На видео бот выполняет реальные копи-сделки в сети - не симуляцию.

**Кошелёк (историческая цель):** `0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d`

> **Важно:** Gabagool22 больше не надёжная цель. Видео подтверждают live-работу в продакшене - см. [Историю 3](#story-3--bot-still-running-after-gabagool22-stopped), как мы переключились на активных лидеров.

### Видео 1 - Live-копирование

https://github.com/user-attachments/assets/2194ef92-b0f7-40e1-9835-4d2965e85e81

- **+$80 прибыли за ~15 минут**
- Бот работал без присмотра
- Реальное исполнение on-chain, не симуляция

### Видео 2 - Второй запуск (подтверждение)

https://github.com/user-attachments/assets/df3a6791-89b5-4230-ae40-fb7130dcadc4

- **Ещё +$230 за следующие ~15 минут**
- Тот же бот, та же логика, отдельный запуск
- Полностью автоматический копи-трейдинг

---

## 📖 Истории из live (реальное использование)

### История 1 - Сессия без присмотра (эпоха Gabagool22)

После обновления бота я запустил его для проверки новой логики и ушёл играть в бильярд с друзьями - бот продолжал работать.

Примерно через час после возвращения:

- ✅ Бот работал штатно
- ✅ Копирование было точным
- ✅ Сделки совпадали с транзакциями целевого трейдера
- ✅ Уже была зафиксирована прибыль

Это полностью автономный live-запуск, не симуляция и не бэктест.

---

### История 2 - Повторяемый результат (видеозаписи)

Два видео выше - из **разных live-сессий** в разные дни. Один код, один конвейер мониторинга и исполнения - без ручных кликов в Polymarket. Мы оптимизируем **стабильную автоматизацию**, а не разовую удачу.

---

### История 3 - Бот работает после того, как Gabagool22 перестал быть целью

<a id="story-3--bot-still-running-after-gabagool22-stopped"></a>

Gabagool22 со временем **снизил активность и перестал быть практичной целью** - меньше сделок, другая модель или просто неактивность. Многие копи-трейдеры упираются в ту же стену: кошелёк, который работал в прошлом месяце, замолкает, и бот кажется «сломанным», хотя проблема в **отсутствии сигнала**, а не в софте.

Что мы сделали:

- Оставили **тот же бот** - без переписывания и «нового продукта»
- Добавили **новые активные кошельки** как цели в дашборде (сохраняется в `targets.yaml`)
- Проверили весь пайплайн: детекция → размер позиции → ордер → логирование

Что увидели:

- ✅ Процесс стабилен
- ✅ Сделки новой цели детектируются и копируются корректно
- ✅ История активности и `state.json` обновляются как ожидается
- ✅ Сбои только в отдельных рыночных/ордерных кейсах, а не «бот умер вместе с Gabagool22»

#### Идеальный результат копи-трейдинга - зеркало **securebet**

После смены цели мы копировали [**securebet**](https://polymarket.com/@securebet) и сделали такой скриншот:

<p align="center">
  <img src="Realtradehistory/securebet.jpg" alt="PnL копи-трейдинга: кошелёк бота vs securebet - совпадение формы графика" width="100%"/>
</p>

**Так и должен выглядеть правильный копи-трейдинг.** Слева - ваш кошелёк бота, справа - целевой трейдер: **одинаковая форма графика PnL** за день - тот же флэт, просадка и отскок в конце. Суммы в долларах отличаются из-за настроек размера и баланса, но **кривая следует за лидером** - сделки детектируются и зеркалируются синхронно.

Те же рынки в вкладках activity/history в той же сессии (например, temperature markets на скриншоте). Это и есть доказательство для трейдеров: **следуете за кошельком - получаете ту же форму equity curve.**

**Вывод для трейдеров:** бот следует за **любым адресом, который вы зададите**. Когда трейдер перестаёт подходить - **меняйте адрес, а не бота.** Прошлые результаты Gabagool22 не гарантируют будущее на любой цели.

---

## ⭐ Возможности

Видео и истории выше - из пайплайна **predictions**. Эта сборка добавляет полноценную платформу:

- **Multi-wallet copy** - несколько лидеров, у каждого свой sizing и cap
- **Web-дашборд** `http://127.0.0.1:8787` - цели, активность, позиции, настройки
- **Predictions + Perps** - один активный venue; переключение в дашборде
- **WebSocket**, share batching, опциональное зеркало выходов (`copy_closes`), Telegram
- **Dry-run** и состояние в `state.json`, `history.db`

| Функция | Этот бот | Альтернативы |
|---------|----------|--------------|
| Live-доказательства | ✅ Видео + истории выше | ❌ Только слова |
| Multi-wallet + дашборд | ✅ | ❌ Один адрес / CLI |
| Perps + зеркало выходов | ✅ | ❌ Только predictions / вход |
| Смена цели при затихании | ✅ В UI | ⚠️ Один кошелёк |
| WebSocket + dry-run | ✅ | ⚠️ Polling / без симуляции |

**Подходит:** пассивный копи-трейдинг на **Python 3.10+** с контролем **Activity**. **Не подходит:** гарантированная прибыль, predictions + perps одновременно, публичный дашборд без `web.token`.

---

**Перейти:** [Быстрый старт](#-быстрый-старт) · [Дашборд](#-дашборд) · [Конфигурация](#конфигурация) · [FAQ](#faq)

## 🚀 Быстрый старт

### Требования

- **Python 3.10+**
- **Кошелёк Polygon** - USDC для predictions, POL/MATIC для gas (`mode: real`)
- **Polymarket CLOB API** - для live-ордеров на prediction markets
- **Пополненный Perps-аккаунт** - только для live Perps
- **Node.js 18+** - только если пересобираете UI дашборда

### Установка

```bash
git clone https://github.com/dexorynlabs/polymarket-trading-bot-python.git
cd polymarket-trading-bot-python

pip install -r requirements.txt

cp config.yaml.example config.yaml
# mode, web, секреты polymarket (real mode)

python -m app.main
```

### Первый запуск

1. Оставьте **`mode: dry_run`** в `config.yaml`
2. **http://127.0.0.1:8787** → **Targets** → кошелёк, venue, sizing → **Start**
3. Проверьте **Activity**, затем **`mode: real`**, перезапуск, **Start** с малым размером

UI (опционально): `cd ui && npm install && npm run build` · см. [`ui/README.md`](../ui/README.md)

**Помощь:** Telegram [@dexoryn](https://t.me/dexoryn)

---

## 🖥 Дашборд

После одноразовой настройки `config.yaml` работайте через дашборд. Цели → `targets.yaml`, tuning → `settings.yaml`. Legacy `target_wallet` мигрирует при первом запуске.

| Страница | Назначение |
|----------|------------|
| **Overview** | Статус копирования, venue, latency |
| **Targets** | Добавление, правка, pause лидеров |
| **Activity** | Live-лента fills и результатов |
| **Positions** | Экспозиция и headroom |
| **Settings** | Sizing, slippage, уведомления |

**Perps:** `venue: perps`, пополните на [polymarket.com](https://polymarket.com). Polling публичного профиля лидера; IOC limits по mark ± slippage.

> **Один venue за раз** - predictions или perps, не оба. Держите `web.host: 127.0.0.1`, если не задан `web.token`.

---

## Конфигурация

| Слой | Файл | Назначение |
|------|------|------------|
| Bootstrap | `config.yaml` | `mode`, API-секреты, web/Telegram, defaults |
| Runtime | `targets.yaml` | Лидеры (страница **Targets**) |
| Runtime | `settings.yaml` | Tuning (страница **Settings**) |

Дашборд перекрывает matching keys в `config.yaml`.

### Основной `config.yaml`

| Настройка | Описание | Пример |
|-----------|----------|--------|
| `mode` | `dry_run` симулирует; `real` постит ордера | `dry_run` |
| `copy.venue` | Начальный venue | `predictions` |
| `web.enabled` | Включить дашборд | `true` |
| `web.host` / `web.port` | Bind | `127.0.0.1` / `8787` |
| `web.token` | Опциональная auth | `""` |
| `risk.max_open_usd_total` | Cap по prediction-целям | `null` |
| `execution.order_type` | `taker` (FAK) или `maker` (GTC) | `taker` |
| `slippage.entry_bps_max` | Макс. slippage BUY (bps) | `1000` |

При `mode: real` заполните `polymarket:`. Поля на цель (`wallet`, `venue`, `enabled`, `copy_closes`, `sizing.*`) - в дашборде. Полный справочник: **`config.yaml.example`**.

---

## Безопасность и риски

⚠️ **`mode: real` - реальные средства.** Отдельный кошелёк с ограниченным балансом, консервативные caps, `logs/copybot.log`, не коммитьте секреты. Прошлое не гарантирует будущее.

---

## FAQ

**Нужен `config.yaml` с дашбордом?**  
Да - для `mode`, API, web/Telegram. Цели и tuning - в дашборде.

**Где логи и состояние?**  
`logs/copybot.log`, `history.db`, `state.json`, `settings.yaml` (gitignored, кроме example).

**Это open source?**  
Да. Также есть premium-сборка с поддержкой в Telegram.

---

## Автор и контакты

**Dexoryn Labs** - автоматизация копи-трейдинга Polymarket

- **Telegram**: [@dexoryn](https://t.me/dexoryn) (быстрее всего)
- **Discord**: `dexoryn_`
- **Twitter**: [@dexoryn](https://x.com/dexoryn)
- **GitHub**: [@dexorynLabs](https://github.com/dexorynLabs)
- **WeChat**: отсканируйте **DexorynWe**

<p align="center">
  <img src="dexoryn_tg.jpg" alt="QR Telegram - @dexoryn" height="260"/>
  &nbsp;&nbsp;
  <img src="dexoryn_wechat.png" alt="QR WeChat - DexorynWe" height="260"/>
</p>

---

## Участие в разработке

См. [CONTRIBUTING.md](../.github/CONTRIBUTING.md). Кратко: fork → branch → `pytest` → PR.

Сообщество: [Code of Conduct](../.github/CODE_OF_CONDUCT.md) · [Security](../.github/SECURITY.md) · [MIT License](../LICENSE)

---

## Правовое предупреждение

Торговля на Polymarket сопряжена с **существенным риском убытков**. Dexoryn не несёт ответственности за потери. Вы отвечаете за кошелёк, цели и капитал.

**Торгуйте только средствами, потерю которых вы можете себе позволить.**

Вопросы: Telegram [@dexoryn](https://t.me/dexoryn) · ⭐ Star, если полезно.
