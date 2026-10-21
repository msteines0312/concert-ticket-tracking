# How I Used AI on This Project

I built this project with Claude Code as a coding partner. This log records the decisions that shaped it: what I asked for, what the AI recommended, and where I accepted, questioned, or overrode that recommendation. The goal is to show how the work was directed, not just what was generated.

Entries are in chronological order. "Accepted" means I agreed with the AI's recommendation after reviewing it. "Overrode" or "Redirected" means the final decision differed from what was proposed.

---

## 1. Data first, before any code
**My call.** I wrote the project brief: the research question (do Billboard charts predict ticket sales, and which artists are booked into the wrong size room), the deliverables, and the rule that no code gets written until we know what data actually exists. I also flagged up front that Spotify had cut off its audio features API, that causation had to be framed honestly, and that terms of service had to be checked before scraping anything.

**Outcome.** The feasibility research found that per-show ticket data is mostly private, Billboard blocks automated access behind a paywall, and setlist.fm's terms forbid storing its data. Checking first avoided building a pipeline on sources we couldn't legally use.

## 2. Data scope: chose the most complete option
**Overrode.** The AI recommended using Wikipedia tour tables alone (simplest, cleanest licensing). I chose to combine Wikipedia with Pollstar's year-end reports.

**Why.** More coverage and a second source to validate against. The follow-up check proved this mattered: Wikipedia coverage drops sharply after 2019 (277 tours in 2015-19 vs. 98 in 2022-25), and Pollstar partly fills that gap.

## 3. Outcome variable: merged sellout and fill rate into one equation
**Redirected.** The AI proposed replacing fill rate (attendance / capacity) with a sellout yes/no outcome, because 68% of shows are exactly 100% sold and fill rate gets squashed at that ceiling. I didn't want to lose fill rate, and pushed for a way to merge the two into a single, more complete measure instead of picking one.

**Outcome.** In response, the AI proposed the formula that became the core of the model:

> expected fill rate = P(sellout) × 100% + (1 − P(sellout)) × predicted fill rate if not sold out

Part 1 is a logistic regression for the chance of selling out. Part 2 predicts how full the room gets when it doesn't. Weighting each part by the sellout probability turns them into one number per artist and venue, which feeds the "right-sizing" score. A Tobit model is planned as a robustness check. Without the push to merge, the analysis would have discarded the fill rate information for every non-sellout show.

## Model building
*To be logged as it happens:* decisions on feature selection, how the two parts are weighted and validated, and overfitting controls (planned: cross-validation grouped by artist, so the model is tested on artists it has never seen).

## 4. Geography: kept worldwide data
**Overrode.** The AI recommended limiting the analysis to US and Canada shows, since Billboard charts measure US popularity. I chose to load worldwide data, run the main analysis on the US and Canada subset, and use worldwide as a robustness check.

**Why.** Keeps the signal-to-outcome match for the main results without throwing away data that can test whether findings hold elsewhere.

## 5. Database and version control
**Accepted.** SQLite over MySQL, so anyone cloning the repo can run it with no database server. Local git repo first, GitHub repo created private until the work is presentable.

## 6. Licensing: questioned the default, then raised the bar on citations
**Questioned, then expanded.** When the AI suggested adding an MIT license, I asked whether it was actually worth it rather than accepting it. Then I asked for every data source to be properly cited.

**Outcome.** A "Data Sources and Licensing" section in the README, plus a per-article source list with Wikipedia revision permalinks so every attendance figure can be traced back to the exact page version it came from. This also surfaced a real constraint: copyrighted Pollstar data must never appear in a published dashboard.

## 7. Dashboard tool: switched from Tableau to Power BI
**My call.** The original plan was Tableau Public, which I already know. I switched to Power BI because it appears more often in the analyst job postings I'm targeting, and asked to learn it hands-on while building the dashboard rather than have it built for me.

**Outcome.** Updated the repo to ignore `.pbix` files (they embed the full dataset) and commit a `.pbit` template instead.

## 8. Ingest speed: faster, but not at the cost of data
**Set the constraint.** The first full Wikipedia download was throttled to about 10 pages a minute (2+ hours total). The AI proposed a faster method. I approved it on one condition: it could not lose any data the model needs.

**Outcome.** Because of that condition, the new method was tested before the full run: old and new downloads were compared page by page on the 99 tours already fetched, and all 99 produced identical engagements. The test also exposed that the faster method alone didn't fix the speed. The real cause was Wikipedia's 2026 rate-limit policy, which caps clients it can't identify at 10 requests per minute, and our User-Agent header didn't meet its format. Fixing the header moved us to the 200 per minute tier. If the switch had been accepted without testing, the pipeline would have stayed slow with the wrong explanation in the code.

## 9. This log
**My call.** I asked for this record to be kept throughout the project so the process is as reviewable as the code.
