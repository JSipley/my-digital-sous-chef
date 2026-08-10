"""Unit test for the bounded request timeout (issue #9).

The Anthropic SDK's default read timeout is 10 minutes, and PTB processes
updates sequentially, so a connection that goes silent mid-turn wedges the
bot for up to ~30 min across retries instead of failing fast into
AGENT_FAILURE_TEXT. AnthropicTransport must configure a much shorter read
timeout on its underlying client.
"""

from sous_chef.agent.client import AnthropicTransport
from sous_chef.config import Settings

SETTINGS = Settings.from_env(
    {
        "ANTHROPIC_API_KEY": "test-key",
        "SOUS_CHEF_TELEGRAM_TOKEN": "test-token",
        "SOUS_CHEF_CHAT_ID": "1",
    }
)


def test_client_timeout_is_bounded_well_under_sdk_default() -> None:
    transport = AnthropicTransport(SETTINGS)
    timeout = transport._client.timeout
    # SDK default is 600s; a wedged connection must fail in well under that
    # so a stalled turn still resolves into a retryable AGENT_FAILURE_TEXT.
    assert timeout.read is not None
    assert timeout.read <= 120.0
