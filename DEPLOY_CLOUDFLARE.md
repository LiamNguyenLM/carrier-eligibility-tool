# Deploying the eligibility tool to Cloudflare (Round 44)

For Liam. This puts up the static page, the Worker and D1, behind Cloudflare Access, on a `workers.dev` address.
Railway stays up until step 5 passes; the steps for retiring it are at the end.

Docs were checked on 2026-10-24. A tag such as [S12] points to the Sources list at the end. **(not verified)** marks
anything the docs don't confirm, or anything that depends on our own code.

Liam's decisions (2026-10-24):
- A CFIG-owned Cloudflare account, with Jonathan invited.
- Login by an emailed one-time PIN; Microsoft 365 can be added later.
- Anyone `@cfigtx.com` can log in.
- Admins are Liam and Jonathan.
- A workers.dev address for now; a custom domain later.
- No long side-by-side with Railway.

## Names (change them here only)

| | |
|---|---|
| Worker / D1 database | `cfig-eligibility` (in `wrangler.toml`) |
| App address | `https://cfig-eligibility.<subdomain>.workers.dev`. `<subdomain>`: Workers & Pages → "Your subdomain" |
| Team domain | `<team>.cloudflareaccess.com`. You pick `<team>` in 4.1 |
| Admins | `liam@cfigtx.com`, plus Jonathan's address (not known yet) |

## Before you start

- A CFIG mailbox to own the Cloudflare account. The **account** is named CFIG, even if your login is the owner.
- Admin rights on the GitHub repo.
- Node 24 and npm. The repo checked out on `main`, then `npm ci` at the repo root.
- Railway's `carrier_docs_db/feedback_log.jsonl` and `usage_log.jsonl`, downloaded from the volume.
- A payment card. Zero Trust asks for one even on the Free plan ("you won't be charged") [S20]. Whether the card is
  strictly required is **(not verified)**.

## 1. Account, and Jonathan

1. Sign up at https://dash.cloudflare.com/sign-up with the CFIG mailbox, then click the link in the verification
   email [S1].
   - Already have a Cloudflare login? Use **Accounts → Create Account** instead, named "CFIG" [S1].
2. Turn on two-factor authentication [S20].
3. **Manage Account → Members → Invite members** [S2]:
   - Jonathan's email;
   - scope: the entire account;
   - role: **Super Administrator - All Privileges**, so there are two owners [S4].

   He shows as **Pending** until he accepts the email.

## 2. One-time setup on your machine (repo root)

1. Log in and check the account:
   - `npx wrangler login`: approve in the browser [S5].
   - `npx wrangler whoami`: it should show the CFIG account. With more than one account, add `account_id` to
     `wrangler.toml` **(not verified)**.
2. Create the database: `npx wrangler d1 create cfig-eligibility`.
   - Copy the `database_id` it prints into `wrangler.toml`'s `[[d1_databases]]` block, replacing the zeros. It is not
     a secret.
   - If it offers to edit the config itself, say No [S6][S7].
3. Create the tables: `npm run migrate:remote` (`wrangler d1 migrations apply DB --remote`). Confirm when it asks;
   it takes a backup first [S7].
4. Load the placement tables. These never reach the browser; the Worker answers the panel from them:
   ```
   node cloudflare/scripts/sync_placement.mjs
   npx wrangler d1 execute cfig-eligibility --remote --file=cloudflare/build/placement_sync.sql
   npx wrangler d1 execute cfig-eligibility --remote --file=cloudflare/scripts/check_placement.sql   # all_ok = 1
   ```
5. Import Railway's logs. Re-running never duplicates a row. The files hold real feedback: delete them afterwards.
   ```
   node cloudflare/scripts/import_logs.mjs --feedback <feedback_log.jsonl> --usage <usage_log.jsonl>
   npx wrangler d1 execute cfig-eligibility --remote --file=cloudflare/build/import_logs.sql
   ```
6. Create the Worker without a public address:
   ```
   npm run build
   npx wrangler deploy
   ```
   - `wrangler.toml` ships with `workers_dev = false` and `preview_urls = false`, so nothing is reachable yet. The
     page carries the engine and its rules tables; it must never be public without Access.
   - This first deploy exists so that step 3 has a Worker to connect to [S9].

