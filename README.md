# Do Billboard Charts Predict Concert Ticket Sales?

Work in progress. This project tests whether Billboard chart success predicts how well an artist actually sells tickets, and compares it against Wikipedia pageviews as an alternative popularity signal. The goal is a practical answer for talent buyers: which signal should you trust when choosing a venue size, and which artists are booked into rooms too big or too small for their demand?

## Data Sources and Licensing
No data files are committed to this repo. Every dataset is downloaded and rebuilt by the ingest scripts, and each source keeps its own license. The MIT license, once added, will cover only the code.

| Source | What it provides | License / terms | How it's used here |
|---|---|---|---|
| [Wikipedia](https://en.wikipedia.org/) concert tour articles in the "[year] concert tours" categories, 2015 to 2025 | Per-show attendance, capacity, and revenue | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | Main source of ticket sales. Data derived from it is shared under the same license, with a link to every article used |
| [Pollstar](https://www.pollstar.com/) year-end Top Concert Grosses charts (2019, 2022, 2023) | Per-show capacity, % sold, ticket prices, gross | © Pollstar. All rights reserved | Validation only. Raw rows are never committed or published. Only summary comparisons appear in results |
| [Billboard](https://www.billboard.com/charts/) Hot 100 and Billboard 200, via [utdata/rwd-billboard-data](https://github.com/utdata/rwd-billboard-data) | Weekly chart positions | Chart data © Billboard. Archive code MIT | Chart-based popularity signals |
| [Wikimedia Pageviews API](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/) | Daily views of each artist's Wikipedia page since July 2015 | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | Alternative popularity signal |

### Notes on attribution
- **Wikipedia figures are secondhand.** Tour articles take their attendance and revenue numbers from Billboard Boxscore and Pollstar reports, which each article cites. Those outlets are the original source. Wikipedia is how the figures were compiled.
- **Per-article credit.** The pipeline writes a source list naming every Wikipedia article used, with its URL and the revision that was read, so any figure can be traced back to its page. Wikipedia's [reuse guidelines](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content) accept a link to each reused page as attribution.
- **Published outputs.** The Power BI dashboard and the written brief carry the same credits. The dashboard is shared as a `.pbit` template plus screenshots, because a `.pbix` file embeds its data. Data loaded into the dashboard comes only from Wikipedia and Wikimedia (CC BY-SA and CC0). Pollstar data stays out of it.

### Citations
- Wikipedia contributors. "[year] concert tours" category articles. *Wikipedia, The Free Encyclopedia*. Retrieved October 2026. Per-article list: see the source list described above.
- Pollstar. "2023 Year End Top 300 Concert Grosses." *Pollstar*, December 11, 2023. [PDF](https://data.pollstar.com/Chart/2024/01/121123_ye.top300.concert.grosses_digital_1040.pdf)
- Pollstar. "2022 Year End Top 300 Concert Grosses." *Pollstar*, December 2022. [PDF](https://data.pollstar.com/chart/2022/12/121222.top.300.concert.grosses_1027.pdf)
- Pollstar. "2019 Year End Top 200 Concert Grosses." *Pollstar*, December 2019. [PDF](https://data.pollstar.com/Chart/2019/12/Top200ConcertGrosses_793.pdf)
- Billboard. "Billboard Hot 100" and "Billboard 200" weekly charts. Compiled by utdata, [rwd-billboard-data](https://github.com/utdata/rwd-billboard-data).
- Wikimedia Foundation. Pageviews API (Analytics Query Service).

Data that hasn't been used yet will be added here when it is. That includes Pollstar files that aren't confirmed, and any later sources such as MusicBrainz.

## Limitations
<!-- DRAFT for Matt to rewrite in his own voice. Numbers are current as of October 2026. -->

**Which shows are in the data**
- Only tours with a Wikipedia article and reported box office are included, which tilts the sample toward big, successful tours. Smaller acts and quiet tours are mostly missing.
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
- Production level is labeled from what each tour's Wikipedia article says. 149 of 240 articles don't describe the show at all, and the ones that do skew toward notable productions, so plain shows are underrepresented (11 labeled Standard). Labels were made with AI assistance and spot-checked by hand against the same evidence.
- Only two acts meet the one-hit definition (Kim Petras and Tate McRae), so that analysis is a case study, not a model feature.

**What the results can and can't say**
- This is observational data. Results show which signals line up with demand, not what causes it.
- Average ticket price is the price after dynamic pricing reacted to demand, so it partly reflects the outcome being predicted. It's only used in the model behind a test that checks for exactly that.

## Status
See [tasks/todo.md](tasks/todo.md) for progress. Full README (tech stack, how to run, key features, what I learned) will be written once the pipeline is complete.
