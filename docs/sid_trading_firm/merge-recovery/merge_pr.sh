#!/usr/bin/env bash
# Validate and merge one PR under delegated merge authority (docs/GOVERNANCE.md section 26).
# Halts (exit 1) on any unexpected condition. Merge commit only; never force-push; keeps branches.
#
# usage: merge_pr.sh <pr> <expected-head-short> <expected-main-sha> "<expected unique commits>" [allow-governance]
set -u
N=$1; HEAD_EXP=$2; MAIN_EXP=$3; COMMITS_EXP=$4; ALLOW_GOV=${5:-no}
R=siddharthatirumala/TradingAgents
REPO="<HOME>/OneDrive/Desktop/Stories/projects/TradingAgents"
RV="<HOME>/AppData/Local/Temp/claude/C--Users-<HOME>-OneDrive-Desktop-Stories-projects-TradingAgents/4df687cf-0c5c-44d8-a264-85829659b34f/scratchpad/review"
PY="$REPO/.venv/Scripts/python.exe"
WT="$RV/wt-merge-pr$N"
stop() { echo "STOP (PR #$N): $*"; cleanup; exit 1; }
cleanup() { cd "$REPO" 2>/dev/null; [ -d "$WT" ] && git worktree remove --force "$WT" >/dev/null 2>&1; git worktree prune; rm -f "$RV/idx-$N"; }
say() { echo "$*"; }

cd "$REPO" && git fetch -q origin || stop "fetch failed"

# 0. main is exactly what the previous step left
[ "$(git rev-parse origin/main)" = "$MAIN_EXP" ] || stop "origin/main is $(git rev-parse --short origin/main), expected ${MAIN_EXP:0:7} (unexpected main change)"
say "[main] origin/main == ${MAIN_EXP:0:7}"

# 1. target main (chained PRs are retargeted explicitly; base branches are never deleted first)
base=$(gh api repos/$R/pulls/$N --jq .base.ref); retargeted=no
if [ "$base" != main ]; then
  gh pr edit "$N" --repo $R --base main >/dev/null || stop "could not retarget to main"
  sleep 5; retargeted=yes
  [ "$(gh api repos/$R/pulls/$N --jq .base.ref)" = main ] || stop "retarget did not take"
fi

# 2. identity and unique commits
[ "$(gh api repos/$R/pulls/$N --jq .state)" = open ] || stop "PR not open"
head=$(gh api repos/$R/pulls/$N --jq .head.sha)
[ "${head:0:7}" = "$HEAD_EXP" ] || stop "head is ${head:0:7}, expected $HEAD_EXP"
unique=$(git log --reverse --format=%h --abbrev=7 "$MAIN_EXP..$head" | tr '\n' ' ' | sed 's/ $//')
[ "$unique" = "$COMMITS_EXP" ] || stop "unique commits vs main [$unique] != expected [$COMMITS_EXP]"
api=$(gh api "repos/$R/pulls/$N/commits?per_page=100" --jq '[.[].sha[0:7]]|join(" ")')
[ "$api" = "$COMMITS_EXP" ] || stop "GitHub PR commits [$api] != expected"
say "[identity] head=${head:0:7} base=main (retargeted: $retargeted); unique: $unique"

# 3. incremental diff = the PR's own patch from its merge base with main
mb=$(git merge-base "$MAIN_EXP" "$head")
own=$(git diff --name-status "$mb" "$head")
api_files=$(gh api "repos/$R/pulls/$N/files?per_page=100" --jq '.[].filename' | sort)
[ "$(echo "$own" | cut -f2- | sort)" = "$api_files" ] || stop "GitHub Files Changed differs from the PR's own patch"
if [ "$ALLOW_GOV" != allow-governance ]; then
  echo "$own" | grep -qE '(^|\s)(AGENTS\.md|docs/GOVERNANCE\.md)$' && stop "PR changes a governance file"
fi
say "[diff] $(git diff --shortstat "$mb" "$head" | sed 's/^ //') since merge base ${mb:0:7}"
echo "$own" | sed 's/^/           /'

# 4. merge result == main + the PR's own patch, conflict-free
cleanup; git worktree add -q --detach "$WT" "$MAIN_EXP" || stop "worktree add failed"
( cd "$WT" && git -c user.name=validator -c user.email=validator@local merge -q --no-ff --no-edit "$head" ) >/dev/null 2>&1 || stop "merge conflict against main"
actual=$(cd "$WT" && git rev-parse HEAD^{tree})
GIT_INDEX_FILE="$RV/idx-$N" git read-tree "$MAIN_EXP"
git diff --binary "$mb" "$head" | GIT_INDEX_FILE="$RV/idx-$N" git apply --cached || stop "PR patch does not apply cleanly to main"
expected=$(GIT_INDEX_FILE="$RV/idx-$N" git write-tree); rm -f "$RV/idx-$N"
[ "$actual" = "$expected" ] || stop "merge tree $actual != main + PR patch $expected"
say "[merge] conflict-free; merged tree == main + PR patch (${actual:0:12})"

