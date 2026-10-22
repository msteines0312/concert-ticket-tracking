# Do Billboard Charts Predict Concert Ticket Sales?

A data pipeline and set of models that test whether Billboard chart success, measured when a show is booked, predicts whether it sells out. It is built for talent buyers deciding what size room to put an artist in. The short answer is no: recent chart buzz barely improves the forecast, while how full the artist's last tour was does say something about whether moving them up a room size will work.

## Results
- **Chart buzz doesn't forecast sellouts.** On tours the models never saw, adding chart signals to a baseline of room size and market left test AUC at 0.587 on 2022-25 tours. On 2019 tours it went from 0.450 to 0.538, with a wide interval on the gain (-0.10 to +0.27). Raw sellout rates do rise with chart activity, but that pattern comes from bigger acts and later years, not from the charts themselves.
- **The last tour matters when upsizing.** Doubling the room after a 100%-full tour multiplies the odds of a sellout by about 2.4. After a tour that was less than 92.9% full, upsizing lowers them (interaction p = 0.001). The result held when any single tour was left out and under a 97% sellout definition.
- **A right-sizing flag a buyer can use.** 13 tours had at least half their shows upsized against that rule. Those 211 shows sold out 70.1% of the time, against 79.3% for other shows with a previous tour.
- **Fill rate is hard to predict.** When a show doesn't sell out, no model beat simply predicting the training average.
- **Ticket price leaks the outcome.** Same-show prices improve the model only because dynamic pricing reacts to demand, so the main models use the previous tour's price instead.

## Tech Stack
- Python 3.13: pandas, NumPy, SciPy, scikit-learn, statsmodels (logistic regression with artist-clustered standard errors)
- SQLite with SQL views (CTEs, window functions) as the analysis layer
- mwparserfromhell, lxml and the MediaWiki API for Wikipedia tour tables; pypdf and Tesseract OCR for the Pollstar validation PDFs
- pytest (323 tests) and Jupyter notebooks for the walkthroughs
- Power BI for the dashboard (in progress)

## How to Run
The raw data is not committed, so a full rebuild downloads everything. That takes a few hours, mostly the rate-limited Wikipedia and pageview downloads. Every download is cached, so later runs take minutes.

1. Clone the repo and create an environment (Python 3.11 or newer):
   ```bash
   git clone https://github.com/msteines0312/concert-ticket-tracking.git
   cd concert-ticket-tracking
   python -m venv .venv
   .venv\Scripts\activate          # macOS / Linux: source .venv/bin/activate
   pip install -r requirements.txt
   pip install -e .
   ```
