-- Bridge table: maps Synology photo units to Immich assets.
-- Created in the Immich database.
CREATE TABLE IF NOT EXISTS syno_photo_migration (
    syno_unit_id    BIGINT PRIMARY KEY,
    immich_asset_id UUID NOT NULL,
    syno_user_id    BIGINT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_spm_immich_asset_id ON syno_photo_migration(immich_asset_id);
CREATE INDEX IF NOT EXISTS idx_spm_syno_user_id    ON syno_photo_migration(syno_user_id);
