#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path
import sys
import os

def run_command(cmd, check=True, capture_output=False):
    """
    Run command and return result
    """
    result = subprocess.run(cmd, shell=True, capture_output=capture_output, text=True)
    if check and result.returncode != 0:
        print(f"Command failed: {cmd}")
        sys.exit(1)

    return result

def get_gh_json(cmd):
    """
    Run gh command and return json output
    """
    result = subprocess.run(cmd, check=False, capture_output=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return f"Command failed:{cmd}"

def main():
    if len(sys.argv) < 3:
        print("Usage: python script.py <REPO_NAME> <PR_NUMBER>")
        sys.exit(1)
    
    REPO_NAME = sys.argv[1]
    PR_NUMBER = sys.argv[2]
    TARGET_REPO = "Child_repo_mirror"
    BRANCH_NAME = f"auto-update-from-{REPO_NAME}-pr-{PR_NUMBER}"

    GH_TOKEN = subprocess.getenv('GH_TOKEN')
    GITHUB_REPOSITORY = subprocess.getenv('GITHUB_REPOSITORY')
    COMMENT_BODY = subprocess.getenv('COMMENT_BODY', '')

    run_command(f"rm -rf {TARGET_REPO}")
    run_command(f"git clone https://{GH_TOKEN}@github.com/QuietHellsPage/{TARGET_REPO}.git")

    target_path = Path(TARGET_REPO)
    os.chdir(target_path)

    run_command('git config user.name "github-actions[bot]"')
    run_command('git config user.email "41898282+github-actions[bot]@users.noreply.github.com"')

    labels = get_gh_json(f"gh label list --repo QuietHellsPage/{TARGET_REPO} --json name")
    label_exists = any(label.get('name') == 'automated pr' for label in labels or [])
    
    if not label_exists:
        run_command(f'gh label create "automated pr" --color "0E8A16" --description "Automated pull request" --repo QuietHellsPage/{TARGET_REPO}')

    branch_check = run_command(f"git show-ref --quiet refs/remotes/origin/{BRANCH_NAME}", check=False)
    if branch_check.returncode == 0:
        run_command(f"git checkout {BRANCH_NAME}")
        run_command(f"git pull origin {BRANCH_NAME}")
    else:
        run_command(f"git checkout -b {BRANCH_NAME}")
    

    if COMMENT_BODY and COMMENT_BODY != "":
        pr_info = get_gh_json(f"gh pr view {PR_NUMBER} --repo {GITHUB_REPOSITORY} --json headRefName")
        PR_BRANCH = pr_info.get('headRefName') if pr_info else ""
        SOURCE_REF = f"parent-repo/{PR_BRANCH}" if PR_BRANCH else ""
    else:
        PR_BRANCH = "main"
        SOURCE_REF = "parent-repo/main"

    if not PR_BRANCH:
        sys.exit(0)

    run_command("git remote add parent-repo https://github.com/$GITHUB_REPOSITORY.git")
    run_command("git fetch parent-repo")

    pr_files_data = get_gh_json(f"gh pr view {PR_NUMBER} --repo {GITHUB_REPOSITORY} --json files")
    CHANGED_FILES = [file['path'] for file in (pr_files_data or [])] if pr_files_data else []

    if not CHANGED_FILES:
        print(f"No changed files found in PR {PR_NUMBER}")
        sys.exit(0)
    
    JSON_EXISTS = False
    JSON_CONTENT = None
    
    json_check = run_command(f"git show {SOURCE_REF}:autosync/test_files.json", check=False, capture_output=True)
    if json_check.returncode == 0:
        try:
            JSON_CONTENT = json.loads(json_check.stdout)
            JSON_EXISTS = True
        except json.JSONDecodeError:
            JSON_EXISTS = False
    else:
        sys.exit(0)

    TEST_JSON_CHANGED = False
    HAS_CHANGES = False
    FILES_TO_SYNC_FOUND = False

    if "autosync/test_files.json" in CHANGED_FILES:
        print("test_files.json changed in PR, applying changes first")
        json_content_cmd = run_command(f"git show {SOURCE_REF}:autosync/test_files.json", capture_output=True)
        if json_content_cmd.returncode == 0:
            test_files_path = Path("autosync/test_files.json")
            test_files_path.parent.mkdir(parents=True, exist_ok=True)
            test_files_path.write_text(json_content_cmd.stdout)
            
            run_command("git add autosync/test_files.json")
            TEST_JSON_CHANGED = True
            HAS_CHANGES = True
            
            try:
                JSON_CONTENT = json.loads(json_content_cmd.stdout)
                JSON_EXISTS = True
                print("Successfully updated test_files.json with new mappings")
            except json.JSONDecodeError:
                print("Updated test_files.json is invalid JSON")
                sys.exit(1)

    for file in CHANGED_FILES:
        if file == "autosync/test_files.json":
            continue
            
        if JSON_EXISTS:
            targets = []
            for mapping in JSON_CONTENT:
                if mapping.get('source') == file:
                    target = mapping.get('target')
                    if target:
                        targets.append(target)
            
            if targets:
                FILES_TO_SYNC_FOUND = True
                break

    if not FILES_TO_SYNC_FOUND and not TEST_JSON_CHANGED:
        print(f"No files to sync found in PR {PR_NUMBER}")
        sys.exit(0)

    for file in CHANGED_FILES:
        if file == "autosync/test_files.json":
            continue
            
        if JSON_EXISTS:
            targets = []
            for mapping in JSON_CONTENT:
                if mapping.get('source') == file:
                    target = mapping.get('target')
                    if target:
                        targets.append(target)
            
            for target_dir in targets:
                if target_dir:
                    target_path = Path(target_dir)
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    file_content_cmd = run_command(f'git show {SOURCE_REF}:"{file}"', check=False, capture_output=True)
                    if file_content_cmd.returncode == 0:
                        target_path.write_text(file_content_cmd.stdout)
                        run_command(f'git add "{target_dir}"')
                        HAS_CHANGES = True
                        print(f"Synced file: {file} -> {target_dir}")
                    else:
                        print(f"Warning: Could not read file {file} from {SOURCE_REF}")

    deleted_files = []
    if pr_files_data:
        for file_info in pr_files_data:
            if file_info.get('status') == 'removed':
                deleted_files.append(file_info['path'])

    for deleted_file in deleted_files:
        if JSON_EXISTS:
            targets = []
            for mapping in JSON_CONTENT:
                if mapping.get('source') == deleted_file:
                    target = mapping.get('target')
                    if target:
                        targets.append(target)
            
            for target_path in targets:
                if target_path and Path(target_path).exists():
                    run_command(f'git rm "{target_path}"', check=False)
                    run_command(f'rm -f "{target_path}"', check=False)
                    HAS_CHANGES = True
                    print(f"Removed synced file: {target_path} (source: {deleted_file})")

    if HAS_CHANGES:
        if TEST_JSON_CHANGED and not FILES_TO_SYNC_FOUND:
            run_command(f'git commit -m "Update sync mapping from {REPO_NAME} PR {PR_NUMBER}"')
        else:
            run_command(f'git commit -m "Sync changes from {REPO_NAME} PR {PR_NUMBER}"')
        
        run_command(f"git push origin {BRANCH_NAME}")
        print(f"Successfully pushed changes to {BRANCH_NAME}")
    else:
        print("No changes to commit")
        sys.exit(0)

    pr_list = get_gh_json(f"gh pr list --repo QuietHellsPage/{TARGET_REPO} --head {BRANCH_NAME} --json number")
    TARGET_PR_NUMBER = pr_list[0]['number'] if pr_list and len(pr_list) > 0 else None

    commit_check = run_command(f"git log --oneline origin/main..{BRANCH_NAME}", capture_output=True)
    if commit_check.stdout.strip():
        if not TARGET_PR_NUMBER:
            run_command(f"""gh pr create \
                --repo QuietHellsPage/{TARGET_REPO} \
                --head {BRANCH_NAME} \
                --base main \
                --title "[Automated] Sync from {REPO_NAME} PR {PR_NUMBER}" \
                --fill \
                --label "automated pr" \
                --assignee QuietHellsPage \
                --reviewer QuietHellsPage""")
            print("Created new PR in target repository")
        else:
            run_command(f"gh pr comment {TARGET_PR_NUMBER} --repo QuietHellsPage/{TARGET_REPO} --body 'Automatically updated'")
            print(f"Updated existing PR #{TARGET_PR_NUMBER} in target repository")
    else:
        print(f"No commits in branch {BRANCH_NAME} - skipping PR creation")


if __name__ == "__main__":
    main()