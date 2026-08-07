#!/usr/bin/env python3
"""
build_bridge.py — Populate immich.syno_photo_migration by SHA-1 matching

Walks NFS-mounted Synology photos, computes SHA-1 of each distinct photo
(deduped by Synology's duplicate_hash MD5), and matches against Immich's
asset.checksum (also SHA-1). Inserts bridge rows linking syno_unit_id to
immich_asset_id.

Idempotent: ON CONFLICT DO NOTHING on syno_unit_id PK.
Resumable: skips units already in syno_photo_migration.
Verified: post-run SHA-1 spot-check (stratified sample per user).

Env vars:
  CONFIG_PATH   Path to YAML config file (default: /config/config.yaml)
  DRY_RUN       If "true", no DB writes (default: false)
  MAX_PHOTOS    Optional smoke-test limit (integer)
  TARGET_UNITS  Optional path to a file with one syno_unit_id per line
"""

import csv
import hashlib
import logging
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path


import psycopg2
import psycopg2.extras

from syno_immich.config import load_config

cfg = load_config()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bridge")


def connect(dsn):
    conn = psycopg2.connect(dsn)
    conn.set_session(autocommit=False)
    return conn


def get_already_bridged(conn):
    """Return set of syno_unit_ids already in syno_photo_migration."""
    with conn.cursor() as cur:
        cur.execute("SELECT syno_unit_id FROM syno_photo_migration")
        return {row[0] for row in cur.fetchall()}


def get_distinct_syno_photos(conn):
    """
    Return (canonical, hash_to_units).

    SELECT DISTINCT ON (duplicate_hash) picks one canonical unit per photo
    to drive the walk. We also fetch ALL units sharing that hash (with their
    own folder, needed to build per-sibling NFS paths) so each can be hashed
    and matched individually.

    duplicate_hash is NOT a content hash. Synology assigns the same
    duplicate_hash to units that share metadata (e.g. iPhone live-photo
    videos with identical duration) even when their file bytes differ.
    Each sibling MUST be hashed and matched on its own content, not blindly
    mapped to the canonical unit's match.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (duplicate_hash)
                u.id AS unit_id, u.id_user, u.filename,
                u.duplicate_hash, f.name AS folder_name
            FROM unit u
            JOIN folder f ON f.id = u.id_folder
            WHERE u.duplicate_hash IS NOT NULL
              AND u.duplicate_hash <> ''
            ORDER BY u.duplicate_hash, u.id
        """
        )
        canonical = cur.fetchall()

        cur.execute(
            """
            SELECT u.duplicate_hash, u.id AS unit_id, u.id_user, u.filename,
                   f.name AS folder_name
            FROM unit u
            JOIN folder f ON f.id = u.id_folder
            WHERE u.duplicate_hash IS NOT NULL AND u.duplicate_hash <> ''
            ORDER BY u.duplicate_hash, u.id
        """
        )
        hash_to_units = {}
        for row in cur.fetchall():
            hash_to_units.setdefault(row["duplicate_hash"], []).append(
                {
                    "unit_id": row["unit_id"],
                    "id_user": row["id_user"],
                    "filename": row["filename"],
                    "folder_name": row["folder_name"],
                }
            )

    return canonical, hash_to_units


def load_immich_checksum_index(conn):
    """
    Return dict: {checksum_bytes: [(asset_id, owner_id), ...]}

    Keyed by raw SHA-1 bytes for O(1) lookup. Multiple assets per checksum
    when the same photo exists in multiple owners' libraries.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT checksum, id, "ownerId"
            FROM asset
            WHERE "deletedAt" IS NULL AND checksum IS NOT NULL
        """
        )
        index = {}
        for checksum, asset_id, owner_id in cur.fetchall():
            index.setdefault(bytes(checksum), []).append((str(asset_id), str(owner_id)))
    return index


def load_immich_filename_index(conn):
    """
    Return set of all originalFileName values in Immich.

    Used as a pre-filter: only hash Synology photos whose filename exists in
    Immich. Cuts NFS reads from the full set to only potential matches.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT "originalFileName"
            FROM asset
            WHERE "deletedAt" IS NULL AND "originalFileName" IS NOT NULL
        """
        )
        return {row[0] for row in cur.fetchall()}


