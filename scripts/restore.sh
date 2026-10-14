#!/bin/sh
# Replace the production database, and optionally the uploaded files, with a backup.
#
#   scripts/restore.sh backups/db-20261014T020000Z.dump [backups/files-20261014T020000Z.tar]
#
# DESTRUCTIVE: everything in the live database is dropped. Asks for the database's name
# before doing anything. Check the backup first with scripts/restore-check.sh.
set -eu

[ $# -ge 1 ] && [ $# -le 2 ] || { echo "usage: $0 <db-backup.dump> [files-backup.tar]" >&2; exit 2; }
dump=$1
files=${2:-}
[ -s "$dump" ] || { echo "$dump is missing or empty" >&2; exit 2; }
[ -z "$files" ] || [ -s "$files" ] || { echo "$files is missing or empty" >&2; exit 2; }

ENV_FILE=${ENV_FILE:-.env.production}
export ENV_FILE

compose() {
    docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE" "$@"
}
# Commands that take no input get none (< /dev/null): otherwise they would swallow what
# is typed at the question below.
live=$(compose exec -T postgres sh -c 'printf %s "$POSTGRES_DB"' < /dev/null)

echo "This replaces everything in the database \"$live\" with $dump."
printf 'Type the database name to go on: '
read -r answer
[ "$answer" = "$live" ] || { echo "Not restored." >&2; exit 1; }

# Nothing may be connected, or write, while the database is replaced.
compose stop nginx backend worker beat

compose exec -T postgres sh -c '
    dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" &&
    createdb -U "$POSTGRES_USER" "$POSTGRES_DB"' < /dev/null
compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error' < "$dump"
# The right to connect belongs to the database, not to its contents, so a dump of the
# contents does not carry it. Everything else the application role may do is in the dump.
compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "GRANT CONNECT ON DATABASE \"$POSTGRES_DB\" TO \"$APP_DB_USER\""' \
    < /dev/null

if [ -n "$files" ]; then
    compose run --rm --no-deps -T backend sh -c \
        'find /data/media /data/private_media -mindepth 1 -delete && tar -C /data -xf -' < "$files"
fi

# Brings the schema up to this version of the code if the backup is older, then starts
# everything again.
compose up -d
echo "Restored. Check the site, then: docker compose -f docker-compose.prod.yml logs --tail 50 backend"
