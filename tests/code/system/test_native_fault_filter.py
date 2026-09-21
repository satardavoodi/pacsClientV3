"""Synthetic crash-report boundaries; never read clinical logs or cause a crash."""
import pytest

from tools.diagnostics import filter_native_fault as report


SESSION = "=== session start 2026-09-15T10:00:00 pid=101 frozen=False exe=python.exe ===\n"
COM = "Windows fatal exception: code 0x8001010d\n"
AV = "Windows fatal exception: access violation\n"
COM_STACK = 'Thread 0x01 (most recent call first):\n  File "synthetic.py", line 1 in com_call\n'
AV_STACK = 'Current thread 0x02 (most recent call first):\n  File "synthetic.py", line 2 in exit_owner\n'


@pytest.mark.parametrize("first,second", [(COM, AV), (AV, COM)])
def test_each_fault_owns_following_stack_not_preceding_stack(first, second):
    stacks = {COM: COM_STACK, AV: AV_STACK}
    text = SESSION + first + stacks[first] + second + stacks[second]
    blocks = report.parse_blocks(text)
    faults = [(code, block) for code, block in blocks if code is not None]
    assert faults == [
        (report._code_of(first.split(":", 1)[1]), first + stacks[first]),
        (report._code_of(second.split(":", 1)[1]), second + stacks[second]),
    ]
    assert "".join(block for _, block in blocks) == text


def test_excluding_com_keeps_access_violation_with_its_stack(tmp_path, capsys):
    src, out = tmp_path / "native_fault.log", tmp_path / "filtered.log"
    text = SESSION + AV + AV_STACK + COM + COM_STACK
    src.write_text(text, encoding="utf-8")
    assert report.main(["--in", str(src), "--out", str(out)]) == 0
    kept = out.read_text(encoding="utf-8")
    assert AV in kept and AV_STACK in kept
    assert COM not in kept and COM_STACK not in kept
    assert SESSION in kept
    assert src.read_text(encoding="utf-8") == text
    assert "REAL CRASH" not in capsys.readouterr().out


@pytest.mark.parametrize("next_header", [
    "Timeout (0:00:05)!\n",
    "Fatal Python error: Aborted\n",
    "Fatal Python error: Segmentation fault\n",
])
def test_non_windows_dump_is_not_swallowed_by_com_filter(next_header):
    next_stack = 'Current thread 0x03:\n  File "synthetic.py", line 3 in other_owner\n'
    text = COM + COM_STACK + next_header + next_stack
    blocks = report.parse_blocks(text)
    kept = "".join(block for code, block in blocks if code != "0x8001010d")
    assert kept == next_header + next_stack
    assert "".join(block for _, block in blocks) == text


def test_session_header_ends_previous_fault_without_assigning_pid():
    child = SESSION.replace("pid=101", "pid=202")
    text = SESSION + COM + COM_STACK + child + AV + AV_STACK
    blocks = report.parse_blocks(text)
    assert (None, SESSION) in blocks
    assert (None, child) in blocks
    assert ("0xc0000005", AV + AV_STACK) in blocks
    assert "".join(block for _, block in blocks) == text


@pytest.mark.parametrize("text", ["", "\n", "unattributed stack\n", AV, SESSION])
def test_empty_unknown_and_truncated_input_is_preserved(text):
    assert "".join(block for _, block in report.parse_blocks(text)) == text


def test_embedded_header_text_is_not_a_dump_boundary():
    text = 'Note: Windows fatal exception: access violation\n'
    assert report.parse_blocks(text) == [(None, text)]


@pytest.mark.parametrize("same_spelling", [True, False])
def test_cli_cannot_overwrite_its_source(tmp_path, same_spelling):
    src = tmp_path / "native_fault.log"
    text = COM + COM_STACK + AV + AV_STACK
    src.write_text(text, encoding="utf-8")
    (tmp_path / "child").mkdir()
    out = src if same_spelling else tmp_path / "child" / ".." / src.name
    assert report.main(["--in", str(src), "--out", str(out)]) == 2
    assert src.read_text(encoding="utf-8") == text


def test_cli_cannot_overwrite_a_hardlinked_source(tmp_path):
    src, out = tmp_path / "native_fault.log", tmp_path / "alias.log"
    src.write_text(COM + COM_STACK, encoding="utf-8")
    out.hardlink_to(src)
    before = src.read_bytes()
    assert report.main(["--in", str(src), "--out", str(out)]) == 2
    assert src.read_bytes() == before


def test_no_exclusions_preserves_all_records(tmp_path):
    src, out = tmp_path / "native_fault.log", tmp_path / "all.log"
    text = SESSION + COM + COM_STACK + AV + AV_STACK
    src.write_text(text, encoding="utf-8")
    assert report.main(["--in", str(src), "--out", str(out), "--benign"]) == 0
    assert out.read_text(encoding="utf-8") == text


def test_missing_source_returns_failure_without_output(tmp_path):
    out = tmp_path / "filtered.log"
    assert report.main(["--in", str(tmp_path / "absent.log"), "--out", str(out)]) == 2
    assert not out.exists()


def test_crlf_and_unknown_fault_text_survive_without_rewriting():
    text = (SESSION + "Windows fatal exception: code 0xDEADBEEF\n" + AV_STACK).replace("\n", "\r\n")
    blocks = report.parse_blocks(text)
    assert blocks[-1][0] == "0xdeadbeef"
    assert "".join(block for _, block in blocks) == text


def test_explicit_exclusion_drops_only_that_fault(tmp_path):
    src, out = tmp_path / "native_fault.log", tmp_path / "filtered.log"
    src.write_text(AV + AV_STACK + COM + COM_STACK, encoding="utf-8")
    assert report.main(["--in", str(src), "--out", str(out), "--benign", "0xC0000005"]) == 0
    assert out.read_text(encoding="utf-8") == COM + COM_STACK
