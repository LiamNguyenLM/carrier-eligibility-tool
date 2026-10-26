-- Round 44b (Liam, 2026-10-25): the placement tables leave D1.
-- On 2026-10-25 loading them blew the D1 free tier: 143k rows written against 100k a day, because each index entry
-- counts as a row written too. The Worker now carries them in its bundle (cloudflare/scripts/build_placement.mjs,
-- rebuilt from rules_data/placement/*.csv on every deploy), so D1 keeps only feedback, usage and login_failures.
--
-- Apply with: npm run migrate:remote   (or migrate:local). IF EXISTS: safe whether the 2026-10-25 load finished,
-- stopped part-way, or never ran. Dropping a table drops its indexes with it.
DROP TABLE IF EXISTS placement_zip;
DROP TABLE IF EXISTS placement_county;
DROP TABLE IF EXISTS placement_profile;
DROP TABLE IF EXISTS placement_all;
DROP TABLE IF EXISTS placement_markets;
DROP TABLE IF EXISTS placement_meta;
