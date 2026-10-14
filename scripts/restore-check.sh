#!/bin/sh
# Prove that a database backup can be restored, without touching the live database.
#
#   scripts/restore-check.sh backups/db-20261014T020000Z.dump
#
# Restores the dump into a scratch database on the same server, checks that it holds what
# a working database must, prints its row counts beside the live ones, and drops it again.
# Exits non-zero if anything is wrong. Run it on a schedule: a backup nobody has restored
# is only a hope.
set -eu

[ $# -eq 1 ] || { echo "usage: $0 <db-backup.dump>" >&2; exit 2; }
dump=$1
[ -s "$dump" ] || { echo "$dump is missing or empty" >&2; exit 2; }

ENV_FILE=${ENV_FILE:-.env.production}
export ENV_FILE
scratch="restore_check_$(date -u +%Y%m%d%H%M%S)"

compose() {
    docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE" "$@"
}
# One value from a query against the named database.
value() {
    compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$0" -At -v ON_ERROR_STOP=1 -c "$1"' "$1" "$2" \
        < /dev/null
}
drop() {
    compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" --if-exists "$0"' "$scratch" < /dev/null
}
live=$(compose exec -T postgres sh -c 'printf %s "$POSTGRES_DB"' < /dev/null)

trap drop EXIT
compose exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" "$0"' "$scratch" < /dev/null
compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$0" --no-owner --exit-on-error' \
    "$scratch" < "$dump"

failed=0
check() {
    if [ "$2" = "$3" ]; then
        echo "ok    $1: $2"
    else
        echo "FAIL  $1: restored has $2, expected $3"
        failed=1
    fi
}

tables="SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
migrations="SELECT count(*) FROM django_migrations"
trigger="SELECT count(*) FROM pg_trigger WHERE tgname = 'audit_auditlog_append_only' AND tgenabled = 'O'"

check "tables" "$(value "$scratch" "$tables")" "$(value "$live" "$tables")"
check "audit log append-only trigger" "$(value "$scratch" "$trigger")" "1"
restored_migrations=$(value "$scratch" "$migrations")
if [ "$restored_migrations" -gt 0 ]; then
    echo "ok    migrations recorded: $restored_migrations (live now: $(value "$live" "$migrations"))"
else
    echo "FAIL  no migrations recorded"
    failed=1
fi

# For a person to read: the live database has moved on since the backup, so these are
# expected to be close, not equal.
echo "rows (restored / live now):"
for table in users_user opportunities_opportunity applications_application audit_auditlog; do
    echo "      $table: $(value "$scratch" "SELECT count(*) FROM $table") / $(value "$live" "SELECT count(*) FROM $table")"
done

if [ "$failed" -ne 0 ]; then
    echo "The backup did NOT pass." >&2
    exit 1
fi
echo "The backup restores cleanly."
