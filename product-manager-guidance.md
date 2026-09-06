# Product manager guidance for Homework 1

Help me complete Homework 1 for the Evaluating and Improving AI Agents course as an interactive tutorial.

I'm a product manager. I've used Claude Code, but Python setup and unfamiliar files can be confusing. I want to do the homework and understand the decisions I'm making. You can handle the implementation and terminal commands. Help me connect that work to the product behavior I'm evaluating.

The starter repository is https://github.com/ai-evals-course/cartwheel-homeworks. We are working on my own local copy of that repository. It already includes SPEC.md and a partially implemented support agent.

## How to work with me

- Give me one manageable step at a time. Briefly explain its purpose, do the technical work you can, and show me the result. Pause at the checkpoints below so I can ask questions or make a decision.
- Ask one question at a time when you need information. Inspect the current folder and available tools before asking me something you can determine yourself.
- Explain unfamiliar terms when we encounter them. Use the actual files and results as examples. Keep explanations short unless I ask for more.
- Ask me to predict or assess behavior in ordinary language. Help me reason through my answer without inventing my judgment or filling in all the answers for me.
- If something fails, inspect the error and try a focused fix. Explain what happened in plain language. If we remain stuck, prepare a short message for the course Discord with the step, the error, and what we tried. Remove secrets from that message.
- Keep a short local progress note with completed steps, evidence, and the next step so we can resume later. Keep it separate from the homework submission files.

## 1. Get oriented

Check whether this session is already in the Cartwheel homework repository. If it is, use the existing files and preserve any work. If it isn't, help me find my copy or clone the repository into a suitable folder. Explain where it will live. If you need me to select or open a folder in the app, give me one concrete action and wait.

Read the repository instructions, README.md, homework/README.md, homework/module-1/hw1.md, and SPEC.md. Inspect relevant code as needed. Use the current HW1 handout as the checklist. The opening sentence may say four tools, but the task list names five; check the actual list and code.

Explain what Cartwheel does and why we'll use it for later evals. Show me where SPEC.md lives and summarize what it already defines. Explain how an intended behavior gets implemented in the system prompt or tool code. Editing SPEC.md alone does not change the running application.

Give me a short overview of the full HW1 finish line, including the working tools, recorded conversations, prompt investigation, and short demonstration video. Then focus on our first milestone: one real conversation with the local Cartwheel agent.

Checkpoint: ask me whether the relationship between the existing repo, the specification, and the running agent is clear before moving on.

## 2. Get one conversation working

Check the Python and uv setup, install the project dependencies, and generate the local data according to the README. Preserve existing files and settings. If data already exists, check whether regenerating it would erase work I want to keep.

Explain that .env is a settings file. The Cartwheel agent needs an API key to call a model when we chat with it. Help me choose one supported provider I can access. Check the project's current configuration rather than guessing a model name. Explain any account setup or API billing I need to handle myself.

Create .env from the supplied template if needed. Show me how to enter my key locally. Do not ask me to paste the key into this conversation, display its value, or include it in git commits. The tests and data generation should work without a model key; if I cannot obtain one yet, we can continue that work and clearly mark live conversations as pending.

Run the supplied baseline checks and explain expected failures from unfinished homework functions. An expected failure does not mean the function is complete.

Help me start a real conversation as shopper user 1 using the provided CLI. Begin with a supported order lookup for order 4127. Inspect the implementation if anything blocks the conversation. Clearly distinguish a technical failure from a behavior we want to evaluate.

Checkpoint: show the actual response and ask what I expected the agent to do. Do not count a simulated response as a real run.

## 3. Complete the tools with me

Follow HW1 Part A for get_policy, search_products, list_my_orders, cancel_order, and find_order. Use the supplied specification and function contracts. For each tool, briefly explain its purpose and ask about one relevant success or failure case. Implement it based on the supplied requirements and our discussion.

Use the existing database and authorization helpers. Preserve permission checks. If a docstring and helper disagree, inspect the implementation and tests, explain the mismatch, and resolve it without weakening the requirements or changing a test merely to make it pass.

Run the focused HW1 tests with --runxfail so unfinished functions cannot be hidden as expected failures. Also run the regression checks named in the handout. Help me consider an additional tool when our conversations reveal a missing capability, following the current assignment's guidance.

Checkpoint: show what now works and which checks passed. Ask whether I want any part explained before we examine more conversations.

## 4. Help me examine behavior

Walk me through Part B one conversation at a time. Cover all required cases and all three roles, then help me design the remaining cases to reach at least ten. Ask what I expect before we run each case, then ask whether the observed behavior met that expectation.

Handle the technical work of capturing the actual request, tool calls and results, and final response in hw1-session.jsonl. Inspect how the CLI exposes those details and arrange reliable capture if needed. Do not invent missing tool calls or results. Use my assessment for the judgment fields and help me distinguish a prompt failure, a tool failure, and an unclear requirement.

Explain when a refund or cancellation changes the local data. Reset between conversations when needed, preserving the records we have already saved and keeping state consistent within each conversation.

## 5. Investigate a prompt improvement and finish

Guide me through Part C. Help me identify a missing or vague model instruction, predict a failure, and test it. Change the prompt only when the observed behavior supports the change, then rerun the same case. If no tested omission causes a prompt failure, help me explain why no edit was justified.

Check every deliverable against the current handout. Verify the conversation records and run the required checks. Prepare the relevant local commits, excluding .env and unrelated files. Leave publishing or pushing to me.

Help me prepare the continuous demonstration video of no more than five minutes. Make a short checklist of what I must show, including the required examples and live checks. I will record the video and explain my own observations. Do not mark the recording complete until I have made it.

Stay on HW1. Docker, Langfuse, and HW2 can wait.

Start by checking the current folder and helping me get oriented. Do not execute the entire tutorial in one turn.
