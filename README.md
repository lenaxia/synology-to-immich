# Synology Photos → Immich Migration

Migrate photos, videos, and face tags from **Synology Photos** to **[Immich](https://immich.app/)**.

Built and tested on a real-world migration of **220K+ assets** (126K photos for one user alone).

## What It Does

| Phase | Command | Description |
|-------|---------|-------------|
| 0 | `syno-dump` | Create a read-only copy of the Synology Photos DB |
| 1 | `syno-bridge` | SHA-1 match Synology photos to Immich assets |
| 2 | `syno-upload` | Upload missing photos via Immich REST API |
| 3 | `syno-faces` | Match Synology face tags to Immich detected faces |

All phases are **idempotent** — safe to re-run, they skip already-completed work.

## Install

### Option A: pip (any OS with Python 3.10+)

```bash
git clone https://github.com/lenaxia/synology-to-immich.git
cd synology-to-immich
pip install -e .
```

Then run any command:
```bash
syno-bridge
syno-upload
syno-faces
```

### Option B: Docker

```bash
docker run --rm \
  -v ./config.yaml:/config/config.yaml:ro \
  -v /mnt/syno-photos:/mnt/syno-photos:ro \
  -e PGPASSWORD=your_pg_password \
  ghcr.io/lenaxia/synology-to-immich:latest \
  syno-bridge
```

### Option C: Docker Compose

```bash
cp config.example.yaml config.yaml
# Edit config.yaml, then:
docker compose run syno-migration syno-bridge
```

### Option D: Kubernetes

See `deploy/k8s/` for Job manifests.

## Quick Start

### 1. Configure

```bash
cp config.example.yaml config.yaml
```

Fill in:
- **Synology DB** connection (a restored copy — never connect to the production NAS DB)
- **Immich DB** connection
- **Immich API** URL
- **NFS mount paths** (where Synology photo shares are mounted)
- **User mappings** (Synology user IDs → Immich user UUIDs)

### 2. Dump the Synology Photos DB

**Never operate on the Synology's production database.** Create a copy:

```bash
# Via SSH (recommended):
ssh admin@syno 'sudo -u postgres pg_dump app' > syno_photos_dump.sql
createdb syno_copy
psql -d syno_copy < syno_photos_dump.sql

# Or via the tool:
syno-dump --syno-host 192.168.1.100 --restore-host localhost --restore-db syno_copy
```

### 3. Create bridge tables in Immich DB

```bash
psql -h <immich-host> -d immich -f schema/01_syno_photo_migration.sql
psql -h <immich-host> -d immich -f schema/02_syno_face_migration.sql
```

### 4. Run the migration

```bash
export CONFIG_PATH=./config.yaml

# Phase 1: Build SHA-1 bridge (matches Synology photos to Immich assets)
syno-bridge

# Phase 2: Upload missing photos
syno-upload

# Phase 3: Match face tags (run after Immich finishes face detection)
syno-faces
```

### Finding Your User IDs

**Synology user IDs:**
```bash
psql -h <syno-host> -d app -c "SELECT id, name FROM user_info ORDER BY id"
```

**Immich user UUIDs:**
```bash
psql -h <immich-host> -d immich -c 'SELECT id, email FROM "user" ORDER BY email'
```

## Key Design Decisions

### SHA-1 Bridge (not filenames)

iPhone filenames collide massively (`IMG_0001.HEIC` exists for every device, every year). We hash file **bytes** via SHA-1 and match against Immich's `asset.checksum`. This gives byte-exact matching.

**The `duplicate_hash` trap:** Synology's `duplicate_hash` field is NOT a content hash — it groups files sharing metadata (e.g., iPhone live-photo video components with identical duration) even when their bytes differ. The bridge handles this by hashing each sibling individually.

### Streaming Uploads

Uses `requests-toolbelt.MultipartEncoder` to stream files from disk without buffering into memory. Critical for multi-GB video files. Includes retry with exponential backoff and JSON checkpoint persistence for crash recovery.

### Face Matching via IoU

Synology stores face bounding boxes in normalized coordinates; Immich uses pixel coordinates. The matcher converts between the two and computes Intersection-over-Union (IoU) to find the best match. Majority vote across all photos of a person determines the Immich person cluster assignment.

## Immich Compatibility

Tested against **Immich v3.1.x**. Queries these Immich tables:
- `asset` (`checksum`, `ownerId`, `originalFileName`)
- `asset_face` (`boundingBoxX1/Y1/X2/Y2`, `imageWidth/Height`, `personId`)
- `person` (`id`, `name`)

## Requirements

- **Python 3.10+** (or Docker)
- **PostgreSQL** accessible (Immich's Postgres, a separate instance, or Docker)
- **Immich v3.x** running with API access
- **Synology NAS** with photos exported via NFS (read-only is fine)

## License

MIT — see [LICENSE](LICENSE).
