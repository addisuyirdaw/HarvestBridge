import types
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, model, messages, temperature=0.3, max_tokens=300):
        self.calls.append({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="MOCKED RECOMMENDATION"))]
        )


class FakeGroqClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_process_farmer_inquiry_uses_guardrails_and_mocked_llm():
    fake_client = FakeGroqClient()
    fake_weather_payload = {
        "city": {"name": "Ondo"},
        "list": [
            {"dt": 1710000000, "dt_txt": "2026-06-03 12:00:00", "rain": {"3h": 20}, "main": {"humidity": 80}},
            {"dt": 1710086400, "dt_txt": "2026-06-04 12:00:00", "rain": {"3h": 15}, "main": {"humidity": 75}},
            {"dt": 1710172800, "dt_txt": "2026-06-05 12:00:00", "rain": {"3h": 10}, "main": {"humidity": 72}},
            {"dt": 1710259200, "dt_txt": "2026-06-06 12:00:00", "rain": {"3h": 8}, "main": {"humidity": 71}},
            {"dt": 1710345600, "dt_txt": "2026-06-07 12:00:00", "rain": {"3h": 6}, "main": {"humidity": 69}},
        ],
    }

    fake_market_data = {
        "market_name": "Ondo Central Market",
        "region": "Ondo",
        "country": "Nigeria",
        "current_price": 42000,
        "currency": "NGN",
        "trend_1m": "Increasing",
        "trend_pct": 8,
        "price_date": "2026-06-03",
        "regional_capital_price": None,
    }

    with patch("main.requests.get", return_value=FakeResponse(fake_weather_payload)) as mocked_get, \
         patch("main.Groq", return_value=fake_client) as mocked_groq, \
         patch("main.load_market_prices", return_value=fake_market_data) as mocked_market:
        original_api_key = main.GROQ_API_KEY
        original_client = main.client
        original_weather_key = main.OPENWEATHER_API_KEY

        try:
            main.GROQ_API_KEY = "fake-key"
            main.client = main.Groq(api_key="fake-key")
            main.OPENWEATHER_API_KEY = "fake-openweather-key"

            result = main.process_farmer_inquiry(
                farmer_id="FARMER_001",
                location="Ondo",
                crop="maize",
                harvest_volume="20 bags",
                storage_capability="Traditional open bags",
                cash_need_level="HIGH",
                country="Nigeria",
            )

            assert result == "MOCKED RECOMMENDATION"
            mocked_market.assert_called_once_with("Ondo", "maize", "Nigeria")
            mocked_get.assert_called_once()
            mocked_groq.assert_called_once_with(api_key="fake-key")

            created_call = fake_client.chat.completions.calls[0]
            assert created_call["model"] == "Llama-3.3-70B-Versatile"
            assert created_call["temperature"] == 0.3
            assert created_call["max_tokens"] == 300

            user_message = created_call["messages"][1]["content"]
            assert "Ondo" in user_message
            assert "maize" in user_message
            assert "Forced Action Override: SELL_IMMEDIATELY" in user_message
            assert "CASH_CONSTRAINT" in user_message or "SPOILAGE_THREAT" in user_message
            assert "Days 1-2 Rainfall:" in user_message
            assert "Days 3-5 Rainfall:" in user_message

        finally:
            main.GROQ_API_KEY = original_api_key
            main.client = original_client
            main.OPENWEATHER_API_KEY = original_weather_key
