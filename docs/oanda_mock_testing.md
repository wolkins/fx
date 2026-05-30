# OANDA mock 統合テスト（ネットワーク・認証情報なし）

OANDA 実 API トークンが用意できない場合でも、`FakeOandaTransport` を使って
`OandaAdapter` の主要動作（fill / reject / close / transaction tracking /
SafetyGuard 連携 / TradeManager reverse flow）をローカルで検証できます。

- **実注文なし・ネットワークなし・認証情報なし**で動作します。
- 通常の `pytest` で実行されます（`oanda_practice` マーカーは付けません）。
- 実 practice smoke は認証情報が揃った場合のみ（[oanda_practice.md](oanda_practice.md) 参照）。

## transport seam

`OandaAdapter` は HTTP 呼び出しを `OandaTransport` プロトコル経由で行います。

```python
class OandaTransport(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def request(self, method: str, path: str, **kwargs) -> dict: ...
```

- 本番は `RealOandaTransport`（`httpx.AsyncClient` 実装）。`OandaAdapter` は `transport`
  を渡さなければ `connect()` 時に自動生成します（public API は不変）。
- テストは `OandaAdapter(account_id=..., api_token=..., transport=FakeOandaTransport())`
  で fake を注入します。
- `request()` は OANDA と同じく HTTP >= 400 で `OandaError` を raise します
  （reject パス処理がそのまま機能します）。
- token / account_id はログ・例外メッセージに出しません。

## FakeOandaTransport

`tests/broker/fakes/fake_oanda.py`。OANDA 形状のレスポンスを返し、リクエスト履歴を保持します。

- `set_price(instrument, bid, ask)` — pricing / fill 価格を設定
- `next_order_reject` / `next_close_reject` — 次の発注 / クローズを reject させる（OANDA 形状の 400 body）
- `requests` — 送信されたリクエスト履歴（method/path/params/json）
- `open_positions` — `GET openPositions` が返すポジション
- ヘルパ: `order_reject_body()` / `close_reject_body()`

再現シナリオ: account summary / instrument details / pricing / candles /
MARKET fill / order reject / long・short close / close reject / order cancel /
reissue 系を含む transaction payload。

## テスト

`tests/broker/test_oanda_fake_transport.py`（通常 `pytest` で実行）:

- read-only: `get_account_summary` / `get_instrument_details` / `get_pricing` /
  `get_tick` / `get_candles`
- fill: MARKET BUY/SELL の約定、`broker_order_id` / `filled_price` / transaction id /
  `clientExtensions`（client_order_id）が `broker_data` に残る
- reject: `OrderExecutor` 経由で `ORDER_REJECTED_BY_BROKER`、`reject_reason` 等保存、sanitize 可能
- close: long/short の `TradeClose`（units/close_price/pnl/closed_at/broker_data）、
  `ExecutionResult.trade_close`、`TRADE_CLOSED` audit、close reject は `trade_close=None`
- SafetyGuard protective mode: client_order_id / SL / TP 無 OPEN は transport 到達前に拒否、
  全項目ありは fake に到達、CLOSE / REDUCE は対象外
- TradeManager reverse flow: REVERSE_TO_BUY の CLOSE→OPEN、close 失敗時は OPEN 未送信

## 実行コマンド

```bash
.venv/bin/python -m pytest tests/broker/test_oanda_fake_transport.py
.venv/bin/python -m pytest            # 既定（fake は実行、oanda_practice は除外）
```

## 安全方針（再掲）

- live 口座で注文テストはしません。
- 本番口座を使う場合でも、まず read-only / live_signal のみから始めます。
- order smoke は practice または専用検証環境でのみ実行します。
- live_trade は有効化しません。
