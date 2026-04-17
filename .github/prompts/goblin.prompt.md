---
description: "Show the Goblin repo startup banner, summarize the remaining S1+ plan, and recommend the next governed action"
name: "goblin"
argument-hint: "Optional focus, e.g. AF-CAND-0733 or Bundle A"
agent: "agent"
model: "GPT-5 (copilot)"
---
You are bootstrapping the Goblin workspace for an operator.

When appropriate, align your summary with the repo CLI command `goblin-startup`, which is the model-agnostic Goblin bootstrap surface.

Start your response with this ASCII goblin banner:

```text
   _____       _     _ _       
  / ____|     | |   | (_)      
 | |  __  ___ | |__ | |_ _ __  
 | | |_ |/ _ \| '_ \| | | '_ \ 
 | |__| | (_) | |_) | | | | | |
  \_____|\___/|_.__/|_|_|_| |_|
```

Then summarize the current Goblin state using these files:

- [Goblin/STATUS.md](../../Goblin/STATUS.md)
- [Goblin/S1_PLUS_PLAN.md](../../Goblin/S1_PLUS_PLAN.md)
- [Goblin/IMPLEMENTATION_TRACKER.md](../../Goblin/IMPLEMENTATION_TRACKER.md)
- [Goblin/MATURITY.md](../../Goblin/MATURITY.md)

Required output shape:

1. One short paragraph stating where Goblin stands now.
2. A compact section called `Remaining Plan` listing the current S1+ phase sequence.
3. A compact section called `Recommended Next` with the single best next governed action.
4. If the user supplied a focus argument, tailor the recommendation to that focus.

Behavior rules:

- Treat Goblin platform phases P00-P15 and takeover stages T1-T4 as complete unless the referenced docs say otherwise.
- Focus on the post-takeover S1+ plan rather than rehashing the historical build roadmap.
- Prefer the smallest actionable recommendation that preserves Goblin phase discipline.
- If AF-CAND-0733 is the active focus, recommend the next Bundle A action unless the docs show it is already complete.