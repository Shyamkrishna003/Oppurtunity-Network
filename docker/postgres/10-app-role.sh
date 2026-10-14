#!/bin/sh
# Runs once, when the database is first created.
#
# Two roles use the database. The owner (POSTGRES_USER) runs migrations and so can change
# its structure. The application, at run time, connects as a second role that can only
# read and write rows: it cannot drop or alter a table, disable the audit log's
# append-only trigger, or TRUNCATE. A bug or a stolen application password cannot reach
# further than that.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v app_user="$APP_DB_USER" -v app_password="$APP_DB_PASSWORD" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password';
GRANT CONNECT ON DATABASE :"DBNAME" TO :"app_user";
GRANT USAGE ON SCHEMA public TO :"app_user";
-- Applies to everything the owner creates from now on, which is every migration.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";
SQL
