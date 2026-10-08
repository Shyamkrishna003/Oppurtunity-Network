#!/bin/sh
# node_modules lives in a named volume that outlives image rebuilds, so it can lag behind
# package-lock.json. Reinstall whenever the lockfile differs from the one last installed.
set -e
if ! cmp -s package-lock.json node_modules/.installed-lock; then
  npm ci
  cp package-lock.json node_modules/.installed-lock
fi
exec "$@"
