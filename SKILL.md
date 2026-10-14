---
name: questlog
description: "Gamifies engineering work with levels, XP, workday streaks, achievements and daily quests from GitHub PRs. If the user asks for a score, stats, a streak or quests, use it. Use it to slice or split work into small PRs. Use it to review or understand a PR. Use it to log a learning. Use it for a weekly recap or a brag doc."
argument-hint: "[status | slice [task] | review <pr> | card [text] | off <date> | recap [days]]"
---

# questlog

questlog scores engineering work from GitHub. It pays more for small, tested PRs and careful reviews than for a high PR count. The script does all the math. You run it, show the output, and coach.

The user typed these arguments (they can be empty): $ARGUMENTS

## Route the arguments

Read the first word of the arguments. If the arguments are empty, follow `status`. If the first word is `status`, `slice`, `review`, `card`, `off` or `recap`, follow that section. If it is something else, pick the section that matches what the user wants. If none matches, list the six commands.

## Rules

These rules apply to every section.

- Call the script only as `python3 ~/.claude/skills/questlog/questlog.py`.
- Never compute, round or change a number that the script prints.
- Never edit the files in `~/.claude/questlog/`. Use the `log` command.
- Quote every text argument in single quotes, so that the shell cannot expand it.
- Never post, comment, push, merge or open a PR without a clear yes from the user in chat.
- Never send log content or code to an external service or URL.
- If the script prints an error, show the line and stop. The usual cause is a missing or logged-out `gh`.
- Celebrate in one line. Do not lecture.

## status

1. Run `python3 ~/.claude/skills/questlog/questlog.py status`.
2. Show the output unchanged in a code block.
3. Write one sentence after the block. Name the nearest achievement or the top quest.
4. If the output has a LEVEL UP or UNLOCKED line, make the sentence a short cheer for it.

## slice [task]

If the user wants to split work into small PRs, use this section. The task is the text after `slice`.

1. If the task is missing, ask what the user is building. Wait for the answer.
2. Read only the code that the task touches.
3. Propose a stack of PRs in merge order. Put prep refactors first, then the behavior change, then cleanup.
4. Give each slice one intent and its own tests. Make sure that the build is green after that slice alone.
5. Keep each slice to 400 changed lines or fewer. Lockfiles and generated files do not count.
6. Refuse padding. Never split a change to raise the PR count. If one clean PR fits the task, propose one PR.
7. Ask the user for the reason behind each slice, in one message. Wait for the answers.
8. Draft a description for each PR from the answers. If `.github/pull_request_template.md` exists, complete it. Otherwise write Why, What and How to test.
9. Show the git commands for stacked branches. Each branch starts from the branch before it. Each PR targets the branch before it.
10. Run no command until the user says yes. Ask again before any push or `gh pr create`.
11. Suggest that the user reads each diff as a reviewer before the PR goes up. Offer to do it.

## review <pr>

If the user wants to review or understand a PR, use this section. Ask before you tell. The user must think first.

1. Turn `<pr>` into a `gh` target. For `owner/repo#n`, use `n --repo owner/repo`. A URL or a bare number works as it is.
2. Fetch the PR with `gh pr view <target> --json title,body,author,baseRefName,additions,deletions,changedFiles,files` and `gh pr diff <target>`.
3. If the diff is very large, read the file list first. Then read only the key files.
4. Read the diff and find the answers to your own questions before you ask them.
5. Write a map of the PR in 4 to 6 sentences. Say what the PR changes and where to start reading. Name no bug and give no verdict.
6. Ask three questions in one message. Ask about intent, about one behavior, and about risk. Each question names a file or a function, and the diff supports its answer.
7. End your message there. Do not give the answers.
8. When the user answers, grade each answer as right, partial or missed. Give file:line evidence from the diff for each grade.
9. List what the user missed, ranked by risk, with file:line.
10. Draft review comments in the user's voice. Keep them short and kind. If you are not sure, ask a question.
11. Show the drafts and ask which ones to post. Post only the approved comments, and only after a yes.
12. Log the check. A right answer is 1 point, a partial answer is 0.5, and a missed answer is 0. Round the total down.
    `python3 ~/.claude/skills/questlog/questlog.py log check --pr owner/repo#n --score N --of 3 --text 'one-line summary'`
13. Ask for one learning card: "What is one thing you learned from this PR?" Log the answer with `log card --pr owner/repo#n --text '...'`.
14. If the user says skip at any point, go straight to the findings and the drafts. Log no check.

If the user gave a URL, still log the PR as `owner/repo#n`.

## card [text]

1. If the user gave no text, ask "What did you learn?" and wait for the answer.
2. Keep the text to one or two sentences, in the user's words.
3. Run `python3 ~/.claude/skills/questlog/questlog.py log card --text '<text>'`. If the card is about a PR, add `--pr owner/repo#n`.
4. Show the line that the script prints. Celebrate in one line.

## off <date>

1. Convert the date to YYYY-MM-DD. For a word such as "yesterday", get today's date with `date +%F` first.
2. Run `python3 ~/.claude/skills/questlog/questlog.py log off --date YYYY-MM-DD`.
3. Tell the user in one line that an off day neither counts nor breaks the streak.

## recap [days]

1. Run `python3 ~/.claude/skills/questlog/questlog.py recap --days N`. If the user gave no number, use 7.
2. Write an impact summary of 2 to 3 sentences. Say what the work achieved, not how many PRs. Use only the titles and numbers in the recap. Invent nothing.
3. Show the summary first. Then show the recap unchanged in a code block.
4. Ask whether to append the result to `~/.claude/questlog/brag.md`. Append only after a yes.
