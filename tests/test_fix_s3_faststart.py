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


class TestMoovBeforeMdatSynthetic(unittest.TestCase):
    """Test moov_before_mdat with synthetic binary data for edge cases."""

    def _make_box(self, box_type, size=None, data=b"", extended=False):
        """Build a raw MP4 box.

        Parameters
        ----------
        box_type : bytes
            4-byte box type (e.g. b"ftyp").
        size : int, optional
            Explicit total size.  Computed automatically when *None*.
        data : bytes
            Box payload.
        extended : bool
            If True, use 64-bit extended size header (size field == 1).
        """
        if extended:
            total = 16 + len(data)  # 8 header + 8 extended size + payload
            return (
                (1).to_bytes(4, "big")
                + box_type
                + total.to_bytes(8, "big")
                + data
            )
        total = size if size is not None else 8 + len(data)
        return total.to_bytes(4, "big") + box_type + data

    def test_mdat_with_size_zero(self):
        """size==0 means the box extends to EOF; moov after mdat should return False."""
        ftyp = self._make_box(b"ftyp", data=b"\x00" * 4)
        # mdat with size 0 (extends to EOF), followed by nothing — but we
        # need moov after, so we build mdat with explicit size 0 and then moov.
        # However, size-0 means rest-of-file, so moov wouldn't be reachable.
        # The realistic case: mdat size==0 is the last box → moov not found → None.
        mdat = (0).to_bytes(4, "big") + b"mdat" + b"\x00" * 10
        moov = self._make_box(b"moov", data=b"\x00" * 4)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(ftyp + mdat + moov)
            path = f.name
        try:
            # size-0 mdat consumes rest of file, so moov is hidden
            result = moov_before_mdat(path)
            self.assertIsNone(result)
        finally:
            os.unlink(path)

    def test_mdat_with_extended_size_moov_after(self):
        """mdat using 64-bit extended size, moov comes after → False."""
        ftyp = self._make_box(b"ftyp", data=b"\x00" * 4)
        mdat_payload = b"\x00" * 20
        mdat = self._make_box(b"mdat", data=mdat_payload, extended=True)
        moov = self._make_box(b"moov", data=b"\x00" * 4)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(ftyp + mdat + moov)
            path = f.name
        try:
            result = moov_before_mdat(path)
            self.assertIs(result, False)
        finally:
            os.unlink(path)

    def test_moov_with_extended_size_before_mdat(self):
        """moov using 64-bit extended size before mdat → True."""
        ftyp = self._make_box(b"ftyp", data=b"\x00" * 4)
        moov = self._make_box(b"moov", data=b"\x00" * 4, extended=True)
        mdat = self._make_box(b"mdat", data=b"\x00" * 20)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(ftyp + moov + mdat)
            path = f.name
        try:
            result = moov_before_mdat(path)
            self.assertIs(result, True)
        finally:
            os.unlink(path)

    def test_normal_mdat_moov_after(self):
        """Normal 32-bit sizes, moov after mdat → False."""
        ftyp = self._make_box(b"ftyp", data=b"\x00" * 4)
        mdat = self._make_box(b"mdat", data=b"\x00" * 20)
        moov = self._make_box(b"moov", data=b"\x00" * 4)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(ftyp + mdat + moov)
            path = f.name
        try:
            result = moov_before_mdat(path)
            self.assertIs(result, False)
        finally:
            os.unlink(path)

    def test_normal_moov_before_mdat(self):
        """Normal 32-bit sizes, moov before mdat → True."""
        ftyp = self._make_box(b"ftyp", data=b"\x00" * 4)
        moov = self._make_box(b"moov", data=b"\x00" * 4)
        mdat = self._make_box(b"mdat", data=b"\x00" * 20)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(ftyp + moov + mdat)
            path = f.name
        try:
            result = moov_before_mdat(path)
            self.assertIs(result, True)
        finally:
            os.unlink(path)


class TestScriptImport(unittest.TestCase):
    def test_fix_s3_faststart_is_importable(self):
        """The fix script should be importable without errors."""
        from scripts.fix_s3_faststart import fix_s3_faststart
        self.assertTrue(callable(fix_s3_faststart))


if __name__ == "__main__":
    unittest.main()
