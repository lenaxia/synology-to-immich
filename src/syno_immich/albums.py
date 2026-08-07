"""
Migrate Synology Photos albums to Immich.

For each Synology album:
1. Query album → items → units → bridge → immich asset IDs
2. Create the album in Immich directly via SQL (ensures correct ownership)
3. Link bridged assets via SQL INSERT into album_asset

Uses SQL instead of the REST API because Immich's API enforces ownership
permissions: you can only add assets to an album if you own both. During
migration, assets may be owned by different users. SQL bypasses this.

Idempotent: checks for existing albums by name + owner before creating.
Skips empty albums (item_count = 0).

Env vars:
  CONFIG_PATH   Path to config.yaml (default: /config/config.yaml)
  DRY_RUN       If "true", no writes, just report what would happen
"""

import logging
import os
import sys
import time
from collections import defaultdict

import psycopg2
import psycopg2.extras

from syno_immich.config import load_config

cfg = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("albums")


def connect(dsn):
    conn = psycopg2.connect(dsn)
    conn.set_session(autocommit=True)
    return conn


def get_syno_albums(conn, target_user_ids):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, id_user, name, shared, item_count, create_time
            FROM album
            WHERE id_user = ANY(%s) AND item_count > 0
            ORDER BY id_user, name
        """,
            (list(target_user_ids),),
        )
        return cur.fetchall()


def get_album_asset_ids(syno_conn, immich_conn, album_id):
    with syno_conn.cursor() as cur:
        cur.execute(
            """
            SELECT u.id AS unit_id
            FROM many_item_has_many_normal_album m
            JOIN item i ON i.id = m.id_item
            JOIN unit u ON u.id_item = i.id
            WHERE m.id_normal_album = %s
        """,
            (album_id,),
        )
        unit_ids = [row[0] for row in cur.fetchall()]

    if not unit_ids:
        return []

    with immich_conn.cursor() as cur:
        cur.execute(
            """
            SELECT immich_asset_id FROM syno_photo_migration
            WHERE syno_unit_id = ANY(%s)
        """,
            (unit_ids,),
        )
        return [row[0] for row in cur.fetchall()]


def get_existing_immich_albums(immich_conn, owner_id):
    with immich_conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a."albumName"
            FROM album a
            JOIN album_user au ON au."albumId" = a.id
            WHERE au."userId" = %s AND a."deletedAt" IS NULL AND au.role = 'owner'
        """,
            (owner_id,),
        )
        return {row[1]: row[0] for row in cur.fetchall()}


def create_album_sql(immich_conn, name, owner_id):
    with immich_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO album ("albumName", "createdAt", "updatedAt", "description",
                              "isActivityEnabled", "order")
            VALUES (%s, now(), now(), '', true, 'desc')
            RETURNING id
        """,
            (name,),
        )
        album_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO album_user ("albumId", "userId", "role")
            VALUES (%s, %s, 'owner')
        """,
            (album_id, owner_id),
        )
    return album_id


def add_assets_sql(immich_conn, album_id, asset_ids):
    inserted = 0
    with immich_conn.cursor() as cur:
        for aid in asset_ids:
            cur.execute(
                """
                INSERT INTO album_asset ("albumId", "assetId", "createdAt", "updatedAt")
                VALUES (%s, %s, now(), now())
                ON CONFLICT DO NOTHING
            """,
                (album_id, aid),
            )
            inserted += cur.rowcount
    return inserted


def main():
    global cfg
    cfg = load_config()
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

    if dry_run:
        log.info("*** DRY-RUN MODE — no DB writes ***")

    syno_conn = connect(cfg.syno_db.dsn)
    immich_conn = connect(cfg.immich_db.dsn)

    target_user_ids = sorted(cfg.syno_to_immich.keys())
    albums = get_syno_albums(syno_conn, target_user_ids)
    log.info(
        "Found %d Synology albums with content (across %d users)",
        len(albums),
        len(target_user_ids),
    )

    stats = {
        "albums_created": 0,
        "albums_skipped_existing": 0,
        "assets_added": 0,
        "assets_unbridged": 0,
    }

    owner_cache = {}
    for album in albums:
        syno_user_id = album["id_user"]
        user = cfg.syno_to_immich.get(syno_user_id)
        if user is None:
            continue

        if syno_user_id not in owner_cache:
            owner_cache[syno_user_id] = get_existing_immich_albums(
                immich_conn, user.immich_user_id
            )
        existing = owner_cache[syno_user_id]

        album_name = album["name"].strip()
        if album_name in existing:
            log.info(
                "SKIP: '%s' (user %d) — album already exists in Immich",
                album_name,
                syno_user_id,
            )
            stats["albums_skipped_existing"] += 1
            continue

        asset_ids = get_album_asset_ids(syno_conn, immich_conn, album["id"])
        if not asset_ids:
            log.info(
                "SKIP: '%s' (user %d) — no bridged assets", album_name, syno_user_id
            )
            continue

        log.info(
            "CREATE: '%s' (user %d, %d assets, shared=%s)",
            album_name,
            syno_user_id,
            len(asset_ids),
            album["shared"],
        )

        if dry_run:
            stats["albums_created"] += 1
            stats["assets_added"] += len(asset_ids)
            continue

        album_id = create_album_sql(immich_conn, album_name, user.immich_user_id)
        stats["albums_created"] += 1
        added = add_assets_sql(immich_conn, album_id, asset_ids)
        stats["assets_added"] += added
        stats["assets_unbridged"] += len(asset_ids) - added
        log.info("  → album %s: %d/%d assets added", album_id, added, len(asset_ids))
        owner_cache[syno_user_id][album_name] = album_id

    log.info("")
    log.info("=" * 60)
    log.info("=== Album Migration Summary ===")
    log.info("  Albums created:          %d", stats["albums_created"])
    log.info("  Albums skipped (exist):  %d", stats["albums_skipped_existing"])
    log.info("  Assets added:            %d", stats["assets_added"])
    log.info("  Assets unbridged:        %d", stats["assets_unbridged"])
    log.info("=" * 60)

    syno_conn.close()
    immich_conn.close()


if __name__ == "__main__":
    main()
