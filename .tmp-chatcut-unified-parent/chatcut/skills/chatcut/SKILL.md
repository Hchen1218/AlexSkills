---
name: chatcut
description: Use ChatCut's official MCP service as one unified entry for editable video work. Trigger whenever the user asks to open or create a ChatCut project; import local, attached, or generated media; edit a timeline; clean speech; transcribe; add captions, subtitles, transitions, B-roll, overlays, or multicam edits; create motion graphics; generate images, video, voiceover, music, sound effects, or shaders; export a video; or verify changes in the ChatCut editor.
---

# ChatCut

Use this skill as the only ChatCut workflow entry. Do not look for or require separate ChatCut sub-skills.

## Core workflow

1. Confirm that the `chatcut` MCP server is available and authenticated. If it is missing in a task created before installation, continue in a new task. If authorization is missing, run the ChatCut login flow before editing.
2. Use the in-app browser when available to open ChatCut and keep the project visible to the user. Create a project or select the intended existing project before changing media.
3. Inspect the user's source media, goal, target platform, duration, aspect ratio, language, and style. Ask only for information that materially changes the edit.
4. Build a short edit plan and preserve an editable timeline. Keep original media intact and prefer reversible project operations.
5. Execute the smallest useful group of ChatCut MCP operations, then read back project or timeline state. Repeat in checkpoints instead of issuing a large unverified batch.
6. Verify important changes in the editor whenever browser controls are available. Do not claim that an edit, generation, or export succeeded solely because a tool call was accepted.
7. Export only after the user approves the edit or explicitly requests an export. Report the resulting project, export state, and any remaining decisions.

## Route requests through this entry

- **Import and setup:** bring in local or attached media, create a project, choose canvas settings, and organize source assets.
- **Editorial:** trim and reorder clips, remove pauses or filler speech, synchronize multicam footage, add transitions, B-roll, overlays, and timing refinements.
- **Text and speech:** transcribe, create or style captions and subtitles, clean dialogue, and add voiceover.
- **Motion graphics:** create editable titles, lower thirds, callouts, explainers, and other MG elements that match the video's visual language.
- **Asset generation:** generate images, video, voice, music, sound effects, or shaders when the user needs missing material. Surface relevant credit or cost information before a material paid generation when the tool provides it.
- **Finish and verification:** review the timeline, check editor-visible results, fix obvious discontinuities, and export in the requested format.

## Operating rules

- Treat the ChatCut editor as the source of truth for timeline-visible state.
- Keep generated and imported assets traceable to their intended timeline use.
- Preserve editability; do not flatten intermediate work unless the user asks.
- When a request is broad, begin with a usable first cut and invite focused revisions.
- If a tool or browser action fails, report the exact failed step and retry recoverable failures before proposing manual work.
- Never expose OAuth tokens, session data, or private media URLs in the response.
