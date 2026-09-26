# Notes and Questions - HW 4

### 1. when to refer to spec
The HW4 says 
```During trace review, consult SPEC.md before deciding whether an observed behavior violates an existing requirement. For example, a reply claiming a refund succeeded before the tool reports success violates RESP-2. Record the relevant requirement identifier in every failure mode derived from an existing requirement.```
but that wasn't what Shreya did in the lecture - it was more casual and faster - didn't need to constantly look up the codes in the spec.
Can you speak to this more? How important is it to refer back to the requirements?
And a lot of the comments weren't really in the spec, they were product ideas identified later when experiencing the app.  Speak to this again.


### Thought
Found that the final 15 when I focused on identifying new modes meant I wasn't just highlighting the old modes anymore. Was good to switch to "just check for new stuff"

## Part D - reviewing suggestions
Do I need to review all suggestions? Claude wants me to review all items that are flagged as possible mode matches, and some modes (write_without_confirmation) had like 30 possible matches - how do you decide how many to label? 

I also reviewed many close negatives, is that part of axial coding?

Reviewing many modes is very time consuming - do you always review all 10? Some I feel like could be labeled well with a deterministic label, or should probably just be fixed because while reviewing I'm realizing the fix is quite simple. How do you balance all that - is it the "art" of this where you build a sense of when to fix, when to label more, how many to label because the class will be tricky to judge?

Labeling is done for each turn - but some modes may only apply to the entire session / scenario (the original intent of the question wasn't resolved in the end) - is that the case, or am I thinking about it wrong?


## Part E 

 Do I really need to label all examples x 10 modes? Maybe I should select 5 modes and a subset of examples?

 ## Question for doing error analysis in practise

 With a team - does one person do it by creating a custom dash, or should the dash be hosted for the team to review a queue? What tends to work?
 Do you build your own annotation queues?

# Questions for office hours
1. Question about the error analysis process - labeling 100 examples per label -> pita. That's after open coding a hundred traces. I already get so much push back about labeling, and I'm practical: okay, let's start with 40. And now go back to do it. How do you talk to teams about this process to tell them what happens when you don't do this?

2. Related - labeling 100 examples per mode is very time consuming - do you always review all 10+ I probably had like 20? Some I feel like could be labeled well with a deterministic label, or should probably just be fixed because while reviewing I'm realizing the fix is quite simple. How do you balance all that - is it the "art" of this where you build a sense of when to fix, when to label more, how many to label because the class will be tricky to judge?

Shreya said - only build judges for failure modes you think will persist or are important in your app.
For the other failure modes that I want to fix and think I can, do we just try to do that, or just use an uncalibrated judge because it's temporary?

1. Labeling is done for each turn (trace) - but some modes may only apply to the entire session / scenario (the original intent of the question wasn't resolved in the end) - is that the case, or am I thinking about it wrong?

2. Error analysis - Maybe not relevant to everyone. Can you speak to how you go through this process for consulting clients - do you do a lot of pairing "let's build a custom labeling dash together" okay let's do open coding, okay now you go. Just curious about your process.


## Lecture notes
Not every failure mode needs an eval 

6. I really have a hard time understadning why we don't want any "happy path" evals - is it just a complete waste of time? Why not have 5 of those. 

3. How to deal with non-English applications. This is for a new client, I don't have much info. For Arabic - input in Arabic - translate to English and continue in English so that the trace is that way, and trust the translation step?

7. What does a continous eval loop look like - any recommenations on - review X traces per week in a queue?


8 Can you speak to what happens in production? 
Do you run your calibrated LLM judge in production on live traces to catch new errors? Random sample or all?