# Deploying the eligibility tool to Cloudflare

For Liam: a deploy this weekend, in **password mode**. Agents sign in with one shared password, as they did on
Railway, on the `workers.dev` address. Cloudflare Access (an emailed code per agent) comes later, once Jonathan has
set up Zero Trust with the company card. Switching over is section 8.

Docs were checked on 2026-10-24/25. A tag such as [S9] points to the Sources list at the end.

| | |
|---|---|
| Worker / D1 database | `cfig-eligibility` (in `wrangler.toml`; the D1 id is already in it, from your commit 9a739a5) |
| App address | `https://cfig-eligibility.<subdomain>.workers.dev`. `<subdomain>`: Workers & Pages → "Your subdomain" |
| How it is protected now | `AUTH_MODE = "password"` in `wrangler.toml`. The Worker runs first for every path, and nothing (page, scripts, engine, rules data, API) is served without a session from its login page |

## 1. One-time setup on your machine (repo root, `main` checked out)

1. `npm ci`, then `npx wrangler login` and `npx wrangler whoami`. The last should show the CFIG account [S5].
2. Your commit 9a739a5 already has the database id. If you ever recreate the database, run
   `npx wrangler d1 create cfig-eligibility`, paste the new `database_id` into `wrangler.toml`, and commit [S6].
3. Create the tables. This is migrations 0001 and 0002; 0002 holds the login lockout [S7]:
   ```
   npm run migrate:remote
   ```
4. Load the placement tables. These never reach the browser; the Worker answers the panel from them:
   ```
   node cloudflare/scripts/sync_placement.mjs
   npx wrangler d1 execute cfig-eligibility --remote --file=cloudflare/build/placement_sync.sql
   npx wrangler d1 execute cfig-eligibility --remote --file=cloudflare/scripts/check_placement.sql   # all_ok = 1
   ```
5. Optional: import Railway's logs, if you can download them. Re-running never duplicates a row. Delete the files
   afterwards; they hold real feedback.
   ```
   node cloudflare/scripts/import_logs.mjs --feedback <feedback_log.jsonl> --usage <usage_log.jsonl>
   npx wrangler d1 execute cfig-eligibility --remote --file=cloudflare/build/import_logs.sql
   ```

## 2. The three secrets

Each command asks for the value; type or paste it, and nothing is echoed. Secrets live only in Cloudflare, never in
`wrangler.toml` or git, and a deploy never deletes them [S25].
```
npx wrangler secret put APP_PASSWORD        # the agents' password
npx wrangler secret put ADMIN_PASSWORD      # yours and Jonathan's: feedback download, weekly counts
npx wrangler secret put SESSION_SECRET      # 32+ random characters, never typed by anyone
```
- **APP_PASSWORD:** pick a strong one, at least 12 characters, for example three or four unrelated words. It must not
  be Railway's old password.
- **ADMIN_PASSWORD:** a different one. The admin password also signs you in to the tool, so you need only that one.
- **SESSION_SECRET:** make one with
  `node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"`. Changing it later signs everyone
  out.
- **What happens without them:** if any of the three is missing, the passwords are the same, or a password is under
  8 characters, the tool fails closed. Every page says "This tool isn't set up yet."
- **Sharing the agent password:** send it the way you shared Railway's, in a Teams chat or email to the agents
  only, never in this repo. To change it, run `npx wrangler secret put APP_PASSWORD` again. That only stops new
  logins; to sign everyone out as well, set a new SESSION_SECRET.

## 3. First deploy, then GitHub builds

1. Build and deploy:
   ```
   npm run build
   npx wrangler deploy
   ```
   The address goes live with this deploy (`workers_dev = true`), already behind the login page. If the secrets
   aren't set yet, the address shows only "isn't set up yet".
2. **Workers & Pages → cfig-eligibility → Settings → Builds → Connect** [S9]:
   - install the Cloudflare GitHub app for this repo only [S10];
   - branch `main`;
   - build command `npm run build`;
   - deploy command `npx wrangler deploy`;
   - root directory empty [S11];
   - leave **Preview Builds** off [S12].

   From then on, a push to `main` deploys. Migrations stay a step on your machine (`npm run migrate:remote`, before
   you push code that needs them).
3. A push also still deploys Railway while it exists. `railpack.json` / `nixpacks.toml` keep it building the Python
   app. If you revive Railway, check its build log says Python.

## 4. The address

`workers_dev = true` is already in `wrangler.toml`, so there is nothing to flip. The gate shipped in the same code,
and it fails closed until the secrets exist. Preview URLs stay off (`preview_urls = false`): they would serve the
same code under another address.

## 5. First checks

1. **A private browser window → the address.** You should see the login page ("Carrier Eligibility Tool, Password"),
   not the tool.
2. **Without a cookie nothing comes back.** From a terminal:
   ```
   curl -sI https://cfig-eligibility.<subdomain>.workers.dev/                 # 302 to /login
   curl -sI https://cfig-eligibility.<subdomain>.workers.dev/engine.tar.gz    # 401
   curl -s  https://cfig-eligibility.<subdomain>.workers.dev/api/whoami       # 401 {"error":"login required"}
   ```
3. **The agent password** (with a name) → the tool loads, and the name is in "Your name". Then check that:
   - a Harris home (ZIP 77248) gets its four columns;
   - the placement panel appears above them;
   - "This looks wrong" on one card says "Sent -- thank you.";
   - the top bar has no "Download feedback" link.
