# OANDA practice 統合テスト

OANDA v20 REST API の **practice 環境のみ** を対象にした統合テストです。
目的は「実際に儲かるか」ではなく、**注文が安全に出せる・止められる・閉じられる・監査ログに残る**
ことの確認です。

## 安全方針

- **practice 専用**。live endpoint / live account は対象外です。
- `OANDA_ENV` が live を示す値（`live` / `fxtrade` / `trade` / `real` / `production` / `prod`）の場合は
  テストを **fail** させます。
- live_trade は有効化しません（`SafetyGuard(enable_live_trading=False)` を必ず経由）。
- **token / account_id をログに平文出力しない**でください。テストでも値を assert / print しません。
  監査ログに残す broker_data は `sanitize_broker_data()` で秘匿します。
- 注文系テストは既定で無効。明示的に許可した場合のみ、**極小 units** で実行します。
- CI では実行しません（既定の `pytest` から除外されます）。

## 必要な環境変数

| 変数 | 必須 | 既定 | 説明 |
| --- | --- | --- | --- |
| `OANDA_ENV` | 必須 | `practice` | `practice` 以外は skip、live を示す値は fail |
| `OANDA_API_TOKEN` | 必須 | — | practice の API トークン（ログ出力禁止） |
| `OANDA_ACCOUNT_ID` | 必須 | — | practice の account id（ログ出力禁止） |
| `OANDA_PRACTICE_INSTRUMENT` | 任意 | `USD_JPY` | 対象通貨ペア |
| `OANDA_PRACTICE_UNITS` | 任意 | `1` | 取引 units。1〜10 のみ許可（>10 は fail） |
| `OANDA_PRACTICE_ALLOW_ORDERS` | 任意 | （未設定） | `true` のときだけ注文系テストを実行 |

認証情報が無い場合、テストは **skip**（fail ではない）されます。

## pytest marker

- `integration` — 外部サービスへ接続するテスト
- `oanda_practice` — OANDA practice account への実呼び出し

既定の `pytest` では `addopts = "-m 'not oanda_practice'"` により **除外** されます。

## 実行方法

### read-only smoke test（注文なし）

```bash
OANDA_ENV=practice \
OANDA_API_TOKEN=*** \
OANDA_ACCOUNT_ID=*** \
.venv/bin/python -m pytest -m oanda_practice \
  tests/integration/oanda/test_oanda_practice_readonly.py
```

確認内容：account summary / instrument 定義 / pricing / tick / candle の取得、
および InstrumentSpec へ反映できるフィールド（pipLocation / displayPrecision /
tradeUnitsPrecision）の存在。

### order smoke test（極小 units、要明示許可）

```bash
OANDA_ENV=practice \
OANDA_API_TOKEN=*** \
OANDA_ACCOUNT_ID=*** \
OANDA_PRACTICE_INSTRUMENT=USD_JPY \
OANDA_PRACTICE_UNITS=1 \
OANDA_PRACTICE_ALLOW_ORDERS=true \
.venv/bin/python -m pytest -m oanda_practice \
  tests/integration/oanda/test_oanda_practice_order.py \
  tests/integration/oanda/test_oanda_practice_reject.py
```

確認内容：

- MARKET + SL/TP + `client_order_id`（prefix `practice-smoke-`）で 1 件発注
- broker_data に OANDA レスポンス（transaction id 等）が残る
- 発注後に必ず `close_position()` でフラット化し、対象 instrument のポジションを残さない
- 不正 units は OANDA 到達前に `SafetyGuard` が拒否する
- OANDA が拒否した注文は reject 情報が broker_data と監査ログに残る

### 既定（オフライン / CI）

```bash
.venv/bin/python -m pytest            # oanda_practice は除外
.venv/bin/python -m pytest -m "not oanda_practice"
```

## live では実行しない

このテスト群は practice 専用です。live account / live endpoint では実行しないでください。
`OANDA_ENV` を live 相当にすると意図的に fail します。

## 失敗時にポジションが残った場合の確認手順

order smoke test は `finally` で必ず `close_position()` を呼びますが、ネットワーク断などで
ポジションが残る可能性があります。その場合は以下で確認・解消してください。

1. OANDA practice の Web 取引画面でオープンポジション / pending order を確認
2. 残っていれば手動でクローズ
3. プログラムから確認する場合（practice、注文許可は不要）:

```bash
OANDA_ENV=practice OANDA_API_TOKEN=*** OANDA_ACCOUNT_ID=*** \
.venv/bin/python -m pytest -m oanda_practice \
  tests/integration/oanda/test_oanda_practice_readonly.py
```

> 注意: 残ポジションの自動クローズスクリプトは本リポジトリには含めていません。
> 誤操作防止のため、解消は手動確認のうえで行ってください。
