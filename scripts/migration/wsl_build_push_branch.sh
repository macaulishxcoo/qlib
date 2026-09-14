#!/usr/bin/env bash
# 在 origin/main 之上构造只含本项目研究成果的分支 (可续跑; 输出到日志)
set -euo pipefail

REPO=/mnt/d/workspaces/qlib
BRANCH=research/daily-strategy-v1
LOG=$REPO/output/live/push_branch.log
mkdir -p "$(dirname "$LOG")"
cd "$REPO"
exec >> "$LOG" 2>&1

echo "=== start $(date) ==="

if [ -s /tmp/delta.tsv ]; then
    echo "[1/4] 复用已有 /tmp/delta.tsv ($(wc -l < /tmp/delta.tsv) 行)"
else
    echo "[1/4] 计算相对 origin/main 的差异 ..."
    git diff --name-status origin/main master > /tmp/delta.tsv
fi
echo "      A=$(awk -F'\t' '$1=="A"' /tmp/delta.tsv | wc -l)  M=$(awk -F'\t' '$1=="M"' /tmp/delta.tsv | wc -l)  D=$(awk -F'\t' '$1=="D"' /tmp/delta.tsv | wc -l)"

awk -F'\t' '($1=="A") || ($1=="M" && $2 !~ /^(examples|qlib)\//)' /tmp/delta.tsv \
  | awk -F'\t' '{print $2}' | sort -u > /tmp/pushfiles.txt
echo "      推送文件数 = $(wc -l < /tmp/pushfiles.txt)"

echo "[2/4] 在 main 的 tree 上叠加 ..."
export GIT_INDEX_FILE=/tmp/idx_new
rm -f /tmp/idx_new
git read-tree "origin/main^{tree}"
echo "      read-tree 完成"
if [ ! -s /tmp/indexinfo.txt ]; then
    : > /tmp/indexinfo.txt
    while IFS= read -r p; do
        sha=$(git rev-parse "master:$p")
        printf '100644 %s\t%s\n' "$sha" "$p" >> /tmp/indexinfo.txt
    done < /tmp/pushfiles.txt
fi
git update-index --index-info < /tmp/indexinfo.txt
echo "      update-index 完成"
TREE=$(git write-tree)
echo "      tree = $TREE"
unset GIT_INDEX_FILE

echo "[3/4] 建立 commit (parent = origin/main) ..."
NEW=$(git commit-tree "$TREE" -p origin/main -F /tmp/commitmsg.txt)
echo "      commit = $NEW"
git branch -f "$BRANCH" "$NEW"

echo "[4/4] 完成"
git log --oneline -2 "$BRANCH"
echo "      相对 main 改动文件数 = $(git diff --name-status origin/main "$BRANCH" | wc -l)"
echo "=== exit=$? $(date) ==="
