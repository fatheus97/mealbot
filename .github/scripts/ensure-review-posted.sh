#!/usr/bin/env bash
#
# Decide whether the Claude PR Review action actually COMPLETED a review on this
# run, as opposed to erroring out, stalling, or posting an empty-turn stub.
#
# Usage:
#   gh api --paginate "repos/$REPO/issues/$PR/comments" \
#     | ensure-review-posted.sh "$GITHUB_RUN_ID"
#
# Reads the issue-comment list on stdin (one JSON array per page, as
# `gh api --paginate` emits). Exits 0 when a completed review is detected, 1
# otherwise with a ::error:: annotation. Any other exit status is a bug in this
# script, not a verdict.
#
# WHY THIS IS PICKY
# `review` is not a required status check, so a red result blocks nothing
# mechanically — the convention is that a human or orchestrator treats red as
# "not reviewed" and re-runs it. That convention is worth exactly as much as the
# guard's inability to false-GREEN, so ambiguous states fail closed: a spurious
# red costs one re-run, a spurious green merges unreviewed code.
#
# KNOWN PROPERTY — this script is checked out from the PR head
# The action itself refuses to run when the workflow file differs from the one on
# the default branch ("Workflow validation failed"), but that protection does not
# extend to this script: a PR editing only .github/scripts/ runs its own version
# of the guard against itself. That is accepted rather than fixed, because
# pinning the guard to the default branch would make it impossible to iterate on
# in a PR, and it grants no capability an author does not already have — `review`
# is not a required check, so a red one can simply be merged past. The
# `review-guard` CI job is the backstop for accidental weakening.
#
# HISTORY
# v1 (#184) counted inline comments and the longest claude[bot] comment across
# the WHOLE PR. On PR #229 run 29685796635 the review errored after 3m35s having
# posted only its unticked in-progress checklist, and the guard passed anyway:
# round 1's two inline comments satisfied `inline > 0`. Any PR whose first round
# succeeded was permanently exempt from the guard on every later push.
set -euo pipefail

run_id="${1:?usage: ensure-review-posted.sh <github.run_id>}"

# Thresholds are calibrated against every claude[bot] comment on PRs #185–#229
# (74 comments). Review CONTENT — the body with the banner, checklist, spinner
# and rules stripped — is what separates a real review from chrome:
#
#   PR #229 errored comment : 540 chars total,  36 chars of content
#   PR #185 empty-turn stub : 164 chars total,  38 chars of content
#   smallest REAL review    : 1248 chars total, 401 chars of content
#
# Note the trap that made v1's successor wrong too: a total-length floor of 300
# would have passed #229's dead comment. Measure content, not boilerplate.
MIN_CONTENT=200

result=$(jq -s -r --arg run "$run_id" --argjson min "$MIN_CONTENT" '
  def lines: .body | split("\n");

  # track_progress chrome: everything that is present whether or not the model
  # actually said anything.
  def is_chrome:
       test("^\\s*$")
    or test("^---\\s*$")
    or test("^- \\[[ x]\\]")
    or test("^\\*\\*Claude (finished|encountered)")
    or test("^<img")
    or test("^</?details")
    or test("^</?summary");

  # The leading chrome region — banner, rule, checklist — up to the first line of
  # real content. Scoping the unticked-box test here means a completed review may
  # freely quote a "- [ ]" checklist in its prose without redding itself.
  def head_block:
    lines as $l
    | ($l | map(is_chrome) | index(false)) as $i
    | if $i == null then $l else $l[0:$i] end;

  def first_line: (lines[0] // "");
  def content_len: lines | map(select(is_chrome | not)) | join("\n") | length;
  def stalled: head_block | map(test("^- \\[ \\]")) | any;

  # Banners are always line 1. Verified across all 74 historical comments:
  # anchoring to the first line gives identical results to a whole-body substring
  # search, while removing the false red where a review quotes the banner text.
  def errored:  first_line | contains("Claude encountered an error");
  def finished: first_line | contains("Claude finished");

  def completed: finished and (errored | not) and (stalled | not) and (content_len > $min);

  def why:
    if   errored  then "the review turn errored out partway through"
    elif stalled  then "its checklist still has unticked items, so it stopped before finishing"
    elif (finished | not) then "it posted no completion marker (\"Claude finished\")"
    else "it posted only \(content_len) chars of review content — that is the chrome of an empty turn, not a review"
    end;

  # A run is identified by the job backlink the action embeds as a MARKDOWN LINK
  # labelled "View job...". Both shapes of the track_progress comment carry it:
  #
  #   in progress : "[View job run](.../actions/runs/<id>)" on its own line,
  #                 under a "### Reviewing PR #N" heading
  #   finished    : "**Claude finished ...** —— [View job](.../actions/runs/<id>)"
  #                 rewritten onto line 1
  #
  # Matching the link FORM rather than the bare URL is what stops a comment
  # belonging to a DIFFERENT run from being credited to this one just by quoting
  # its job URL in prose — which is exactly how PR #197 run 29195401264 refers to
  # its job from a separately posted write-up. The literal ")" additionally stops
  # run 998 from claiming the comments of run 9981.
  #
  # (Apostrophes are avoided in this jq program: it is single-quoted in bash.)
  #
  # A run can leave several tracking comments (a re-run of a failed attempt
  # appends a fresh one), so the question is whether ANY comment from this run
  # shows a completed review — never "the newest one". Comments from OTHER runs
  # are ignored entirely, which is what closes the #229 hole.
  # Identity: anchored, and a GitHub App account rather than a user. This repo is
  # PUBLIC, so anyone may comment on a PR; an unanchored substring match on
  # "claude" would let a login like `claude-fan` post a forged "Claude finished"
  # banner and green the guard on its own. The "[bot]" suffix cannot occur in a
  # human login (logins are alphanumeric + hyphen), and `.user.type` is a second,
  # independent barrier.
  [ ((add // [])[])
    | select((.user.login | test("^claude(-code)?\\[bot\\]$")) and .user.type == "Bot")
    | select(.body | test("\\[View job[^\\]]*\\]\\([^)]*actions/runs/" + $run + "\\)")) ] as $mine
  | ($mine | map(select(completed))) as $done
  | if ($mine | length) == 0 then
      "FAIL\tit posted no comment for this run (actions/runs/\($run)), so the review never ran. Either the action failed before posting (check the job log with show_full_output: true, and the CLAUDE_CODE_OAUTH_TOKEN secret), or it declined to run at all — which is expected on a PR that edits .github/workflows/."
    elif ($done | length) > 0 then
      "OK\t\($done[0] | content_len) chars of review content across \($mine | length) comment(s)"
    else
      "FAIL\t" + ($mine | map(why) | unique | join("; ")) + "."
    end')

status=${result%%$'\t'*}
detail=${result#*$'\t'}

if [ "$status" = "OK" ]; then
  echo "✅ Completed review detected for this run — $detail."
  exit 0
fi

echo "::error::Claude PR Review did not complete: $detail Treat this check as NOT REVIEWED — re-run it and confirm a completed review before merging."
exit 1
