-- Face match table: maps Synology face detections to Immich asset_face rows.
-- Created in the Immich database.
CREATE TABLE IF NOT EXISTS syno_face_migration (
    syno_face_id      BIGINT PRIMARY KEY,
    immich_face_id    UUID,
    immich_asset_id   UUID,
    immich_person_id  UUID,
    iou_score         FLOAT,
    syno_person_id    BIGINT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sfm_immich_person_id ON syno_face_migration(immich_person_id);
CREATE INDEX IF NOT EXISTS idx_sfm_syno_person_id   ON syno_face_migration(syno_person_id);
