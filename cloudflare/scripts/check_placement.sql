-- After a placement refresh: each table's rows against the counts the sync wrote. all_ok must be 1.
--   npx wrangler d1 execute cfig-eligibility --remote --file=cloudflare/scripts/check_placement.sql
-- (One SELECT, no UNION: D1 refuses a compound SELECT of more than a few terms.)
WITH m AS (SELECT key, value FROM placement_meta),
     c AS (SELECT (SELECT count(*) FROM placement_zip) AS zip, (SELECT count(*) FROM placement_county) AS county,
                  (SELECT count(*) FROM placement_profile) AS profile, (SELECT count(*) FROM placement_all) AS all_rows,
                  (SELECT count(*) FROM placement_markets) AS markets)
SELECT (SELECT value FROM m WHERE key = 'data_through') AS data_through,
       (SELECT value FROM m WHERE key = 'sync_csv_sha256') AS csv_sha256,
       c.zip, c.county, c.profile, c.all_rows, c.markets,
       (c.zip = CAST((SELECT value FROM m WHERE key = 'sync_rows_zip') AS INTEGER)
        AND c.county = CAST((SELECT value FROM m WHERE key = 'sync_rows_county') AS INTEGER)
        AND c.profile = CAST((SELECT value FROM m WHERE key = 'sync_rows_profile') AS INTEGER)
        AND c.all_rows = CAST((SELECT value FROM m WHERE key = 'sync_rows_all') AS INTEGER)
        AND c.markets = CAST((SELECT value FROM m WHERE key = 'sync_rows_markets') AS INTEGER)
        AND c.zip > 0 AND c.markets > 0) AS all_ok
FROM c;
