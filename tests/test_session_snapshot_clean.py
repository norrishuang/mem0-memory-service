"""Tests for clean_content() noise filtering in session_snapshot.py"""
import sys
from pathlib import Path

# Allow importing from pipelines/
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines.session_snapshot import clean_content, build_message_lines, _is_low_value_filler


# ── 1. System metadata blocks ────────────────────────────────────────────────

def test_strip_conversation_info_metadata():
    text = 'Hello\nConversation info (untrusted metadata): ```json\n{"id": "123"}\n```\nGoodbye'
    result = clean_content(text)
    assert 'untrusted metadata' not in result
    assert 'Hello' in result
    assert 'Goodbye' in result


def test_strip_sender_metadata():
    text = 'Sender (untrusted metadata): ```json\n{"name": "bot"}\n```\nActual message here'
    result = clean_content(text)
    assert 'untrusted' not in result
    assert 'Actual message here' in result


def test_strip_replied_message_metadata():
    text = 'Replied message (untrusted, for context): ```json\n{"text": "old"}\n```\nNew reply'
    result = clean_content(text)
    assert 'untrusted' not in result
    assert 'New reply' in result


def test_strip_runtime_line():
    text = 'Some content\nRuntime: agent=agent1 | host=ip-10-0-1-5 | pid=12345\nMore content'
    result = clean_content(text)
    assert 'Runtime:' not in result
    assert 'Some content' in result
    assert 'More content' in result


def test_strip_group_chat_context_section():
    text = '## Group Chat Context\nSome group info\nMore group info\n## Next Section\nKeep this'
    result = clean_content(text)
    assert 'Group Chat Context' not in result
    assert 'Keep this' in result


def test_strip_inbound_context_section():
    text = '## Inbound Context (trusted metadata)\nTrusted stuff\n'
    result = clean_content(text)
    assert 'Inbound Context' not in result


# ── 2. Injected system context ───────────────────────────────────────────────

def test_strip_injected_md_file():
    text = '## /home/ec2-user/workspace/project/AGENTS.md\nAgent config content\nMore lines\n'
    result = clean_content(text)
    assert 'AGENTS.md' not in result


def test_strip_dynamic_project_context():
    text = 'Intro\n## Dynamic Project Context\nProject tree here\nFiles list\n'
    result = clean_content(text)
    assert 'Dynamic Project Context' not in result
    assert 'Intro' in result


def test_strip_silent_replies_section():
    text = '## Silent Replies\nSilent config\n'
    result = clean_content(text)
    assert 'Silent Replies' not in result


def test_strip_authorized_senders_section():
    text = '## Authorized Senders\nSender list\n'
    result = clean_content(text)
    assert 'Authorized Senders' not in result


# ── 3. Tool call raw outputs ─────────────────────────────────────────────────

def test_strip_large_json_block():
    json_lines = '  {"key": "value"},\n' * 5
    text = f'Before\n```json\n{json_lines}```\nAfter conclusion'
    result = clean_content(text)
    assert '{"key"' not in result
    assert '[...output omitted...]' in result
    assert 'After conclusion' in result


def test_strip_long_shell_output():
    shell_lines = 'line of output\n' * 10
    text = f'Ran command:\n```bash\n{shell_lines}```\nResult: success'
    result = clean_content(text)
    assert 'line of output' not in result
    assert 'Result: success' in result


def test_keep_short_code_block():
    text = 'Here is the fix:\n```json\n{"ok": true}\n```\nDone'
    result = clean_content(text)
    # Short blocks (< 3 JSON lines) should be kept
    assert '{"ok": true}' in result


# ── 4. Low-value filler ──────────────────────────────────────────────────────

def test_filler_chinese():
    assert clean_content('好的') == ''
    assert clean_content('收到') == ''
    assert clean_content('明白了') == ''


def test_filler_english():
    assert clean_content('OK') == ''
    assert clean_content('Done') == ''
    assert clean_content('Sure') == ''


def test_filler_with_context_kept():
    # Longer text with filler word is NOT filler
    result = clean_content('OK, I will refactor the module now')
    assert result != ''
    assert 'refactor' in result


# ── 5. Preserve structure ────────────────────────────────────────────────────

def test_preserve_session_header():
    text = '### [14:30] Session abc123\nSome content here'
    result = clean_content(text)
    assert '### [14:30] Session abc123' in result


def test_truncate_long_content():
    text = 'A' * 600
    result = clean_content(text)
    assert len(result) <= 504  # 500 + '...'
    assert result.endswith('...')


# ── 6. Edge cases ────────────────────────────────────────────────────────────

def test_empty_input():
    assert clean_content('') == ''
    assert clean_content('   ') == ''
    assert clean_content(None) == ''


def test_normal_content_preserved():
    text = 'We decided to use PostgreSQL for the user service because of its JSON support.'
    assert clean_content(text) == text


# ── 7. build_message_lines integration ───────────────────────────────────────

def test_build_message_lines_filters_empty():
    messages = [
        {'role': 'user', 'content': 'Hello, let us discuss the plan'},
        {'role': 'assistant', 'content': '好的'},  # filler → filtered
        {'role': 'assistant', 'content': 'The plan is to refactor module X'},
    ]
    lines = build_message_lines(messages, 'agent1')
    assert len(lines) == 2
    assert 'Boss:' in lines[0]
    assert 'Agent1:' in lines[1]
    assert '好的' not in '\n'.join(lines)


def test_build_message_lines_cleans_metadata():
    messages = [
        {'role': 'user', 'content': 'Sender (untrusted metadata): ```json\n{"id":"x"}\n```\nReal question here'},
    ]
    lines = build_message_lines(messages, 'agent1')
    assert len(lines) == 1
    assert 'untrusted' not in lines[0]
    assert 'Real question here' in lines[0]
