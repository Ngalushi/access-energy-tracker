# ACCESS Energy Finance and Access Tracker

Live dashboard: https://ngalushi.github.io/access-energy-tracker/

Tracks World Bank and AfDB energy finance, electricity and clean-cooking access, NDCs and Mission 300 in Sub-Saharan Africa since the 2015 Paris Agreement.

## How it updates
- `.github/workflows/update-data.yml` runs every Monday (07:00 Nairobi) and on demand (Actions tab → "Weekly data refresh" → Run workflow).
- `scripts/update.py` pulls the World Bank WDI and Projects APIs, AfDB IATI data (d-portal), Climate Watch NDC data, the AfDB Mission 300 tracker and the World Bank Group Mission 300 Progress Portal, then rewrites `data.json`.
- If a source fails, the last good data is kept and the failure shows in the dashboard's "Data status" panel.
- `index.html` reads `data.json` when it loads.
