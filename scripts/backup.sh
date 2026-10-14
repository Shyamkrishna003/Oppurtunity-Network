#!/bin/sh
# Back up the production database and uploaded files into BACKUP_DIR (default ./backups).
#
#   scripts/backup.sh
#
# Run from the repository root, on the host, with the stack up. Safe to run while the site
# is in use: pg_dump reads one consistent snapshot. Copy the results off the machine;
# a backup on the same disk as the database protects against very little.
#
#   ENV_FILE     environment file of the stack   (default .env.production)
#   BACKUP_DIR   where to write                  (default ./backups)
#   KEEP_DAYS    delete backups older than this  (default 14; 0 keeps everything)
set -eu

ENV_FILE=${ENV_FILE:-.env.production}
BACKUP_DIR=${BACKUP_DIR:-./backups}
KEEP_DAYS=${KEEP_DAYS:-14}
export ENV_FILE

compose() {
    docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE" "$@"
}

stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
database="$BACKUP_DIR/db-$stamp.dump"
files="$BACKUP_DIR/files-$stamp.tar"

# Written under a temporary name first, so a failed run never leaves something that looks
# like a finished backup.
compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
    < /dev/null > "$database.partial"
# A dump that cannot be listed is not a backup.
compose exec -T postgres pg_restore --list < "$database.partial" > /dev/null
mv "$database.partial" "$database"

# Uploaded files: public ones (avatars, logos) and private ones (resumes).
compose exec -T backend tar -C /data -cf - media private_media < /dev/null > "$files.partial"
mv "$files.partial" "$files"

chmod 600 "$database" "$files"
if [ "$KEEP_DAYS" -gt 0 ]; then
    find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'db-*.dump' -o -name 'files-*.tar' \) \
        -mtime "+$KEEP_DAYS" -delete
fi

echo "database: $database ($(wc -c < "$database") bytes)"
echo "files:    $files ($(wc -c < "$files") bytes)"