# 5. local validation on the merged tree
cd "$WT"
where=$("$PY" -c "import tradingagents, sid_trading_firm; print(tradingagents.__file__, sid_trading_firm.__file__)")
case "$where" in *"wt-merge-pr$N"*"wt-merge-pr$N"*) ;; *) stop "imports resolve outside the worktree";; esac
export PYTHONPATH="$RV"
SID_VALIDATION_REPORT="$RV/evidence/merge_pr${N}_upstream.jsonl" "$PY" -m pytest -q -p no:cacheprovider -p sid_validation_plugin > "$RV/evidence/merge_pr${N}_upstream.txt" 2>&1
say "[upstream] $(tail -1 "$RV/evidence/merge_pr${N}_upstream.txt")"
"$PY" "$RV/check_upstream_failures.py" "$RV/evidence/merge_pr${N}_upstream.jsonl" "$RV/windows_exceptions.json" > "$RV/evidence/merge_pr${N}_check.txt"
ok=$?; sed 's/^/           /' "$RV/evidence/merge_pr${N}_check.txt"
[ $ok = 0 ] || stop "upstream suite failed the exception checker"
sid=$("$PY" -m pytest tests_sid -q -p no:cacheprovider 2>&1 | tail -1)
echo "$sid" | grep -qE "failed|error" && stop "SID suite: $sid"
echo "$sid" | grep -q passed || stop "SID suite produced no result: $sid"
say "[sid] $sid"
if [ -d sid_trading_firm/persistence/migrations ]; then
  mig=$("$PY" -c "
import tempfile, pathlib
from sqlalchemy import inspect
from sid_trading_firm.persistence.migrate import upgrade, downgrade
from sid_trading_firm.persistence import make_engine
p = pathlib.Path(tempfile.mkdtemp()) / 'm.db'; url = f'sqlite:///{p.as_posix()}'
upgrade(url); e = make_engine(url); t = sorted(inspect(e).get_table_names()); e.dispose()
downgrade(url, 'base'); e = make_engine(url); a = sorted(inspect(e).get_table_names()); e.dispose()
upgrade(url); print('upgrade', t, 'downgrade', a, 're-upgrade ok')" 2>&1 | tail -1)
  echo "$mig" | grep -q "re-upgrade ok" || stop "migration round trip failed: $mig"
  say "[migrations] $mig"
fi
lint=$("$REPO/.venv/Scripts/ruff.exe" check . 2>&1 | tail -1)
[ "$lint" = "All checks passed!" ] || stop "ruff: $lint"
say "[ruff] $lint"
cleanup

# 6. CI on the exact head commit (fresh re-run after a retarget)
for wf in "CI" "SID Trading Firm CI"; do
  run=$(gh run list --repo $R --commit "$head" --event pull_request --workflow "$wf" --json databaseId --jq '[.[].databaseId]|max // 0')
  [ "$run" -gt 0 ] || stop "no '$wf' run for ${head:0:7}"
  status=$(gh run view "$run" --repo $R --json status --jq .status)
  if [ "$status" = completed ] && [ "$retargeted" = yes ]; then
    gh run rerun "$run" --repo $R >/dev/null 2>&1 || stop "could not re-run '$wf'"; sleep 8
  fi
  gh run watch "$run" --repo $R --exit-status --interval 15 >/dev/null 2>&1 || stop "'$wf' run $run failed on ${head:0:7}"
  sha=$(gh run view "$run" --repo $R --json headSha --jq .headSha)
  [ "$sha" = "$head" ] || stop "'$wf' run $run is for $sha, not $head"
  bad=$(gh run view "$run" --repo $R --json jobs --jq '[.jobs[]|select(.conclusion!="success")]|length')
  [ "$bad" = 0 ] || stop "'$wf' run $run has non-successful jobs"
  say "[ci-pr] '$wf' run $run on ${head:0:7}: $(gh run view "$run" --repo $R --json jobs,attempt --jq '"attempt \(.attempt): \([.jobs[]|.conclusion]|group_by(.)|map("\(.[0])=\(length)")|join(" "))"')"
done

# 7. merge (merge commit; branch kept)
[ "$(git ls-remote origin refs/heads/main | cut -f1)" = "$MAIN_EXP" ] || stop "main moved before merge"
gh pr merge "$N" --repo $R --merge >/dev/null 2>&1
[ "$(gh api repos/$R/pulls/$N --jq .merged)" = true ] || stop "merge did not complete"
mc=$(gh api repos/$R/pulls/$N --jq .merge_commit_sha)
git fetch -q origin
[ "$(git rev-parse origin/main)" = "$mc" ] || stop "main is not at the merge commit"
[ "$(git rev-list --parents -n 1 "$mc" | cut -d' ' -f2-)" = "$MAIN_EXP $head" ] || stop "merge commit parents unexpected"
[ "$(git rev-parse "$mc^{tree}")" = "$actual" ] || stop "main tree differs from the validated merge tree"
say "[merged] ${mc:0:7} = merge(${MAIN_EXP:0:7}, ${head:0:7}); tree == validated tree"

# 8. CI on main for the merge commit, before anything else merges
for wf in "CI" "SID Trading Firm CI"; do
  for i in $(seq 1 40); do
    run=$(gh run list --repo $R --commit "$mc" --event push --workflow "$wf" --json databaseId --jq '[.[].databaseId]|max // 0')
    [ "$run" -gt 0 ] && break; sleep 6
  done
  [ "$run" -gt 0 ] || stop "no '$wf' run on main for ${mc:0:7}"
  gh run watch "$run" --repo $R --exit-status --interval 15 >/dev/null 2>&1 || stop "'$wf' failed on main ${mc:0:7} (run $run)"
  say "[ci-main] '$wf' run $run on ${mc:0:7}: success"
done
say "MERGED PR #$N -> main ${mc}"
