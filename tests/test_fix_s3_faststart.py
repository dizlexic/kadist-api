import os
import subprocess
import sys
import tempfile
import unittest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scripts.fix_s3_faststart import moov_before_mdat


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


def _create_mp4(filepath, faststart=False):
    """Create a tiny MP4 file, optionally with faststart."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1:r=1",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", "1",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac",
    ]
    if faststart:
        cmd += ["-movflags", "+faststart"]
    cmd.append(filepath)
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@unittest.skipUnless(_has_ffmpeg(), "ffmpeg not available")
class TestMoovBeforeMdat(unittest.TestCase):
    def test_detects_moov_after_mdat(self):
        """A default ffmpeg MP4 (no faststart) should have moov after mdat."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "no_faststart.mp4")
            _create_mp4(path, faststart=False)
            result = moov_before_mdat(path)
            # Default ffmpeg puts moov after mdat
            self.assertFalse(result)

    def test_detects_moov_before_mdat(self):
        """An MP4 created with faststart should have moov before mdat."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "with_faststart.mp4")
            _create_mp4(path, faststart=True)
            result = moov_before_mdat(path)
            self.assertTrue(result)

    def test_returns_none_for_non_mp4(self):
        """A non-MP4 file should return None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "not_an_mp4.txt")
            with open(path, "w") as f:
                f.write("this is not an mp4 file")
            result = moov_before_mdat(path)
            self.assertIsNone(result)


class TestScriptImport(unittest.TestCase):
    def test_fix_s3_faststart_is_importable(self):
        """The fix script should be importable without errors."""
        from scripts.fix_s3_faststart import fix_s3_faststart
        self.assertTrue(callable(fix_s3_faststart))


if __name__ == "__main__":
    unittest.main()
