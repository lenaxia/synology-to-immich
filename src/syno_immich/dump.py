#!/usr/bin/env python3
"""
dump_syno_db.py — Create a read-only copy of the Synology Photos database.

Synology Photos stores its metadata in a PostgreSQL database called "app".
This script creates a safe, read-only snapshot by:

1. Connecting to the Synology's PostgreSQL instance
2. Dumping only the metadata tables (unit, folder, person, face, etc.)
3. Writing a portable SQL dump that can be restored into any PostgreSQL

NEVER operate directly on the Synology's production database. Always work
from a restored copy.

Usage:
  # Option A: Dump from Synology to a file
  python dump_syno_db.py --syno-host 192.168.1.100 --syno-port 5432 \\
      --output /tmp/syno_photos_dump.sql

  # Option B: Dump + restore into a target database in one step
  python dump_syno_db.py --syno-host 192.168.1.100 \\
      --restore-host localhost --restore-db syno_copy

  # Option C: Use pg_dump directly (if you have shell access to Synology)
  # ssh admin@syno 'sudo -u postgres pg_dump app' > syno_photos_dump.sql
  # psql -h <target> -c "CREATE DATABASE syno_copy"
  # psql -h <target> -d syno_copy < syno_photos_dump.sql
"""

import argparse
import os
import subprocess
import sys
import tempfile


# Tables that constitute the Synology Photos metadata.
# We dump these selectively to avoid backing up irrelevant Synology DB state.
SYNO_PHOTO_TABLES = [
    "user_info",  # Synology users
    "unit",  # Photo/video records (id, filename, duplicate_hash, etc.)
    "folder",  # Directory structure
    "person",  # Named face clusters
    "face",  # Individual face detections (bounding boxes)
    "many_unit_has_many_person",  # Unit ↔ person associations
    "album",  # Photo albums
    "item",  # Album items
    "tag",  # Tags
    "many_album_has_many_unit",
    "many_item_has_many_unit",
    "many_tag_has_many_unit",
    "general_setting",
    "user_setting",
    "photo_setting",
    "loggedin_user_info",
]


def dump_via_pg_dump(host, port, user, password, output_path, tables=None):
    """Use pg_dump to create a selective dump of Synology Photos tables."""
    if not tables:
        tables = SYNO_PHOTO_TABLES

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    cmd = ["pg_dump"]
    cmd.extend(["-h", host, "-p", str(port), "-U", user])
    cmd.extend(["-d", "app"])  # Synology Photos always uses "app"

    # Dump only the photo-related tables (skip Synology system tables)
    for t in tables:
        cmd.extend(["-t", t])

    cmd.extend(["--no-owner", "--no-acl", "--inserts"])  # Portable restore
    cmd.extend(["-f", output_path])

    print(f"Dumping {len(tables)} tables from {host}:{port}/app → {output_path}")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"pg_dump failed:\n{result.stderr}", file=sys.stderr)
        return False

    # Check output size
    size = os.path.getsize(output_path)
    print(f"Dump complete: {size / 1024 / 1024:.1f} MB")
    return True


def restore_dump(host, port, user, password, dbname, dump_path):
    """Restore a dump file into a target PostgreSQL database."""
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    # Create database if it doesn't exist
    create_cmd = [
        "psql",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-tAc",
        f"SELECT 1 FROM pg_database WHERE datname='{dbname}'",
    ]
    result = subprocess.run(create_cmd, env=env, capture_output=True, text=True)
    if result.stdout.strip() != "1":
        createdb = ["createdb", "-h", host, "-p", str(port), "-U", user, dbname]
        r = subprocess.run(createdb, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"Failed to create database {dbname}:\n{r.stderr}", file=sys.stderr)
            return False
        print(f"Created database: {dbname}")

    # Restore
    print(f"Restoring {dump_path} → {host}:{port}/{dbname}")
    restore_cmd = [
        "psql",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        dbname,
        "-f",
        dump_path,
        "-q",
    ]
    result = subprocess.run(restore_cmd, env=env, capture_output=True, text=True)

    if result.returncode != 0:
        print(
            f"Restore completed with warnings:\n{result.stderr[:500]}", file=sys.stderr
        )
    else:
        print("Restore complete.")

    # Verify
    verify_cmd = [
        "psql",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        dbname,
        "-tAc",
        "SELECT COUNT(*) FROM unit",
    ]
    result = subprocess.run(verify_cmd, env=env, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Verification: {result.stdout.strip()} units in restored DB")
    return True


def main():
    parser = argparse.ArgumentParser(description="Dump Synology Photos DB (read-only)")
    parser.add_argument("--syno-host", required=True, help="Synology NAS host/IP")
    parser.add_argument(
        "--syno-port", type=int, default=5432, help="PostgreSQL port (default: 5432)"
    )
    parser.add_argument(
        "--syno-user", default="postgres", help="PostgreSQL user (default: postgres)"
    )
    parser.add_argument(
        "--syno-password", default="", help="PostgreSQL password (or set PGPASSWORD)"
    )

    parser.add_argument(
        "--output", help="Output file for the dump (default: syno_photos_dump.sql)"
    )
    parser.add_argument(
        "--restore-host", help="If set, restore the dump into this PostgreSQL host"
    )
    parser.add_argument("--restore-port", type=int, default=5432)
    parser.add_argument(
        "--restore-db",
        default="syno_copy",
        help="Target database name (default: syno_copy)",
    )
    parser.add_argument("--restore-user", default="postgres")
    parser.add_argument("--restore-password", default="")

    args = parser.parse_args()

    output_path = args.output or "syno_photos_dump.sql"

    success = dump_via_pg_dump(
        args.syno_host, args.syno_port, args.syno_user, args.syno_password, output_path
    )
    if not success:
        sys.exit(1)

    if args.restore_host:
        restore_dump(
            args.restore_host,
            args.restore_port,
            args.restore_user,
            args.restore_password,
            args.restore_db,
            output_path,
        )

    print("\nNext steps:")
    print(
        f"  1. Point config.yaml syno_db.host to: {args.restore_host or 'your postgres host'}"
    )
    print(
        f"  2. Set syno_db.dbname to: {args.restore_db if args.restore_host else 'syno_copy'}"
    )
    print("  3. Run the bridge build: python 01-bridge/build_bridge.py")


if __name__ == "__main__":
    main()
