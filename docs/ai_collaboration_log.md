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

**Follow-up.** When the pageviews download passed 30 minutes, I asked for its efficiency to be checked. It was healthy (no errors, no retries, one process) and running at the pace we chose on purpose to stay under the rate limit. Restarting would have saved a few minutes at most and risked getting throttled again, so we let it finish.

## 9. This log
**My call.** I asked for this record to be kept throughout the project so the process is as reviewable as the code.

## 10. Featured credits: kept separate from lead credits
**Redirected.** The AI proposed building two chart signals (lead credits only vs. any credit) and letting the model pick. I agreed, but required that every credit keep its role, because a featured appearance can be the first sign of a breakout. My example: Don Toliver's feature on Travis Scott's "Can't Say" (2018) launched his career before he led anything.

**Outcome.** Credits are stored as lead or featured. The data backed the idea: 17 of 123 tour artists with both credit types were featured before they ever led a chart entry, including The Weeknd (Drake's "Crew Love," 7 months before his first lead) and Charli XCX (Icona Pop's "I Love It," over a year before). "Featured-credit momentum" is now a planned model feature.

## 11. Artist names: required online validation and attention to name changes
**My call.** I told the AI to look names up online whenever matching was uncertain, and to specifically account for artists who changed their names.

**Outcome.** This turned a simple matching script into a validated process:
- Wikipedia's API resolved duplicate spellings of the same artist ("the Weeknd" vs. "The Weeknd," "Sam Smith (singer)" vs. "Sam Smith"), which had silently sent all of The Weeknd's chart credits to a duplicate record. A warning now fires on any future name collision.
- Former names are pulled from Wikipedia redirects (Lady Antebellum to Lady A, Dixie Chicks to The Chicks, Ghost B.C. to Ghost, Paul Simon's early stage names Jerry Landis and Tico and the Triumphs).
- An audit report of every redirect-based match showed the raw redirects were unsafe: songs and products redirect to artist pages too ("X (fragrance)" to Westlife, "Live (perfume)" to Jennifer Lopez, "Abel." matched the duo "Kane & Abel"). Five filter rules now keep only real alternate names. One-word aliases (Janet, Ye, NKOTB, Ke$ha) are added only after checking the actual chart credits by hand.
- The same directive shaped the pageviews data. Wikipedia counts views under the title a reader requested, so before a rename an artist's views sit under the old title (Lady Antebellum's views before 2020 aren't under "Lady A"). Each artist's daily views therefore add up their current title plus every redirect to it, with the current-title-only count kept for robustness checks.
- Final result: 244 of 255 tour artists matched to chart history. The 11 unmatched were each checked and genuinely never appeared on a US Billboard chart (e.g. Helene Fischer, JJ Lin, Dead & Company).

## 12. Popularity beyond Billboard: streaming and social signals
**My idea.** I raised that Billboard and radio don't capture modern popularity on their own: some songs are widely known without charting high, and Spotify, Apple Music and TikTok-style platforms drive discovery.

**Research findings.** Since 2013 the Hot 100 already counts streaming and YouTube, so Billboard isn't radio-only, but its top-100 cutoff misses widely known songs that never rank. Spotify's Top 200 (with stream counts) and Viral 50 charts are available for 2017-2021 under an open database license. TikTok's Billboard chart existed only from 2023 to 2025 and sits behind a paywall, and Apple Music has no public history.

**Decision (accepted recommendation).** The main model uses Billboard plus Wikipedia pageviews across 2015-2025. A separate 2017-2021 sub-analysis tests whether Spotify US stream counts and Viral 50 virality add predictive power on top. TikTok and Apple Music are documented as limitations and future work.

**Follow-up.** I asked about Tidal and SoundCloud too. Neither has a usable chart history, and Billboard already counts streams from Apple Music, Tidal and SoundCloud in its charts. So they're covered inside the Billboard signal, just not separately, and the README will say so.

## 13. Puerto Rico: inside the US market, but flagged
**My call.** The AI asked whether Puerto Rico's shows belong in the US + Canada analysis. I said yes, since Billboard's US charts cover it, but required that it be marked separately because listening there is culturally different (much more Latin music), so a US chart signal may not track local demand the same way.

**Outcome.** Puerto Rico shows count toward the US + Canada sample and carry their own `is_puerto_rico` flag, so models can control for the difference and it can be tested once features exist. There are only 18 model-ready Puerto Rico shows, which will be noted as a limitation.

## 14. Data readiness audit before building on the data
**My call.** Before moving on to the database and features, I asked whether we actually had all the data we needed and whether it was properly cleaned. I wanted an explicit check, not an assumption.

**Outcome.** The audit checked every dataset for duplicates, impossible values, time coverage and stale files, and found problems that would have reached the model:
- The same show was listed on two artists' tour pages 15 times (for example, Kenny Chesney and Jason Aldean merged their tours for ten 2015 stadium shows). Left alone, one sellout would count twice. Each case was checked against the tour pages and merged into one row, keeping co-headliners and dropping openers.
- Three shows have sources that disagree, so they're flagged and kept out of the model instead of guessing which page is right.
- About 500 US shows from 2012 to 2015 happened before Wikipedia pageview data begins, so they can only be used in a chart-only comparison.
- 454 redirects to artist pages were once separate articles ("Drake discography", 25.5 million views). Counting them would put a fake jump in an artist's popularity on the day the pages were merged, so they're excluded.

I accepted the AI's recommendations on how to fix each one.

## 15. COVID: a comparison, not just a footnote
**Redirected.** The AI proposed keeping 2020-21 shows with a COVID flag and running one robustness check without them. I wanted COVID to be part of the analysis itself: compare shows before and after the shutdown, since fans came back with pent-up demand and different habits.

**Outcome.** Every show is labeled pre, during or post shutdown (March 12, 2020 to August 1, 2021). There are only 5 model-ready US shows during the shutdown, so the comparison is pre (6,165 shows) vs. post (2,194 shows): does the same chart or pageview signal predict sellouts differently after COVID?

## 16. When to measure popularity: six months before the show
**Accepted.** The AI asked whether chart and pageview signals should be measured on the show date or earlier. It recommended six months before, as a stand-in for when the venue is booked and tickets go on sale, because tour announcements and sellout news push pageviews up in the months before a show. Measuring on the show date would let the tour's own hype leak into the signal and overstate how well it predicts demand. I agreed.

**Outcome.** Signals are measured as of six months before each show. The show-date version is kept only as a robustness check.

**Follow-up.** The feature build enforces the cutoff with a test: flooding every source with fake hype from the cutoff through the show date leaves every feature unchanged. To make sure the test can actually fail, the code was broken on purpose (counting data from the cutoff day itself), and the test caught it.

## 17. Lookback windows: more data, but only if it isn't noise
**Redirected.** The AI offered three choices: a 52-week window plus 13-week momentum (its recommendation), a 26-week window, or building several windows and letting the model choose. It warned that the last option risks overfitting. I asked for a mix: build the extra windows, but keep one only if it actually improves the model.

**Outcome.** The 52-week window plus 13-week momentum is the baseline. A 26-week window is also built, and it stays only if it beats the baseline in time-based cross-validation on the training years, so the extra window can't be tuned against the test set. The 52-week window sets the model start date at about January 2017 (roughly 5,800 US and Canada shows).

## 18. Keeping the record current
**My call.** Partway through this phase I asked for the task list to be checked off as each item finishes, and for this log to be updated from the session transcript after every two completed tasks, instead of in one pass at the end.

**Outcome.** Entries 16 to 18 are the first update made on that schedule. The same session's Pollstar validation found that Wikipedia labels some near-sellouts (96 to 99% sold in Pollstar) as sold out. That raises a question about how "sold out" should be defined, which I still need to decide before modeling.

## 19. Taking back the design decisions
**Redirected.** After I chose the signal timing and lookback windows, the AI built the Pollstar matching, the database, every feature definition and a first set of SQL analysis views, and explained its choices only after they were built. I stopped it and said again that I want to lead this project, with room to put my own spin on things, not just approve finished work.

**Outcome.** The AI paused before committing the SQL views and listed every judgment call it had made on its own, eleven in all. Examples: how chart positions are scored, whether Spotify featured credits are kept separate from lead credits (adding them together contradicted my rule in entry 10), how co-headlined shows are handled, the venue size bands, and which questions the analysis views answer. All of them are open for me to change. The working rule from here: any choice with more than one reasonable answer comes to me before it's built, and only mechanical work goes ahead without asking. The decisions I make on that list will be logged as separate entries.
