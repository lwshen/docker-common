"""Real PostgreSQL regression tests; requires Docker and PostgreSQL 18 client tools."""

import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tarfile
import time
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "postgres-common"))
import backup_tools


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
                     "--tmpfs", "/var/lib/postgresql:rw,size=512m",
                     "-e", "POSTGRES_PASSWORD=" + password, "postgres:18"])
                port = run(["docker", "inspect", "--format",
                            '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}', name])
                env = {**os.environ, "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": port,
                       "POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": password,
                       "POSTGRES_DATABASE": "postgres", "PGPASSWORD": password,
                       "RESTORE_EXISTING_ROLES": "preserve", "DROP_PUBLIC": "no"}
                environments.append(env)
                for attempt in range(120):
                    ready = subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"], capture_output=True)
                    if ready.returncode == 0:
                        break
                    time.sleep(0.5)
                else:
                    raise RuntimeError("PostgreSQL did not become ready: " + run(["docker", "logs", name]))

            source, target = environments

            def sql(env, query, database="postgres"):
                return run(["psql", "-XAt", "-v", "ON_ERROR_STOP=1", "-h", env["POSTGRES_HOST"],
                            "-p", env["POSTGRES_PORT"], "-U", "postgres", "-d", "dbname='" + database.replace("\\", "\\\\").replace("'", "\\'") + "'", "-c", query], env=env)

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
            sql(source, "CREATE DATABASE \"odd = 'db\"")
            sql(source, "CREATE EXTENSION backup_search; CREATE TABLE items (id int); INSERT INTO items VALUES (1),(2),(3)", "app")
            sql(source, "ALTER ROLE postgres CONNECTION LIMIT 11; CREATE ROLE app_owner; CREATE ROLE app_reader")
            sql(source, "ALTER TABLE items OWNER TO app_owner; GRANT SELECT ON items TO app_reader", "app")

            sql(source, "ALTER ROLE app_reader IN DATABASE app SET search_path TO public; REVOKE CONNECT ON DATABASE app FROM PUBLIC; GRANT CONNECT ON DATABASE app TO app_reader")
            sql(source, "CREATE DATABASE user_template TEMPLATE template0 IS_TEMPLATE true")
            sql(source, "CREATE TABLE template_probe(id int); INSERT INTO template_probe VALUES(7)", "template1")
            sql(source, "CREATE DATABASE omitted_probe")
            sql(source, "CREATE DATABASE invalid_probe")
            sql(source, "UPDATE pg_database SET datconnlimit = -2 WHERE datname = 'invalid_probe'")
            special_name = 'back\\slash"quote'
            sql(source, 'CREATE DATABASE "' + special_name.replace('"', '""') + '"')
            sql(source, "CREATE DATABASE ascii_probe TEMPLATE template0 ENCODING 'SQL_ASCII' LC_COLLATE 'C' LC_CTYPE 'C'")
            sql(source, "CREATE TABLE bytes_probe(value text); INSERT INTO bytes_probe VALUES(convert_from(decode('ff','hex'), 'SQL_ASCII'))", "ascii_probe")
            run(["docker", "exec", names[0], "sh", "-c", "mkdir /var/lib/postgresql/backup-space && chown postgres /var/lib/postgresql/backup-space"])
            sql(source, "CREATE TABLESPACE source_space LOCATION '/var/lib/postgresql/backup-space'")
            sql(source, "CREATE DATABASE placed_probe TABLESPACE source_space")

            # Use real pg_dump/psql/gzip; replace only the S3 transport with a file copy.
            bin_dir = work / "bin"
            bin_dir.mkdir()
            aws = bin_dir / "aws"
            aws.write_text('#!/bin/sh\nset -eu\n[ "$1" = s3 ] && [ "$2" = cp ]\ncp "$3" "$TEST_UPLOAD"\n')
            aws.chmod(0o755)
            archive = work / "all.tar.gz"
            env = {**source, "PATH": str(bin_dir) + ":" + os.environ["PATH"], "POSTGRES_DATABASE": "all",
                   "POSTGRES_EXTRA_OPTS": "--no-owner --no-acl --no-tablespaces --exclude-database=omitted*",
                   "POSTGRES_DUMP_ROLE_PASSWORDS": "false", "S3_BUCKET": "test", "S3_PREFIX": "backup",
                   "S3_ACCESS_KEY_ID": "test", "S3_SECRET_ACCESS_KEY": "test", "S3_ENDPOINT": "None",
                   "S3_REGION": "us-west-1", "ENCRYPTION_PASSWORD": "None", "DELETE_OLDER_THAN": "None",
                   "TEST_UPLOAD": str(archive)}
            run(["sh", str(ROOT / "postgres-backup-s3/backup.sh")], env=env)
            with tarfile.open(archive, "r:gz") as data:
                metadata = json.load(data.extractfile("manifest.json"))
                roles = data.extractfile("roles.sql").read().decode()
                app_sql = data.extractfile("databases/app.sql").read().decode()
                members = data.getnames()
            assert metadata["databases"]["app"]["file"] == "databases/app.sql"
            assert "databases/back%5Cslash%22quote.sql" in members and "databases/odd%20%3D%20%27db.sql" in members, members
            assert "CREATE DATABASE app" in app_sql and "OWNER TO" not in app_sql and "GRANT " not in app_sql
            assert metadata["databases"]["app"]["extensions"]
            assert "PASSWORD " not in roles
            assert "postgres" in metadata["databases"]
            assert "template1" in metadata["databases"] and "user_template" in metadata["databases"]
            assert "invalid_probe" not in metadata["databases"] and "omitted_probe" not in metadata["databases"]
            assert special_name in metadata["databases"]
            target["BACKUP_FILE"] = str(archive)
            result = subprocess.run(["sh", str(ROOT / "postgres-restore-file/restore.sh")], env=target, text=True, capture_output=True)
            assert result.returncode != 0 and "version mismatch" in result.stderr, result.stderr
            assert sql(target, "SELECT count(*) FROM pg_database WHERE datname = 'app'") == "0"
            print("PASS: metadata version mismatch fails before creating databases", flush=True)

            legacy = work / "legacy.sql"
            with legacy.open("w") as output:
                subprocess.run(["pg_dumpall", "-h", source["POSTGRES_HOST"], "-p", source["POSTGRES_PORT"],
                                "-U", "postgres", "--no-role-passwords", "--no-owner", "--no-acl", "--no-tablespaces"],
                               env=source, stdout=output, check=True)
            assert special_name in backup_tools.plan(legacy), repr([line for line in legacy.read_text(errors="surrogateescape").splitlines() if line.startswith("\\connect")]) + repr(backup_tools.plan(legacy))
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

            assert sql(target, "SELECT count(*) FROM pg_roles WHERE rolname IN ('app_owner','app_reader')") == "0"
            assert sql(target, "SELECT tableowner FROM pg_tables WHERE tablename = 'items'", "app") == "postgres"
            print("PASS: default restore skips global roles, ownership, ACLs and tablespaces", flush=True)

            assert sql(target, "SELECT count(*) FROM pg_database WHERE datname = 'odd = ''db'") == "1"
            assert sql(target, "SELECT count(*) FROM pg_database WHERE datname = '" + special_name + "'") == "1"
            assert sql(target, "SELECT encode(convert_to(value, 'SQL_ASCII'), 'hex') FROM bytes_probe", "ascii_probe") == "ff"
            assert sql(target, "SELECT id FROM template_probe", "template1") == "7"
            assert sql(target, "SELECT datistemplate FROM pg_database WHERE datname='user_template'") == "t"
            assert sql(target, "SELECT t.spcname FROM pg_database d JOIN pg_tablespace t ON t.oid=d.dattablespace WHERE d.datname='placed_probe'") == "pg_default"
            print("PASS: SQL_ASCII bytes, template databases, unusual names and portable database tablespaces", flush=True)
            # Roles can be restored with a selected database; objects still belong to the restoring user.
            encrypted = work / "all.tar.gz.enc"
            run(["sh", str(ROOT / "postgres-backup-s3/backup.sh")],
                env={**env, "TEST_UPLOAD": str(encrypted), "ENCRYPTION_PASSWORD": "test-encryption",
                     "POSTGRES_DUMP_ROLE_PASSWORDS": "true"})
            sql(target, "DROP DATABASE app")
            selected = {**target, "RESTORE_DATABASE": "app", "RESTORE_ROLES": "true",
                        "BACKUP_FILE": str(encrypted), "ENCRYPTION_PASSWORD": "test-encryption"}
            run(["sh", str(ROOT / "postgres-restore-file/restore.sh")], env=selected)
            assert sql(target, "SELECT count(*) FROM pg_roles WHERE rolname IN ('app_owner','app_reader')") == "2"
            assert sql(target, "SELECT tableowner FROM pg_tables WHERE tablename = 'items'", "app") == "postgres"
            assert sql(target, "SELECT rolconnlimit FROM pg_roles WHERE rolname = 'postgres'") == "-1"
            assert sql(target, "SELECT count(*) FROM items", "app") == "3"
            assert sql(target, "SELECT count(*) FROM pg_db_role_setting s JOIN pg_database d ON d.oid = s.setdatabase "
                               "JOIN pg_roles r ON r.oid = s.setrole WHERE d.datname = 'app' AND r.rolname = 'app_reader'") == "1"
            print("PASS: encrypted selected-database restore adds roles and preserves existing passwords", flush=True)

            # A database file from the bundle can also be restored by hand with psql.
            sql(target, "DROP DATABASE app")
            manual = work / "manual"
            with tarfile.open(archive, "r:gz") as data:
                data.extract("databases/app.sql", manual, filter="data")
            run(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", target["POSTGRES_HOST"], "-p", target["POSTGRES_PORT"],
                 "-U", "postgres", "-d", "postgres", "-f", str(manual / "databases/app.sql")], env=target)
            assert sql(target, "SELECT count(*) FROM items", "app") == "3"
            assert sql(target, "SELECT tableowner FROM pg_tables WHERE tablename = 'items'", "app") == "postgres"
            print("PASS: bundle SQL file restores manually with psql", flush=True)

            # Restore old gzip/zip files into fresh empty databases as well.
            sql(source, "CREATE DATABASE plain_source TEMPLATE template0")
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
                sql(target, "CREATE DATABASE " + database + " TEMPLATE template0")
                case_env = {**target, "POSTGRES_DATABASE": database, "BACKUP_FILE": str(compressed)}
                run(["sh", str(ROOT / "postgres-restore-file/restore.sh")], env=case_env)
                assert sql(target, "SELECT id FROM plain_items", database) == "42"
            print("PASS: legacy gzip and ZIP backups restore correctly", flush=True)

            # Metadata collection must work without pg_read_all_settings.
            sql(source, "CREATE ROLE backup_reader LOGIN PASSWORD 'reader'; GRANT pg_read_all_data TO backup_reader")
            single = work / "reader.sql.gz"
            run(["sh", str(ROOT / "postgres-backup-s3/backup.sh")], env={**env,
                "POSTGRES_DATABASE": "plain_source", "POSTGRES_USER": "backup_reader",
                "POSTGRES_PASSWORD": "reader", "POSTGRES_EXTRA_OPTS": "auto", "TEST_UPLOAD": str(single)})
            print("PASS: non-superuser backup succeeds without pg_read_all_settings", flush=True)

            # Historical LATIN1 dumps pass through Python without transcoding.
            sql(source, "CREATE DATABASE latin_probe TEMPLATE template0 ENCODING 'LATIN1' LC_COLLATE 'C' LC_CTYPE 'C'")
            sql(source, "CREATE TABLE latin_items(value text); INSERT INTO latin_items VALUES(convert_from(decode('e9','hex'), 'LATIN1'))", "latin_probe")
            latin = work / "latin.sql.gz"
            result = subprocess.run(["pg_dump", "-h", source["POSTGRES_HOST"], "-p", source["POSTGRES_PORT"],
                                     "-U", "postgres", "--no-owner", "--no-acl", "latin_probe"], env=source, capture_output=True, check=True)
            with gzip.open(latin, "wb") as out:
                out.write(result.stdout)
            sql(target, "CREATE DATABASE latin_target TEMPLATE template0 ENCODING 'LATIN1' LC_COLLATE 'C' LC_CTYPE 'C'")
            run(["sh", str(ROOT / "postgres-restore-file/restore.sh")], env={**target, "POSTGRES_DATABASE": "latin_target", "BACKUP_FILE": str(latin)})
            assert sql(target, "SELECT encode(convert_to(value, 'LATIN1'), 'hex') FROM latin_items", "latin_target") == "e9"
            print("PASS: legacy LATIN1 gzip restore preserves bytes", flush=True)

            broken = work / "broken.sql"
            broken.write_text("CREATE TABLE restore_probe(id int);\nSELECT nonexistent_function();\nCREATE TABLE must_not_exist(id int);\n")
            target["BACKUP_FILE"] = str(broken)
            result = subprocess.run(["sh", str(ROOT / "postgres-restore-file/restore.sh")], env=target, text=True, capture_output=True)
            assert result.returncode != 0 and "Restore complete" not in result.stdout
            assert sql(target, "SELECT to_regclass('public.must_not_exist') IS NULL") == "t"
            print("PASS: SQL error stops restore and never reports success", flush=True)
    finally:
        for name in names:
            subprocess.run(["docker", "rm", "-fv", name], capture_output=True)


if __name__ == "__main__":
    main()
