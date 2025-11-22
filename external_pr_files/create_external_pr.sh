#!/bin/bash
set -e

REPO_NAME=$1
PR_NUMBER=$2
TARGET_REPO="Child_repo_mirror"
BRANCH_NAME="auto-update-from-$REPO_NAME-pr-$PR_NUMBER"

COMMENT_BODY=${COMMENT_BODY:-""}

# Clone Target Repo
rm -rf $TARGET_REPO
git clone https://$GH_TOKEN@github.com/QuietHellsPage/$TARGET_REPO.git
cd $TARGET_REPO
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

# Create Label (если не существует)
if ! gh label list --repo QuietHellsPage/$TARGET_REPO --json name -q '.[] | select(.name == "automated pr")' | grep -q "automated pr"; then
    gh label create "automated pr" --color "0E8A16" --description "Automated pull request" --repo QuietHellsPage/$TARGET_REPO
fi

# Check PR and Update Branch
if git show-ref --quiet refs/remotes/origin/$BRANCH_NAME; then
    git push origin --delete $BRANCH_NAME 2>/dev/null || true
    git branch -D $BRANCH_NAME 2>/dev/null || true
    sleep 2
fi

git checkout main
git pull origin main
git checkout -b $BRANCH_NAME

CHANGED_FILES=$(gh pr view $PR_NUMBER --repo $GITHUB_REPOSITORY --json files --jq '.files[].path' 2>/dev/null || echo "")

if [ -z "$CHANGED_FILES" ]; then
    echo "No changed files found in PR $PR_NUMBER"
    exit 0
fi

JSON_EXISTS=false
if [ -f "../autosync/test_files.json" ]; then
    JSON_EXISTS=true
    JSON_CONTENT=$(cat ../autosync/test_files.json)
    
    if ! echo "$JSON_CONTENT" | jq -e . >/dev/null 2>&1; then
        JSON_EXISTS=false
    fi
else
    exit 0
fi

HAS_CHANGES=false
FILES_TO_SYNC_FOUND=false

for file in $CHANGED_FILES; do
    if [ "$JSON_EXISTS" = true ]; then
        TARGETS=$(echo "$JSON_CONTENT" | jq -r --arg file "$file" '.[] | select(.source == $file) | .target' 2>/dev/null || echo "")
        if [ -n "$TARGETS" ]; then
            FILES_TO_SYNC_FOUND=true
            break
        fi
    fi
done

if [ "$FILES_TO_SYNC_FOUND" = false ]; then
    echo "No files to sync found in PR $PR_NUMBER"
    exit 0
fi

for file in $CHANGED_FILES; do
    if [ "$JSON_EXISTS" = true ]; then
        TARGETS=$(echo "$JSON_CONTENT" | jq -r --arg file "$file" '.[] | select(.source == $file) | .target' 2>/dev/null || echo "")
        
        for TARGET_DIR in $TARGETS; do
            if [ -n "$TARGET_DIR" ]; then
                TARGET_DIR_ONLY=$(dirname "$TARGET_DIR")
                mkdir -p "$TARGET_DIR_ONLY"
                if [ -f "../$file" ]; then
                    cp "../$file" "$TARGET_DIR"
                    git add "$TARGET_DIR"
                    HAS_CHANGES=true
                fi
            fi
        done
    fi
done

PR_DELETED_FILES=$(gh pr view $PR_NUMBER --repo $GITHUB_REPOSITORY --json files --jq '.files[] | select(.status == "removed") | .path' 2>/dev/null || echo "")

for deleted_file in $PR_DELETED_FILES; do
    if [ "$JSON_EXISTS" = true ]; then
        TARGETS=$(echo "$JSON_CONTENT" | jq -r --arg file "$deleted_file" '.[] | select(.source == $file) | .target' 2>/dev/null || echo "")
        
        for TARGET_PATH in $TARGETS; do
            if [ -n "$TARGET_PATH" ] && [ -f "$TARGET_PATH" ]; then
                git rm "$TARGET_PATH" 2>/dev/null || rm "$TARGET_PATH"
                HAS_CHANGES=true
            fi
        done
    fi
done

if [ "$HAS_CHANGES" = true ]; then
    git commit -m "Sync changes from $REPO_NAME PR $PR_NUMBER"
    git push -f origin $BRANCH_NAME
    echo "Changes committed and pushed"
else
    echo "No changes to commit"
    exit 0
fi

TARGET_PR_NUMBER=$(gh pr list --repo QuietHellsPage/$TARGET_REPO --head $BRANCH_NAME --json number -q '.[0].number' 2>/dev/null || true)

if git log --oneline origin/main..$BRANCH_NAME | grep -q .; then
    if [ -z "$TARGET_PR_NUMBER" ]; then
        gh pr create \
            --repo QuietHellsPage/$TARGET_REPO \
            --head $BRANCH_NAME \
            --base main \
            --title "[Automated] Sync from $REPO_NAME PR $PR_NUMBER" \
            --fill \
            --label "automated pr" \
            --assignee QuietHellsPage \
            --reviewer QuietHellsPage
    else
        gh pr comment $TARGET_PR_NUMBER --repo QuietHellsPage/$TARGET_REPO --body "Automatically updated"
    fi
else
    echo "No commits in branch $BRANCH_NAME - skipping PR creation"
fi