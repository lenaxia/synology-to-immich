#!/usr/bin/env python3
"""
upload.py — Upload Synology photos to Immich via REST API

For each user in the config:
1. Query the Synology DB for all units (file path + metadata)
2. Hash each NFS file (SHA-1) to dedup locally
3. Skip files already in Immich (checksum index)
4. Upload remaining via POST /api/assets

Uses requests_toolbelt.MultipartEncoder for streaming uploads (critical
for multi-GB video files). Retries with exponential backoff on transient
errors. Checkpoints are written per-owner so a restart skips re-hashing.

Idempotent: re-runs skip already-uploaded files (checksum-skip + checkpoint
re-filter). Safe to re-run after partial failure.

Env vars:
  CONFIG_PATH     Path to YAML config file (default: /config/config.yaml)
  DRY_RUN         If "true", no uploads (default: false)
  UPLOAD_USERS    Comma-separated syno_user_id integers, or "all" (default: all)
  CHECKPOINT_DIR  Directory for per-owner checkpoint JSON (default: /checkpoint)
"""

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone


import psycopg2
import psycopg2.extras
import requests

from syno_immich.config import load_config

cfg = load_config()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("upload")


def connect(dsn):
    conn = psycopg2.connect(dsn)
    conn.set_session(autocommit=True)
    return conn


def compute_sha1(path):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.digest()
    except (FileNotFoundError, PermissionError, IsADirectoryError, OSError) as e:
        log.debug("  skip %s: %s", path, e)
        return None


def epoch_to_iso(epoch):
    if not epoch or epoch <= 0:
        return datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def get_syno_units(conn, syno_user_ids):
    """Get all units for the given syno users with NFS path info."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT u.id AS unit_id, u.id_user, u.filename, u.filesize,
                   u.createtime, u.mtime, u.takentime, f.name AS folder_name
            FROM unit u
            JOIN folder f ON f.id = u.id_folder
            WHERE u.id_user = ANY(%s)
            ORDER BY u.id_user, u.id
        """,
            (list(syno_user_ids),),
        )
        return cur.fetchall()


def load_immich_checksums(conn, owner_id):
    """Return set of SHA-1 bytes already in immich for this owner."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT checksum FROM asset
            WHERE "ownerId" = %s AND "deletedAt" IS NULL AND checksum IS NOT NULL
        """,
            (owner_id,),
        )
        return {bytes(row[0]) for row in cur.fetchall()}


def upload_file(api_key, immich_url, unit_id, path, takentime, mtime):
    """
    Upload a single file via Immich REST API. Returns (status, detail).

    Uses requests_toolbelt.MultipartEncoder for streaming uploads — avoids
    loading entire file into memory (critical for multi-GB video files).

    Retries up to cfg.upload_max_retries times with exponential backoff
    (cfg.upload_retry_base_backoff × 2^attempt) to handle transient
    immich-server restarts under upload load.
    """
    from requests_toolbelt import MultipartEncoder

    filename = os.path.basename(path)
    file_ext = os.path.splitext(filename)[1]
    max_retries = cfg.upload_max_retries

    for attempt in range(max_retries + 1):
        try:
            with open(path, "rb") as f:
                m = MultipartEncoder(
                    fields={
                        "deviceAssetId": f"syno-{unit_id}",
                        "deviceId": "synology-migration",
                        "fileCreatedAt": epoch_to_iso(takentime),
                        "fileModifiedAt": epoch_to_iso(mtime),
                        "isFavorite": "false",
                        "fileExtension": file_ext,
                        "duration": "0",
                        "assetData": (filename, f, "application/octet-stream"),
                    }
                )
                resp = requests.post(
                    f"{immich_url}/api/assets",
                    headers={
                        "x-api-key": api_key,
                        "Content-Type": m.content_type,
                    },
                    data=m,
                    timeout=600,
                )
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                backoff = cfg.upload_retry_base_backoff * (2**attempt)
                log.warning(
                    "    retry %d/%d unit=%d after %ds (%s)",
                    attempt + 1,
                    max_retries,
                    unit_id,
                    backoff,
                    str(e)[:100],
                )
                time.sleep(backoff)
                continue
            return ("error", str(e)[:200])

        if resp.status_code in (200, 201):
            body = resp.json()
            status = body.get("status", "unknown")
            return (status, body.get("id", ""))
        elif resp.status_code >= 500 and attempt < max_retries:
            backoff = cfg.upload_retry_base_backoff * (2**attempt)
            log.warning(
                "    retry %d/%d unit=%d after %ds (HTTP %d)",
                attempt + 1,
                max_retries,
                unit_id,
                backoff,
                resp.status_code,
            )
            time.sleep(backoff)
            continue
        else:
            return (f"http_{resp.status_code}", resp.text[:200])

    return ("error", "max retries exceeded")


