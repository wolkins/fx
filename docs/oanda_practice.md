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

- **発注前に対象 instrument がフラット（ポジションなし）であることを必須とする**。
  既存ポジションがあれば **fail して注文を出さない**（後述）
- **protective mode を有効にする**（後述）。SL/TP/`client_order_id` のない OPEN は
  OANDA 到達前に `SafetyGuard` が拒否する
- MARKET + SL/TP + `client_order_id`（prefix `practice-smoke-`）で 1 件発注
- broker_data に OANDA レスポンス（transaction id 等）が残る
- 発注後（注文送信時のみ）に `close_position()` でフラット化し、対象 instrument のポジションを残さない
- 不正 units は OANDA 到達前に `SafetyGuard` が拒否する
- OANDA が **実際に** 拒否した注文は reject 情報が broker_data と監査ログに残る
  （この確認のみ protective mode を意図的に外す）

### protective orders mode（practice でも live 相当の OPEN 保護）

`SafetyGuard` は live OPEN に対して常に `stop_loss` / `take_profit` / `client_order_id` を必須に
しますが、practice/paper でも同じ保護を強制できる opt-in フラグを持ちます。

- `require_protective_orders_for_open=True` → OPEN に `stop_loss` と `take_profit` を必須化
- `require_client_order_id_for_open=True` → OPEN に `client_order_id` を必須化
- CLOSE / REDUCE は対象外
- live OPEN は両フラグが false でも従来どおり常に必須

practice 統合テストの `oanda_guard` fixture は **protective mode ON** で生成されます
（forward test では SL/TP/client_order_id 必須）。OANDA の実 reject payload を取得する
テストだけは、`oanda_guard_without_protective_mode_for_reject_test` fixture を使い
**意図的に protective mode を外して** OANDA へ到達させます。

### order smoke test は対象 instrument がフラットであること

`close_position()` は **instrument + side 単位** でクローズします。そのため、対象 instrument に
既存ポジションがある状態で order smoke test を実行すると、テスト用の極小注文だけでなく
**既存ポジション全体を閉じてしまう** 危険があります。

これを防ぐため、order smoke test と OANDA reject test は **発注前に preflight チェック**
（`assert_instrument_flat`）を実行します。

- 対象 instrument にポジションが 1 件でもあれば **fail し、注文を出しません**
- クリーンアップ（`close_position`）は **実際に注文を送信した場合のみ** 実行します
- **専用の空 practice 口座** での実行を推奨します
- 既存ポジションがある場合は、Web 取引画面または手動で対象 instrument をフラットにしてから再実行してください

### 既定（オフライン / CI）

```bash
.venv/bin/python -m pytest            # oanda_practice は除外
.venv/bin/python -m pytest -m "not oanda_practice"
```

## close_position の方針

`close_position()` は **side 指定クローズを原則** とします。`side=None` は long/short 両方の
クローズになり得ますが、現状 `_parse_close_response()` は片側の `TradeClose` のみ返します
（もう片側は `broker_data` に残ります）。両建てを個別に表現したい場合は将来
`list[TradeClose]` を返す設計を検討します（コード内 TODO 参照）。practice 検証では
side 指定クローズを使ってください。

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
