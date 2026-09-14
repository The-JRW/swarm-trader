# Elestio: set SWARM_CRON_SECRET

**Do not put a real secret in this repo.**

1. Open the Elestio service env UI for `swarm-master`.
2. Add `SWARM_CRON_SECRET` = a long random string (e.g. `openssl rand -hex 32`).
3. Redeploy / restart backend so cron routes accept `X-Swarm-Cron-Secret`.
4. Keep `SWARM_MONITOR_DRY_RUN=true` until dry-run week exit criteria in `docs/AUTOMATION_A1_A2.md` are met.

Without `SWARM_CRON_SECRET`, all `/cron/*` routes return **401 FAIL_CLOSED**.
