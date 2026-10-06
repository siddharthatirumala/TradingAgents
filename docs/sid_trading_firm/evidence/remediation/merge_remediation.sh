#!/usr/bin/env bash
# Merge one remediation PR (#27-#31) under the owner's explicit instruction of 2026-10-05.
# Merge commit only; no squash, no force-push, no branch deletion. Halts (exit 1) on anything unexpected.
#
# usage: merge_remediation.sh <pr> <expected-head-sha> <expected-main-sha> "<expected commits>" <expected-merged-tree>
#
# The upstream suite is verified by GitHub Linux CI only: since PR #27 the fail-closed checker
# rejects the Windows yfinance failure (its exception ended at the Phase 1A gate) and no
# exception is extended. Locally: SID unit suite, migrations round trip and ruff on the merged tree.
set -u
N=$1; HEAD_EXP=$2; MAIN_EXP=$3; COMMITS_EXP=$4; TREE_EXP=$5
R=siddharthatirumala/TradingAgents
REPO="<HOME>/OneDrive/Desktop/Stories/projects/TradingAgents"
RV="<HOME>/AppData/Local/Temp/claude/C--Users-<USER>-OneDrive-Desktop-Stories-projects-TradingAgents/4df687cf-0c5c-44d8-a264-85829659b34f/scratchpad/review"
PY="$REPO/.venv/Scripts/python.exe"
WT="$RV/wt-rem-pr$N"
cleanup() { cd "$REPO" 2>/dev/null; [ -d "$WT" ] && git worktree remove --force "$WT" >/dev/null 2>&1; git worktree prune; }
stop() { echo "STOP (PR #$N): $*"; cleanup; exit 1; }
say() { echo "$*"; }

cd "$REPO" && git fetch -q origin || stop "fetch failed"

# 1. main is exactly what the previous step left
[ "$(git rev-parse origin/main)" = "$MAIN_EXP" ] || stop "origin/main is $(git rev-parse --short origin/main), expected ${MAIN_EXP:0:7}"
say "[main] origin/main == ${MAIN_EXP:0:7}"

# 2. identity: open, base main, exact head, exact commits
info=$(gh pr view "$N" --repo $R --json state,baseRefName,headRefOid,isDraft -q '"\(.state) \(.baseRefName) \(.headRefOid) \(.isDraft)"')
[ "$info" = "OPEN main $HEAD_EXP false" ] || stop "PR state/base/head/draft is [$info], expected [OPEN main $HEAD_EXP false]"
api=$(gh api "repos/$R/pulls/$N/commits?per_page=100" --jq '[.[].sha[0:7]]|join(" ")')
[ "$api" = "$COMMITS_EXP" ] || stop "PR commits [$api] != expected [$COMMITS_EXP]"
say "[identity] head=${HEAD_EXP:0:7} base=main commits: $api"

# 3. diff: GitHub Files Changed == the PR's own patch; no governance file
mb=$(git merge-base "$MAIN_EXP" "$HEAD_EXP")
own=$(git diff --name-status "$mb" "$HEAD_EXP")
api_files=$(gh api "repos/$R/pulls/$N/files?per_page=100" --jq '.[].filename' | sort)
[ "$(echo "$own" | cut -f2- | sort)" = "$api_files" ] || stop "GitHub Files Changed differs from the PR's own patch"
echo "$own" | grep -qE '(^|\s)(AGENTS\.md|docs/GOVERNANCE\.md)$' && stop "PR changes a governance file"
say "[diff] $(git diff --shortstat "$mb" "$HEAD_EXP" | sed 's/^ //') since merge base ${mb:0:7}"
echo "$own" | sed 's/^/           /'

# 4. local merge result: conflict-free and equal to the predicted tree
cleanup; git worktree add -q --detach "$WT" "$MAIN_EXP" || stop "worktree add failed"
( cd "$WT" && git -c user.name=validator -c user.email=validator@local merge -q --no-ff --no-edit "$HEAD_EXP" ) >/dev/null 2>&1 \
  || stop "merge conflict against main"
actual=$(cd "$WT" && git rev-parse HEAD^{tree})
[ "$actual" = "$TREE_EXP" ] || stop "merged tree $actual != predicted $TREE_EXP"
say "[merge] conflict-free; merged tree == predicted (${actual:0:12})"

