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