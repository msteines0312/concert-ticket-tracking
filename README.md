# Do Billboard Charts Predict Concert Ticket Sales?

Work in progress. This project tests whether Billboard chart success predicts how well an artist actually sells tickets, and compares it against Wikipedia pageviews as an alternative popularity signal. The goal is a practical answer for talent buyers: which signal should you trust when choosing a venue size, and which artists are booked into rooms too big or too small for their demand?

## Data Sources
- **Wikipedia tour articles**: per-show attendance, capacity, and revenue for major tours (CC BY-SA)
- **Pollstar year-end Top 300 Concert Grosses**: per-show validation data for 2019, 2022, 2023 (copyrighted, used for analysis only and never committed)
- **Billboard Hot 100 and Billboard 200 history**: [utdata/rwd-billboard-data](https://github.com/utdata/rwd-billboard-data)
- **Wikimedia Pageviews API**: daily artist page views since July 2015

No data files are committed. Every dataset is rebuilt by the ingest scripts.

## Status
See [tasks/todo.md](tasks/todo.md) for progress. Full README (tech stack, how to run, key features, what I learned) will be written once the pipeline is complete.
