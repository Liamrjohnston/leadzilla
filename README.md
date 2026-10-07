# LEADZILLA

**Find and qualify business leads for a fraction of a cent.** Name a niche, a place and what you sell. LEADZILLA finds every matching business it can, reads their websites, pulls out their emails, phones and social profiles, and scores each one against your offer. You get a spreadsheet that imports straight into Instantly, Smartlead, Lemlist, Google Sheets or Excel.

```bash
leadzilla run --niche "real estate brokerages" --place "Vancouver, BC" \
  --offer "AI marketing and automation for brokerages" --target 100 --out leads.xlsx
```

## Why it's cheap

Most AI scrapers send every whole web page to a big language model and pay for every token. LEADZILLA doesn't:

| Job | Who does it | Cost |
|---|---|---|
| Finding businesses | OpenStreetMap open data, plus free web search | free |
| Fetching pages | [Scrapling](https://github.com/D4Vinci/Scrapling) | free |
| Pulling emails, phones, addresses, socials | plain code (links, page text, schema.org data) | free |
| Checking an email's domain takes mail | a DNS lookup | free |
| **Every judgement:** is this a real business in the niche? which page has the contacts? which email is the right one? which search result is its website? how well does it fit your offer? | **[Jev](https://typesafe.ai)**, TypeSafe's yes/no, pick-one and score model | $0.042 per million tokens |

Jev never writes text and never does maths; code does both. It only answers typed questions, with a probability and a confidence for every answer. That is why it costs about a cent per hundred sites.

Every run prints its own bill, and an estimate of what the same pages would cost read by Claude:

```
LEADZILLA: 45 new leads -> leads.xlsx
  sites checked 101, pages read 221
  Jev: 51 calls, 184,646 tokens, $0.0078
  Same pages read by Claude (estimate): Haiku $0.75, Sonnet $1.50, Opus $3.76
```

That estimate assumes ~4 characters per token for page text, 300 prompt tokens and 250 output tokens per page, at Anthropic list prices. It's an estimate of the per-page LLM approach, not a measured Claude run.

## Install

```bash
git clone https://github.com/Liamrjohnston/leadzilla && cd leadzilla
python3 -m venv .venv && . .venv/bin/activate     # Python 3.10+
pip install -e .
export TYPESAFE_API_KEY=...                       # from typesafe.ai
```

Or, in Claude Code, paste the repo link and say "install this". `SKILL.md` tells Claude how to run it.

If you use Composio with the `jev` toolkit connected, LEADZILLA can call Jev through it instead (`--backend composio`).

## What you get

Each lead has a status (`qualified`, or `review` when Jev was unsure it's the right kind of business), plus:
- company, website, best email (with "general inbox" or "named"), other emails, phone and address;
- LinkedIn, Instagram, Facebook, X, YouTube and TikTok links;
- a fit score from 0 to 4 against your offer, with a confidence;
- size, and a one-line reason.

Choose the layout with `--format`, or let the file extension decide:

| `--format` | For |
|---|---|
| `csv` | Excel, Google Sheets, Numbers. UTF-8 with a BOM, so accents survive Excel |
| `xlsx` | A formatted spreadsheet: frozen header, filters, clickable links, best fit first |
| `instantly`, `smartlead`, `lemlist` | Column names those tools map on import. Rows without an email are left out |
| `linkedin` | LinkedIn outreach: company page, website and contact details |

Re-export any time without re-running: `leadzilla export --niche ... --place ... --offer ... --out leads.csv --format instantly`.

## Run it again for more

Everything is remembered in `~/.leadzilla/leadzilla.db`. Running the same niche, place and offer again skips every site already checked and only looks for new ones. Change `--offer` and the leads are re-scored as a separate campaign.

## Where the ideas came from

- **[Scrapling](https://github.com/D4Vinci/Scrapling)** (BSD-3): the fetching layer.
- **[ScrapeGraphAI](https://github.com/ScrapeGraphAI/Scrapegraph-ai)** (MIT): the search-then-scrape pipeline shape and schema-first output. LEADZILLA reads the `mailto:`, `tel:` and schema.org data that per-page LLM scraping throws away.
- **[OpenOutreach](https://github.com/eracle/OpenOutreach)** (GPL-3.0): the ideas of a reason on every lead, "find N more" runs that resume, and paying only for leads you're confident about. No code was copied.

## Behaving well

- **robots.txt is obeyed.** A site that disallows us, or blocks us, is skipped.
- **One request per site per second** by default (`--delay`).
- **No fake referer and no anti-bot bypass.**
- **LinkedIn is never fetched.** Company pages come from the business's own website or public search results.
- **Nothing is sent anywhere** except to Jev (the text it judges) and the public map and search services.
- Business data from OpenStreetMap is © OpenStreetMap contributors, under the ODbL.
- **LEADZILLA finds and qualifies leads. It does not send email.** Before you email anyone, follow the anti-spam law where you and they are: CASL in Canada, CAN-SPAM in the US, GDPR/PECR in the UK and EU. That includes consent rules, identifying yourself, a postal address and an unsubscribe link.

## Tests

```bash
python -m unittest discover tests     # offline: no network, no Jev calls
```

MIT licensed.
