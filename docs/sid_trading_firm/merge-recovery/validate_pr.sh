#!/usr/bin/env bash
# Review-mode validation of one Phase 1A PR against an anchored main. Never merges, retargets or pushes.
# Exits non-zero (STOP) on any unexpected condition.
#
# usage: PHASE=<validation phase> validate_pr.sh <pr> <expected-head> <previous-pr-head> "<expected unique commits>" <anchor-main-sha>
set -u
PHASE=${PHASE:?set PHASE to the validation phase (exceptions apply only within their recorded scope)}
N=$1; HEAD_EXP=$2; PREV=$3; COMMITS_EXP=$4; ANCHOR=$5
R=siddharthatirumala/TradingAgents
REPO="<HOME>/OneDrive/Desktop/Stories/projects/TradingAgents"
RV="<HOME>/AppData/Local/Temp/claude/C--Users-<HOME>-OneDrive-Desktop-Stories-projects-TradingAgents/4df687cf-0c5c-44d8-a264-85829659b34f/scratchpad/review"
PY="$REPO/.venv/Scripts/python.exe"
WT="$RV/wt-pr$N"
# Governance files committed directly to main; preserved at exactly these blobs.
GOV_AGENTS=2ff76018acf612058e36daab108cca931c9c8e8d
GOV_GOVERNANCE=4cb8ff105c7630b23bf6565aedee308b52ee2c30
# Expected first-parent history of the anchor, newest first (anchor .. upstream pin).
EXPECTED_CHAIN="059b9ffad6889b4909b4236d136d2619f8e745ec 5307185a9d7f58ed478acf14c41529d7a21e7657 08a643e55c92c3ba85327ede0d19866b7a29487e 3b42234c8b64 35dd01be2d60 b0320c9565d9 1394a3f72aa4393e1a98f51b382434c4b4c2d972"
FLAKY="tests/test_memory_log.py::test_concurrent_writers_keep_every_decision_and_outcome"

stop() { echo "STOP (PR #$N): $*"; cleanup; exit 1; }
cleanup() { cd "$REPO" 2>/dev/null; [ -d "$WT" ] && git worktree remove --force "$WT" >/dev/null 2>&1; git worktree prune; }
say() { echo "$*"; }

cd "$REPO" && git fetch -q origin || stop "fetch failed"

# --- 0. main must be exactly the anchor ---------------------------------------------------------
main_now=$(git rev-parse origin/main)
[ "$main_now" = "$ANCHOR" ] || stop "origin/main is $main_now, not the anchor $ANCHOR (unexpected main change)"
say "[anchor] origin/main == $ANCHOR"

# --- 1. ancestry -------------------------------------------------------------------------------
chain=$(git log --first-parent --format=%H "$ANCHOR" | head -7)
i=0
for want in $EXPECTED_CHAIN; do
  i=$((i+1)); got=$(echo "$chain" | sed -n "${i}p")
  case "$got" in "$want"*) ;; *) stop "first-parent ancestry position $i is $got, expected $want";; esac
done
git merge-base --is-ancestor "$PREV" "$ANCHOR" || stop "previous PR head $PREV is not in main"
say "[ancestry] first-parent chain matches (anchor -> governance x2 -> #3 -> #2 -> #1 -> upstream pin); $PREV in main"

# --- 2. governance blobs and anchor tree -------------------------------------------------------
[ "$(git rev-parse "$ANCHOR:AGENTS.md")" = "$GOV_AGENTS" ] || stop "AGENTS.md blob changed"
[ "$(git rev-parse "$ANCHOR:docs/GOVERNANCE.md")" = "$GOV_GOVERNANCE" ] || stop "docs/GOVERNANCE.md blob changed"
extra=$(diff <(git ls-tree -r "$PREV") <(git ls-tree -r "$ANCHOR") | grep '^[<>]')
want_extra=$(printf '> 100644 blob %s\tAGENTS.md\n> 100644 blob %s\tdocs/GOVERNANCE.md' "$GOV_AGENTS" "$GOV_GOVERNANCE")
[ "$extra" = "$want_extra" ] || stop "anchor tree differs from $PREV by more than the two governance files: $extra"
say "[governance] AGENTS.md=$GOV_AGENTS docs/GOVERNANCE.md=$GOV_GOVERNANCE; anchor tree = $PREV tree + exactly these two"