def insert_bridge_rows(conn, rows):
    """
    Batch insert into syno_photo_migration. Each row:
    (syno_unit_id, immich_asset_id, syno_user_id).
    ON CONFLICT DO NOTHING for idempotency.
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO syno_photo_migration (syno_unit_id, immich_asset_id, syno_user_id)
            VALUES %s
            ON CONFLICT (syno_unit_id) DO NOTHING
            """,
            rows,
            page_size=1000,
        )
        return cur.rowcount


def compute_sha1(path):
    """Compute SHA-1 of a file, streaming to handle large files."""
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.digest()
    except (FileNotFoundError, PermissionError, IsADirectoryError, OSError) as e:
        log.debug("  skip %s: %s", path, e)
        return None


def main():
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    max_photos = int(os.environ["MAX_PHOTOS"]) if "MAX_PHOTOS" in os.environ else None
    target_units_path = os.environ.get("TARGET_UNITS")

    if dry_run:
        log.info("*** DRY-RUN MODE — no DB writes ***")
    if max_photos:
        log.info("*** LIMITING TO %d PHOTOS (smoke test) ***", max_photos)
    if target_units_path:
        log.info("*** TARGET MODE: processing units from %s ***", target_units_path)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    unmatched_path = Path(f"/tmp/unmatched-{ts}.csv")

    syno_conn = connect(cfg.syno_db.dsn)
    immich_conn = connect(cfg.immich_db.dsn)

    log.info("Loading already-bridged units...")
    bridged = get_already_bridged(immich_conn)
    log.info("  %d units already bridged", len(bridged))

    log.info("Loading Immich checksum index...")
    checksum_index = load_immich_checksum_index(immich_conn)
    log.info(
        "  %d distinct checksums across %d assets",
        len(checksum_index),
        sum(len(v) for v in checksum_index.values()),
    )

    log.info("Loading Immich filename index (pre-filter)...")
    immich_filenames = load_immich_filename_index(immich_conn)
    log.info("  %d distinct filenames in Immich", len(immich_filenames))

    log.info("Loading distinct Synology photos...")
    canonical, hash_to_units = get_distinct_syno_photos(syno_conn)
    log.info("  %d distinct photos (by MD5)", len(canonical))

    matchable = [
        c
        for c in canonical
        if cfg.syno_to_immich.get(c["id_user"])
        and cfg.syno_to_immich[c["id_user"]].immich_user_id
    ]
    skipped_no_account = len(canonical) - len(matchable)
    log.info(
        "  %d matchable (user has Immich account), %d skipped (no account yet)",
        len(matchable),
        skipped_no_account,
    )

    before_filter = len(matchable)
    to_hash = [c for c in matchable if c["filename"] in immich_filenames]
    filtered_out = before_filter - len(to_hash)
    log.info(
        "  FILENAME PRE-FILTER: %d to hash, %d skipped (filename not in Immich) — cuts ~%.0f%% of NFS reads",
        len(to_hash),
        filtered_out,
        100 * filtered_out / before_filter if before_filter else 0,
    )

    to_process = [
        c
        for c in to_hash
        if not any(
            sib["unit_id"] in bridged for sib in hash_to_units[c["duplicate_hash"]]
        )
    ]
    log.info("  %d to process after removing already-bridged", len(to_process))

    if target_units_path:
        with open(target_units_path) as f:
            target_ids = {int(line.strip()) for line in f if line.strip().isdigit()}
        target_hashes = set()
        for h, units in hash_to_units.items():
            if any(sib["unit_id"] in target_ids for sib in units):
                target_hashes.add(h)
        to_process = [c for c in to_process if c["duplicate_hash"] in target_hashes]
        log.info(
            "  TARGET MODE: %d photos contain %d target unit_ids",
            len(to_process),
            len(target_ids),
        )

    if max_photos:
        to_process = to_process[:max_photos]
        log.info("  LIMITED to %d photos for smoke test", len(to_process))

    start_time = time.time()
    stats = {"matched": 0, "not_in_immich": 0, "file_error": 0, "units_bridged": 0}
    unmatched_rows = []
    batch = []
    BATCH_SIZE = 500
    user_tally = {}

    for i, photo in enumerate(to_process):
        if (i + 1) % 1000 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            remaining = (len(to_process) - i - 1) / rate if rate > 0 else 0
            match_rate = 100 * stats["matched"] / (i + 1)
            eta_min = remaining / 60
            log.info(
                "  Progress: %d/%d (%.1f%%) — matched=%d (%.1f%%) not_in_immich=%d errors=%d bridged=%d | rate=%.0f photos/min ETA=%.0fmin (%.0fs)",
                i + 1,
                len(to_process),
                100 * (i + 1) / len(to_process),
                stats["matched"],
                match_rate,
                stats["not_in_immich"],
                stats["file_error"],
                stats["units_bridged"],
                rate * 60,
                eta_min,
                remaining,
            )

        path = cfg.nfs_path(photo["id_user"], photo["folder_name"], photo["filename"])
        if path is None:
            continue

        sha1 = compute_sha1(path)
        if sha1 is None:
            stats["file_error"] += 1
            for sib in hash_to_units[photo["duplicate_hash"]]:
                unmatched_rows.append(
                    {
                        "syno_unit_id": sib["unit_id"],
                        "syno_user_id": sib["id_user"],
                        "reason": "file_read_error",
                        "path": path,
                    }
                )
            continue

        immich_matches = checksum_index.get(sha1, [])
        if not immich_matches:
            stats["not_in_immich"] += 1
            for sib in hash_to_units[photo["duplicate_hash"]]:
                unmatched_rows.append(
                    {
                        "syno_unit_id": sib["unit_id"],
                        "syno_user_id": sib["id_user"],
                        "reason": "not_uploaded_to_immich",
                        "path": path,
                    }
                )
            continue

        siblings = hash_to_units[photo["duplicate_hash"]]
        stats["matched"] += 1

        if len(siblings) == 1:
            sib = siblings[0]
            suid = sib["id_user"]
            umap = cfg.syno_to_immich.get(suid)
            owner_id = umap.immich_user_id if umap else None
            if owner_id:
                asset_id = next(
                    (aid for aid, oid in immich_matches if oid == owner_id), None
                )
                if asset_id:
                    batch.append((sib["unit_id"], asset_id, suid))
                    stats["units_bridged"] += 1
                    user_tally[suid] = user_tally.get(suid, 0) + 1
        else:
            for sib in siblings:
                suid = sib["id_user"]
                umap = cfg.syno_to_immich.get(suid)
                owner_id = umap.immich_user_id if umap else None
                if not owner_id:
                    continue
                sib_path = cfg.nfs_path(suid, sib["folder_name"], sib["filename"])
                if sib_path is None:
                    continue
                sib_sha1 = compute_sha1(sib_path)
                if sib_sha1 is None:
                    continue
                sib_matches = checksum_index.get(sib_sha1, [])
                if not sib_matches:
                    continue
                asset_id = next(
                    (aid for aid, oid in sib_matches if oid == owner_id), None
                )
                if asset_id:
                    batch.append((sib["unit_id"], asset_id, suid))
                    stats["units_bridged"] += 1
                    user_tally[suid] = user_tally.get(suid, 0) + 1

        if len(batch) >= BATCH_SIZE:
            if not dry_run:
                insert_bridge_rows(immich_conn, batch)
                immich_conn.commit()
            log.debug(
                "  batch committed: %d rows | user_tally=%s", len(batch), user_tally
            )
            batch.clear()

    if batch and not dry_run:
        insert_bridge_rows(immich_conn, batch)
        immich_conn.commit()

    if unmatched_rows:
        try:
            with open(unmatched_path, "w", newline="") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["syno_unit_id", "syno_user_id", "reason", "path"]
                )
                writer.writeheader()
                writer.writerows(unmatched_rows)
        except OSError as e:
            log.warning("Could not write unmatched CSV to %s: %s", unmatched_path, e)

    elapsed_total = time.time() - start_time
    log.info("")
    log.info("=== Bridge Build Summary ===")
    log.info("  Distinct photos processed:    %d", len(to_process))
    log.info("  Matched to Immich assets:     %d", stats["matched"])
    log.info("  Not in Immich (not uploaded): %d", stats["not_in_immich"])
    log.info("  File read errors:             %d", stats["file_error"])
    log.info("  Bridge rows inserted:         %d", stats["units_bridged"])
    log.info("  Elapsed:                      %.1f min", elapsed_total / 60)
    log.info("  User distribution:            %s", user_tally)
    log.info(
        "  Unmatched CSV:                %s",
        unmatched_path if unmatched_rows else "(none)",
    )
    if dry_run:
        log.info("  (DRY-RUN — no rows actually written)")

    if not dry_run and stats["units_bridged"] > 0:
        verify_bridge(immich_conn, syno_conn, stats["units_bridged"])

    syno_conn.close()
    immich_conn.close()


