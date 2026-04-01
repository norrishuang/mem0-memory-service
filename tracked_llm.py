"""
TrackedAWSBedrockLLM — AWSBedrockLLM wrapper that captures token usage
from Bedrock Converse API responses.

Token stats are stored in a per-call counter object that is passed explicitly,
avoiding threading.local() cross-thread isolation issues.
"""
import threading
import logging
from typing import Optional
from mem0.llms.aws_bedrock import AWSBedrockLLM

logger = logging.getLogger("mem0-tracked-llm")

# Global accumulator for the current request — protected by a lock.
# Each /memory/add call resets this before invoking memory.add().
# Since we serialize memory.add() calls via a semaphore (max 5 concurrent),
# and each call is scoped to a single thread-pool worker, using a single
# global dict with a lock is safe and avoids threading.local() cross-thread issues.
_counter_lock = threading.Lock()
_current_counter: dict = {
    "llm_calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
}


def reset_token_counter():
    """Reset global token counter (call before each memory.add())."""
    with _counter_lock:
        _current_counter["llm_calls"] = 0
        _current_counter["input_tokens"] = 0
        _current_counter["output_tokens"] = 0
        _current_counter["total_tokens"] = 0


def get_token_stats() -> dict:
    """Get a snapshot of current token stats."""
    with _counter_lock:
        return dict(_current_counter)


def _record_usage(response: dict):
    """Extract usage from Bedrock Converse API response and accumulate."""
    try:
        usage = response.get("usage", {})
        if not usage:
            return
        with _counter_lock:
            _current_counter["llm_calls"] += 1
            _current_counter["input_tokens"] += usage.get("inputTokens", 0)
            _current_counter["output_tokens"] += usage.get("outputTokens", 0)
            _current_counter["total_tokens"] += usage.get("totalTokens", 0)
        logger.debug(
            f"Token usage recorded: input={usage.get('inputTokens', 0)}, "
            f"output={usage.get('outputTokens', 0)}, total={usage.get('totalTokens', 0)}"
        )
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
