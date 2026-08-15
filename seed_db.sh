#!/bin/sh
# One-time seed for the persistent volume. If carrier_docs_db (the volume
# mount) is empty or missing, populate it from carrier_docs_db_seed (a
# pre-built snapshot checked into the repo, built locally where memory
# isn't a constraint). After this first copy, all further carrier updates
# go through the app's "Manage Carriers" tab and live in the volume from
# then on -- this script becomes a no-op on every subsequent boot, since
# it only acts when the volume is empty.
set -e

echo "=== seed_db.sh starting ==="
echo "Working directory: $(pwd)"
echo "Contents of working directory:"
ls -la

echo "--- carrier_docs_db_seed ---"
if [ -d "carrier_docs_db_seed" ]; then
  echo "carrier_docs_db_seed exists. Contents:"
  ls -la carrier_docs_db_seed
else
  echo "carrier_docs_db_seed does NOT exist in this working directory."
fi

echo "--- carrier_docs_db ---"
if [ -d "carrier_docs_db" ]; then
  echo "carrier_docs_db exists. Contents:"
  ls -la carrier_docs_db
else
  echo "carrier_docs_db does NOT exist yet."
fi

if [ ! -d "carrier_docs_db" ]; then
  REAL_CONTENTS=""
else
  # Count real contents, ignoring lost+found -- which is auto-created by
  # the volume mount itself and must NOT count as "already populated",
  # or the seed will wrongly skip on a genuinely-empty fresh volume.
  REAL_CONTENTS="$(ls -A carrier_docs_db 2>/dev/null | grep -v '^lost+found$' || true)"
fi

# FORCE_RESEED=1 (set as a Railway env var) wipes and re-copies the seed
# even if the volume looks populated -- use this to recover from a bad or
# empty stub database, then REMOVE the env var afterward so normal boots
# don't wipe real uploaded data.
if [ "$FORCE_RESEED" = "1" ]; then
  echo "FORCE_RESEED=1 set -- wiping carrier_docs_db and re-copying seed"
  rm -rf carrier_docs_db/*
  mkdir -p carrier_docs_db
  cp -r carrier_docs_db_seed/. carrier_docs_db/
  echo "Forced reseed complete. New contents of carrier_docs_db:"
  ls -la carrier_docs_db
elif [ -z "$REAL_CONTENTS" ]; then
  echo "carrier_docs_db is empty (ignoring lost+found) -- seeding from carrier_docs_db_seed"
  mkdir -p carrier_docs_db
  cp -r carrier_docs_db_seed/. carrier_docs_db/
  echo "Seed copy complete. New contents of carrier_docs_db:"
  ls -la carrier_docs_db
else
  echo "carrier_docs_db already populated -- skipping seed"
fi

echo "=== seed_db.sh finished ==="