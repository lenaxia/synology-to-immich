"""Tests for config loading and YAML parsing."""

import os
import textwrap
import pytest

from syno_immich.config import load_config, Config, DBConfig, UserMapping


def write_config(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(content))
    return str(path)


class TestConfigLoading:
    def test_minimal_config(self, tmp_path):
        path = write_config(
            tmp_path,
            """
            syno_db:
              host: localhost
              dbname: app
              user: postgres
            immich_db:
              host: localhost
              dbname: immich
              user: postgres
            immich_api:
              url: http://localhost:2283
            nfs_mounts:
              photos: /mnt/photos
            users:
              - syno_user_id: 1
                immich_user_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
                mount: photos
                home_dir: user1
        """,
        )
        os.environ["CONFIG_PATH"] = path
        cfg = load_config()
        assert cfg.syno_db.host == "localhost"
        assert cfg.syno_db.dbname == "app"
        assert cfg.immich_db.dbname == "immich"
        assert cfg.immich_url == "http://localhost:2283"
        assert len(cfg.users) == 1
        assert cfg.users[0].syno_user_id == 1

    def test_missing_config_exits(self, tmp_path):
        os.environ["CONFIG_PATH"] = str(tmp_path / "nonexistent.yaml")
        with pytest.raises(SystemExit):
            load_config()

    def test_empty_users_exits(self, tmp_path):
        path = write_config(
            tmp_path,
            """
            syno_db:
              host: localhost
              dbname: app
              user: postgres
            immich_db:
              host: localhost
              dbname: immich
              user: postgres
            immich_api:
              url: http://localhost:2283
            nfs_mounts:
              photos: /mnt/photos
            users: []
        """,
        )
        os.environ["CONFIG_PATH"] = path
        with pytest.raises(SystemExit):
            load_config()

    def test_empty_nfs_mounts_exits(self, tmp_path):
        path = write_config(
            tmp_path,
            """
            syno_db:
              host: localhost
              dbname: app
              user: postgres
            immich_db:
              host: localhost
              dbname: immich
              user: postgres
            immich_api:
              url: http://localhost:2283
            nfs_mounts: {}
            users:
              - syno_user_id: 1
                immich_user_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
                mount: photos
                home_dir: user1
        """,
        )
        os.environ["CONFIG_PATH"] = path
        with pytest.raises(SystemExit):
            load_config()


class TestNfsPath:
    def test_valid_user(self):
        cfg = Config(
            syno_db=None,
            immich_db=None,
            immich_url="",
            admin_api_key="",
            nfs_mounts={"photos": "/mnt/photos"},
            users=[
                UserMapping(
                    syno_user_id=1,
                    immich_user_id="aaa",
                    mount="photos",
                    home_dir="john",
                )
            ],
        )
        path = cfg.nfs_path(1, "/2024/06", "IMG_0001.JPG")
        assert path == "/mnt/photos/john/Photos/2024/06/IMG_0001.JPG"

    def test_unknown_user(self):
        cfg = Config(
            syno_db=None,
            immich_db=None,
            immich_url="",
            admin_api_key="",
            nfs_mounts={"photos": "/mnt/photos"},
            users=[],
        )
        assert cfg.nfs_path(999, "/", "test.JPG") is None

    def test_unknown_mount(self):
        cfg = Config(
            syno_db=None,
            immich_db=None,
            immich_url="",
            admin_api_key="",
            nfs_mounts={"photos": "/mnt/photos"},
            users=[
                UserMapping(
                    syno_user_id=1,
                    immich_user_id="aaa",
                    mount="nonexistent",
                    home_dir="john",
                )
            ],
        )
        assert cfg.nfs_path(1, "/", "test.JPG") is None


class TestDSN:
    def test_dsn_with_password(self):
        db = DBConfig(
            host="localhost",
            port=5432,
            dbname="test",
            user="postgres",
            password="secret",
        )
        dsn = db.dsn
        assert "host=localhost" in dsn
        assert "password=secret" in dsn
        assert "dbname=test" in dsn

    def test_dsn_without_password_uses_env(self):
        os.environ["PGPASSWORD"] = "env_pw"
        db = DBConfig(
            host="localhost", port=5432, dbname="test", user="postgres", password=""
        )
        dsn = db.dsn
        assert "password=env_pw" in dsn
        del os.environ["PGPASSWORD"]


class TestUserApiKey:
    def test_inline_key(self):
        u = UserMapping(
            syno_user_id=1,
            immich_user_id="a",
            mount="x",
            home_dir="x",
            api_key="inline_key_123",
            api_key_env="USER_KEY",
        )
        assert u.get_api_key() == "inline_key_123"

    def test_env_key_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_USER_KEY", "env_key_456")
        u = UserMapping(
            syno_user_id=1,
            immich_user_id="a",
            mount="x",
            home_dir="x",
            api_key="",
            api_key_env="MY_USER_KEY",
        )
        assert u.get_api_key() == "env_key_456"

    def test_no_key(self, monkeypatch):
        monkeypatch.delenv("NO_KEY", raising=False)
        u = UserMapping(
            syno_user_id=1,
            immich_user_id="a",
            mount="x",
            home_dir="x",
            api_key="",
            api_key_env="NO_KEY",
        )
        assert u.get_api_key() == ""
