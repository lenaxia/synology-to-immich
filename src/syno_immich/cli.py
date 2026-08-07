"""
CLI entry points for syno-immich commands.

Each function wraps a phase script so it can be called as a console script:
  syno-dump   — Phase 0: dump Synology Photos DB
  syno-bridge — Phase 1: build SHA-1 bridge
  syno-upload — Phase 2: upload missing photos
  syno-faces  — Phase 3: match face tags
  syno-albums — Phase 4: migrate albums
"""

import os
import sys


def dump_main():
    os.execvp(sys.executable, [sys.executable, "-m", "syno_immich.dump"] + sys.argv[1:])


def bridge_main():
    from syno_immich import bridge

    bridge.main()


def upload_main():
    from syno_immich import upload

    upload.main()


def faces_main():
    from syno_immich import faces

    faces.main()


def albums_main():
    from syno_immich import albums

    albums.main()
