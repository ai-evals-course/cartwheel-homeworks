# Review UI walkthrough

The current caption-free walkthrough is `review_ui_no_captions.mp4`: **29 seconds**, 1440 × 900, with no on-screen narrative captions.

`review_ui_subtitled.mp4` adds readable subtitles from `review_ui.srt`. Subtitle cues follow the three scene timings; fine-grained speech alignment remains pending voice generation. The taxonomy capture has been replaced with the supplied current screenshot, including the updated groups and comment counts. The suggestions preview also uses the current taxonomy backdrop.

| Time | Process |
| --- | --- |
| 0–12 seconds | Highlight evidence, enter a comment, and press Enter to save. |
| 12–19 seconds | Inspect the taxonomy groupings. |
| 19–29 seconds | Review the suggestion evidence, select a candidate, and consider Accept or Reject. |

The comment interaction comes from the existing `anon.mp4` recording, now played at its original pace with a short hold on the saved comment. Taxonomy uses an existing Review UI capture. The suggestions panel and selection are an illustrated preview based on actual saved retrieval quotes and scenario IDs; the explanatory comment is shortened. The panel retains its preview disclosure. No assessment or suggestion decision is written.

## Generate synchronized voice narration

Set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` in the root `.env`, then run from the repository root with network access:

```bash
.venv/bin/python video/add_narration.py
```

The script generates three narration segments in the configured voice and aligns them with the visual sections. It saves `review_ui_narration.mp3` and produces `review_ui_voice.mp4` with subtitles, capped at 29 seconds. It pads pauses and permits at most a 15% audio speed adjustment; an overly long segment stops generation rather than clipping speech. Matching generated segments are cached to avoid repeat API calls.

Spoken script:

1. “Start in Review. Highlight the relevant text to open a comment box. Describe what went wrong, then press Enter to save your note.”
2. “Next, open Taxonomy. Related comments appear in groups, making recurring failure patterns easier to see.”
3. “Finally, review Agent suggestions. Check the highlighted evidence and proposed failure group. Select a candidate, then accept or reject it after reviewing the conversation.”

The latest ElevenLabs request was blocked by this environment's network restrictions. The expanded narration remains pending. Any existing `review_ui_voice.mp4` and `review_ui_narration.mp3` are the earlier seven-second version until this command succeeds.

`review_ui.gif` and `review_ui.mp4` preserve the original seven-second captioned cut. Source assets for the extended cut are in `assets/`. Media verification and Python syntax checks were offline; no new live model generation completed.
