# Trading AI Termux — Public Site

Public GitHub Pages dashboard for live Indodax BTCIDR market data. Market price, chart and spread come from the exchange WebSocket; model weights and validation refresh on the scheduled GitHub Actions snapshot. Account access is invite-only and fails closed until Supabase is configured.

## Production account setup

Follow [`docs/ACCOUNT_SETUP.md`](docs/ACCOUNT_SETUP.md) before enabling account access. The account gate is **fail-closed**: it hides the dashboard until Supabase has confirmed a signed-in account and active invitation.

The backend migration and Edge Functions are in the private [`TradingAI-Termux` repository](https://github.com/Yantotsu/TradingAI-Termux/tree/main/supabase). Do not put a Supabase secret/service-role key in this public repository. The browser uses only the publishable key, with database access controlled by RLS.

User balances shown in the portal are labeled `SIM_IDR` and are simulation credits only. This site does not accept deposits, withdrawals, or real-money trading balances. GitHub Pages serves static market assets publicly; Supabase RLS, not the visual gate, is the boundary protecting account data.
