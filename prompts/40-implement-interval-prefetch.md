# Implement interval prefetch

Implement your approach if it reflects project requirements. Read README, AGENTS, and other appropriate docs to get the best idea.

Accepted approach from prompt 39: return SQLite history immediately; initially load about 300–500 bars with independent indicator warm-up; prefetch bounded recent windows after the first chart appears; reuse the chart and refresh caches from committed updates; retain older paging, source/completion metadata and replay isolation. Preserve existing work and use focused, bounded checks rather than unrelated full/scale regressions.
