# Project 4.1 Report

## Repository

- The Pirate's Plunderer

#### Link to the repository

- https://github.com/Vinnyfio04/live-market-trading-app

## Recent Commit

- `eec27a4d37a1418aa0ef96aa585b1e86aad1bc63` — Extend market history and add Shift-wheel chart panning `[skip ci]`

## What was completed

- A working version with a more accurate UI was created.
- As of right now, the user can view live candles for one minute, five minute, fifteen minute, one hour, and one day intervals.
- The data path is set up to update live and hold past data for data replay.
- The program reads the current stock information and stores it in the database cache. It then uses the backend files to create the candles and populate the view.
- A snapshot function is also implemented where the AI assistant will suggest what action to take based on the current context of the market snapshot. It uses OpenAI's GPT-6 Luna, which analyzes a snapshot given by the frontend and decides the best course of action based on how the chart looks at that given moment.
- There is also a live chat system in place to chat with the AI assistant about what to do next.
- A paper trading system was created so the user can practice trading properly without using any real money.

## Remaining Limitations

- The indicators still need more work and do not do as much as I want right now. SMA is present in the current project, but EMA has not been implemented yet, and the indicator experience still needs to be expanded.
- Further UI changes are also needed to make sure everything is as easy and digestible as needed.
- This submission mainly focuses on getting the core features set up before personalizing it to my vision.
- The full live source path still needs to be verified during a regular market session.
- The live chat system is in place, but the full microphone and speaker check still needs to be completed.
- The chart analyses is still being implemented, as of now it can make a decision but some of the checks are not passing. Along with that, the UI for the decision is not super readable. 

## Key Design Decisions

- I want to make the UI as readable as possible so users who are not familiar with trading can have an easier time getting familiar with trading.
- I may include customizable features later to make the program more complicated but also more useful.
- I chose to store the stock information in the database cache and use the backend files to create the candles before populating the view.
- For the model, I chose GPT-6 Luna because the pricing is strangely low. I need higher computational thinking to analyze the photo very carefully and consider every element of the decision before giving it.
- The AI assistant is used for suggestions and decision support. It does not automatically make a live trade for the user.
- The paper trading needs further refinement to make it more accurate to how TradingView has it. My goal is to make it easier to use and more efficient for the user.
- When loading the data, I implemented a pre-loading system where it loads a set number of candles that the user would need in that moment (most recent ones) and waits for the rest to load after displaying the pre-loaded information.

## Verification Results

- The offline browser SmokeTest passed using the real frontend, backend, browser, and an isolated SQLite database.
- Stored market history was loaded through the backend and displayed in the chart. Database values were compared with the values shown in the program.
- Candle updates, data replay, database persistence, unavailable-feed behavior, and backend reconnect behavior passed their recorded checks using labeled test data.
- The snapshot feature passed focused backend and browser checks. One real GPT-6 Luna request also completed successfully, and the result matched the saved database record. The market candles used for that model check were labeled synthetic data.
- Actual Yahoo history has been matched through the database, backend history response, and visible chart. A new regular-session Yahoo message has not yet been matched through the entire live WebSocket path.
- Live voice chat has not been tested properly due to 

## Video

- 
