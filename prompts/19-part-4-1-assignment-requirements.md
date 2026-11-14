# Part 4.1 assignment requirements

Student request received November 14, 2026:

> Here are some requirements for the current state of the project. Store this in `docs/assignment_instructions.md` and use it to compare the current state of the project to where it should be:
>
> **Outcome:** a working client-server dashboard with live-streaming market data and persistent records.
>
> - **Live visualization.** Connect to Yahoo Finance and use a charting library to display updating candlesticks and corresponding volume. Use WebSockets for real-time communication. Make the data source, age, and feed status visible.
> - **Persistence and replay.** Store market observations in SQLite so that they can be retrieved and replayed. Preserve observation identity, source and receipt times, revisions, and whether a candle is complete. Explain and test how duplicate, revised, and out-of-order observations are handled.
> - **Working evidence.** Demonstrate the path from the live source through the backend to the chart and database, including an unavailable-feed condition. Maintain the README, agent instructions, and design notes describing the data flow and SQLite schema. Document database initialization and startup without exposing credentials.
>
> **CSV loading is ungraded in-class practice.** The Part 4.1 deliverable must demonstrate live streaming. Recorded observations support development and replay when the market is closed.
