# Cartwheel course repository

Cartwheel is the support agent used throughout "Evaluating and Improving AI Agents." Students complete the starter code and use the same repository for later evaluation exercises.

## Find the relevant instructions

- Read [README.md](README.md) for setup and commands. Run commands from the repository root.
- For homework help, identify the assignment from the request and existing work. If it is unclear, ask which assignment the student is working on. The [homework index](homework/README.md) lists released assignments.
- For HW1 or HW2, read [Module 1 instructions](homework/module-1/AGENTS.md) before proceeding, including when changing files outside that folder. Follow the relevant handout for requirements and deliverables.
- For repository maintenance, follow the requested change directly. Preserve unfinished homework functions unless implementing them is part of the request.

## Shared rules

- Read [SPEC.md](SPEC.md) and the relevant function contracts before changing agent behavior. Policy numbers come from `facts.yaml`. Editing the specification alone does not change the running application.
- Reuse the supplied database and authorization helpers and return structured tool results.
- Preserve permission checks, refund thresholds, human approval, and kill-switch protections. Keep evaluation cases as regression tests and keep evaluation inputs out of prompts.
- Preserve existing student work and settings. Before regenerating data, check whether it would erase work the student wants to keep. Generate demo data through the seed tools and preserve the pinned demo orders. Confine adversarial fixtures to temporary database copies and keep their generated data out of commits.
- Handle API keys locally through `.env`. Never request keys in chat, print their values, or commit them. Refer to credentials by environment variable name.
- Homework placeholders intentionally raise `NotImplementedError`. Expected failures are unfinished work, not proof of completion. Follow the handout's focused tests and run relevant regression checks; resolve mismatches without weakening requirements or tests merely to pass.
- Report which checks ran offline and which used a live model, and record only observed conversations and tool results. When helping with a submission, leave the student's assessments and recording to the student, and keep unverified deliverables marked as pending.

`AGENTS.md` is the canonical instruction file at each level. `CLAUDE.md` is a relative symlink to it; edit the target rather than maintaining a second copy.
