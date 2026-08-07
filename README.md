# Synology Photos → Immich Migration

Migrate photos, videos, and face tags from **Synology Photos** to **[Immich](https://immich.app/)**.

This toolset was built for a real-world migration of 220K+ assets. It handles:

- **Phase 1 — Bridge**: SHA-1 matching of Synology photos to Immich assets
- **Phase 2 — Upload**: REST API upload of missing photos via streaming multipart
- **Phase 3 — Faces**: Bounding-box IoU matching of Synology face tags to Immich detected faces

## How It Works

```
Synology NAS (NFS)          Synology DB Copy           Immich
┌─────────────────┐        ┌──────────────────┐      ┌──────────────────┐
│ /volume1/homes  │        │  PostgreSQL       │      │  PostgreSQL       │
│   user1/Photos  │        │  (restored copy   │      │  (immich DB)      │
│   user2/Photos  │◄───────│   of synophoto)   │      │                   │
│   ...           │  NFS   │                   │      │  REST API         │
└─────────────────┘ read   │  unit, folder,    │      │  /api/assets      │
                           │  person, face     │      │                   │
                           └──────────────────┘      └──────────────────┘
                                    │                          │
                                    └──────────┬───────────────┘
                                               │
                          Phase 1: SHA-1 bridge (unit ↔ asset)
                          Phase 2: Upload missing photos
                          Phase 3: Face name matching (IoU)
```

## Prerequisites

1. **Immich** installed and running (v3.x)
2. **Synology NAS** with NFS shares exported (read-only is fine)
3. **PostgreSQL** accessible (can be the Immich Postgres, a separate instance, or Docker)
4. **Python 3.12+**

## Quick Start

### 1. Copy `config.example.yaml` → `config.yaml`

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml` and fill in:
- Synology DB connection (the restored copy, NOT the production NAS DB)
- Immich DB connection
- Immich API URL
- NFS mount paths
- User mappings (Synology user IDs → Immich user UUIDs)

### 2. Dump the Synology Photos DB (read-only)

**Never operate on the Synology's production database.** Create a copy:

```bash
# Option A: Remote dump (if Synology PostgreSQL is network-accessible)
python 00-dump-syno-db/dump_syno_db.py \
    --syno-host 192.168.1.100 \
    --restore-host localhost \
    --restore-db syno_copy

# Option B: SSH dump (recommended)
ssh admin@syno 'sudo -u postgres pg_dump app' > syno_photos_dump.sql
createdb syno_copy
psql -d syno_copy < syno_photos_dump.sql
```

### 3. Create bridge tables in the Immich DB

```bash
psql -h <immich-host> -U postgres -d immich -f schema/01_syno_photo_migration.sql
psql -h <immich-host> -U postgres -d immich -f schema/02_syno_face_migration.sql
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Run the migration phases

```bash
# Phase 1: Build the SHA-1 bridge (matches Synology photos to Immich assets)
CONFIG_PATH=./config.yaml python 01-bridge/build_bridge.py

# Phase 2: Upload missing photos (users not yet fully in Immich)
CONFIG_PATH=./config.yaml python 02-upload/upload.py

# Phase 3: Match Synology face tags to Immich detected faces
CONFIG_PATH=./config.yaml python 03-faces/match_faces.py
```

### Finding Your User IDs

**Synology user IDs:**
```bash
psql -h <syno-host> -U postgres -d app -c "SELECT id, name FROM user_info ORDER BY id"
```

**Immich user UUIDs:**
```bash
psql -h <immich-host> -U postgres -d immich -c 'SELECT id, email FROM "user" ORDER BY email'
```

## Key Design Decisions

### SHA-1 Bridge (Phase 1)

Rather than relying on filenames (which collide across devices — e.g., `IMG_0001.JPG` exists for every iPhone), we hash file bytes via SHA-1 and match against Immich's `asset.checksum` column. This provides byte-exact matching.

**The `duplicate_hash` trap:** Synology's `duplicate_hash` field is NOT a content hash. Synology assigns the same `duplicate_hash` to files sharing metadata (e.g., iPhone live-photo video components with identical duration) even when their bytes differ. The bridge script handles this by hashing each sibling individually rather than trusting `duplicate_hash`.

### Streaming Uploads (Phase 2)

Uses `requests-toolbelt.MultipartEncoder` to stream files directly from NFS without buffering into memory. This is critical for multi-GB video files. Includes retry with exponential backoff and checkpoint persistence for crash recovery.

### Face Matching (Phase 3)

Synology stores face bounding boxes in normalized coordinates. Immich uses pixel coordinates. The matcher converts between the two and computes Intersection-over-Union (IoU) to find the best match. Majority vote across all photos of a person determines the Immich person cluster assignment.

## Immich Version Compatibility

Tested against **Immich v3.1.x**. The scripts query these Immich tables:
- `asset` (checksum, ownerId, originalFileName)
- `asset_face` (boundingBoxX1/Y1/X2/Y2, imageWidth/Height, personId)
- `person` (id, name)

If Immich changes its schema in future versions, these queries will need updating.

## Idempotency

All three phases are idempotent and safe to re-run:
- **Bridge**: `INSERT ... ON CONFLICT (syno_unit_id) DO NOTHING`
- **Upload**: Checks Immich's checksum index before uploading (skips existing)
- **Faces**: `INSERT ... ON CONFLICT (syno_face_id) DO NOTHING`

## License

MIT — see [LICENSE](LICENSE).
