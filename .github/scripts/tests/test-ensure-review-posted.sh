#!/usr/bin/env bash
#
# Regression tests for ensure-review-posted.sh.
#
# The comment shapes below are reproduced from real claude[bot] comments in this
# repo — PR #229 (runs 29685264910 / 29685796635), PR #197 (run 29195401264) and
# the PR #185 empty-turn stub. Bodies are padded rather than pasted in full; only
# the banner, the checklist state, the job backlink and the length matter here.
set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
guard="$here/../ensure-review-posted.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

pass=0
fail=0

# comment <run_id> <banner> <checklist> <padding_len>
# The canonical track_progress comment: banner + line-1 [View job] backlink,
# then a rule, the checklist, and the review content.
comment() {
  jq -n --arg run "$1" --arg banner "$2" --arg list "$3" \
        --arg pad "$(head -c "$4" /dev/zero | tr '\0' 'x')" '
    { user: { login: "claude[bot]", type: "Bot" },
      body: ( $banner + " —— [View job](https://github.com/fatheus97/mealbot/actions/runs/" + $run + ")\n\n---\n"
              + $list + "\n" + $pad ) }'
}

# mention <run_id> <text> <padding_len>
# A comment posted via `gh pr comment`: no banner, no line-1 backlink — it only
# refers to the job URL in prose. Models PR #197 run 29195401264, and equally the
# case of another run's review quoting this run's URL.
mention() {
  jq -n --arg run "$1" --arg text "$2" --arg pad "$(head -c "$3" /dev/zero | tr '\0' 'x')" '
    { user: { login: "claude[bot]", type: "Bot" },
      body: ( $text + "\n\nSee https://github.com/fatheus97/mealbot/actions/runs/" + $run + " for the job log.\n\n" + $pad ) }'
}

# check <name> <expected PASS|FAIL> <fixture> <run_id> [expected_reason_substring]
#
# A FAIL expectation asserts exit status EXACTLY 1 plus the specific rejection
# reason — not merely "non-zero". Accepting any non-zero status silently turns
# this suite green whenever the guard is broken outright: with jq missing the
# guard dies at rc=127 on every fixture, and every FAIL case would still report
# ok, including the headline #229 regression test.
check() {
  local name="$1" expected="$2" fixture="$3" run="$4" want_reason="${5:-}" out rc
  out=$(bash "$guard" "$run" <"$fixture" 2>&1)
  rc=$?

  local problem=""
  if [ "$expected" = PASS ]; then
    [ $rc -eq 0 ] || problem="expected exit 0, got $rc"
  else
    if [ $rc -ne 1 ]; then
      problem="expected exit 1 (a clean rejection), got $rc"
    elif ! printf '%s' "$out" | grep -q '::error::'; then
      problem="exit 1 but no ::error:: annotation for the log"
    elif [ -n "$want_reason" ] && ! printf '%s' "$out" | grep -qF "$want_reason"; then
      problem="rejected for the wrong reason — no '$want_reason' in the message"
    fi
  fi

  if [ -z "$problem" ]; then
    pass=$((pass + 1))
    printf '  ok   %s\n' "$name"
  else
    fail=$((fail + 1))
    printf '  FAIL %s — %s\n' "$name" "$problem"
    printf '%s\n' "$out" | sed 's/^/         | /'
  fi
}

# Guard against the whole suite passing vacuously if the guard cannot run at all.
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required to run these tests" >&2
  exit 2
fi
# The jq program is single-quoted inside the script, so a stray apostrophe in one
# of its comments silently ends the string and breaks every case at once.
if ! bash -n "$guard"; then
  echo "$guard is not valid bash" >&2
  exit 2
fi

DONE_LIST='- [x] Gather context (diff, prior review threads)
- [x] Read changed files
- [x] Review correctness/edge cases
- [x] Post final review'
PART_LIST='- [x] Gather context (diff since last review, prior review threads)
- [ ] Verify the `leftover_policy` rollout-gate fix (commit 4742ec4)
- [ ] Review remaining diff for new issues
- [ ] Post final review'

# --- PR #229: round 1 completed (run ...264910), round 2 errored (run ...796635).
# The exact state that fooled the v1 guard: a long, completed, inline-commented
# review already sits on the PR when the later run dies.
{
  comment 29685264910 "**Claude finished @fatheus97's task in 3m 44s**" "$DONE_LIST" 3000
  comment 29685796635 "**Claude encountered an error after 3m 35s**"    "$PART_LIST" 100
} | jq -s '.' >"$work/errored-round-2.json"

# Same PR after the failed run was re-run and succeeded — same run id, new comment.
{
  jq '.[]' "$work/errored-round-2.json"
  comment 29685796635 "**Claude finished @fatheus97's task in 59s**" "$DONE_LIST" 2200
} | jq -s '.' >"$work/rerun-succeeded.json"

# --- PR #197 run 29195401264: the tracking comment, then the review body posted
# separately via `gh pr comment` (no banner, no checklist) AFTER it. Taking the
# newest comment for the run would red a perfectly good review.
{
  comment 29195401264 "**Claude finished @fatheus97's task in 1m 12s**" "$DONE_LIST" 900
  mention 29195401264 "### Review: docs-only ROADMAP reconciliation" 1300
} | jq -s '.' >"$work/separate-review-comment.json"

