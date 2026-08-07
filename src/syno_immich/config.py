"""
Shared configuration loader for Synology → Immich migration.

Reads a YAML config file (CONFIG_PATH env var, default: /config/config.yaml)
and provides typed access to all migration settings.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


@dataclass
class DBConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    sslmode: str = "prefer"

    @property
    def dsn(self) -> str:
        pw = self.password or os.environ.get("PGPASSWORD", "")
        return f"host={self.host} port={self.port} dbname={self.dbname} user={self.user} password={pw} sslmode={self.sslmode}"


@dataclass
class UserMapping:
    syno_user_id: int
    immich_user_id: str
    mount: str
    home_dir: str
    api_key: str = ""
    api_key_env: str = ""

    def get_api_key(self) -> str:
        return self.api_key or os.environ.get(self.api_key_env, "")


@dataclass
class Config:
    syno_db: DBConfig
    immich_db: DBConfig
    immich_url: str
    admin_api_key: str
    nfs_mounts: dict[str, str]
    users: list[UserMapping]
    bridge_sample_size: int = 3000
    bridge_accuracy_threshold: float = 99.0
    upload_concurrency: int = 4
    upload_max_retries: int = 3
    upload_retry_base_backoff: int = 30
    upload_error_abort_threshold: int = 20
    face_iou_threshold: float = 0.3
    face_min_votes: int = 5
    face_margin_ratio: float = 2.0

    @property
    def syno_to_immich(self) -> dict[int, UserMapping]:
        return {u.syno_user_id: u for u in self.users}

    def nfs_path(self, syno_user_id: int, folder: str, filename: str) -> Optional[str]:
        user = self.syno_to_immich.get(syno_user_id)
        if user is None:
            return None
        root = self.nfs_mounts.get(user.mount)
        if root is None:
            return None
        return f"{root}/{user.home_dir}/Photos{folder}/{filename}"


def load_config(path: Optional[str] = None) -> Config:
    config_path = path or os.environ.get("CONFIG_PATH", "/config/config.yaml")
    if not os.path.exists(config_path):
        print(f"Config file not found: {config_path}", file=sys.stderr)
        print(
            "Copy config.example.yaml to config.yaml and fill in your values.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    def db(cfg_key: str, password_env: str = "") -> DBConfig:
        d = raw[cfg_key]
        return DBConfig(
            host=d["host"],
            port=d.get("port", 5432),
            dbname=d["dbname"],
            user=d["user"],
            password=d.get("password", "")
            or os.environ.get(password_env, os.environ.get("PGPASSWORD", "")),
            sslmode=d.get("sslmode", "prefer"),
        )

    syno_db = db("syno_db", "SYNO_DB_PASSWORD")
    immich_db = db("immich_db", "IMMICH_DB_PASSWORD")

    api = raw.get("immich_api", {})
    admin_key = api.get("admin_api_key", "") or os.environ.get("ADMIN_API_KEY", "")
    immich_url = api.get("url", "http://localhost:2283")

    mounts = raw.get("nfs_mounts", {})
    if not mounts:
        print("Error: nfs_mounts is empty in config", file=sys.stderr)
        sys.exit(1)

    users = []
    for u in raw.get("users", []):
        users.append(
            UserMapping(
                syno_user_id=u["syno_user_id"],
                immich_user_id=u["immich_user_id"],
                mount=u["mount"],
                home_dir=u["home_dir"],
                api_key=u.get("api_key", ""),
                api_key_env=u.get("api_key_env", ""),
            )
        )

    if not users:
        print("Error: no users configured", file=sys.stderr)
        sys.exit(1)

    bridge = raw.get("bridge", {})
    upload = raw.get("upload", {})
    faces = raw.get("faces", {})

    return Config(
        syno_db=syno_db,
        immich_db=immich_db,
        immich_url=immich_url,
        admin_api_key=admin_key,
        nfs_mounts=mounts,
        users=users,
        bridge_sample_size=bridge.get("sample_size", 3000),
        bridge_accuracy_threshold=bridge.get("accuracy_threshold", 99.0),
        upload_concurrency=upload.get("concurrency", 4),
        upload_max_retries=upload.get("max_retries", 3),
        upload_retry_base_backoff=upload.get("retry_base_backoff", 30),
        upload_error_abort_threshold=upload.get("error_abort_threshold", 20),
        face_iou_threshold=faces.get("iou_threshold", 0.3),
        face_min_votes=faces.get("min_votes", 5),
        face_margin_ratio=faces.get("margin_ratio", 2.0),
    )
