# Module 1 homework help

Read the repository's [shared instructions](../../AGENTS.md). These instructions apply when helping with HW1, HW2, or HW3, including implementation in `agent/`, `server/`, `observability/`, or `scenarios/`.

## HW1: choose how to help

Read [Homework 1](hw1.md) and inspect existing work before starting. Use a help style the student has already requested or chosen. An explicit request for the tutorial starts it directly; a specific debugging request starts with that problem. Repository maintenance does not need this interview.

If the student asks for general HW1 help without choosing a style, ask one question before implementation: "How would you like to work through Homework 1?"

1. **Instructor-prepared tutorial (recommended if you want explanations):** Follow the course instructors' walkthrough. The agent handles the technical work and pauses for your predictions and observations.
2. **Direct implementation help:** The agent works through the requested task with brief updates, asking when it needs your input.
3. **Help with a blocker:** Focus on the step or error that is holding you up.

Use a native choice picker when available, or present the numbered choices. Accept a free-text preference and wait for the answer. If the student chooses blocker help without describing the problem, ask which step or error they need help with. Skip questions already answered in the conversation or progress note, and let the student change style later. Job title or Python experience alone does not determine the style.

For the guided choice, read [the HW1 tutorial](hw1-tutorial.md) and follow its checkpoints. For direct help or a blocker, use the handout and relevant code without requiring tutorial checkpoints. The handout's student assessments and deliverables still apply in every style.

## HW2

Read [Homework 2](hw2.md) and work from its requirements. The HW1 tutorial does not cover HW2. The handout opens with a walkthrough prompt for students who want an interactive tutorial; when the student pastes it, follow it: one step at a time, a plain language proposal before each step, nothing run or changed until the student says to go ahead, understanding confirmed with few questions, and a diagram where one helps. If a missing HW1 prerequisite blocks HW2, explain the specific dependency and help with it; offer the full HW1 tutorial only when the student wants that walkthrough.

## HW3

Read [Homework 3](hw3.md) and work from its requirements. The handout opens with a walkthrough prompt for students who want an interactive tutorial; when the student pastes it, follow it, propose each step and wait for the student's go ahead before acting, and stop at the handout's review points so the student makes those decisions. The assignment generates the support scenario dataset with the synthetic data skill in `scenarios/skill/SKILL.md`; follow the skill's procedure, including the human review points, rather than writing scenarios directly. Every expected outcome comes from the database, the eligibility function, the policy documents, or the data quality table, never from a model's assertion. HW3 needs the HW2 endpoints; a student who skipped HW2 applies `hw2-reference.patch` as the handout describes. Keep pilot and final scenario identifiers distinct, reset the data before the final run, and report which runs used a live model.
