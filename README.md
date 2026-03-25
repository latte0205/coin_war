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

## 環境變數

在專案根目錄建立 `.env` 檔：

```
FINMIND_TOKEN=你的token
```

## License

MIT
