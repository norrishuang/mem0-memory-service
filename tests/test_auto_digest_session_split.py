"""Tests for split_into_session_blocks in auto_digest.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "pipelines"))

from auto_digest import split_into_session_blocks, MAX_BLOCK_BYTES


def test_split_on_session_boundaries():
    content = (
        "### [09:00] Morning session\nSome morning notes\n\n"
        "### [10:30] Mid-morning\nMore notes\n\n"
        "### [14:00] Afternoon\nAfternoon work"
    )
    blocks = split_into_session_blocks(content)
    assert len(blocks) == 3
    assert blocks[0].startswith("### [09:00]")
    assert blocks[1].startswith("### [10:30]")
    assert blocks[2].startswith("### [14:00]")


def test_no_session_markers_returns_single_block():
    content = "Just some plain text\nwith multiple lines\nbut no session markers"
    blocks = split_into_session_blocks(content)
    assert len(blocks) == 1
    assert blocks[0] == content.strip()


def test_empty_content():
    assert split_into_session_blocks("") == []
    assert split_into_session_blocks("   \n\n  ") == []


def test_oversized_block_triggers_sub_split():
    # Build a single session block that exceeds MAX_BLOCK_BYTES
    paragraph = "A" * 1024 + "\n\n"
    # Need enough paragraphs to exceed 100KB
    num_paragraphs = (MAX_BLOCK_BYTES // 1026) + 10
    big_block = "### [09:00] Big session\n\n" + paragraph * num_paragraphs

    blocks = split_into_session_blocks(big_block)
    assert len(blocks) > 1
    for b in blocks:
        assert len(b.encode("utf-8")) <= MAX_BLOCK_BYTES


def test_preamble_before_first_marker():
    content = "# Diary header\nSome preamble\n\n### [09:00] First session\nNotes"
    blocks = split_into_session_blocks(content)
    assert len(blocks) == 2
    assert blocks[0].startswith("# Diary header")
    assert blocks[1].startswith("### [09:00]")


def test_mixed_normal_and_oversized():
    small = "### [08:00] Small\nshort content"
    paragraph = "B" * 1024 + "\n\n"
    num = (MAX_BLOCK_BYTES // 1026) + 10
    big = "\n### [12:00] Big session\n\n" + paragraph * num
    tail = "\n### [18:00] Evening\nwrap up"

    blocks = split_into_session_blocks(small + big + tail)
    # First block is small, big block is sub-split into multiple, last is tail
    assert blocks[0].startswith("### [08:00]")
    assert blocks[-1].startswith("### [18:00]")
    assert len(blocks) >= 4  # at least: small + 2 sub-splits + tail