def main():
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    upload_users = os.environ.get("UPLOAD_USERS", "all").lower().split(",")
    checkpoint_dir = os.environ.get("CHECKPOINT_DIR", "/checkpoint")

    if dry_run:
        log.info("*** DRY-RUN MODE — no uploads ***")

    if "all" in upload_users:
        target_syno_ids = sorted(cfg.syno_to_immich.keys())
    else:
        target_syno_ids = []
        for u in upload_users:
            u = u.strip()
            try:
                sid = int(u)
            except ValueError:
                log.warning("Invalid syno_user_id '%s', skipping", u)
                continue
            if sid in cfg.syno_to_immich:
                target_syno_ids.append(sid)
            else:
                log.warning("Unknown syno_user_id '%s', skipping", u)

    if not target_syno_ids:
        log.error("No users to process")
        sys.exit(1)

    log.info("Processing syno users: %s", target_syno_ids)

    syno_conn = connect(cfg.syno_db.dsn)
    immich_conn = connect(cfg.immich_db.dsn)

    owner_to_synos = {}
    for sid in target_syno_ids:
        owner_id = cfg.syno_to_immich[sid].immich_user_id
        owner_to_synos.setdefault(owner_id, []).append(sid)

    grand_stats = {
        "uploaded": 0,
        "skipped_existing": 0,
        "skipped_dedup": 0,
        "file_error": 0,
        "upload_error": 0,
        "total_units": 0,
    }

    for owner_id, syno_ids in owner_to_synos.items():
        api_key = cfg.syno_to_immich[syno_ids[0]].get_api_key()
        if not api_key:
            log.error("Missing API key for immich owner %s", owner_id)
            sys.exit(1)

        log.info("")
        log.info("=" * 60)
        log.info("Processing immich owner: %s (syno users: %s)", owner_id, syno_ids)
        log.info("=" * 60)

        existing = load_immich_checksums(immich_conn, owner_id)
        log.info("  %d existing assets in immich for this owner", len(existing))

        units = get_syno_units(syno_conn, syno_ids)
        log.info("  %d syno units to process", len(units))
        grand_stats["total_units"] += len(units)

        checkpoint_path = f"{checkpoint_dir}/to_upload_{owner_id}.json"

        to_upload = []

        if os.path.exists(checkpoint_path):
            log.info("  Phase 1: loading checkpoint %s", checkpoint_path)
            with open(checkpoint_path) as cf:
                checkpointed = json.load(cf)
            log.info("  Checkpoint has %d files hashed", len(checkpointed))

            still_pending = []
            for entry in checkpointed:
                if entry["sha1_hex"] in {h.hex() for h in existing}:
                    grand_stats["skipped_existing"] += 1
                else:
                    still_pending.append(entry)
            log.info(
                "  After re-filtering against immich: %d still pending (%d already uploaded since checkpoint)",
                len(still_pending),
                len(checkpointed) - len(still_pending),
            )
            to_upload = still_pending
            hash_errors = 0
        else:
            log.info("  Phase 1: hashing + dedup (no checkpoint found)...")
            seen_hashes = set()
            hash_errors = 0
            start = time.time()
            checkpoint_entries = []

            for i, u in enumerate(units):
                if (i + 1) % 2000 == 0:
                    elapsed = time.time() - start
                    rate = (i + 1) / elapsed
                    log.info(
                        "    hashed %d/%d (%.0f%%) — to_upload=%d dup=%d exist=%d err=%d | rate=%.0f/s",
                        i + 1,
                        len(units),
                        100 * (i + 1) / len(units),
                        len(to_upload),
                        grand_stats["skipped_dedup"],
                        grand_stats["skipped_existing"],
                        hash_errors,
                        rate,
                    )

                path = cfg.nfs_path(u["id_user"], u["folder_name"], u["filename"])
                if path is None:
                    continue

                sha1 = compute_sha1(path)
                if sha1 is None:
                    hash_errors += 1
                    continue

                if sha1 in seen_hashes:
                    grand_stats["skipped_dedup"] += 1
                    continue
                seen_hashes.add(sha1)

                if sha1 in existing:
                    grand_stats["skipped_existing"] += 1
                    continue

                to_upload.append(u)
                checkpoint_entries.append(
                    {
                        "unit_id": u["unit_id"],
                        "id_user": u["id_user"],
                        "filename": u["filename"],
                        "folder_name": u["folder_name"],
                        "filesize": u["filesize"],
                        "takentime": u["takentime"],
                        "mtime": u["mtime"],
                        "sha1_hex": sha1.hex(),
                    }
                )

            try:
                os.makedirs(checkpoint_dir, exist_ok=True)
                with open(checkpoint_path, "w") as cf:
                    json.dump(checkpoint_entries, cf)
                log.info(
                    "  Checkpoint written: %s (%d entries)",
                    checkpoint_path,
                    len(checkpoint_entries),
                )
            except OSError as e:
                log.warning("  Could not write checkpoint: %s", e)

            log.info(
                "  Phase 1 done: %d to upload, %d local dupes skipped, %d already in immich, %d hash errors",
                len(to_upload),
                grand_stats["skipped_dedup"],
                grand_stats["skipped_existing"],
                hash_errors,
            )

        if dry_run or not to_upload:
            if not to_upload:
                log.info("  Nothing to upload for %s", owner_id)
            continue

        log.info("  Phase 2: uploading %d files (sequential)...", len(to_upload))
        upload_start = time.time()

        for i, u in enumerate(to_upload):
            if (i + 1) % 100 == 0:
                elapsed = time.time() - upload_start
                done = i + 1
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (len(to_upload) - done) / rate if rate > 0 else 0
                log.info(
                    "    uploaded %d/%d (%.1f%%) | ok=%d err=%d | rate=%.1f/s ETA=%.0fmin",
                    done,
                    len(to_upload),
                    100 * done / len(to_upload),
                    grand_stats["uploaded"],
                    grand_stats["upload_error"],
                    rate,
                    remaining / 60,
                )

            try:
                path = cfg.nfs_path(u["id_user"], u["folder_name"], u["filename"])
                if path is None:
                    continue
                status, detail = upload_file(
                    api_key,
                    cfg.immich_url.rstrip("/"),
                    u["unit_id"],
                    path,
                    u["takentime"],
                    u["mtime"],
                )
            except Exception as e:
                status = "exception"
                detail = f"{type(e).__name__}: {str(e)[:150]}"

            if status in ("created", "replaced"):
                grand_stats["uploaded"] += 1
            elif status in ("duplicate", "skip"):
                grand_stats["skipped_existing"] += 1
            else:
                grand_stats["upload_error"] += 1
                if grand_stats["upload_error"] <= cfg.upload_error_abort_threshold:
                    log.warning(
                        "    UPLOAD ERROR unit=%d status=%s detail=%s",
                        u["unit_id"],
                        status,
                        detail,
                    )
                if grand_stats["upload_error"] == cfg.upload_error_abort_threshold:
                    log.error("    Too many errors, aborting to preserve logs")
                    break

        elapsed = time.time() - upload_start
        log.info(
            "  Phase 2 done for %s: %d uploaded in %.1f min",
            owner_id,
            grand_stats["uploaded"],
            elapsed / 60,
        )

    log.info("")
    log.info("=" * 60)
    log.info("=== Upload Summary ===")
    log.info("  Total units processed:  %d", grand_stats["total_units"])
    log.info("  Uploaded (new):         %d", grand_stats["uploaded"])
    log.info("  Skipped (in immich):    %d", grand_stats["skipped_existing"])
    log.info("  Skipped (local dedup):  %d", grand_stats["skipped_dedup"])
    log.info("  File read errors:       %d", grand_stats["file_error"])
    log.info("  Upload errors:          %d", grand_stats["upload_error"])
    log.info("=" * 60)

    syno_conn.close()
    immich_conn.close()


if __name__ == "__main__":
    import traceback

    try:
        main()
    except Exception:
        log.error("FATAL EXCEPTION — full traceback:")
        log.error(traceback.format_exc())
        sys.stderr.flush()
        raise