# 5. local validation on the merged tree (imports from the worktree)
cd "$WT"
where=$("$PY" -c "import tradingagents, sid_trading_firm; print(tradingagents.__file__, sid_trading_firm.__file__)")
case "$where" in *"wt-rem-pr$N"*"wt-rem-pr$N"*) ;; *) stop "imports resolve outside the worktree";; esac
sid=$("$PY" -m pytest tests_sid -q -p no:cacheprovider -m "not integration" 2>&1 | tail -1)
echo "$sid" | grep -qE "failed|error" && stop "SID suite: $sid"
echo "$sid" | grep -q passed || stop "SID suite produced no result: $sid"
say "[sid] $sid"
mig=$("$PY" - <<'EOF' 2>&1 | tail -1
import pathlib, tempfile
from sqlalchemy import inspect
from sid_trading_firm.persistence import make_engine
from sid_trading_firm.persistence.migrate import upgrade, downgrade
p = pathlib.Path(tempfile.mkdtemp()) / "m.db"; url = f"sqlite:///{p.as_posix()}"
upgrade(url); e = make_engine(url); t = sorted(inspect(e).get_table_names()); e.dispose()
downgrade(url, "base"); e = make_engine(url); a = sorted(inspect(e).get_table_names()); e.dispose()
upgrade(url); print(f"upgrade {len(t)} tables, downgrade {a}, re-upgrade ok")
EOF
)
echo "$mig" | grep -q "re-upgrade ok" || stop "migration round trip failed: $mig"
say "[migrations] $mig"
lint=$("$REPO/.venv/Scripts/ruff.exe" check . 2>&1 | tail -1)
[ "$lint" = "All checks passed!" ] || stop "ruff: $lint"
say "[ruff] $lint"
cd "$REPO"

# 6. GitHub CI green on the exact head (pull_request event), both workflows, every job
for wf in "CI" "SID Trading Firm CI"; do
  line=$(gh run list --repo $R --commit "$HEAD_EXP" --event pull_request --workflow "$wf" --limit 1 \
         --json databaseId,status,conclusion,headSha -q '.[0] | "\(.databaseId) \(.status) \(.conclusion) \(.headSha)"')
  set -- $line
  [ "${2:-}" = completed ] && [ "${3:-}" = success ] && [ "${4:-}" = "$HEAD_EXP" ] || stop "'$wf' on ${HEAD_EXP:0:7} is [$line]"
  bad=$(gh run view "$1" --repo $R --json jobs -q '[.jobs[] | select(.conclusion != "success")] | length')
  [ "$bad" = 0 ] || stop "'$wf' run $1 has $bad non-successful job(s)"
  say "[ci-pr] '$wf' run $1 on ${HEAD_EXP:0:7}: success, all jobs green"
done
gl=$(gh run list --repo $R --commit "$HEAD_EXP" --event pull_request --workflow "SID Trading Firm CI" --limit 1 --json databaseId -q '.[0].databaseId')
say "[gitleaks] $(gh run view "$gl" --repo $R --log 2>/dev/null | sed -E 's/\x1b\[[0-9;]*m//g' | awk -F'\t' '$1=="gitleaks"' | grep -oE '[0-9]+ commits scanned|no leaks found|leaks found: [0-9]+' | sort -u | tr '\n' ' ')"
state=$(gh pr view "$N" --repo $R --json mergeStateStatus -q .mergeStateStatus)
[ "$state" = CLEAN ] || stop "merge state is $state, not CLEAN"

# 7. merge commit, pinned to the exact head; branch kept
gh pr merge "$N" --repo $R --merge --match-head-commit "$HEAD_EXP" >/dev/null || stop "gh pr merge failed"
sleep 5; git fetch -q origin
new=$(git rev-parse origin/main)
[ "$(git rev-parse "$new^1")" = "$MAIN_EXP" ] && [ "$(git rev-parse "$new^2")" = "$HEAD_EXP" ] \
  || stop "main ${new:0:7} parents are not (${MAIN_EXP:0:7}, ${HEAD_EXP:0:7})"
[ "$(git rev-parse "$new^{tree}")" = "$TREE_EXP" ] || stop "main tree $(git rev-parse "$new^{tree}") != predicted $TREE_EXP"
[ "$(gh pr view "$N" --repo $R --json state -q .state)" = MERGED ] || stop "PR not reported MERGED"
say "[merged] ${new:0:7} = merge(${MAIN_EXP:0:7}, ${HEAD_EXP:0:7}); tree == predicted"

# 8. main CI after the merge (push event), both workflows, every job
for wf in "CI" "SID Trading Firm CI"; do
  run=""
  for i in $(seq 1 40); do
    run=$(gh run list --repo $R --commit "$new" --event push --workflow "$wf" --limit 1 --json databaseId -q '.[0].databaseId // empty')
    [ -n "$run" ] && break; sleep 15
  done
  [ -n "$run" ] || stop "no '$wf' push run on main ${new:0:7}"
  gh run watch "$run" --repo $R --interval 20 >/dev/null 2>&1
  c=$(gh run view "$run" --repo $R --json conclusion -q .conclusion)
  [ "$c" = success ] || stop "'$wf' run $run on main ${new:0:7}: $c"
  say "[ci-main] '$wf' run $run on ${new:0:7}: success"
done
cleanup
say "MERGED PR #$N -> main $new"
