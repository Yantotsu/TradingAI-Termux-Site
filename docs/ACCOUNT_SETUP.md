# Account setup and deployment

The account gate is live in the website code, but it stays locked until an owner connects a Supabase project. This prevents the site from silently falling back to an unprotected dashboard.

## Provision the backend

1. Create a Supabase project owned by the project operator.
2. In the private `TradingAI-Termux` repo, use the account backend instructions and run `supabase/migrations/202611200001_accounts_and_demo_ledger.sql` against that project.
3. Create the owner's account in Supabase Auth. Insert that account's Auth UUID into both `public.account_profiles` (status `active`) and `public.account_admins` using the SQL snippet in the private repo's `docs/ACCOUNT_BACKEND.md`. This bootstraps the first owner without an invitation; later members must redeem one.
4. Deploy the `issue-invite` and `redeem-invite` Edge Functions from the private repo with JWT verification enabled. The functions use the caller's JWT and publishable key; never disable RLS.
5. In Supabase Auth URL Configuration, set the site URL to `https://yantotsu.github.io/TradingAI-Termux-Site/` and add that exact URL to Redirect URLs for password recovery. Enable email confirmation and configure a real SMTP sender before inviting public users. Review Auth rate limits and enable CAPTCHA before broad signup if needed.
6. In the public site's GitHub repository settings, add these **Actions variables**:
   - `SUPABASE_URL`: the project's HTTPS URL.
   - `SUPABASE_PUBLISHABLE_KEY`: the browser publishable key (or legacy anon key).

   These are public browser configuration, not server secrets. Never put a Supabase secret/service-role key into Actions variables, Pages, or the browser bundle.
7. Run the `Refresh and publish dashboard` workflow manually. The generated `auth-config.js` is built into `_site` and is not committed. Confirm that an unconfigured or signed-out browser sees only the access screen, while an authorized invited user can enter.
8. Sign in as the owner. The dashboard's **Buat kode undangan** button calls the admin-checked Edge Function. Enter each approved person’s verified email in the invite panel. The code is bound to that email, appears once, expires after 7 days, and can only be redeemed once. Send the code privately; do not publish codes in a public issue or chat.

Supabase production secrets belong in Supabase Dashboard → Edge Function Secrets. Local `.env` files are ignored by Git. The public site intentionally does not use a service-role key.

## What the account can access

RLS binds profiles, `demo_balance`, and `demo_ledger` reads to `auth.uid()`. Ledger mutations are unavailable to the browser except the admin-only SQL function for simulation credits. A balance is displayed as `SIM_IDR`; it is not fiat, cannot be redeemed, and is not a record of a cash deposit.

There is no deposit, withdrawal, payment collection, or user-funded trading route in this build. Do not record real customer money in the demo ledger. A real-money account requires an approved payment/custody model and a legal review before implementation.

## Deployment behavior

GitHub Pages automatically deploys each push to `main`. If the Supabase variables are missing, the workflow publishes the locked configuration state. If auth settings or migrations are missing, login will report a backend error; do not bypass the gate or expose personal data to make the page appear functional.

## What GitHub Pages does not hide

GitHub Pages serves static files publicly. The invite screen controls the normal user interface, but anyone can still fetch the public HTML/JavaScript and market snapshot directly. Those assets contain public market data only. Personal profiles, simulation balances, and ledger rows stay behind Supabase Auth and RLS, so the UI gate is not their security boundary. If every page asset must be inaccessible until login, move the site to an authenticated server/proxy; do not publish private data or secret market files through Pages.
