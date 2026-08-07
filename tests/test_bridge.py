"""Tests for SHA-1 computation and NFS path utilities."""

import hashlib
import os
import tempfile

from syno_immich.config import Config, UserMapping


class TestSha1:
    def test_known_content(self):
        from syno_immich.bridge import compute_sha1

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            f.flush()
            path = f.name
        try:
            result = compute_sha1(path)
            expected = hashlib.sha1(b"hello world").digest()
            assert result == expected
        finally:
            os.unlink(path)

    def test_empty_file(self):
        from syno_immich.bridge import compute_sha1

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"")
            f.flush()
            path = f.name
        try:
            result = compute_sha1(path)
            assert result == hashlib.sha1(b"").digest()
        finally:
            os.unlink(path)

    def test_large_file(self):
        from syno_immich.bridge import compute_sha1

        data = os.urandom(5 * 1024 * 1024)
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
            f.flush()
            path = f.name
        try:
            result = compute_sha1(path)
            assert result == hashlib.sha1(data).digest()
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        from syno_immich.bridge import compute_sha1

        result = compute_sha1("/nonexistent/path/file.jpg")
        assert result is None

    def test_directory_not_file(self):
        from syno_immich.bridge import compute_sha1

        result = compute_sha1("/tmp")
        assert result is None
