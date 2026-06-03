import os

import pytest
from dotenv import load_dotenv


def test_openrouter_connection():
    load_dotenv(override=True)
    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        pytest.skip("OPENROUTER_API_KEY is not set")

    from openai import OpenAI

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )
    completion = client.chat.completions.create(
        model="openrouter/free",
        messages=[{"role": "user", "content": "Say 'OpenRouter connection successful!' if you can read this."}],
        max_tokens=32,
    )

    assert completion.choices
    assert isinstance(completion.choices[0].message.content, str)
    assert completion.choices[0].message.content.strip()