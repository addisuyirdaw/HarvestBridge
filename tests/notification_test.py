import os

import pytest
from dotenv import load_dotenv


def test_twilio_notification_client():
    load_dotenv(override=True)

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
    my_number = os.getenv("MY_NUMBER")

    if not all([account_sid, auth_token, twilio_number, my_number]):
        pytest.skip("Twilio credentials are not set")

    from twilio.rest import Client

    client = Client(account_sid, auth_token)
    message = client.messages.create(
        from_=f"whatsapp:{twilio_number}",
        to=f"whatsapp:{my_number}",
        body=(
            "🌾 HarvestBridge Test\n\n"
            "If you are reading this, the notification pipeline is working.\n\n"
            "💰 Fair Price: ₦38,000 – ₦42,000 per tonne\n"
            "🚫 Floor Price: Do not accept below ₦34,000\n"
            "📈 Leverage: Global cassava demand is up 6% this quarter\n\n"
            "This is a test from Week 1 of the build."
        ),
    )

    assert message.sid
    assert message.status in {"queued", "accepted", "sent"}