2. For the Spotify sub-analysis, put a [Kaggle API token](https://www.kaggle.com/docs/api) in `~/.kaggle/`. Nothing else needs an account.
3. Build the data in this order. Each step reads what the one before it saved.
   ```bash
   python -m concert_demand.ingest.wikipedia_tours --start-year 2015 --end-year 2025
   python -m concert_demand.ingest.billboard_charts
   python -m concert_demand.clean.artist_names
   python -m concert_demand.ingest.spotify_charts
   python -m concert_demand.ingest.pageviews
   python -m concert_demand.clean.genres
   python -m concert_demand.ingest.cpi
   python -m concert_demand.load_db
   python -m concert_demand.clean.production
   python -m concert_demand.features.signals
   python -m concert_demand.features.one_hit
   python -m concert_demand.analysis_views
   ```
4. Fit the models and write the result tables to `reports/tables/` (about 4 minutes):
   ```bash
   python -m concert_demand.models
   ```
5. Export the dashboard tables to `data/dashboard/`:
   ```bash
   python -m concert_demand.dashboard
   ```
6. Run the tests with `pytest`, and open `notebooks/01_signal_exploration.ipynb` and `notebooks/02_models.ipynb` for the walkthroughs.

The Pollstar validation (`python -m concert_demand.ingest.pollstar`) is optional. It downloads the year-end PDFs, and reading the scanned 2019 chart needs [Tesseract](https://github.com/UB-Mannheim/tesseract) installed.

## Key Features
- **Leakage-safe signals.** Every chart and pageview signal is measured as of 6 months before the show, roughly when it would be booked. A test floods everything after that date with fake hype and checks that no feature changes.
- **Evaluation by tour, over time.** Models train on 2017-18 tours and are tested on 2019 and 2022-25 tours, so no tour appears on both sides. Artist-grouped cross-validation is a robustness check.
- **Checked against an independent source.** Wikipedia ticket counts were matched to Pollstar's year-end charts, and 95% of 476 engagements agree within 1%.
- **Two-part demand model.** 68% of shows sell out exactly, so the models predict the chance of a sellout and, separately, how full the room gets when it doesn't. A Tobit model checks the combined result.
- **Real-world parsing.** The Wikipedia parser handles footnotes, leg totals, multi-night runs, European number formats and years hidden in table captions. Each bug found while checking the output has its own test.
- **Decisions on the record.** [docs/ai_collaboration_log.md](docs/ai_collaboration_log.md) logs how the project was directed: what the AI proposed, what I decided, and where I overrode it.

## Project Structure
```
src/concert_demand/
  ingest/        download and parse each source (Wikipedia, Billboard, Spotify, pageviews, CPI, Pollstar)
  clean/         attendance parsing, countries, artist names, genres, production labels
  features/      as-of-booking chart and pageview signals, one-hit flags
  models/        dataset, sellout and fill-rate models, robustness checks, right-sizing score
  dashboard/     exports the tables the Power BI dashboard loads
sql/             database schema and analysis views
notebooks/       signal exploration and model walkthroughs
reports/tables/  model results (CSV)
data/labels/     hand-made production labels (committed)
data/dashboard/  dashboard tables (committed)
docs/            AI collaboration log, Wikipedia source list, design docs
tests/           pytest suite
```

## Data Sources and Licensing
Raw and processed data are not committed. Every dataset is downloaded and rebuilt by the ingest scripts, and each source keeps its own license. The [MIT license](LICENSE) covers only the code. Two small sets of data files are committed:
- `data/labels/`: production-level labels made by hand from Wikipedia articles (CC BY-SA 4.0).
- `data/dashboard/`: the tables the Power BI dashboard loads, so it opens without rebuilding the pipeline. They hold Wikipedia-derived show data (CC BY-SA 4.0), Wikimedia pageview averages (CC0), and Billboard chart activity only as quarterly point totals. No weekly ranks, song titles or Pollstar data.

| Source | What it provides | License / terms | How it's used here |
|---|---|---|---|
| [Wikipedia](https://en.wikipedia.org/) concert tour articles in the "[year] concert tours" categories, 2015 to 2025 | Per-show attendance, capacity, and revenue | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | Main source of ticket sales. Data derived from it is shared under the same license, with a link to every article used |
| [Pollstar](https://www.pollstar.com/) year-end Top Concert Grosses charts (2019, 2022, 2023) | Per-show capacity, % sold, ticket prices, gross | © Pollstar. All rights reserved | Validation only. Raw rows are never committed or published. Only summary comparisons appear in results |
| [Billboard](https://www.billboard.com/charts/) Hot 100 and Billboard 200, via [utdata/rwd-billboard-data](https://github.com/utdata/rwd-billboard-data) | Weekly chart positions | Chart data © Billboard. Archive code MIT | Chart-based popularity signals |
| [Wikimedia Pageviews API](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/) | Daily views of each artist's Wikipedia page since July 2015 | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | Alternative popularity signal |

### Notes on attribution
- **Wikipedia figures are secondhand.** Tour articles take their attendance and revenue numbers from Billboard Boxscore and Pollstar reports, which each article cites. Those outlets are the original source. Wikipedia is how the figures were compiled.
- **Per-article credit.** The pipeline writes a source list, [docs/wikipedia_sources.csv](docs/wikipedia_sources.csv), naming every Wikipedia article used, with its URL and the revision that was read, so any figure can be traced back to its page. Wikipedia's [reuse guidelines](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content) accept a link to each reused page as attribution.
- **Published outputs.** The Power BI dashboard and the written brief carry the same credits. The dashboard is shared as a `.pbit` template plus screenshots, because a `.pbix` file embeds its data. Data loaded into the dashboard comes from Wikipedia and Wikimedia (CC BY-SA and CC0), plus Billboard chart activity summed by quarter. Pollstar data stays out of it.

### Citations
- Wikipedia contributors. "[year] concert tours" category articles. *Wikipedia, The Free Encyclopedia*. Retrieved October 2026. Per-article list: [docs/wikipedia_sources.csv](docs/wikipedia_sources.csv).
- Pollstar. "2023 Year End Top 300 Concert Grosses." *Pollstar*, December 11, 2023. [PDF](https://data.pollstar.com/Chart/2024/01/121123_ye.top300.concert.grosses_digital_1040.pdf)
- Pollstar. "2022 Year End Top 300 Concert Grosses." *Pollstar*, December 2022. [PDF](https://data.pollstar.com/chart/2022/12/121222.top.300.concert.grosses_1027.pdf)
- Pollstar. "2019 Year End Top 200 Concert Grosses." *Pollstar*, December 2019. [PDF](https://data.pollstar.com/Chart/2019/12/Top200ConcertGrosses_793.pdf)
- Billboard. "Billboard Hot 100" and "Billboard 200" weekly charts. Compiled by utdata, [rwd-billboard-data](https://github.com/utdata/rwd-billboard-data).
- Wikimedia Foundation. Pageviews API (Analytics Query Service).

Data that hasn't been used yet will be added here when it is. That includes Pollstar files that aren't confirmed, and any later sources such as MusicBrainz.

## Limitations
**The biggest limitation: the sample favors big tours.** Only tours with a Wikipedia article and reported box office numbers are included, so the data leans toward large, successful acts, and 68% of shows sold out. Smaller acts might not follow the same patterns, so these results may not carry over to a buyer booking club-sized shows.

**Which shows are in the data**
- Coverage thins out after 2019: 261 tours started in 2015-19, 109 in 2022-25.
- The model sample is 5,806 US and Canada shows from December 2016 to April 2026. Earlier shows lack a full year of pageview history before their booking cutoff.
- 18 shows are in Puerto Rico. They count as part of the US market, since Billboard's US charts cover it, but listening there is different (more Latin music), so they carry their own flag.

**How accurate the ticket figures are**
- Wikipedia's numbers are secondhand: editors copy them from Billboard Boxscore and Pollstar. Checked against Pollstar's year-end charts (2019, 2022, 2023), 95% of 476 matched engagements are within 1% on tickets sold.
- That check only covers the top-grossing shows of those years, so it says less about smaller shows.
- Wikipedia tends to round near-sellouts up. 18 shows it lists as sold out were 96-99% sold in Pollstar, against 2 in the other direction. "Sold out" means exactly 100% in the main model, with 97% tested as a robustness check.

**What the popularity signals miss**
- Billboard's Hot 100 has a top-100 cutoff, so widely known songs that never ranked don't count.
- Spotify chart data only covers 2017-2021, so the streaming comparison is a sub-analysis. TikTok's Billboard chart (2023-25) is paywalled, and Apple Music, Tidal and SoundCloud have no public chart history. Billboard already counts streams from all of these, just not separately.
- Wikipedia pageviews measure attention at a moment in time, not the size of a fan base. Example: Migos drew more pageviews than Drake in the year before their joint 2018 tour, so the co-headliner rule uses Migos' numbers.
- Only English and Spanish Wikipedia are counted. Artists whose fans mostly read another language (K-pop in Korean, Brazilian artists in Portuguese) are undercounted.

**COVID**
- Only 5 model-ready US shows took place during the shutdown (March 2020 to August 2021), so the COVID analysis compares before and after, not during.

**Production level and one-hit acts**
- Production level is labeled from what each tour's Wikipedia article says. 149 of 240 articles don't describe the show at all, and the ones that do skew toward notable productions, so plain shows are underrepresented (11 labeled Standard). Labels were made with AI assistance from a rubric I wrote. A blind hand-check of 40 tours is still to come.
- Only two acts meet the one-hit definition (Kim Petras and Tate McRae), so that analysis is a case study, not a model feature.

**What the results can and can't say**
- This is observational data. Results show which signals line up with demand, not what causes it.
- Average ticket price is the price after dynamic pricing reacted to demand, so it partly reflects the outcome being predicted. It's only used in the model behind a test that checks for exactly that.

## What I Learned
The biggest lesson was judging which features actually add signal and which only add noise, and testing that on the training data instead of keeping whatever scored best on the test set. I also learned to use AI as a tool rather than letting it run with everything: I made the design calls, and the [collaboration log](docs/ai_collaboration_log.md) records where I pushed back or changed course.

## Status
Phase 1 (data pipeline) and Phase 2 (models) are complete. Phase 3 is in progress: a Power BI dashboard for talent buyers and a written brief.
