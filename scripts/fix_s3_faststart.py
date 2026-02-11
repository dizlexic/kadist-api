#!/usr/bin/env python
"""Re-mux existing S3 videos with faststart (moov atom at the beginning).

Videos already on S3 that were uploaded before the faststart fix will have
their moov atom at the end of the file, which prevents browsers from
streaming them properly.  This script:

  1. Lists all *.mp4 objects in the configured S3 bucket.
  2. Downloads each file to a local temp directory.
  3. Checks whether the moov atom already precedes mdat.
  4. If not, re-muxes the file with ``ffmpeg -movflags +faststart`` and
     re-uploads it to S3 (overwriting the original key).

Usage examples
--------------
Dry-run (report which files need fixing, don't change anything)::

    python -m scripts.fix_s3_faststart --dry-run

Fix all full-length videos (skip clips)::

    python -m scripts.fix_s3_faststart

Fix everything including clips::

    python -m scripts.fix_s3_faststart --include-clips

Fix a single file by key::

    python -m scripts.fix_s3_faststart --key abc123.mp4
"""

import argparse
import os
import sys
import tempfile

from dotenv import load_dotenv

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv()

from lib.s3helper import S3Helper
from scripts.pipeline.download_optimized import ensure_faststart

bucket_name = os.getenv("S3_BUCKET_NAME", "ktv")


def moov_before_mdat(filepath):
    """Return True if the moov atom appears before the mdat atom.

    Returns None if either atom is not found (not a valid MP4 or empty file).
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


def fix_s3_faststart(
    bucket=None,
    dry_run=False,
    include_clips=False,
    key=None,
    verbose=False,
):
    """Download, check, and re-upload S3 mp4 files with faststart.

    Parameters
    ----------
    bucket : str, optional
        S3 bucket name.  Falls back to the ``S3_BUCKET_NAME`` env var.
    dry_run : bool
        If True, report which files need fixing without modifying anything.
    include_clips : bool
        If False (default), skip files whose key contains ``_clip_``.
    key : str, optional
        Process only this single S3 key instead of the full bucket.
    verbose : bool
        Print extra progress information.

    Returns
    -------
    dict
        Summary with counts: ``total``, ``skipped``, ``already_ok``,
        ``fixed``, ``failed``.
    """
    bucket = bucket or bucket_name
    s3 = S3Helper(bucket)

    stats = {"total": 0, "skipped": 0, "already_ok": 0, "fixed": 0, "failed": 0}

    if key:
        keys = [(key, None)]
    else:
        all_files = s3.list_files()
        keys = [(k, sz) for k, sz in all_files if k.lower().endswith(".mp4")]

    print(f" * Found {len(keys)} .mp4 file(s) in bucket '{bucket}'")

    for s3_key, _ in keys:
        stats["total"] += 1

        if not include_clips and "_clip_" in s3_key:
            if verbose:
                print(f"   SKIP (clip): {s3_key}")
            stats["skipped"] += 1
            continue

        if verbose or dry_run:
            print(f"   Checking: {s3_key}")

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, s3_key)

            # Download from S3
            try:
                s3.s3.Object(s3.bucket.name, s3_key).download_file(local_path)
            except Exception as e:
                print(f"   ERROR downloading {s3_key}: {e}")
                stats["failed"] += 1
                continue

            # Check moov position
            result = moov_before_mdat(local_path)

            if result is True:
                if verbose:
                    print(f"   OK (already faststart): {s3_key}")
                stats["already_ok"] += 1
                continue

            if result is None:
                print(f"   WARNING: could not determine atom layout for {s3_key}, attempting fix anyway")

            # Needs fixing
            if dry_run:
                print(f"   NEEDS FIX: {s3_key}")
                stats["fixed"] += 1  # count as "would fix"
                continue

            print(f"   Fixing: {s3_key}")
            if ensure_faststart(local_path):
                # Verify the fix worked
                if moov_before_mdat(local_path) is True:
                    s3.put_file(s3_key, local_path, only_if_modified=False)
                    print(f"   FIXED and re-uploaded: {s3_key}")
                    stats["fixed"] += 1
                else:
                    print(f"   ERROR: faststart did not move moov for {s3_key}")
                    stats["failed"] += 1
            else:
                print(f"   ERROR: ensure_faststart failed for {s3_key}")
                stats["failed"] += 1

    # Summary
    print()
    print("=" * 50)
    mode = "DRY RUN" if dry_run else "COMPLETE"
    print(f" Faststart fix {mode}")
    print(f"   Total MP4 files : {stats['total']}")
    print(f"   Skipped (clips) : {stats['skipped']}")
    print(f"   Already OK      : {stats['already_ok']}")
    label = "Would fix" if dry_run else "Fixed"
    print(f"   {label:15s}  : {stats['fixed']}")
    print(f"   Failed          : {stats['failed']}")
    print("=" * 50)

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fix existing S3 videos by adding faststart (moov atom before mdat)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report which files need fixing without modifying anything.",
    )
    parser.add_argument(
        "--include-clips",
        action="store_true",
        help="Also process clip files (keys containing '_clip_').",
    )
    parser.add_argument(
        "--key",
        type=str,
        default=None,
        help="Process only this single S3 key instead of the full bucket.",
    )
    parser.add_argument(
        "--bucket",
        type=str,
        default=None,
        help=f"S3 bucket name (default: {bucket_name}).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print extra progress information.",
    )

    args = parser.parse_args()

    fix_s3_faststart(
        bucket=args.bucket,
        dry_run=args.dry_run,
        include_clips=args.include_clips,
        key=args.key,
        verbose=args.verbose,
    )
