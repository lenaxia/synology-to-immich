# Project Context: synology-to-immich

## What this project is

A Python toolkit for migrating photos, videos, and face tags from Synology
Photos to Immich. Three phases: SHA-1 bridge matching, REST API uploads,
and IoU-based face name matching.

## Tech stack

- **Language**: Python 3.10+
- **Dependencies**: psycopg2-binary, requests, requests-toolbelt, PyYAML
- **Package**: pip-installable via pyproject.toml (entry points: syno-bridge,
  syno-upload, syno-faces, syno-dump)
- **Deployment**: Native Python, Docker, or Kubernetes (optional manifests)

## Key design constraints

- **Never operate on the Synology production database** — always work from
  a restored copy (dump_syno_db.py or pg_dump)
- **SHA-1 matching, not filenames** — iPhone filenames collide massively
- **duplicate_hash is NOT a content hash** — Synology groups files by
  metadata similarity, not byte identity. Each sibling must be hashed
  individually.
- **Streaming uploads** — MultipartEncoder, never buffer full files in
  memory (multi-GB video files)
- **All phases are idempotent** — ON CONFLICT DO NOTHING, checksum-skip

## File structure

```
src/syno_immich/     # Package: config.py, bridge.py, upload.py, faces.py, dump.py, cli.py
schema/              # DDL for bridge tables
deploy/k8s/          # Optional Kubernetes Job manifests
config.example.yaml  # Template config (users fill in their values)
```
