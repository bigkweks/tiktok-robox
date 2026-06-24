---
name: handoff
description: Generate and merge a session handoff into HANDOFF.md, then commit and push. Use this at the end of any working session to document what changed, what works, and what's next. Invoke with /handoff.
---

# Handoff Skill

Generate a complete session handoff, merge it into `HANDOFF.md`, commit, and push to the current branch.

## When to use

Run `/handoff` at the end of every working session. The goal is that any future Claude Code session can read `HANDOFF.md` and immediately continue — no re-reading history, no re-deriving context.

## Workflow

### 1. Gather session facts

Run these in parallel:

```bash
git log --oneline -20                         # what shipped this session
git diff HEAD~5 HEAD --stat                   # which files changed
python -m pytest --tb=no -q 2>&1 | tail -3   # current test count
```

Also read:
- `HANDOFF.md` — to understand current structure and where to insert the new entry
- Any new or heavily-modified source files to get precise descriptions

### 2. Synthesise the session changelog entry

Write a `## Session changelog — <title> (latest)` block that captures:

- **Brief**: one sentence stating what the session was asked to do
- **What changed**: bullet per meaningful change, format:
  `- **<What changed> (`<file.py>`).**  <Why it matters / the problem it solved> + <key design decision>. <Test coverage added>.`
- **Test count**: `Full suite: N passing.`

Rules for the entry:
- Use present-tense active voice ("Adds", "Fixes", "Replaces")  
- Name the exact file and the exact function/class/constant that changed
- State the *problem* the change solved, not just what the code does
- If a previous entry says "(latest)", change it to "(prior)" — only the new one is "(latest)"
- Keep prior entries intact — never delete history

### 3. Update the State section

Update the single line: `- **Test suite: N passing**.` to match the actual count.

If any bullet in the "State: what works now" section is newly true this session, update or add it.

### 4. Update the Architecture section (if needed)

If a **new file** was created (`creator_brief.py`, a new template, etc.), add it to the `src/` tree in the Architecture block with a one-line description. If a file's description is now stale, fix it.

### 5. Update "Likely next steps"

Replace completed items with ✅. Add new items if the session surfaced follow-up work.

### 6. Merge the new content into HANDOFF.md

- Insert the new `## Session changelog` block **immediately after** the `## State: what works now` block and before the previous "(latest)" entry (which you now retitle "(prior)").
- Do NOT rewrite or reorder existing sections — only insert, update the State line, and retitle the previous latest.
- Never truncate the file.

### 7. Commit and push

Stage only `HANDOFF.md` (and `.claude/` if skills were added this session):

```bash
git add HANDOFF.md .claude/
git commit -m "docs: update handoff for <session-title> session

Co-Authored-By: Claude <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01J31MKKPiitg4T3ZATKgFFr"
git push -u origin <current-branch>
```

Replace `<session-title>` with a 3-5 word summary of what the session accomplished.

## Output format

After pushing, reply with:

```
Handoff updated and pushed.

Session title  : <title>
Commits this session : N
Tests          : N passing
Branch         : <branch>

New entry covers:
- <bullet 1>
- <bullet 2>
...
```

No other prose. The file is the record.
