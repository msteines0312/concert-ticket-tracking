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

## 20. Does the type of show matter? Production level as a new angle
**My idea.** I asked whether the kind of show affects demand: a full production with dancers and choreography versus a fairly standard concert.

**Research findings.** setlist.fm is off limits (its terms forbid storing data), but the cached Wikipedia tour articles describe many shows. A quick first scan suggested 65% of the 242 tours in the model sample had a stage or production section and 90% had a set list. (Corrected later: that scan counted "Shows" and "Cancelled shows" headings as production sections. The real figures are 53 of 240 tours with a production section, 91 with any description of the show, and 212 with a set list.) The AI flagged four problems: production is a tour-level trait (about 240 tours, not 5,800 shows), bigger tours get longer and more detailed articles, genre is mixed in (pop tours have dancers, rock tours mostly don't), and big productions get booked into stadiums.

**Decision.** Of four options (keyword flags, labeling everything by hand, AI labeling with a hand check, set length), I chose to write the rubric myself, have Claude label each tour from its article text, and hand-check a random sample to measure agreement. Set length (songs per show) is added as its own number. The model will control for article length and genre so production level doesn't become a disguised popularity measure.

## 21. One-hit wonders: do fresh hits get artists overbooked?
**My idea.** I wanted recent chart runs studied as their own question: does a one-off hit lead tour managers to book an artist into rooms bigger than their real fan base can fill? I also cut day of week from the analysis, since it wasn't worth a view.

**Outcome so far.** A quick check with a placeholder definition supports the idea. Shows by artists whose chart history is mostly from the past year were booked into rooms about 1.7 times bigger than their usual, and sold out less often than established artists who were also charting (69% vs. 77%). The placeholder also mislabels new solo careers (Harry Styles, Niall Horan) as breakouts, so I'm choosing the final definition of a one-hit artist myself.

**Follow-up: my definition.** I defined a one-hit act as hype without a fan base: one song that went viral, rather than a dedicated fan base responding to an album. The test is low attention to the artist before the song arrived (Wikipedia pageviews in the year before the song first charted), combined with album chart success that's weak compared with the song's. With one song providing at least 70% of recent chart points, those shows sold out about 15 points less often and filled about 10 points less than other charting artists. Only 4 to 7 artists qualify, so it works as a case study, not a model feature. Testing my definition also exposed two measurement problems: English Wikipedia undercounts Latin artists, whose fans read Spanish Wikipedia (J Balvin and Aventura looked unknown), which also biases the main pageview signal; and a one-year album window misses established artists who are between albums (Brad Paisley).

## 22. Spanish Wikipedia, genre groups, and cutting rituals
**My call (Spanish pageviews).** After the one-hit check showed that English Wikipedia undercounts Latin artists, I decided to add Spanish Wikipedia pageviews, since the bias affects the main popularity signal and not just one-hit detection.

**Accepted (genres).** I asked for a generally accepted set of genre groups. The AI proposed Billboard's top-level chart genres (Pop, Rock/Alternative, R&B/Hip-Hop, Country, Latin, Dance/Electronic, Other), which is the industry standard and matches the chart data already in the project. Genre is needed as a control for production level, which I'd decided should be judged against genre norms.

**My call (rituals).** I had raised concert rituals as an angle (Role Model's "Sally" moment and similar fan traditions). After looking at the problems (rituals often become famous partway through a tour, they mostly belong to superstars who already sell out, and only 15 to 30 tours would qualify) I decided to drop it: it would add more noise than signal.

**Outcome.** Genre groups come from each artist's Wikipedia infobox. Every listed genre is mapped to a group and the artist gets the majority, because infoboxes don't list genres in order of importance. The first version had two bugs, found by reviewing the output: citation links inside the genre field were read as genres ("AllMusic", "Rolling Stone"), and unmatched labels outvoted real ones (Lady Gaga came out as "Other"). Both are fixed and tested. The final split across 255 artists: Rock/Alternative 85, Pop 61, R&B/Hip-Hop 53, Country 22, Latin 21, Dance/Electronic 10, Other 2. The 57 ties are broken by the first-listed genre and flagged for my review.

## 23. Clearing the open decisions in one pass
**My call (format).** With 15 design questions open, I asked for a simple selection list so I could go through them quickly. Most choices below accept the AI's recommendation after I compared the options. The ones where I chose something else are marked.

- **Sellout definition (accepted):** exactly 100% sold stays the main outcome, and the Pollstar-based 97% threshold becomes a robustness check.
- **Production tiers (my pick):** Standard is a band with instruments and lights in a smaller venue; Enhanced includes dancing; the top tier is a themed show built around a story or eras (like the Eras Tour or Renaissance). I chose this over a count of big production elements.
- **Genre ties (accepted):** the 57 tie-broken genre assignments stand.
- **2019 Pollstar (accepted):** OCR the scanned PDF so validation also covers pre-COVID shows.
- **One-hit definition (accepted):** under 3,000 daily pageviews before the song charted, and album support measured over the whole career, so established artists between albums aren't flagged.
- **Chart scoring (accepted):** keep linear points and add a separate count of top-10 weeks.
- **Spotify (accepted):** split lead and featured streams, in line with my rule in entry 10.
- **Co-headliners (accepted):** use the stronger act's signal.
- **Momentum (accepted):** keep pageview momentum and add chart momentum, which ties into my one-hit question.
- **Ticket price (my variant):** the AI recommended keeping average ticket price out of the model, because it's the price after dynamic pricing reacted to demand. I chose to include it, but only behind a test: compare the model with and without price, and if price inflates accuracy enough to suggest it's leaking the outcome, fall back to descriptive use only.
- **Model framing (accepted):** build both the two-part sellout model and a demand model (tickets per show compared to capacity), and compare them.
- **Analysis views (my pick):** right-sizing, booking history and signal diagnostics. I left out the COVID and seasonality views; the COVID comparison from entry 15 stays in Phase 2.
- **Notebook (accepted):** save the exploration as a cleaned notebook.
- **README limitations (my pick):** the AI drafts, I edit it into my own voice.
- **Pollstar matching (accepted):** keep the validated rule.

## 24. Results of the decision batch
**My call (logistics).** For production labels, I chose to have Claude label the tours in the working session rather than through an API script, and had it install the OCR tool for the 2019 Pollstar PDF.

**One-hit result.** My full definition (one song at least 70% of recent chart points, under 3,000 daily pageviews before the song, weak album support over the whole career) is much stricter than the first rough version. It flags two acts: Kim Petras ("Unholy"), 12 shows with no sellouts and 42% of seats filled, and Tate McRae ("Greedy"), 15 shows, all sold out. My two refinements removed the false positives: Spanish pageviews cleared J Balvin, and counting the whole album career cleared Brad Paisley. Two acts with nearly the same profile at booking, opposite outcomes: the case study for the brief.

**Co-headliner edge case.** Using the stronger act's signals, 140 co-headlined shows switch to the other act, mostly as expected (Journey and Mötley Crüe for Def Leppard). One looks wrong at first: the Aubrey & the Three Migos tour uses Migos' signals instead of Drake's, because Migos really did draw more Wikipedia traffic in the year before the cutoff (15,400 vs. 13,100 views a day). The rule worked as designed, but it shows that pageviews measure attention at a point in time, not the size of a fan base. I'm keeping the rule and noting the limitation.

**2019 Pollstar result.** The OCR I asked for worked after one fix: each show's first line is printed on a gray band that the OCR tool skipped until the scans were converted to pure black and white. 184 of the 200 shows were read; 15 were dropped because their numbers didn't add up (tickets should equal capacity x shows x percent sold), which caught misreads like "17%" for "77%". The pre-COVID check matches the later years: 104 engagements, 93% within 1% of Wikipedia on tickets sold, against 95 to 97% for 2022 and 2023. Across all three years, 476 engagements match, 95% within 1%.

**Production labels (following my rubric).** Claude labeled all 240 tours from the article evidence. Two interpretations of my rubric, both open to my review: video screens and lighting alone count as Standard, since nearly every arena tour has them; and Themed requires a concept (acts, eras or a story) plus production beyond Standard. Result: 11 Standard, 42 Enhanced, 38 Themed, and 149 whose articles don't describe the show. That exposes a selection bias for the limitations section: Wikipedia describes a show's production mostly when it's notable, so plain shows are underrepresented, and what can be measured is documented production level. A random 40-tour sample is set aside for me to label blind (without seeing Claude's labels), so the agreement rate is a fair check.

**Notebook.** The exploration I asked to keep is in `notebooks/01_signal_exploration.ipynb`: eight checks, each with a short reading of the result, ending with the takeaways that carry into Phase 2. It reads from the pipeline's database, so it reruns from scratch, and outputs are cleared before committing.

## 25. Closing Phase 1
**My call.** Before pushing, I asked for Phase 1, the task list and all the housekeeping rules I'd set to be confirmed complete, not assumed.

**Outcome.** The full pipeline was rebuilt from scratch in order (database, features, one-hit flags, views, production labels) and reproduced every number; all 263 tests pass. A sweep of the repo against my rules found two leftover em dashes, one in a test's simulated OCR noise and one in quoted Wikipedia text, both removed. No commit uses a Co-Authored-By line or a conventional-commit prefix, and the notebook's outputs are cleared. The README limitations section is drafted with every number checked against the data, for me to rewrite in my own voice. Two items are mine to finish: rewriting that section, and blind-labeling the 40-tour production sample so the agreement with Claude's labels can be measured.

**Source list (my call).** The list of every Wikipedia article used, with the exact revision read, was being written to the ignored data folder, so it wasn't visible on GitHub even though the README promises it. I had it moved to `docs/wikipedia_sources.csv`, where it's published with the code and linked from the README.

## 26. Phase 2 evaluation design
**Context.** The model sample has 5,806 shows but only 240 tours from 162 artists, and shows on one tour are close to copies of each other. A random split would let the model see a tour's other nights during training, so the evaluation had to be designed before any model was fit.

- **Split (my pick):** the AI recommended a time split by tour (train on tours starting 2017-18, test on 2019, with 2022-25 as a second holdout). I chose to add an artist-grouped check on top, so the results also show whether the model works on artists it has never seen.
- **Baselines (accepted):** a signal only counts as working if it improves on a controls-only model. A harder second test adds the artist's previous-tour sellout rate, which answers whether a buyer could just look at last tour's numbers instead.
- **Ticket price (accepted, refining my entry 23 rule):** same-show price is revenue divided by tickets sold, so sellouts push it up mechanically. The main model uses the artist's previous-tour price, which is known at booking. My with/without test still runs on same-show price, as a demonstration of how much it leaks.
- **Explain vs. predict (accepted):** both. Coefficients come from statsmodels with standard errors clustered by artist, so they are honest about the small number of artists; out-of-sample scoring uses scikit-learn.

## 27. Model inputs
I went through a second batch of choices about what goes into the models. I accepted the AI's recommendation on each after comparing the options:

- **Controls:** log capacity per show, venue size, genre group and country in the main model. Production level and set length are tested as a separate block, since 149 of 240 tours have no production description and that gap mostly reflects how much attention a tour got on Wikipedia.
- **Year trend:** the sellout rate rises from 51% in 2017 to 83% in 2019, and a year dummy can't predict a year it never saw. The predictive model has no year term and is judged mainly on ranking (AUC), with the calibration gap reported. The explanatory model is fit on all years with year dummies.
- **Not charting:** a charted yes/no flag plus log(1 + chart points). Best rank is dropped because points already capture height and duration.
- **Tours that straddle COVID:** 9 tours started before the shutdown and kept going after it (180 shows). Their post-shutdown shows are left out of training and testing, so the pre-COVID splits stay pre-COVID, but they still count in the COVID comparison.
- **Number of nights:** left out of the main model, because buyers often add nights after the first one sells out, which is after the six-month cutoff. A robustness run adds it to measure how much it inflates accuracy, the same idea as my price test.
- **Previous tour:** the artist's most recent other tour, worldwide, using only shows that ended before the cutoff. 125 of 240 tours have one.
- **Inflation:** previous-tour prices are converted to constant dollars with the BLS CPI-U annual average.

## 28. Catching a flaw in the previous-tour rule
**Caught.** The AI built the previous-tour history, and its summary mentioned in passing that some previous tours were tiny. It treated that as a threshold question. I asked how Future's previous tour could be a single show with a 0% sellout rate, since it sounded like a cancellation. That question is what exposed the bug: the AI's rule was wrong, and its tests hadn't covered the cases that broke it.

**Outcome.** It wasn't a cancellation. Future's Hndrxx Tour page lists only one box score row, a show that was 96% full but counts as a miss under the exactly-100% rule. Tracing it exposed a flaw in the AI's "most recent tour" rule: it also picked tours that had barely started at the cutoff (Bad Bunny's El Último Tour del Mundo, one show in, instead of his 36-show X 100pre Tour) and a small side tour running alongside a main one (Ed Sheeran's − Tour, one show at 0%, instead of the 84-show ÷ Tour). I chose the AI's recommended fix: the previous tour must have at least 5 finished shows, otherwise the rule falls back to the one before it. I also accepted adding the previous tour's average fill rate next to its sellout rate, which mattered right away: Future's Nobody Safe Tour sold out 11% of its shows but was 94% full, and Ed Sheeran's ÷ Tour sold out 73% but was 98% full. 119 of 240 tours now have a previous tour.

**My call (tours still in progress).** Under the new rule, a tour still running at the cutoff can count once it has 5 finished shows (Bad Bunny's later World's Hottest dates use El Último Tour del Mundo). I chose to keep it as is.

## 29. How the sellout model is built up
I accepted the AI's recommendation on each of these after comparing the options:

- **Career chart history** is its own block, separate from the last year's chart activity, so the results can tell buzz (charting now) from legacy (having a catalog).
- **Both orders:** charts and pageviews overlap, and whichever enters the model first gets credit for what they share. Running charts-first and pageviews-first shows what each adds that the other doesn't.
- **Plain logistic regression,** no penalty, so the coefficients and the test scores describe the same model.

**Outcome.** One fix came up during the build: the explanatory model failed to converge. The AI traced it to 2016 (1 show) and 2026 (11 shows, one artist), where every show sold out, which makes the best-fitting year coefficient infinitely large. Those years were folded into 2017 and 2025, and the code now stops with an error if the fit doesn't converge instead of reporting unreliable numbers.

## 30. Room size compared with the artist's last tour
**My call.** The first sellout models showed that chart and pageview signals barely improve on the controls (test AUC 0.52 to 0.62), even though differences between tours could in principle explain far more (about 0.91 if you cheat and use each tour's own sellout rate). Of the options the AI laid out, I chose to test whether the room relative to the artist's previous tour is the missing piece, building on my one-hit finding that breakout acts were booked into rooms 1.69 times their usual size.

**What the data showed first.** The raw pattern runs the opposite way from overbooking: shows in rooms 2.5 times or more the previous tour's size sold out the most (86.5%). Buyers upsize acts they have watched grow, so the raw ratio mostly measures the buyer's confidence. The AI recommended measuring upsizing together with how full the previous tour was, and I accepted that, plus using the previous tour's median room so a few stadium dates don't make an arena act look bigger.

**Outcome.** The room terms don't improve predictions on held-out tours. They do explain a clear pattern across all years: doubling the room raises the odds of a sellout by about 40% after a tour that was 100% full, and lowers them by about 27% after a tour that was 90% full, with the break-even near 95% full. Shows moved into a room twice as big after a tour that was under 95% full sold out 63% of the time, against 89% when the last tour was nearly full (Halsey's Love and Power Tour: last tour 83% full, 0 of 16 sold out). The pattern rests on only 10 tours, so it needs a robustness check before it goes in the brief.

## 31. Stress-testing the room finding before using it
**My call.** The AI offered three next steps: check the room finding now, move on to ticket price, or start building the right-sizing score on the 95% break-even. Because the finding rested on about 10 tours, I chose to check it first, by refitting the model once per tour with that tour left out.

**Outcome.** The pattern holds. Of 117 refits, 115 ran; the other two failed for an unrelated reason (removing J. Cole's Off-Season Tour or Ricky Martin's Movimiento Tour leaves a year in which every remaining show sold out, so that year can't be fit), and they are reported rather than worked around. In all 115, upsizing still helps after a full tour and hurts after one that wasn't full. 114 stay statistically significant. The one exception is dropping Halsey's Love and Power Tour, the clearest case, which weakens it to p = 0.063 without changing the direction. The break-even stays between 93.5% and 98.2% full whichever tour is removed. So no single tour creates the pattern, but Halsey's tour is its strongest example and the brief should say so.

## 32. The rest of Phase 2 in one batch
**My call (pace).** I asked to finish Phase 2 in one push and then review the whole analysis for anything adding noise. The remaining design questions came as one batch; I accepted the AI's recommendation on each after comparing the options:

- **Part 2 (fill rate when not sold out):** a fractional logit, which models the rate directly so predictions stay between 0 and 100%, scored by mean absolute error.
- **COVID comparison:** one model on all shows where each signal gets a post-COVID interaction term, so a changed effect is tested directly instead of eyeballed across two models.
- **Right-sizing score:** built from the room finding that survived the leave-one-out check (upsizing after a tour that wasn't nearly full), rather than from expected vs. actual fill or a model-recommended room size, which would lean on the confounded capacity effect.
- **Spotify:** an extra block on top of charts and pageviews for shows inside the 2017-21 Spotify window.

## 33. Correcting the score for expected fill
**AI correction.** The AI planned to score the combined expected fill rate by mean absolute error. Checking the baselines showed that was wrong for this outcome: predicting 100% full for every show scored 2.4 to 2.9 points, far better than any model (6.5 to 7.3), while saying nothing. Absolute error rewards predicting the median, and the median show sold out. Expected fill is an average, and squared error (RMSE) rewards getting averages right; on RMSE, "always 100%" is no better than the mean. The combined model is now scored by RMSE, with MAE kept in the table and "always 100%" shown as a baseline. Part 2 keeps MAE as I chose, since shows that didn't sell out don't bunch at a single value.

**Outcome.** Neither the two-part model nor the Tobit check beats predicting the average for every show, and the two agree, so the result doesn't depend on that modeling choice.

## 34. Phase 2 results
**Outcome.** The rest of Phase 2 was built in the order I approved, each step with tests and its own commit, and one command (`python -m concert_demand.models`) now rebuilds the whole stage and reproduces every table.

- **Price and nights (my leakage tests):** on top of the previous tour's price, the same show's price adds about +0.036 AUC on 2022-25, and the number of nights about +0.034, both with intervals above zero. Both are set after sales start, which confirms my calls to keep them out of the main model.
- **Part 2 and the combined model:** nothing beats predicting the average fill rate. The two-part model and the Tobit check agree.
- **Charts vs. pageviews:** neither adds anything the other doesn't, and Spotify adds nothing on top.
- **COVID:** no signal's effect changed after the shutdown.
- **Robustness:** the results hold under my 97% sellout rule, English-only pageviews and the worldwide sample. Signals add nothing for artists the model hasn't seen. My 26-week window tied the 52-week one on the training years, so under my rule 52 weeks stays.
- **Right-sizing:** the score follows my "upsizing risk" definition. Its first version also flagged downsizing after a sold-out tour as risky (Madonna moving from stadiums to theaters, 7 of 7 sold out), because the model fits one line through both directions. Since my definition is about growth, only growth is scored now. Shows upsized against the 95% rule sold out 73% of the time, against 80% for the rest; Halsey and Niall Horan top the list.

The overall answer to the project question: chart and pageview signals measured at booking barely beat knowing the room, genre and country. What does carry information is the artist's catalog and how their last tour sold, especially for deciding whether to move up a room size. Next is my review of which parts of the analysis add noise.

## 35. Applying my window rule
**My call.** In Phase 1 I set the rule that 26-week signal windows would be kept only if they beat the 52-week window plus 13-week momentum on the training years. They tied (AUC 0.640 vs. 0.637 when fitting on 2017 tours and scoring 2018 tours). I agreed that a tie doesn't meet the rule, so the models keep 52 weeks.

## 36. Noise review
**My call.** After Phase 2 I asked for a review of which parts of the analysis add noise instead of signal. Every check was run on the training tours only (cross-validation grouped by artist), so cutting features couldn't be tuned to the test sets.

**Two problems found in the AI's work first.**
- **The production block was never built.** I chose production level and set length as a separate add-on block when planning Phase 2, and it was skipped. In the review it turned out to carry the most information of any block (+0.051 AUC in training CV, better in 78% of folds).
- **A biased cross-validation score.** The first diagnostics pooled out-of-fold predictions into one AUC, which came out below 0.5 for every model. Because artists differ so much in how often they sell out, pooling penalizes the model for those differences; scoring each fold separately fixed it (room size alone: 0.43 pooled, 0.54 per fold). The artist-grouped robustness check already committed used the pooled version and gets the same fix.

**Decisions.**
- **Production (accepted):** run as the add-on block I originally chose, with a check on whether the gain comes from real production levels or only from whether Wikipedia describes the show at all, which would make it a measure of attention.
- **Charts (accepted):** drop the yes/no "charted" flags. They were 95% correlated with chart points, which made the coefficients flip sign, and dropping them helped in 74% of folds.
- **Genre (accepted):** out of the predictive models, where it added noise, but kept in the explanatory models, where it controls for real genre differences.
- **Room size (accepted):** separate terms for upsizing and downsizing, which fit clearly better. Upsizing is the real effect, with a break-even of about 92% full; downsizing shows none. This replaces the workaround in the right-sizing score.
- **Career (overrode):** the AI recommended keeping only Hot 100 career entries, since Billboard 200 career added nothing. I kept both, so album careers stay in for my "albums mean fans" idea.
- **Thin tests (accepted):** results on fewer than 25 tours stay in the tables, flagged as thin, and out of headline claims.
- **Spotify and Part 2 (accepted):** both kept and reported as clean negative results rather than cut or tuned.
- **Momentum:** dropping it made predictions worse (30% of folds better), so it stays.

## 37. Keeping the noise review after seeing the test results
**What happened.** Rerun with the noise-review changes, the full model scored slightly lower on the held-out tours (0.556 to 0.522 on 2019, 0.624 to 0.600 on 2022-25), well inside the noise. The production block, which looked best in training cross-validation (+0.051), lost accuracy on both test sets (about -0.03), and "described or not" alone did no better, so it doesn't generalize. The room finding got stronger: with separate terms for growing and shrinking, doubling the room after a full tour multiplies the odds of a sellout by 2.4, the break-even is 92.9% full (91.1% to 94.7% when any one tour is left out), and the right-sizing flag now separates 193 upsized shows that sold out 67% of the time from the rest at 80%.

**My call (accepted).** The AI recommended keeping the changes and reporting both versions; I agreed. Reverting because the test scores dipped would mean picking the model by its test score, and then the test sets would no longer be a fair check. The before and after numbers are both in the notebook, so the comparison is public.


## 38. What the dashboard is for
**My call.** Starting Phase 3, I set the dashboard's purpose: show which metrics lead to a sellout rather than overbooking an artist into too big a room, and keep a brief Billboard run from making a buyer overconfident about where an act can play. The main user is a talent buyer checking a specific artist before booking. I chose a two-page layout from three mockups: a page that teaches the rule, and a drill-through page with a scorecard on top and the artist's tour timeline below. No sellout probabilities are shown, since the model barely beats chance on later years.

## 39. Artists with no previous tour
**My call.** About half the tours have no qualifying previous tour, so the scorecard's main tiles would be blank. I chose to show a "no previous tour" note and use career chart history instead. The AI pointed out that recent chart buzz is the thing the dashboard warns against, while career history was the one chart signal with some support, so I kept career history and a "weak signal" caption on it.

## 40. Data connection and a corrected claim
**My call (accepted).** I chose CSV exports over a SQLite ODBC driver, so anyone who clones the repo can open the template without installing a driver. A review of the design then found an error in the AI's proposal: it had said sellout rate by chart decile would look flat, but the raw view rises from 61% to 85%, because bigger acts and later years both chart more and sell out more. The flat result only holds out of sample after controls. I accepted the recommendations that followed: the chart panel shows the tested comparison (AUC with and without charts), a tour counts as flagged when at least half its shows were upsized past the rule (13 tours, not 18, so mostly-downsized tours like Noel Gallagher's drop out), the drill-through page works per tour, and the small aggregated dashboard CSVs are committed with Billboard data as totals only.
