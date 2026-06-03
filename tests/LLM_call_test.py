import os

import pytest
from dotenv import load_dotenv


def test_groq_connection():
    load_dotenv(override=True)
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        pytest.skip("GROQ_API_KEY is not set")

    from groq import Groq

    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model="Llama-3.3-70B-Versatile",
        messages=[{"role": "user", "content": "Say 'Groq connection successful!' if you can read this."}],
        max_tokens=32,
    )

    assert completion.choices
    assert isinstance(completion.choices[0].message.content, str)
    assert completion.choices[0].message.content.strip()