## 3. Connect GitHub (a push to main deploys)

1. **Workers & Pages → cfig-eligibility → Settings → Builds → Connect** [S9].
2. Install the **Cloudflare Workers and Pages** GitHub app with access to this repo only [S10].
3. Build settings [S11]:
   - branch `main`;
   - build command `npm run build`;
   - deploy command `npx wrangler deploy`;
   - root directory empty (`wrangler.toml` is at the root).
4. Leave **Enable Preview Builds** off [S12]. A preview gets no production bindings and would need a staging D1
   [S13][S14].
5. Database migrations stay a step on your machine (`npm run migrate:remote`), run before you push code that needs
   them. The build's own token has no D1 permission [S11] (inferred; **not verified**).

## 4. Access: the login for agents, then the address

**4.1 Zero Trust (once).**
1. Dashboard → **Zero Trust**. Pick the team name; it gives `<team>.cloudflareaccess.com`. Choose **Free** [S20].
2. **Zero Trust → Integrations → Identity providers → Add new → One-time PIN** [S17].

**4.2 Protect the Worker.**
1. **Workers & Pages → cfig-eligibility → Access** tab → **Protect this Worker behind Access** → **All traffic**. This
   covers the workers.dev address, version URLs and a later custom domain [S18].
2. Policy: **Email domain** `cfigtx.com` [S18][S19].
3. Session duration: the default is 24 h [S21]. One week means agents type a code about once a week.
4. **Apply Access**.

If that tab is missing, use the manual route: **Zero Trust → Access controls → Applications → Create → Self-hosted**,
hostname `cfig-eligibility.<subdomain>.workers.dev` (you may need "Switch to custom input"; **not verified**), with
the same policy [S23].

**4.3 Wire the Worker to Access, and turn the address on.**
1. Copy the **Application Audience (AUD) Tag**: **Zero Trust → Access controls → Applications →** the app →
   **Configure → Additional settings** [S24].
2. Edit `wrangler.toml`:
   - `ACCESS_TEAM_DOMAIN = "<team>.cloudflareaccess.com"`;
   - `ACCESS_AUD = "<the AUD tag>"`;
   - `ADMIN_EMAILS = "liam@cfigtx.com,<jonathan's address>"`;
   - `workers_dev = true`.

   Keep these in `wrangler.toml`, not the dashboard: every deploy overwrites dashboard-set variables [S25][S26].
3. Commit and push to `main`. This is the first deploy with an address.
4. Seats: anyone who logs in once takes one of the 50 free seats until removed; past 50 it is $7 a user a month
   [S27][S28]. Remove leavers at **Zero Trust → Team & Resources → Users**.

The Worker checks the Access token itself on every `/api` route. If `ACCESS_AUD` is still the placeholder, every
`/api` call fails closed with a 500, and the check still runs in the browser.

## 5. First checks

1. A private browser window → the app address. You should see a Cloudflare page asking for an email.
2. `liam@cfigtx.com` → an email from `noreply@notify.cloudflare.com` with a code (10 minutes, single use) [S17] → the
   page loads. The first load is about 6 MB and a few seconds; later visits come from the browser's cache.
3. Run one check (a Harris home, for example):
   - the four columns fill in;
   - the placement panel appears above them, which proves `/api/placement` accepts the Access token [S24];
   - send one **This looks wrong**; it should say "Sent -- thank you."
4. Open `/api/admin/weekly`, and click **Download feedback** at the top of the page: you get the data. The CSV comes
   300 reports at a time to stay under the Free plan's 10 ms CPU; the link joins them into one file. Have an agent
   try: they get 403.
5. A non-`@cfigtx.com` address gets the "check your email" screen, but no email arrives (by design) [S17].
6. `curl -sI https://cfig-eligibility.<subdomain>.workers.dev/` with no login → a redirect to
   `cloudflareaccess.com`, never the page.

## 6. Monthly placement refresh (replaces "commit and push the refreshed CSVs")

