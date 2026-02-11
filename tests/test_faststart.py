import os
import subprocess
import sys
import tempfile
import unittest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scripts.pipeline.download_optimized import ensure_faststart


def _has_ffmpeg():
    """Return True if ffmpeg is available on PATH."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except FileNotFoundError:
        return False


def _moov_before_mdat(filepath):
    """Return True if the moov atom appears before the mdat atom in an MP4 file.

    MP4 files are structured as a sequence of top-level "boxes" (atoms).  Each
    box starts with a 4-byte big-endian length followed by a 4-byte type code.
    We scan the file linearly, recording the offset of 'moov' and 'mdat'.
    """
    moov_offset = None
    mdat_offset = None
    with open(filepath, "rb") as f:
        offset = 0
        while True:
            header = f.read(8)
            if len(header) < 8:
                break
            size = int.from_bytes(header[:4], "big")
            box_type = header[4:8]
            if box_type == b"moov":
                moov_offset = offset
            elif box_type == b"mdat":
                mdat_offset = offset
            if size < 8:
                break
            offset += size
            f.seek(offset)
    if moov_offset is not None and mdat_offset is not None:
        return moov_offset < mdat_offset
    return None


def _create_test_mp4_without_faststart(filepath):
    """Create a small MP4 with the moov atom at the end (no faststart)."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1:r=1",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", "1",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac",
        filepath,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@unittest.skipUnless(_has_ffmpeg(), "ffmpeg not available")
class TestEnsureFaststart(unittest.TestCase):
    def test_ensure_faststart_moves_moov_atom(self):
        """After ensure_faststart the moov atom should precede mdat."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mp4_path = os.path.join(tmpdir, "test_video.mp4")
            _create_test_mp4_without_faststart(mp4_path)

            # Verify file was created
            self.assertTrue(os.path.exists(mp4_path))
            self.assertGreater(os.path.getsize(mp4_path), 0)

            result = ensure_faststart(mp4_path)
            self.assertTrue(result, "ensure_faststart should return True on success")
            self.assertTrue(os.path.exists(mp4_path), "File should still exist after faststart")
            self.assertGreater(os.path.getsize(mp4_path), 0)

            # Check moov is before mdat
            self.assertTrue(
                _moov_before_mdat(mp4_path),
                "moov atom should appear before mdat after ensure_faststart",
            )

    def test_ensure_faststart_returns_false_for_missing_file(self):
        """ensure_faststart should return False for a non-existent file."""
        result = ensure_faststart("/tmp/nonexistent_video_abc123.mp4")
        self.assertFalse(result)

    def test_clipify_command_includes_faststart(self):
        """Verify that the _clipify ffmpeg command includes -movflags +faststart."""
        import inspect
        from scripts.pipeline.download_optimized import _clipify
        source = inspect.getsource(_clipify)
        self.assertIn("-movflags +faststart", source)


if __name__ == "__main__":
    unittest.main()
