# Homework 1 tutorial

The course instructors prepared this walkthrough for students who want guided help. Your coding agent should follow the steps and checkpoints below when you choose the tutorial.

Help me complete Homework 1 for the Evaluating and Improving AI Agents course as an interactive tutorial.

I want to do the homework and understand the decisions I'm making. You can handle the implementation and terminal commands. Adapt your explanations to what I already know, and help me connect the technical work to the product behavior I'm evaluating.

The starter repository is https://github.com/ai-evals-course/cartwheel-homeworks. We are working on my own local copy of that repository. It already includes SPEC.md and a partially implemented support agent.

## How to work with me

- Give me one manageable step at a time. Briefly explain its purpose, do the technical work you can, and show me the result. Pause at the checkpoints below so I can ask questions or make a decision.
- Ask one question at a time when you need information. Inspect the current folder and available tools before asking me something you can determine yourself.
- Once I answer a checkpoint or ask you to continue, carry out the agreed step and proceed to the next question that needs my input. Avoid a separate permission question for each command or an extra "ready to continue?" after I have already answered.
- Explain unfamiliar terms when we encounter them. Use the actual files and results as examples. Keep explanations short unless I ask for more.
- Ask me to predict or assess behavior in ordinary language. Show the actual result and ask what I notice before suggesting a pass/fail label or the source of a failure. If I am unsure, help me compare the result with the relevant requirement, then let me make the assessment. If my answer conflicts with the specification, explain the conflict and ask me to reconsider.
- If something fails, inspect the error and try a focused fix. Explain what happened in plain language. If we remain stuck, prepare a short message for the course Discord with the step, the error, and what we tried. Remove secrets from that message.
- Keep a short local progress note with completed steps, evidence, and the next step so we can resume later. Maintain a current checklist of all deliverables, including the additional-tool requirement and my video, so unfinished work stays visible. Update the current status as we progress rather than only appending a history of old next steps. Keep the note separate from the homework submission files.

## 1. Get oriented

Check whether this session is already in the Cartwheel homework repository. If it is, use the existing files and preserve any work. If it isn't, help me find my copy or clone the repository into a suitable folder. Explain where it will live. If you need me to select or open a folder in the app, give me one concrete action and wait.

Read the [repository instructions](../../AGENTS.md), [Module 1 instructions](AGENTS.md), and [HW1 handout](hw1.md), along with README.md and SPEC.md at the repository root. Inspect relevant code as needed. Use the current handout as the checklist. The student has chosen the tutorial, so begin orientation without asking them to choose a help style again.

Explain what Cartwheel does and why we'll use it for later evals. Show me where SPEC.md lives and summarize what it already defines. Explain how an intended behavior gets implemented in the system prompt or tool code. Editing SPEC.md alone does not change the running application.

Give me a short overview of the full HW1 finish line, including the five required tools and the additional-tool work requested in Part A. Also explain the recorded conversations, prompt investigation, and short demonstration video. Then focus on our first milestone: one real conversation with the local Cartwheel agent.

Checkpoint: ask me whether the relationship between the existing repo, the specification, and the running agent is clear before moving on.

## 2. Get one conversation working

Check the Python and uv setup, install the project dependencies, and generate the local data according to the README. Preserve existing files and settings. If data already exists, check whether regenerating it would erase work I want to keep.

Explain that .env is a settings file. The Cartwheel agent needs an API key to call a model when we chat with it. Help me choose one supported provider I can access. Check the project's current configuration rather than guessing a model name. Explain any account setup or API billing I need to handle myself.

Create .env from the supplied template if needed and show me how to enter my key locally, following the shared credential rules. The tests and data generation should work without a model key; if I cannot obtain one yet, we can continue that work and clearly mark live conversations as pending.

Run the supplied baseline checks and explain expected failures from unfinished homework functions. An expected failure does not mean the function is complete.

Help me start a real conversation as shopper user 1 using the provided CLI. Begin with a supported order lookup for order 4127. Before running the request, ask what I expect the agent to do and wait for my answer. Inspect the implementation if anything blocks the conversation. Clearly distinguish a technical failure from a behavior we want to evaluate.

Checkpoint: show the actual response and ask whether it met my expectation. Do not count a simulated response as a real run.

## 3. Complete the tools with me

Follow HW1 Part A for get_policy, search_products, list_my_orders, cancel_order, and find_order. Use the supplied specification and function contracts. For each tool, briefly explain its purpose and ask about one relevant success or failure case. Implement it based on the supplied requirements and our discussion.

If a docstring and helper disagree, inspect the implementation and tests. Explain the mismatch and apply the shared implementation rules.

Run the focused HW1 tests with --runxfail so unfinished functions cannot be hidden as expected failures. Also run the regression checks named in the handout. When a conversation reveals a missing capability, help me define an appropriate tool, implement it, and register it for the correct roles, following the current assignment's guidance.

Checkpoint: show what now works and which checks passed. Ask whether I want any part explained before we examine more conversations.

## 4. Help me examine behavior

Walk me through Part B one conversation at a time. Cover all required cases and all three roles, then help me design the remaining cases to reach at least ten. Ask what I expect before we run each case, then ask whether the observed behavior met that expectation.

Start each separate conversation in a fresh CLI session so earlier requests and tool results do not influence it. Quit and relaunch the CLI between conversations, keeping follow-up turns within the same conversation together. Resetting the order database does not clear conversation history.

Handle the technical work of capturing the actual request, tool calls and results, and final response in hw1-session.jsonl. Inspect how the CLI exposes those details and arrange reliable capture if needed. Do not invent missing tool calls or results. Use my assessment for the judgment fields and help me distinguish a prompt failure, a tool failure, and an unclear requirement.

Explain when a refund or cancellation changes the local data. Reset between conversations when needed, preserving the records we have already saved and keeping state consistent within each conversation.

Track missing capabilities as we examine conversations. Before leaving Part B, review them with me and choose a useful additional tool to satisfy Part A. Help me define its expected behavior, then implement, register, and test it. If we have not identified a gap, revisit the handout's suggestions together. Keep this requirement marked as pending until we have done the work.

## 5. Investigate a prompt improvement and finish

Guide me through Part C. Help me identify a missing or vague model instruction, predict a failure, and test it. If the agent already satisfies the first requirement, test another possible omission before concluding the investigation. Change the prompt only when the observed behavior supports the change, then rerun the same case in a fresh session with the same starting data. If none of the tested omissions causes a prompt failure, help me explain which omissions we tested and why no edit was justified.

Check every deliverable against the current handout. Verify the conversation records and run the required checks. Prepare the relevant local commits, excluding .env and unrelated files. Leave publishing or pushing to me.

Help me prepare the continuous demonstration video of no more than five minutes. Make a short checklist of what I must show, including the required examples and live checks. I will record the video and explain my own observations. Do not mark the recording complete until I have made it.

Stay on HW1. Docker, Langfuse, and HW2 can wait.

Start by checking the current folder and helping me get oriented. Do not execute the entire tutorial in one turn.
