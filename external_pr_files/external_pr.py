#!/usr/bin/env python3

"""
Wrapper for the bash script to generate external PR
"""

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class GHCommandException(Exception):
    """
    Raised when running GH command fails
    """


@dataclass
class CommitContextStorage:
    """
    Storage for commit information
    """
    repo_name: str
    pr_number: str
    branch_name: str
    test_json_changed: bool
    files_to_sync_found: bool
    has_changes: bool


def run_command(
    cmd: str, check: bool = True, capture_output: bool = False
) -> Optional[subprocess.CompletedProcess]:
    """
    Run command and return result
    """
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=capture_output, text=True, check=check
        )
        return result

    except subprocess.CalledProcessError as e:
        print(f"Command {cmd} failed with exit code {e.returncode}")
        sys.exit(e.returncode)


def get_gh_json(cmd: Union[str, List[str]]) -> Optional[Any]:
    """
    Run gh command and return json output
    """
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)

    result = subprocess.run(cmd, check=False, capture_output=True, text=True)

    if (exitcode := result.returncode) != 0:
        raise GHCommandException(f"Running GH command failed with exit code {exitcode}")

    try:
        return json.loads(result.stdout)

    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON from command: {cmd} due to error {e}")
        return None


def get_pr_files_data(
    pr_files_data: Union[List[Dict[str, Any]], Dict[str, Any], str, None],
) -> List[Dict[str, Any]]:
    """
    Extract file information from pr_files_data in a consistent format
    """
    files_list = []

    if not pr_files_data:
        return files_list

    if isinstance(pr_files_data, list):
        files_list = pr_files_data

    elif isinstance(pr_files_data, dict) and "files" in pr_files_data:
        files_list = pr_files_data["files"]

    elif isinstance(pr_files_data, str):
        print("Warning: PR files data is an invalid string format")
        return files_list

    valid_files = []

    for file_info in files_list:
        if isinstance(file_info, dict) and "path" in file_info:
            valid_files.append(file_info)
        else:
            print(f"Invalid file info format here: {file_info}")

    return valid_files


def setup_and_authorize(target_repo: str, gh_token: str) -> None:
    """
    Clone repo and authorize as bot
    """
    run_command(f"rm -rf {target_repo}")
    run_command(f"git clone https://{gh_token}@github.com/QuietHellsPage/{target_repo}.git")

    target_path = Path(target_repo)
    os.chdir(target_path)

    run_command('git config user.name "github-actions[bot]"')
    run_command('git config user.email "41898282+github-actions[bot]@users.noreply.github.com"')


def use_or_create_label(target_repo: str) -> None:
    """
    Ensure needed label exists or create it
    """
    labels = get_gh_json(f"gh label list --repo QuietHellsPage/{target_repo} --json name")

    label_exists = False

    if labels and isinstance(labels, list):
        label_exists = any(
            isinstance(label, dict) and label.get("name") == "automated pr" for label in labels
        )

    if not label_exists:
        run_command(
            f'gh label create "automated pr" '
            f'--color "0E8A16" '
            f'--description "Automated pull request" '
            f"--repo QuietHellsPage/{target_repo}"
        )


def setup_branch(branch_name: str) -> None:
    """
    Create new branch or checkout on it
    """
    branch_check = run_command(
        f"git show-ref --quiet refs/remotes/origin/{branch_name}", check=False
    )
    if branch_check.returncode == 0:
        run_command(f"git checkout {branch_name}")
        run_command(f"git pull origin {branch_name}")
    else:
        run_command(f"git checkout -b {branch_name}")


def get_source_ref(github_repository: str, pr_number: str, comment_body: str) -> str:
    """
    Define source ref for sync
    """
    if comment_body and comment_body != "":
        pr_info = get_gh_json(
            f"gh pr view {pr_number} --repo {github_repository} --json headRefName"
        )
        pr_branch = pr_info.get("headRefName", "") if pr_info and isinstance(pr_info, dict) else ""
        source_ref = f"parent-repo/{pr_branch}" if pr_branch else ""
    else:
        pr_branch = "main"
        source_ref = "parent-repo/main"

    return source_ref


