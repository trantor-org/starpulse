import os
from pathlib import Path

from starpulse.scheduler.adapters.transcripts import transcript_written


def test_a_sessions_transcript_is_read_by_its_last_write_across_projects(tmp_path: Path) -> None:
    transcript = tmp_path / "-home-adinb-trantor" / "b55dc5cc.jsonl"
    transcript.parent.mkdir()
    transcript.write_text("{}\n")
    os.utime(transcript, (1_000.0, 1_000.0))
    written = transcript_written(tmp_path)

    assert written("b55dc5cc") == 1_000.0
    assert written("missing") is None
    assert written("") is None