# --- Cross-run credit: run 55555 posted only an errored, unticked checklist,
# while run 77777's completed review happens to quote 55555's job URL in prose.
# Matching the URL anywhere in the body lets 55555 claim 77777's review.
{
  comment 55555 "**Claude encountered an error after 1m**" "$PART_LIST" 100
  comment 77777 "**Claude finished @fatheus97's task in 2m**" "$DONE_LIST" 1500
  mention 55555 "Reviewed the retry logic; see the earlier job" 900
} | jq -s '.' >"$work/cross-run.json"

# --- The IN-PROGRESS shape, verbatim from PR #231 run 29700278618 while the
# review was still running. Note it differs from the finished shape: no banner,
# a "### Reviewing PR #N" heading, and the backlink is "[View job run](...)" on
# its own line rather than "[View job](...)" on line 1. The action rewrites the
# comment into the banner form when it finishes, so the guard only ever sees this
# if it is evaluated too early — or if the run dies without rewriting.
# At 313 chars it also clears the old 300-char length floor.
jq -n '[{ user: { login: "claude[bot]", type: "Bot" },
  body: "### Reviewing PR #231\n\n- [x] Gather context (PR description, diff, prior review threads)\n- [ ] Read ROADMAP.md diff\n- [ ] Check prior review rounds for dismissed findings\n- [ ] Post review feedback\n\n<img src=\"https://github.com/user-attachments/assets/5ac382c7.png\" width=\"14px\" height=\"14px\" />\n\n[View job run](https://github.com/fatheus97/mealbot/actions/runs/29700278618)" }]' \
  >"$work/in-progress.json"

# --- Run 88888 errored; run 99999 then posted a completed review that QUOTES
# 88888's backlink verbatim, as a full markdown link rather than a bare URL —
# plausible here, since the reviewer reads prior rounds and this guard is itself
# the subject under review. Matching the link form alone would credit 88888 with
# 99999's review; taking each comment FIRST backlink as its own run does not.
jq -n --arg pad "$(head -c 1500 /dev/zero | tr '\0' 'x')" '
  [ { user: { login: "claude[bot]", type: "Bot" },
      body: ("**Claude encountered an error after 1m** —— [View job](https://github.com/fatheus97/mealbot/actions/runs/88888)\n\n---\n- [ ] Post final review\n") },
    { user: { login: "claude[bot]", type: "Bot" },
      body: ("**Claude finished @fatheus97 task in 2m** —— [View job](https://github.com/fatheus97/mealbot/actions/runs/99999)\n\n---\n- [x] Post final review\n\nThe previous round left this comment:\n\n> **Claude encountered an error after 1m** —— [View job](https://github.com/fatheus97/mealbot/actions/runs/88888)\n\n" + $pad) } ]' \
  >"$work/quoted-backlink.json"

# --- PR #185: a "finished" banner over an empty model turn (the #181–#183 shape).
comment 4945588626 "**Claude finished @fatheus97's task in 3s**" "" 0 | jq -s '.' >"$work/empty-stub.json"

# --- Run-id prefix collision: run 998's comment must not satisfy run 9981.
comment 998 "**Claude finished @fatheus97's task in 2m**" "$DONE_LIST" 1000 | jq -s '.' >"$work/prefix.json"

# --- gh api --paginate emits one array per page; the guard must span pages.
{ comment 111 "**Claude finished @fatheus97's task in 2m**" "$DONE_LIST" 1000 | jq -s '.'
  comment 222 "**Claude finished @fatheus97's task in 1m**" "$DONE_LIST" 1000 | jq -s '.'
} >"$work/paginated.json"

# --- Degenerate inputs: a PR with no comments, and no pages at all.
echo '[]' >"$work/no-comments.json"
: >"$work/empty-input.json"

# --- The repo is PUBLIC, so any account can comment on a PR. A human whose login
# genuinely CONTAINS "claude" must not be able to forge a completed review.
# ("claudia-dev" would be a vacuous fixture — it does not contain "claude" at
# all, so it satisfied the old substring filter for the wrong reason.)
jq -n --arg pad "$(head -c 600 /dev/zero | tr '\0' 'y')" '
  [{ user: { login: "not-claude-a-human", type: "User" },
     body: ("**Claude finished @x task in 1m** —— [View job](https://github.com/o/r/actions/runs/777)\n\n---\n- [x] done\n\n" + $pad) }]' \
  >"$work/human-lookalike.json"

# --- The same forgery from an account that is somehow typed as a Bot, and a
# real-looking login typed as a User: each conjunct of the identity test must
# carry its own weight.
jq -n --arg pad "$(head -c 600 /dev/zero | tr '\0' 'y')" '
  [{ user: { login: "claude-fan", type: "Bot" },
     body: ("**Claude finished @x task in 1m** —— [View job](https://github.com/o/r/actions/runs/778)\n\n---\n- [x] done\n\n" + $pad) }]' \
  >"$work/bot-typed-impostor.json"
