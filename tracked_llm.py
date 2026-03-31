"""
TrackedAWSBedrockLLM — AWSBedrockLLM wrapper that captures token usage
from Bedrock Converse API responses via thread-local counters.
"""
import threading
import logging

from mem0.llms.aws_bedrock import AWSBedrockLLM

logger = logging.getLogger("mem0-tracked-llm")

_token_local = threading.local()


def reset_token_counter():
    """Reset token counter for current thread (call before each request)."""
    _token_local.llm_calls = 0
    _token_local.input_tokens = 0
    _token_local.output_tokens = 0
    _token_local.total_tokens = 0


def get_token_stats() -> dict:
    """Get token stats for current thread."""
    return {
        "llm_calls": getattr(_token_local, "llm_calls", 0),
        "input_tokens": getattr(_token_local, "input_tokens", 0),
        "output_tokens": getattr(_token_local, "output_tokens", 0),
        "total_tokens": getattr(_token_local, "total_tokens", 0),
    }


def _record_usage(response: dict):
    """Extract usage from Bedrock Converse API response and accumulate."""
    try:
        usage = response.get("usage", {})
        if not usage:
            return
        _token_local.llm_calls = getattr(_token_local, "llm_calls", 0) + 1
        _token_local.input_tokens = getattr(_token_local, "input_tokens", 0) + usage.get("inputTokens", 0)
        _token_local.output_tokens = getattr(_token_local, "output_tokens", 0) + usage.get("outputTokens", 0)
        _token_local.total_tokens = getattr(_token_local, "total_tokens", 0) + usage.get("totalTokens", 0)
    except Exception as e:
        logger.debug(f"Could not record token usage: {e}")


class TrackedAWSBedrockLLM(AWSBedrockLLM):
    """AWSBedrockLLM that captures token usage from every converse() call."""

    def _generate_with_tools(self, messages, tools, stream=False):
        original_converse = self.client.converse

        def tracked_converse(**kwargs):
            resp = original_converse(**kwargs)
            _record_usage(resp)
            return resp

        self.client.converse = tracked_converse
        try:
            return super()._generate_with_tools(messages, tools, stream)
        finally:
            self.client.converse = original_converse

    def _generate_standard(self, messages, stream=False):
        original_converse = self.client.converse

        def tracked_converse(**kwargs):
            resp = original_converse(**kwargs)
            _record_usage(resp)
            return resp

        self.client.converse = tracked_converse
        try:
            return super()._generate_standard(messages, stream)
        finally:
            self.client.converse = original_converse
