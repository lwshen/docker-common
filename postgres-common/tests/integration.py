"""Real PostgreSQL regression tests; requires Docker and PostgreSQL 18 client tools."""

import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[2]


def run(args, **kwargs):
    result = subprocess.run(args, text=True, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed:\n{result.stderr}\n{result.stdout}")
    return result.stdout.strip()


def main():
    names = ["backup-preflight-" + uuid.uuid4().hex[:10] for _ in range(2)]
    try:
        with tempfile.TemporaryDirectory(prefix="postgres-preflight-test-") as folder:
            work = Path(folder)
            environments = []
            for index, name in enumerate(names):
                password = "source-password" if index == 0 else "target-password"
                run(["docker", "run", "-d", "--name", name, "-p", "127.0.0.1::5432",
                     "-e", "POSTGRES_PASSWORD=" + password, "postgres:18"])
                port = run(["docker", "inspect", "--format",
                            '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}', name])
                env = {**os.environ, "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": port,
                       "POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": password,
                       "POSTGRES_DATABASE": "postgres", "PGPASSWORD": password,
                       "RESTORE_EXISTING_ROLES": "preserve", "DROP_PUBLIC": "no"}
                environments.append(env)
                for attempt in range(60):
                    ready = subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"], capture_output=True)
                    if ready.returncode == 0:
                        break
                    time.sleep(0.5)
                else:
                    raise RuntimeError("PostgreSQL did not become ready")

            source, target = environments

            def sql(env, query, database="postgres"):
                return run(["psql", "-XAt", "-v", "ON_ERROR_STOP=1", "-h", env["POSTGRES_HOST"],
                            "-p", env["POSTGRES_PORT"], "-U", "postgres", "-d", database, "-c", query], env=env)

            def extension(index, name, version, requires=""):
                shared = sql(environments[index], "SELECT setting FROM pg_config WHERE name = 'SHAREDIR'")
                files = {
                    name + ".control": f"default_version = '{version}'\nrelocatable = true\n" +
                                       (f"requires = '{requires}'\n" if requires else ""),
                    name + "--" + version + ".sql": "SELECT 1;\n",
                }
                for filename, content in files.items():
                    path = work / filename
                    path.write_text(content)
                    run(["docker", "cp", str(path), names[index] + ":" + shared + "/extension/" + filename])

            # A version/dependency change like pg_search gaining a vector dependency.
            extension(0, "backup_search", "1.0")
            extension(1, "backup_search", "2.0", "backup_vector")
            extension(1, "backup_vector", "1.0")
            sql(source, "CREATE DATABASE app")
            sql(source, "CREATE EXTENSION backup_search; CREATE TABLE items (id int); INSERT INTO items VALUES (1),(2),(3)", "app")
            sql(source, "ALTER ROLE postgres CONNECTION LIMIT 11")

            # Use real pg_dump/psql/gzip; replace only the S3 transport with a file copy.
            bin_dir = work / "bin"
            bin_dir.mkdir()
            aws = bin_dir / "aws"
            aws.write_text('#!/bin/sh\nset -eu\n[ "$1" = s3 ] && [ "$2" = cp ]\ncp "$3" "$TEST_UPLOAD"\n')
            aws.chmod(0o755)
            archive = work / "all.sql.gz"
            env = {**source, "PATH": str(bin_dir) + ":" + os.environ["PATH"], "POSTGRES_DATABASE": "all",
                   "POSTGRES_EXTRA_OPTS": "--no-owner --no-acl --no-tablespaces",
                   "POSTGRES_DUMP_ROLE_PASSWORDS": "false", "S3_BUCKET": "test", "S3_PREFIX": "backup",
                   "S3_ACCESS_KEY_ID": "test", "S3_SECRET_ACCESS_KEY": "test", "S3_ENDPOINT": "None",
                   "S3_REGION": "us-west-1", "ENCRYPTION_PASSWORD": "None", "DELETE_OLDER_THAN": "None",
                   "TEST_UPLOAD": str(archive)}
            run(["sh", str(ROOT / "postgres-backup-s3/backup.sh")], env=env)
            with gzip.open(archive, "rt") as data:
                header = data.readline()
                payload = data.read()
            metadata = json.loads(header.split(": ", 1)[1])
            assert metadata["databases"]["app"]["extensions"]
            target["BACKUP_FILE"] = str(archive)
            result = subprocess.run(["sh", str(ROOT / "postgres-restore-file/restore.sh")], env=target, text=True, capture_output=True)
            assert result.returncode != 0 and "version mismatch" in result.stderr, result.stderr
            assert sql(target, "SELECT count(*) FROM pg_database WHERE datname = 'app'") == "0"
            print("PASS: metadata version mismatch fails before creating databases", flush=True)

            legacy = work / "legacy.sql"
            legacy.write_text(payload)
            target["BACKUP_FILE"] = str(legacy)
            result = subprocess.run(["sh", str(ROOT / "postgres-restore-file/restore.sh")], env=target, text=True, capture_output=True)
            assert result.returncode != 0 and "requires 'backup_vector'" in result.stderr, result.stderr
            assert sql(target, "SELECT count(*) FROM pg_database WHERE datname = 'app'") == "0"
            print("PASS: legacy dump dependency failure detected before restore", flush=True)

            extension(1, "backup_search", "1.0")
            target["BACKUP_FILE"] = str(archive)
            run(["sh", str(ROOT / "postgres-restore-file/restore.sh")], env=target)
            assert sql(target, "SELECT count(*) FROM items", "app") == "3"
            assert sql(target, "SELECT rolconnlimit FROM pg_roles WHERE rolname = 'postgres'") == "-1"
            assert sql(target, "SELECT extversion FROM pg_extension WHERE extname = 'backup_search'", "app") == "1.0"
            print("PASS: full restore succeeds with matching extensions; existing target password and attributes retained", flush=True)

            # Restore old gzip/zip files into fresh empty databases as well.
            sql(source, "CREATE DATABASE plain_source")
            sql(source, "CREATE TABLE plain_items(id int); INSERT INTO plain_items VALUES(42)", "plain_source")
            dump = work / "plain.sql"
            with dump.open("w") as out:
                subprocess.run(["pg_dump", "-h", source["POSTGRES_HOST"], "-p", source["POSTGRES_PORT"],
                                "-U", "postgres", "--no-owner", "--no-acl", "plain_source"],
                               env=source, stdout=out, check=True)
            for suffix in ("gz", "zip"):
                compressed = work / ("legacy.sql." + suffix)
                if suffix == "gz":
                    with dump.open("rb") as src, gzip.open(compressed, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                else:
                    with zipfile.ZipFile(compressed, "w") as zip_output:
                        zip_output.write(dump, "dump.sql")
                database = "legacy_" + suffix
                sql(target, "CREATE DATABASE " + database)
                case_env = {**target, "POSTGRES_DATABASE": database, "BACKUP_FILE": str(compressed)}
                run(["sh", str(ROOT / "postgres-restore-file/restore.sh")], env=case_env)
                assert sql(target, "SELECT id FROM plain_items", database) == "42"
            print("PASS: legacy gzip and ZIP backups restore correctly", flush=True)

            broken = work / "broken.sql"
            broken.write_text("CREATE TABLE restore_probe(id int);\nSELECT nonexistent_function();\nCREATE TABLE must_not_exist(id int);\n")
            target["BACKUP_FILE"] = str(broken)
            result = subprocess.run(["sh", str(ROOT / "postgres-restore-file/restore.sh")], env=target, text=True, capture_output=True)
            assert result.returncode != 0 and "Restore complete" not in result.stdout
            assert sql(target, "SELECT to_regclass('public.must_not_exist') IS NULL") == "t"
            print("PASS: SQL error stops restore and never reports success", flush=True)
    finally:
        for name in names:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)


if __name__ == "__main__":
    main()
