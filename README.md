# Job Hunter: worldwide mid-level Sales job alerts (last 2 hours) on Telegram

## One-time setup (about 15 minutes)

1. **Telegram bot**: open Telegram, message `@BotFather`, send `/newbot`, copy the **token**.
   Then message your new bot once ("hi"), open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id` = your **chat id**.
2. **Adzuna key** (free): https://developer.adzuna.com -> register -> copy `app_id` and `app_key`.
3. **Jooble key** (free, optional): https://jooble.org/api/about
4. **GitHub**: create a *private* repo, upload all files in this folder (keep the `.github` folder).
5. Repo -> Settings -> Secrets and variables -> Actions -> add:
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_KEY`
6. Repo -> Actions tab -> "Job alerts" -> **Run workflow**. After that it runs every 15 minutes by itself.

## Test on your laptop
    pip install -r requirements.txt
    export ADZUNA_APP_ID=... ADZUNA_APP_KEY=...
    python job_hunter.py --dry-run --hours 24     # see what would be alerted

## Tuning (profile.yaml)
- Too many alerts: raise `min_score` (try 60-70). Too few: lower it or widen `window_hours`.
- Add company career boards under `greenhouse_boards` / `lever_boards` (token = name in the careers URL).
- Edit `skills` weights as your target roles change.

## Scoring (0-100)
Title fit (40) + skills match from your resume (50) + location (10).
Each alert lists your matched skills and tools the JD asks for that are not on your resume.

## Also turn on (native alerts, 2 minutes each)
LinkedIn, Naukri and Indeed block scraping, so use their built-in alerts:
set "Instant" / "Immediate" alerts for the same job titles + Gurugram/Delhi NCR, with notifications on.

## Worldwide coverage
- Adzuna: India every run + one other country rotated each run (GB, US, CA, AU, SG, DE, NL). Free-tier call limits are why countries rotate.
- Jooble: worldwide queries, rotated. RemoteOK, Remotive, Arbeitnow (Europe): checked every run.
- Add country boards in `profile.yaml` (`adzuna_other_countries`) if you target a specific country.
- Alerts for jobs outside India are tagged "Abroad role" with a note on visa/work-authorization wording found in the ad.
