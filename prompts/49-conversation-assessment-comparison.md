# Compare chart assessments in a conversation

Extend the chart assistant to compare a new assessment with an earlier assessment of the same ticker and data mode in the same conversation. Keep the earlier tool result and chart time available to the agent; explicitly report when none exists. Add New chat to start a separate conversation.

Test through the running UI, using one conversation:

1. "What does WAIT mean in this app?"
2. "Run the decision on the chart I'm looking at. What do you recommend?"
3. After displaying a later snapshot: "Run a new decision for this chart and compare it with the earlier assessment."

Verify tool selection, returned choices/probabilities, both chart times in comparison, and updated chart result. Save screenshots and record observations/mismatches. Follow CHECK, TAKE ACTION, VERIFY if another dependency is needed.
