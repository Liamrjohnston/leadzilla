---
name: leadzilla
description: Find and qualify business leads for a niche and place, scored against what the user sells, and export them for cold email tools, LinkedIn outreach, Google Sheets or Excel. Use when the user asks for a lead list, prospects, or businesses to contact.
---

# LEADZILLA

1. **Ask for three things if they're missing:** the niche ("real estate brokerages"), the place ("Vancouver, BC") and what they sell (one sentence). Also ask how many leads they want (default 50) and where they'll use them: Instantly, Smartlead, Lemlist, LinkedIn, Google Sheets or Excel.
2. **Check the setup.** `leadzilla --help` should work. If it doesn't, install from this repo: `pip install -e .` in a Python 3.10+ virtual environment. Jev needs `TYPESAFE_API_KEY` in the environment (typesafe.ai), or Composio with the `jev` toolkit connected. Never print the key.
3. **Run it:**
   ```bash
   leadzilla run --niche "<niche>" --place "<place>" --offer "<what they sell>" --target <n> --out leads.xlsx
   ```
   It prints progress, and at the end the leads found, Jev's real cost, and an estimate of what the same pages would cost read by Claude. Report those numbers exactly as printed.
4. **Export for their tool:** `leadzilla export ... --format instantly` (or `smartlead`, `lemlist`, `linkedin`, `csv`, `xlsx`). Use the same niche, place and offer as the run.
5. **For more leads,** run the same command again: it skips every site already checked. A bigger `--radius-km` widens the area.

Tell the user:
- Leads marked `review` need a human look.
- LEADZILLA finds and qualifies leads but never sends email.
- Cold email has to follow the law where they and their prospects are (CASL, CAN-SPAM, GDPR).

Do not add flags that bypass robots.txt or site blocks.
