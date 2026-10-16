# Authored explanatory motion

Long-form scenes can select `visual_type: authored_diagram`. This is an original
schematic, never a stock search result, brain scan, recorded event or data plot.
`src/explanatory_motion.py` defines the bounded execution contract and prompt rules.
The contract carries a title, 2-4 labeled nodes, up to four labeled directed arrows,
and 2-4 ordered highlight states with captions. Unsupported indices, duplicate
nodes, empty or repeated states, unsafe text and overflowing labels fail closed.

`visuals.get_visual(..., scene=scene)` validates and saves the complete scene as
`.diagram.json` and returns `authored-motion` / `original-schematic`. The long editor
renders that exact spec using measured voice duration, 1920x1080 at 24fps, with
12 unique motion frames/sec. State highlights and a dot moving along the selected
arrow make the explanation visible. The bottom 170px stays clear for subtitles.
No diagram failure can become stock or gradient. Stock queries remain literal;
random aesthetic query modifiers no longer change long-form scene searches.
Legacy Shorts callers keep their existing behavior.

Reviewers see executed diagrams and their source/illustration limits, not unused
stock alternatives. Structural validation alone never passes a scene. Independent
review still checks uniqueness and feasibility at the existing >=7 threshold.
Mixed plans must pass both lanes independently: a good diagram cannot average
away an infeasible stock shot. Stock feasibility uses the original prompt/threshold.
All scenes are included, including those beyond the former 30-keyword cutoff.

Scene breakdown and review-directed repair are chapter-bounded. Repair is atomic (6500 output tokens per
chapter). Repair retains the outline, full source context, review findings, scene count
and identity. Invalid units stop the repair; partial repairs never replace a plan.
The original and each response remain in private diagnostics. All authoring paths,
including cached/fallback/storyboard paths, require Gemini final review before
independent gates and render. Gemini cannot silently strip or relabel an already
reviewed schematic. Required final-review failure remains a failure, with no paid
quota fallback.

Tests: `python -m unittest discover -s tests`. The motion tests exercise the real
editor normalization path and FFmpeg duration, not just source-string wiring.