# --- 3. PR identity and unique commits ---------------------------------------------------------
state=$(gh api repos/$R/pulls/$N --jq .state); head=$(gh api repos/$R/pulls/$N --jq .head.sha)
base=$(gh api repos/$R/pulls/$N --jq .base.ref); base_sha=$(gh api repos/$R/pulls/$N --jq .base.sha)
[ "$state" = open ] || stop "PR is $state"
[ "${head:0:7}" = "$HEAD_EXP" ] || stop "head is ${head:0:7}, expected $HEAD_EXP"
unique=$(git log --reverse --format=%h --abbrev=7 "$ANCHOR..$head" | tr '\n' ' ' | sed 's/ $//')
[ "$unique" = "$COMMITS_EXP" ] || stop "unique commits vs main [$unique] != expected [$COMMITS_EXP]"
api_commits=$(gh api repos/$R/pulls/$N/commits --jq '[.[].sha[0:7]]|join(" ")')
[ "$api_commits" = "$COMMITS_EXP" ] || stop "GitHub PR commits [$api_commits] != expected"
say "[identity] open, head=$head, current base=$base@${base_sha:0:7} (not retargeted: paused)"
say "[commits] unique vs main: $unique"
git log --reverse --format='           %h %s' "$ANCHOR..$head"

# --- 4. incremental diff ------------------------------------------------------------------------
own=$(git diff --name-status "$PREV" "$head")
vs_main=$(git diff --name-status "$ANCHOR...$head")
[ "$own" = "$vs_main" ] || stop "diff vs main differs from the PR's own delta"
api_files=$(gh api "repos/$R/pulls/$N/files?per_page=100" --jq '.[].filename' | sort)
[ "$(echo "$own" | cut -f2- | sort)" = "$api_files" ] || stop "GitHub Files Changed differs from the PR's own delta"
echo "$own" | grep -qE '(^|\s)(AGENTS\.md|docs/GOVERNANCE\.md)$' && stop "PR touches a governance file"
dup=$(git diff --name-only "$PREV" "$head" -- $(git diff --name-only 1394a3f72aa4393e1a98f51b382434c4b4c2d972 "$PREV" | grep -v '^$') 2>/dev/null)
say "[diff] $(git diff --shortstat "$PREV" "$head" | sed 's/^ //') (own delta == diff vs main == GitHub Files Changed)"
git diff --stat=100 "$PREV" "$head" | sed 's/^/           /'
[ -z "$dup" ] && say "[duplication] PR modifies no file introduced by earlier Phase 1A PRs" \
             || say "[duplication] PR edits earlier Phase 1A files (incremental, not duplicated): $(echo $dup)"

# --- 5. merge tree ------------------------------------------------------------------------------
cleanup; git worktree add -q --detach "$WT" "$ANCHOR" || stop "worktree add failed"
cd "$WT"
git -c user.name=validator -c user.email=validator@local merge -q --no-ff --no-edit "$head" >/dev/null 2>&1 || stop "merge conflict against main"
tree_diff=$(diff <(git ls-tree -r "$head") <(git ls-tree -r HEAD) | grep '^[<>]')
[ "$tree_diff" = "$want_extra" ] || stop "merged tree != PR head tree + governance blobs: $tree_diff"
say "[merge] conflict-free; merged tree = PR head tree + exactly the two governance blobs (entry-by-entry ls-tree)"