def handle_update(source_ref: str, changed_files: List[Any]) -> tuple[bool, bool, Any]:
    """
    Process if tracked_files.json is updated in PR
    """
    test_json_changed = False
    json_exists = False
    json_content = None

    if "autosync/test_files.json" in changed_files:
        print("tracked_files.json changed in PR, applying changes first")
        json_content_cmd = run_command(
            f"git show {source_ref}:autosync/test_files.json",
            capture_output=True,
        )
        if json_content_cmd.returncode == 0:
            test_files_path = Path("autosync/test_files.json")
            test_files_path.parent.mkdir(parents=True, exist_ok=True)
            test_files_path.write_text(json_content_cmd.stdout, encoding="utf-8")

            run_command("git add autosync/test_files.json")
            test_json_changed = True

            try:
                json_content = json.loads(json_content_cmd.stdout)
                json_exists = True
                print("Successfully updated tracked_files.json with new mappings")
            except json.JSONDecodeError:
                print("Updated tracked_files.json is invalid JSON")
                sys.exit(1)

    return test_json_changed, json_exists, json_content


def has_files_for_sync(changed_files: List[str], json_content: Any) -> bool:
    """
    Check if files for synchronization exist
    """
    if not json_content:
        return False

    for file in changed_files:
        if file == "autosync/test_files.json":
            continue

        for mapping in json_content:
            if mapping.get("source") == file:
                target = mapping.get("target")
                if target:
                    return True
    return False


def sync_modified_files(changed_files: List[str], json_content: Any, source_ref: str) -> bool:
    """
    Synchronize modified files
    """
    has_changes = False

    for file in changed_files:
        if file == "autosync/test_files.json":
            continue
        if json_content:
            targets = []
            for mapping in json_content:
                if mapping.get("source") == file:
                    target = mapping.get("target")
                    if target:
                        targets.append(target)

            for target_dir in targets:
                if target_dir:
                    target_path = Path(target_dir)
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    file_content_cmd = run_command(
                        f'git show {source_ref}:"{file}"', check=False, capture_output=True
                    )

                    if file_content_cmd.returncode == 0:
                        target_path.write_text(file_content_cmd.stdout, encoding="utf-8")
                        run_command(f'git add "{target_dir}"')
                        has_changes = True
                        print(f"Synced file: {file} -> {target_dir}")
                    else:
                        print(f"Warning: Could not read file {file} from {source_ref}")

    return has_changes


def handle_deleted_files(files_data: List[Dict[str, Any]], json_content: Any) -> bool:
    """
    Handle deleted files if they are tracked
    """
    has_changes = False
    deleted_files = []

    for file_info in files_data:
        if file_info.get("status") == "removed":
            deleted_files.append(file_info.get("path"))

    for deleted_file in deleted_files:
        if json_content:
            targets = []
            for mapping in json_content:
                if mapping.get("source") == deleted_file:
                    target = mapping.get("target")
                    if target:
                        targets.append(target)

            for target_dir in targets:
                if target_dir and Path(target_dir).exists():
                    run_command(f'git rm "{target_dir}"', check=False)
                    run_command(f'rm -f "{target_dir}"', check=False)
                    has_changes = True
                    print(f"Removed synced file: {target_dir} (source: {deleted_file})")

    return has_changes


def commit_and_push(commit_context: CommitContextStorage) -> None:
    """
    Commit and push changes if they exist
    """
    if not commit_context.has_changes:
        print("No changes to commit")
        sys.exit(0)

    if commit_context.test_json_changed and not commit_context.files_to_sync_found:
        run_command(
            'git commit -m "Update sync mapping from ' 
            f'{commit_context.repo_name} PR {commit_context.pr_number}"'
        )
    else:
        run_command(
            'git commit -m "Sync changes from '
            f'{commit_context.repo_name} PR {commit_context.pr_number}"'
        )

    run_command(f"git push origin {commit_context.branch_name}")
    print(f"Successfuly pushed changes to {commit_context.branch_name}")


