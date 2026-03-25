# coin_war

台股訊號分析 + 加密貨幣跨所套利系統

## 安裝

```bash
curl -sSL https://raw.githubusercontent.com/latte0205/coin_war/master/install.sh | bash
```

## 使用方式

```bash
# 查看說明
coinwar --help

# 掃描台股訊號
coinwar scan

# 加密貨幣套利（模擬）
coinwar arb --dry-run

# 加密貨幣套利（真實下單）
coinwar arb --run

# 回測
coinwar backtest --ticker 2330

# 顯示持倉
coinwar positions

# 批次下載資料
coinwar download
```

## 環境變數設定

複製範例檔並填入你的 API key：

```bash
cp .env.example .env
```

編輯 `.env`：

```
# 台股資料（於 https://finmindtrade.com/ 免費申請）
FINMIND_TOKEN=你的token

# 加密貨幣交易所 API（依需求填入）
BINANCE_API_KEY=
BINANCE_API_SECRET=
OKX_API_KEY=
OKX_API_SECRET=
OKX_PASSPHRASE=
BYBIT_API_KEY=
BYBIT_API_SECRET=
MAX_API_KEY=
MAX_API_SECRET=
BITOPRO_API_KEY=
BITOPRO_API_SECRET=
```

> `.env` 已列入 `.gitignore`，不會被上傳到 GitHub。

## License

MIT