jq -n --arg pad "$(head -c 600 /dev/zero | tr '\0' 'y')" '
  [{ user: { login: "claude[bot]", type: "User" },
     body: ("**Claude finished @x task in 1m** —— [View job](https://github.com/o/r/actions/runs/779)\n\n---\n- [x] done\n\n" + $pad) }]' \
  >"$work/user-typed-impostor.json"

# Every fixture above must be non-empty valid JSON, except the two that are
# deliberately degenerate. A fixture that silently fails to build makes its test
# pass for the wrong reason — that has now happened twice while writing this file.
for f in "$work"/*.json; do
  case "$(basename "$f")" in
    no-comments.json|empty-input.json) continue ;;  # degenerate on purpose
  esac
  if ! jq -e 'length > 0' "$f" >/dev/null 2>&1; then
    printf 'fixture %s is empty or malformed — the tests using it would pass vacuously\n' "$(basename "$f")" >&2
    exit 2
  fi
done

echo "the regression this guard exists for:"
check "errored review is red even though round 1 reviewed the PR" \
  FAIL "$work/errored-round-2.json" 29685796635 "errored out partway through"

echo "states that must stay green:"
check "round 1's own completed review" \
  PASS "$work/errored-round-2.json" 29685264910
check "completed review from a re-run under the same run id" \
  PASS "$work/rerun-succeeded.json" 29685796635
check "review body posted separately after the tracking comment (PR #197)" \
  PASS "$work/separate-review-comment.json" 29195401264
check "match on a later --paginate page" \
  PASS "$work/paginated.json" 222

echo "other incomplete states:"
check "action posted nothing for this run" \
  FAIL "$work/rerun-succeeded.json" 99999999999 "no comment for this run"
check "empty-turn stub under a finished banner (PR #185)" \
  FAIL "$work/empty-stub.json" 4945588626 "chars of review content"
check "the live in-progress checklist (PR #231) is not a completed review" \
  FAIL "$work/in-progress.json" 29700278618 "no completion marker"
check "run id must not prefix-match a longer run id" \
  FAIL "$work/prefix.json" 9981 "no comment for this run"
check "PR with no comments at all" \
  FAIL "$work/no-comments.json" 12345 "no comment for this run"
check "no pages on stdin" \
  FAIL "$work/empty-input.json" 12345 "no comment for this run"
check "human login containing 'claude' cannot satisfy the guard" \
  FAIL "$work/human-lookalike.json" 777 "no comment for this run"
check "impostor login typed as a Bot cannot satisfy the guard" \
  FAIL "$work/bot-typed-impostor.json" 778 "no comment for this run"
check "bot login typed as a User cannot satisfy the guard" \
  FAIL "$work/user-typed-impostor.json" 779 "no comment for this run"
check "another run's review quoting this run's job URL is not credited" \
  FAIL "$work/cross-run.json" 55555 "errored out partway through"
check "another run's review quoting this run's backlink as a markdown link is not credited" \
  FAIL "$work/quoted-backlink.json" 88888 "errored out partway through"
check "the quoting run itself still passes" \
  PASS "$work/quoted-backlink.json" 99999

# An unticked checklist under a *finished* banner — the "exited 0 but the review
# never actually finished" case, distinct from the errored banner above.
{ comment 555 "**Claude finished @fatheus97's task in 4m**" "$PART_LIST" 1500; } \
  | jq -s '.' >"$work/finished-but-unticked.json"
check "finished banner but the checklist is still unticked" \
  FAIL "$work/finished-but-unticked.json" 555 "unticked items"

# A ticked checklist with no review under it. The real #229 dead comment was 540
# chars — a total-length floor of 300 waves it through, which is why the guard
# measures CONTENT with the chrome stripped.
{ comment 556 "**Claude finished @fatheus97's task in 8s**" "$DONE_LIST" 0; } \
  | jq -s '.' >"$work/chrome-only.json"
check "ticked checklist but no review content beneath it" \
  FAIL "$work/chrome-only.json" 556 "review content"

echo "false-red regressions (a completed review must survive these):"

# A finished review that quotes an unticked checklist and the error banner in its
# own prose. Whole-body substring matching reds this; line-1 anchoring and
# head-block scoping do not.
jq -n --arg pad "$(head -c 900 /dev/zero | tr '\0' 'z')" '
  [{ user: { login: "claude[bot]", type: "Bot" },
     body: ("**Claude finished @fatheus97'"'"'s task in 2m** —— [View job](https://github.com/o/r/actions/runs/661)\n\n---\n"
            + "- [x] Gather context\n- [x] Post final review\n\n"
            + "The PR description still has unticked work:\n\n- [ ] update the changelog\n\n"
            + "Also, the log line \"Claude encountered an error\" on line 12 should be quoted.\n\n" + $pad) }]' \
  >"$work/quotes-chrome.json"
check "completed review quoting '- [ ]' and the error banner in its prose" \
  PASS "$work/quotes-chrome.json" 661

printf '\npassed=%d failed=%d\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