def create_or_update_pr(target_repo: str, branch_name: str, repo_name: str, pr_number: str) -> None:
    """
    Create or update PR in target repo
    """
    pr_list = get_gh_json(
        f"gh pr list --repo QuietHellsPage/{target_repo} --head {branch_name} --json number"
    )

    target_pr_number = None

    if pr_list and isinstance(pr_list, list) and len(pr_list) > 0:
        first_pr = pr_list[0]
        if isinstance(first_pr, dict) and "number" in first_pr:
            target_pr_number = first_pr["number"]

    commit_check = run_command(f"git log --oneline origin/main..{branch_name}", capture_output=True)
    if commit_check.stdout.strip():
        if not target_pr_number:
            run_command(
                f"""gh pr create \
                --repo QuietHellsPage/{target_repo} \
                --head {branch_name} \
                --base main \
                --title "[Automated] Sync from {repo_name} PR {pr_number}" \
                --fill \
                --label "automated pr" \
                --assignee QuietHellsPage \
                --reviewer QuietHellsPage"""
            )
            print("Created new PR in target repository")
        else:
            run_command(
                f"""gh pr comment {target_pr_number} \
            --repo QuietHellsPage/{target_repo} \
            --body 'Automatically updated'"""
            )
            print(f"Updated existing PR #{target_pr_number} in target repository")
    else:
        print(f"No commits in branch {branch_name} - skipping PR creation")


def main() -> None: # pylint: disable=too-many-locals
    """
    Main function to run the process
    """
    if (sys_len := len(sys.argv)) < 3:
        print(f"Lenght of command line args is {sys_len}, what is less than 3")
        sys.exit(1)

    repo_name = sys.argv[1]
    pr_number = sys.argv[2]

    target_repo = "Child_repo_mirror"
    branch_name = f"auto-update-from-{repo_name}-pr-{pr_number}"

    gh_token = os.getenv("GH_TOKEN")
    github_repository = os.getenv("GITHUB_REPOSITORY")
    comment_body = os.getenv("COMMENT_BODY", "")

    setup_and_authorize(target_repo=target_repo, gh_token=gh_token)
    use_or_create_label(target_repo=target_repo)
    setup_branch(branch_name=branch_name)

    source_ref = get_source_ref(
        github_repository=github_repository, pr_number=pr_number, comment_body=comment_body
    )

    if not source_ref:
        print("Source ref not found")
        sys.exit(1)

    pr_files_data = get_gh_json(f"gh pr view {pr_number} --repo {github_repository} --json files")
    files_data = get_pr_files_data(pr_files_data)
    changed_files = [file["path"] for file in files_data]

    if not changed_files:
        print(f"No changed files found in PR {pr_number}")
        sys.exit(0)

    test_json_changed, json_exists, json_content = handle_update(
        source_ref=source_ref, changed_files=changed_files
    )

    files_to_sync_found = has_files_for_sync(changed_files, json_content) if json_exists else False

    if not files_to_sync_found and not test_json_changed:
        print(f"No files to sync found in PR {pr_number}")
        sys.exit(0)

    has_changes = False

    if json_exists:
        has_changes = sync_modified_files(
            changed_files=changed_files, json_content=json_content, source_ref=source_ref
        )
        has_deleted_files = handle_deleted_files(files_data=files_data, json_content=json_content)

        has_changes = has_changes or has_deleted_files

    context = CommitContextStorage(repo_name, pr_number, branch_name, test_json_changed,
                                   files_to_sync_found, has_changes)

    commit_and_push(context)

    create_or_update_pr(
        target_repo=target_repo, branch_name=branch_name, repo_name=repo_name, pr_number=pr_number
    )


if __name__ == "__main__":
    main()
