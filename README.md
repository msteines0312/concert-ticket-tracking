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
- Pollstar. "2019 Year End Top 200 Concert Grosses." *Pollstar*, December 2019. [PDF](https://www.pollstar.com/Chart/2019/12/Top200ConcertGrosses_793.pdf)
- Billboard. "Billboard Hot 100" and "Billboard 200" weekly charts. Compiled by utdata, [rwd-billboard-data](https://github.com/utdata/rwd-billboard-data).
- Wikimedia Foundation. Pageviews API (Analytics Query Service).

Data that hasn't been used yet will be added here when it is. That includes Pollstar files that aren't confirmed, and any later sources such as MusicBrainz.

## Status
See [tasks/todo.md](tasks/todo.md) for progress. Full README (tech stack, how to run, key features, what I learned) will be written once the pipeline is complete.