def verify_bridge(immich_conn, syno_conn, total_rows):
    """
    Post-run verification: sample bridge rows stratified per syno_user_id,
    re-compute SHA-1 from NFS, and compare to Immich checksum.

    Sample size targets cfg.bridge_sample_size rows, stratified proportionally
    per user. Flags for review below cfg.bridge_accuracy_threshold accuracy.
    """
    log.info("")
    log.info("=== Post-run Verification ===")

    with immich_conn.cursor() as cur:
        cur.execute(
            """
            SELECT spm.syno_user_id, COUNT(*) AS cnt
            FROM syno_photo_migration spm
            GROUP BY spm.syno_user_id ORDER BY cnt DESC
        """
        )
        user_counts = cur.fetchall()

    total = sum(c for _, c in user_counts)
    target_sample = min(cfg.bridge_sample_size, total)

    log.info(
        "  Total bridge rows: %d, sampling %d (stratified per user)",
        total,
        target_sample,
    )

    sample_per_user = {}
    allocated = 0
    for suid, cnt in user_counts:
        n = max(50, round(target_sample * cnt / total))
        n = min(n, cnt)
        sample_per_user[suid] = n
        allocated += n

    if allocated != target_sample:
        largest = max(sample_per_user, key=lambda k: sample_per_user[k])
        sample_per_user[largest] += target_sample - allocated

    log.info("  Sample allocation: %s", sample_per_user)

    all_samples = []
    for suid, n in sample_per_user.items():
        with immich_conn.cursor() as cur:
            cur.execute(
                """
                SELECT spm.syno_unit_id, spm.syno_user_id, encode(a.checksum, 'hex')
                FROM syno_photo_migration spm
                JOIN asset a ON a.id = spm.immich_asset_id
                WHERE spm.syno_user_id = %s
                ORDER BY RANDOM() LIMIT %s
            """,
                (suid, n),
            )
            all_samples.extend(cur.fetchall())

    log.info("  Sampled %d rows total, verifying...", len(all_samples))

    unit_ids = [s[0] for s in all_samples]
    with syno_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT u.id, u.id_user, u.filename, f.name AS folder_name
            FROM unit u JOIN folder f ON f.id = u.id_folder
            WHERE u.id = ANY(%s)
        """,
            (unit_ids,),
        )
        unit_paths = {r["id"]: r for r in cur.fetchall()}

    matched = mismatched = missing = path_missing = 0
    mismatches = []

    for unit_id, suid, immich_sha1 in all_samples:
        u = unit_paths.get(unit_id)
        if not u:
            path_missing += 1
            continue
        path = cfg.nfs_path(u["id_user"], u["folder_name"], u["filename"])
        if not path:
            path_missing += 1
            continue
        sha1 = compute_sha1(path)
        if sha1 is None:
            missing += 1
            continue
        if sha1.hex() == immich_sha1:
            matched += 1
        else:
            mismatched += 1
            if len(mismatches) < 10:
                mismatches.append((unit_id, sha1.hex()[:12], immich_sha1[:12], path))

    total_checked = matched + mismatched + missing + path_missing
    accuracy = 100 * matched / total_checked if total_checked else 0

    log.info(
        "  RESULTS: matched=%d mismatched=%d missing=%d path_missing=%d / %d checked",
        matched,
        mismatched,
        missing,
        path_missing,
        total_checked,
    )
    log.info("  ACCURACY: %.2f%%", accuracy)
    if mismatches:
        log.warning("  FIRST MISMATCHES (showing up to 10):")
        for uid, nfs, imm, path in mismatches:
            log.warning("    unit=%d nfs=%s immich=%s path=%s", uid, nfs, imm, path)

    if accuracy < cfg.bridge_accuracy_threshold and total_checked >= 100:
        log.error(
            "  ACCURACY BELOW %.1f%% THRESHOLD — flagging for review",
            cfg.bridge_accuracy_threshold,
        )

    return accuracy


if __name__ == "__main__":
    main()
