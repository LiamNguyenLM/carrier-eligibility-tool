#!/bin/sh
# One-time seed for the persistent volume. If carrier_docs_db (the volume
# mount) is empty or missing, populate it from carrier_docs_db_seed (a
# pre-built snapshot checked into the repo, built locally where memory
# isn't a constraint). After this first copy, all further carrier updates
# go through the app's "Manage Carriers" tab and live in the volume from
# then on -- this script becomes a no-op on every subsequent boot, since
# it only acts when the volume is empty.
set -e

if [ ! -d "carrier_docs_db" ] || [ -z "$(ls -A carrier_docs_db 2>/dev/null)" ]; then
  echo "carrier_docs_db is empty -- seeding from carrier_docs_db_seed"
  mkdir -p carrier_docs_db
  cp -r carrier_docs_db_seed/. carrier_docs_db/
else
  echo "carrier_docs_db already populated -- skipping seed"
fi