1. Refresh the CSVs as today (`rules_data/placement/sync_from_out.py`), then commit and push them; they stay the
   source.
2. Note today's undo point: `npx wrangler d1 time-travel info cfig-eligibility` [S29].
3. Load them, then check `all_ok = 1`, as in 2.4.

The panel never changes a verdict, so a refresh needs no golden-file re-export.

## 7. Rolling back

**Code**
1. **Workers & Pages → cfig-eligibility → Deployments** → ⋯ on the good version → **Rollback** [S30]. From the
   terminal: `npx wrangler deployments list`, then `npx wrangler rollback <VERSION_ID> --message "why"` [S26].
2. Then `git revert` the bad commit and push. Otherwise the next push redeploys it.
3. Limits: the last 100 versions. A rollback never touches D1, and it is blocked if a binding changed between the
   two versions [S30].

**Data**
1. `npx wrangler d1 time-travel restore cfig-eligibility --bookmark=<bookmark>` [S29]. Anything written since is
   lost. The restore prints a new bookmark, so it can itself be undone.
2. Time Travel keeps 7 days on Free and 30 on Paid. For longer:
   `npx wrangler d1 export cfig-eligibility --remote --output=backup.sql` [S7].

## 8. What to tell agents

> The eligibility tool has moved to **https://cfig-eligibility.<subdomain>.workers.dev**. Please bookmark it.
> To sign in, type your @cfigtx.com email, and enter the code that arrives from noreply@notify.cloudflare.com within
> 10 minutes (check Junk). You stay signed in for <the session length>.
> What's different: no "Ask the Guides" chat tab, and no upload in the app (send new carrier guides to Liam).
> Checks, cards and "This looks wrong" work as before. The first visit takes a few seconds to load.

If codes don't arrive, allowlist `noreply@notify.cloudflare.com` in Microsoft 365 [S17].

## 9. Turning off Railway

1. Once step 5 passes and agents have used the new address for a day or two:
   - download Railway's logs once more and import them (2.5); duplicates are skipped;
   - point Hermes / the MCP config and any bookmarks at the new address.
2. Delete the Railway service, or pause it for a few days first, then cancel the plan.
3. Note the date in `handoff.md`.

## Sources

- [S1] https://developers.cloudflare.com/fundamentals/account/create-account/
- [S2] https://developers.cloudflare.com/fundamentals/manage-members/manage/
- [S4] https://developers.cloudflare.com/fundamentals/manage-members/roles/
- [S5] https://developers.cloudflare.com/workers/wrangler/commands/general/
- [S6] https://developers.cloudflare.com/d1/get-started/
- [S7] https://developers.cloudflare.com/workers/wrangler/commands/d1/
- [S9] https://developers.cloudflare.com/workers/ci-cd/builds/
- [S10] https://developers.cloudflare.com/workers/ci-cd/builds/git-integration/github-integration/
- [S11] https://developers.cloudflare.com/workers/ci-cd/builds/configuration/
- [S12] https://developers.cloudflare.com/workers/ci-cd/builds/build-branches/
- [S13] https://developers.cloudflare.com/workers/previews/
- [S14] https://developers.cloudflare.com/workers/previews/configuration/
- [S17] https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/
- [S18] https://developers.cloudflare.com/workers/configuration/cloudflare-access/
- [S19] https://developers.cloudflare.com/cloudflare-one/access-controls/policies/
- [S20] https://developers.cloudflare.com/cloudflare-one/setup/
- [S21] https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/session-management/
- [S23] https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/
- [S24] https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
- [S25] https://developers.cloudflare.com/workers/configuration/environment-variables/
- [S26] https://developers.cloudflare.com/workers/wrangler/configuration/ and https://developers.cloudflare.com/workers/wrangler/commands/workers/
- [S27] https://developers.cloudflare.com/cloudflare-one/team-and-resources/users/seat-management/
- [S28] https://www.cloudflare.com/sase/products/access/
- [S29] https://developers.cloudflare.com/d1/reference/time-travel/
- [S30] https://developers.cloudflare.com/workers/configuration/versions-and-deployments/rollbacks/
