from crypto_history import class_builders
import pytest
from binance import client


@pytest.fixture
def binance_market_operator():
    exchange_factory = class_builders.get("market").get("binance")()
    market_requester = exchange_factory.create_market_requester()
    market_operator = exchange_factory.create_market_operations(market_requester)
    return market_operator


@pytest.mark.parametrize(
    "string_of_time, binance_enum, exception", [
        ("1d", client.Client.KLINE_INTERVAL_1DAY, None),
        ("1h", client.Client.KLINE_INTERVAL_1HOUR, None),
        ("3d", client.Client.KLINE_INTERVAL_3DAY, None),
        ("31d", None, AssertionError)
    ])
def test_match_binance_enum(binance_market_operator, string_of_time, binance_enum, exception):
    if exception is None:
        resulting_enum = binance_market_operator._match_binance_enum(string_of_time)
        assert resulting_enum == binance_enum
    else:
        with pytest.raises(exception):
            binance_market_operator._match_binance_enum(string_of_time)