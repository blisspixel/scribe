"""
Manual test for XAI provider.

Usage: 
    export XAI_API_KEY="your_key"
    python tests/manual/test_xai_provider.py
"""

from scribe.providers import get_provider

# Test XAI provider for jokes
print("Testing XAI provider for jokes...")
print("=" * 60)

try:
    provider = get_provider(
        feature="joke",
        provider_name="xai"
    )

    print(f"Provider: {provider.config.provider_name}")
    print(f"Model: {provider.config.model}")
    print()

    # Test chat completion
    messages = [
        {"role": "user", "content": "Tell me a short joke about AI meetings."}
    ]

    print("Sending request...")
    response = provider.chat_completion(messages, max_tokens=100)

    print(f"Response: {response['content']}")
    print(f"Usage: {response['usage']}")
    print()
    print("✓ XAI provider works!")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