# --- 6. local validation (imports from the worktree, no network, no paid calls) -----------------
where=$("$PY" -c "import tradingagents, sid_trading_firm; print(tradingagents.__file__, sid_trading_firm.__file__)")
case "$where" in *"wt-pr$N"*"wt-pr$N"*) ;; *) stop "imports resolve outside the worktree";; esac
export PYTHONPATH="$RV"
SID_VALIDATION_REPORT="$RV/evidence/pr${N}_upstream.jsonl" "$PY" -m pytest -q -p no:cacheprovider -p sid_validation_plugin > "$RV/evidence/pr${N}_upstream.txt" 2>&1
pytest_code=$?
say "[upstream] $(tail -1 "$RV/evidence/pr${N}_upstream.txt") (exit $pytest_code)"
check_args=(--pytest-exit-code "$pytest_code" --phase "$PHASE" --gate-records "$WT/docs/PHASES.md")
"$PY" "$RV/check_upstream_failures.py" "$RV/evidence/pr${N}_upstream.jsonl" "$RV/windows_exceptions.json" "${check_args[@]}" > "$RV/evidence/pr${N}_check.txt"
check_code=$?; sed 's/^/           /' "$RV/evidence/pr${N}_check.txt"
[ $check_code = 0 ] || stop "upstream suite failed the exception checker"
sid=$(SID_VALIDATION_REPORT="$RV/evidence/pr${N}_sid.jsonl" "$PY" -m pytest tests_sid -q -p no:cacheprovider -p sid_validation_plugin 2>&1 | tail -1)
echo "$sid" | grep -qE "failed|error" && stop "SID suite: $sid"
echo "$sid" | grep -q "passed" || stop "SID suite produced no result: $sid"
say "[sid] $sid (Postgres integration deselected locally: runs in CI)"
mig=$("$PY" - <<'EOF' 2>&1
import tempfile, pathlib
from sqlalchemy import inspect
from sid_trading_firm.persistence.migrate import upgrade, downgrade
from sid_trading_firm.persistence import make_engine
p = pathlib.Path(tempfile.mkdtemp()) / "m.db"; url = f"sqlite:///{p.as_posix()}"
upgrade(url); e = make_engine(url); t = sorted(inspect(e).get_table_names()); e.dispose()
downgrade(url, "base"); e = make_engine(url); after = sorted(inspect(e).get_table_names()); e.dispose()
upgrade(url); print("upgrade->", t, "| downgrade->", after, "| re-upgrade ok")
EOF
)
echo "$mig" | grep -q "re-upgrade ok" || stop "migration round trip failed: $mig"
say "[migrations] $(echo "$mig" | tail -1)"
lint=$("$REPO/.venv/Scripts/ruff.exe" check . 2>&1 | tail -1)
[ "$lint" = "All checks passed!" ] || stop "ruff: $lint"
say "[ruff] $lint"
acc=0; rej=0; fails=0
for i in $(seq 1 30); do
  rpt="$RV/evidence/pr${N}_flaky_$i.jsonl"
  SID_VALIDATION_REPORT="$rpt" "$PY" -m pytest -q -p no:cacheprovider -p sid_validation_plugin "$FLAKY" >/dev/null 2>&1
  code=$?
  if [ $code = 0 ]; then rm -f "$rpt"
  else fails=$((fails+1)); "$PY" "$RV/check_upstream_failures.py" "$rpt" "$RV/windows_exceptions.json"          --pytest-exit-code "$code" --phase "$PHASE" --gate-records "$WT/docs/PHASES.md" >/dev/null && acc=$((acc+1)) || rej=$((rej+1)); fi
done
[ "$rej" = 0 ] || stop "$rej concurrency failure(s) on main+PR#$N did not match the exception signature"
say "[reproduction] $FLAKY on main+PR#$N: $fails/30 failed, all $acc accepted by the exception checker"
cleanup

# --- 7. GitHub CI: re-run this PR's own pull_request runs on the unchanged head -----------------
total=0
for wf in "CI" "SID Trading Firm CI"; do
  run=$(gh run list --repo $R --commit "$head" --event pull_request --workflow "$wf" --json databaseId --jq '[.[].databaseId]|max // 0')
  [ "$run" -gt 0 ] || stop "no existing '$wf' run for ${head:0:7}"
  status=$(gh run view "$run" --repo $R --json status --jq .status)
  if [ "$status" = completed ]; then
    gh run rerun "$run" --repo $R >/dev/null 2>&1 || stop "could not re-run '$wf' run $run"
    sleep 8
  else
    say "[ci] '$wf' run $run is already running for this head ($status); waiting for it instead of re-running"
  fi
  gh run watch "$run" --repo $R --exit-status --interval 15 >/dev/null 2>&1 || stop "fresh '$wf' run $run failed: $(gh run view "$run" --repo $R --json jobs --jq '[.jobs[]|select(.conclusion!="success")|"\(.name)=\(.conclusion)"]|join(", ")')"
  info=$(gh run view "$run" --repo $R --json attempt,headSha,jobs --jq '"attempt \(.attempt), head \(.headSha[0:7]): " + ([.jobs[]|"\(.name)=\(.conclusion)"]|join(", "))')
  n_ok=$(gh run view "$run" --repo $R --json jobs --jq '[.jobs[]|select(.conclusion=="success")]|length')
  n_bad=$(gh run view "$run" --repo $R --json jobs --jq '[.jobs[]|select(.conclusion!="success")]|length')
  [ "$n_bad" = 0 ] || stop "'$wf' run $run has non-successful jobs"
  total=$((total+n_ok))
  say "[ci] '$wf' run $run ($info)"
  if [ "$wf" = "SID Trading Firm CI" ]; then
    say "[ci] SID py3.13 unit | postgres: $(gh run view "$run" --repo $R --log 2>/dev/null | grep -E 'sid tests \(py3.13\).*passed' | sed 's/.*Z //' | tr '\n' '|')"
  fi
done
[ "$total" = 10 ] || stop "expected 10 passing CI jobs, got $total"
say "[ci] 10/10 jobs passed; runs test the PR head merged with its current base $base@${base_sha:0:7} (tree == main minus the two governance docs)"

# --- 8. main unchanged during validation ---------------------------------------------------------
git fetch -q origin
[ "$(git rev-parse origin/main)" = "$ANCHOR" ] || stop "origin/main moved during validation (unexpected main change)"
say "[anchor] origin/main still == $ANCHOR after validation"
say "VALIDATED (review only: not merged, not retargeted)"