4. **Five wrong passwords** → "That password isn't right." each time. After 10 in 15 minutes from one address that
   address is locked out for 15 minutes ("Too many wrong passwords").
5. **Log out**, then sign in with the admin password → **Download feedback** gives the CSV, and
   `/api/admin/weekly` gives the counts.
6. **Log out** → back to the login page, and the tool's address shows the login page again.

## 6. Rolling back

**Code**
1. **Workers & Pages → cfig-eligibility → Deployments** → ⋯ on the good version → **Rollback** [S30]. From the
   terminal: `npx wrangler deployments list`, then `npx wrangler rollback <VERSION_ID> --message "why"` [S26].
2. Then `git revert` the bad commit and push. Otherwise the next push redeploys it.
3. A rollback never touches D1 or the secrets, and it keeps the last 100 versions [S30].

**Data**
1. `npx wrangler d1 time-travel restore cfig-eligibility --bookmark=<bookmark>` [S29]. Get a bookmark first with
   `npx wrangler d1 time-travel info cfig-eligibility`.
2. Time Travel keeps 7 days on the free plan. For longer, back up with
   `npx wrangler d1 export cfig-eligibility --remote --output=backup.sql` [S7].

**Emergency**
- To take the tool off the internet: **Settings → Domains & Routes → workers.dev → Disable**, or set
  `workers_dev = false` and push [S32].

## 7. Message to agents

> The eligibility tool is back, at a new address: **https://cfig-eligibility.<subdomain>.workers.dev**. Please
> bookmark it. Sign in with the password I'm sending separately, plus your name if you like (it goes on any "This
> looks wrong" report you send). You stay signed in for 7 days on that computer.
> What's different from the old site: no "Ask the Guides" chat tab. The first visit takes a few seconds to load the
> tool; after that it's quick. Checks, cards and "This looks wrong" work as before.

## 8. Later: switching to Cloudflare Access (after Jonathan's Zero Trust setup)

1. **Zero Trust:** dashboard → **Zero Trust**, pick the team name (`<team>.cloudflareaccess.com`), choose **Free** (it
   asks for the company card; "you won't be charged") [S20]. Then **Integrations → Identity providers → Add new →
   One-time PIN** [S17].
2. **Protect the Worker:** **Workers & Pages → cfig-eligibility → Access** tab → **Protect this Worker behind
   Access** → **All traffic** [S18]:
   - policy: **Email domain** `cfigtx.com` [S19];
   - session length: up to you (the default is 24 h) [S21];
   - then **Apply Access**.

   Seats: one per person who logs in; 50 are free, then $7 a user a month [S27][S28].
3. **Wire the Worker to Access:** copy the app's **AUD tag** (**Zero Trust → Access controls → Applications →** the
   app → **Configure → Additional settings**) [S24]. In `wrangler.toml` set:
   - `ACCESS_AUD = "<the tag>"`;
   - `ACCESS_TEAM_DOMAIN = "<team>.cloudflareaccess.com"`;
   - `ADMIN_EMAILS = "liam@cfigtx.com,<jonathan>"`;
   - `AUTH_MODE = "access"`.

   Optionally set `run_worker_first = ["/api/*"]`; Access then guards the static files, and they stop costing Worker
   requests. Commit and push.
4. **Check:** a private window shows Cloudflare's email page, a `@cfigtx.com` address gets a code, and the tool
   loads with your email in the top bar.
5. **Remove the password secrets:**
   ```
   npx wrangler secret delete APP_PASSWORD
   npx wrangler secret delete ADMIN_PASSWORD
   npx wrangler secret delete SESSION_SECRET
   ```
   Tell agents to sign in with their email from now on.

## Turning off Railway

Once agents have used the new address for a day or two:
1. import Railway's final logs (1.5), if you can still download them;
2. point any bookmarks at the new address;
3. delete the Railway service and cancel the plan;
4. note the date in `handoff.md`.

CFIG-GPT needs nothing: its MCP server imports the engine on your laptop and never called Railway.

## Sources

- [S5] https://developers.cloudflare.com/workers/wrangler/commands/general/
- [S6] https://developers.cloudflare.com/d1/get-started/
- [S7] https://developers.cloudflare.com/workers/wrangler/commands/d1/
- [S9] https://developers.cloudflare.com/workers/ci-cd/builds/
- [S10] https://developers.cloudflare.com/workers/ci-cd/builds/git-integration/github-integration/
- [S11] https://developers.cloudflare.com/workers/ci-cd/builds/configuration/
- [S12] https://developers.cloudflare.com/workers/ci-cd/builds/build-branches/
- [S17] https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/
- [S18] https://developers.cloudflare.com/workers/configuration/cloudflare-access/
- [S19] https://developers.cloudflare.com/cloudflare-one/access-controls/policies/
- [S20] https://developers.cloudflare.com/cloudflare-one/setup/
- [S21] https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/session-management/
- [S24] https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
- [S25] https://developers.cloudflare.com/workers/configuration/secrets/
- [S26] https://developers.cloudflare.com/workers/wrangler/commands/workers/
- [S27] https://developers.cloudflare.com/cloudflare-one/team-and-resources/users/seat-management/
- [S28] https://www.cloudflare.com/sase/products/access/
- [S29] https://developers.cloudflare.com/d1/reference/time-travel/
- [S30] https://developers.cloudflare.com/workers/configuration/versions-and-deployments/rollbacks/
- [S32] https://developers.cloudflare.com/workers/configuration/routing/workers-dev/
