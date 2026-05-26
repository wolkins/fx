# FX Trading System

FX自動売買システム。ブローカーアダプターを抽象化し、複数のブローカーに対応可能。

## 対応ブローカー

| ブローカー | 状態 | API |
|---|---|---|
| OANDA (practice) | 対応済 | v20 REST API |
| OANDA (live) | 対応済 (デフォルト無効) | v20 REST API |
| Paper (シミュレーション) | 対応済 | - |
| MT5系 (外為ファイネスト等) | スタブ | MT5 API |

## セットアップ

```bash
pip install -e ".[dev]"
cp .env.example .env
# .env を編集してOANDA API認証情報を設定
```

## 環境変数

| 変数 | 説明 | デフォルト |
|---|---|---|
| `BROKER_TYPE` | `paper` / `oanda` / `mt5` | `oanda` |
| `OANDA_ACCOUNT_ID` | OANDA口座ID | - |
| `OANDA_API_TOKEN` | OANDA APIトークン | - |
| `OANDA_ENV` | `practice` / `live` | `practice` |
| `ENABLE_LIVE_TRADING` | ライブ取引の有効化 | `false` |

## 安全制御

- **ライブ取引はデフォルトで無効**です。`ENABLE_LIVE_TRADING=true` を明示的に設定しない限り、live口座での注文は拒否されます。
- practice口座では自由にデモ取引が可能です。
- ライブ取引を有効化する前に、バックテスト結果とpractice口座でのフォワードテスト結果（30日以上推奨）を確認してください。

## 口座選定に関する注意事項

本システムを利用する際は、以下を**ユーザー自身の責任**で確認してください：

1. **金融庁登録業者であること** — 金融庁の[免許・許可・登録等を受けている業者一覧](https://www.fsa.go.jp/menkyo/menkyo.html)で確認できます
2. デモ口座またはpractice環境が利用可能であること
3. 利用規約上、API経由の自動売買が禁止されていないこと
4. スプレッド・約定力・取引単位・手数料が明示されていること

## テスト

```bash
pytest
```

## アーキテクチャ

```
BrokerAdapter (ABC)
├── OandaAdapter    — OANDA v20 REST API
├── PaperBroker     — インメモリシミュレーション
└── MT5Adapter      — MT5 stub (将来実装)

SafetyGuard — ライブ取引の安全制御ラッパー
BrokerCapabilities — 各ブローカーの機能記述
```
