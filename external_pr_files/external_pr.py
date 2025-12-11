"""
Python tool for synchronization between source and target repositories.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast, Dict, List, Optional, Tuple

from config.cli_unifier import _run_console_tool, handles_console_error
from config.console_logging import get_child_logger

logger = get_child_logger(__file__)


@dataclass(slots=True)
class ConfigData:
    """
    Storage for info about configuration for creating PR
    """

    repo_path: str
    remote_name: str
    pr_branch: str
    changed_files: List[str]
    json_content: Dict
    json_changed: bool


@dataclass(slots=True)
class CommitConfig:
    """
    Storage for commit data
    """

    repo_path: str
    branch_name: str
    repo_name: str
    pr_number: str
    json_changed: bool
    files_to_sync_found: bool


@dataclass(slots=True)
class SyncConfig:
    """
    Storage for final PR data
    """

    target_repo: str
    changed_files: List[str]
    deleted_files: List[str]
    json_content: Optional[dict]
    json_changed: bool
    pr_branch: str


@dataclass(slots=True)
class SyncResult:
    """
    Result of synchronization operation
    """

    has_changes: bool
    files_to_sync_found: bool
    json_changed: bool


# Wrappers for basic commands
@handles_console_error(ok_codes=(0, 1))
def run_git(args: List[str], **kwargs: List[str]) -> Tuple[str, str, int]:
    """
    Run git command via imported function
    """
    return _run_console_tool("git", args, **kwargs)


@handles_console_error(ok_codes=(0, 1))
def run_gh(args: List[str], **kwargs: List[str]) -> Tuple[str, str, int]:
    """
    Run gh command via imported function
    """
    return _run_console_tool("gh", args, **kwargs)


@handles_console_error(ok_codes=(0,))
def run_mkdir(args: List[str], **kwargs: List[str]) -> Tuple[str, str, int]:
    """
    Create directory via imported function
    """
    return _run_console_tool("mkdir", args, **kwargs)


@handles_console_error(ok_codes=(0,))
def run_rm(args: List[str], **kwargs: List[str]) -> Tuple[str, str, int]:
    """
    Remove anything via imported function
    """
    return _run_console_tool("rm", args, **kwargs)


@handles_console_error(ok_codes=(0,))
def run_sleep(args: List[str], **kwargs: List[str]) -> Tuple[str, str, int]:
    """
    Run sleep command via imported function
    """
    return _run_console_tool("sleep", args, **kwargs)


def get_pr_data(repo_name: str, pr_number: str) -> Dict[str, Any]:
    """
    Get PR data via gh
    """
    stdout, stderr, return_code = run_gh(
        [
            "pr",
            "view",
            pr_number,
            "--repo",
            repo_name,
            "--json",
            "headRefName,headRepository,headRepositoryOwner,files",
        ]
    )

    if return_code != 0 or not stdout:
        logger.warning("Failed to get PR data: %s", stderr)
        return {}

    data = json.loads(stdout)
    return cast(Dict[str, Any], data)


def check_branch_exists(branch_name: str, repo_path: str = ".") -> bool:
    """
    Check if branch in remote repo exists
    """
    _, _, return_code = run_git(
        ["show-ref", "--quiet", f"refs/remotes/origin/{branch_name}"], cwd=repo_path
    )
    return bool(return_code == 0)


def clone_repo(target_repo: str, gh_token: str) -> None:
    """
    Clone target repo
    """
    target_path = Path(target_repo)
    if target_path.exists():
        run_rm(["-rf", str(target_path)])

    run_git(["clone", f"https://{gh_token}@github.com/QuietHellsPage/{target_repo}.git"])


def setup_git_config(repo_path: str) -> None:
    """
    Setup config
    """
    run_git(["config", "user.name", "github-actions[bot]"], cwd=repo_path)
    run_git(
        ["config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        cwd=repo_path,
    )


def check_and_create_label(target_repo: str) -> None:
    """
    Check if label exists or create it
    """
    stdout, stderr, return_code = run_gh(
        ["label", "list", "--repo", f"QuietHellsPage/{target_repo}", "--json", "name"]
    )

    if return_code != 0:
        logger.warning("Failed to get labels: %s", stderr)
        return

    labels = json.loads(stdout) if stdout else []
    label_exists = any(label.get("name") == "automated pr" for label in labels)

    if not label_exists:
        run_gh(
            [
                "label",
                "create",
                "automated pr",
                "--color",
                "0E8A16",
                "--description",
                "Automated pull request",
                "--repo",
                f"QuietHellsPage/{target_repo}",
            ]
        )
        run_sleep(["2"])


def checkout_or_create_branch(branch_name: str, repo_path: str) -> None:
    """
    Checkout on existing branch or create it
    """
    if check_branch_exists(branch_name, repo_path):
        run_git(["checkout", branch_name], cwd=repo_path)
        run_git(["pull", "origin", branch_name], cwd=repo_path)
    else:
        run_git(["checkout", "-b", branch_name], cwd=repo_path)


def add_remote_and_fetch(remote_name: str, repo_url: str, repo_path: str) -> None:
    """
    Add remote and fetch
    """
    stdout, _, _ = run_git(["remote"], cwd=repo_path)
    remotes = stdout.split()

    if remote_name not in remotes:
        run_git(["remote", "add", remote_name, repo_url], cwd=repo_path)

    run_git(["fetch", remote_name], cwd=repo_path)


def get_and_update_json_if_changed(
    repo_path: str, 
    remote_name: str, 
    pr_branch: str, 
    changed_files: List[str]
) -> Tuple[Optional[Dict], bool]:
    """
    Get JSON content from remote branch and update it locally if changed
    """
    json_file_path = "autosync/test_files.json"
    
    json_content = None
    json_changed = json_file_path in changed_files

    stdout, _, return_code = run_git(
        ["show", f"{remote_name}/{pr_branch}:{json_file_path}"],
        cwd=repo_path,
    )
    
    if return_code == 0 and stdout:
        json_content = json.loads(stdout)

        if json_changed:
            json_path = Path(repo_path) / json_file_path
            json_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(stdout)
                
            run_git(["add", json_file_path], cwd=repo_path)
    elif json_changed:
        json_path = Path(repo_path) / json_file_path
        if json_path.exists():
            run_git(["rm", json_file_path], cwd=repo_path)
            json_content = {}
    
    return json_content, json_changed


def get_sync_mapping(
    json_content: Optional[Dict]
) -> List[Tuple[str, str]]:
    """
    Extract sync mapping from JSON.
    """
    sync_mapping = []
    if json_content:
        for item in json_content:
            source = item.get("source")
            target = item.get("target")
            if source and target:
                sync_mapping.append((source, target))
    return sync_mapping


def sync_files_from_pr(
    repo_path: str,
    remote_name: str,
    pr_branch: str,
    sync_mapping: List[Tuple[str, str]]
) -> bool:
    """
    Sync files from PR into target repo using provided sync mapping.
    Returns True if any files were synced.
    """
    has_changes = False

    for source_path, target_path in sync_mapping:
        target_dir = Path(target_path).parent
        if str(target_dir):
            run_mkdir(["-p", str(target_dir)], cwd=repo_path)

        stdout, _, return_code = run_git(
            ["show", f"{remote_name}/{pr_branch}:{source_path}"],
            cwd=repo_path,
        )

        if return_code == 0 and stdout:
            full_target_path = Path(repo_path) / target_path
            full_target_path.parent.mkdir(parents=True, exist_ok=True)

            with open(full_target_path, "w", encoding="utf-8") as f:
                f.write(stdout)

            run_git(["add", target_path], cwd=repo_path)
            has_changes = True
        else:
            logger.warning(
                "Couldn't read file %s from %s/%s",
                source_path,
                remote_name,
                pr_branch,
            )

    return has_changes


def handle_deleted_files(
    repo_path: str, 
    deleted_files: List[str], 
    sync_mapping: List[Tuple[str, str]]
) -> bool:
    """
    Process deleted files using sync mapping.
    Returns True if any files were deleted.
    """
    has_changes = False

    source_to_targets = {}
    for source, target in sync_mapping:
        if source not in source_to_targets:
            source_to_targets[source] = []
        source_to_targets[source].append(target)

    for deleted_file in deleted_files:
        targets = source_to_targets.get(deleted_file, [])
        
        for target_path in targets:
            if not target_path:
                continue
            full_path = Path(repo_path) / target_path
            if not full_path.exists():
                continue
            _, _, return_code = run_git(["rm", target_path], cwd=repo_path)

            if return_code != 0:
                run_rm(["-f", str(full_path)])

            has_changes = True

    return has_changes


def commit_and_push_changes(commit_config: CommitConfig) -> None:
    """
    Commit and push changes
    """
    if commit_config.json_changed and not commit_config.files_to_sync_found:
        commit_msg = (
            f"Update sync mapping from {commit_config.repo_name} " f"PR {commit_config.pr_number}"
        )
    else:
        commit_msg = f"Sync changes from {commit_config.repo_name} PR {commit_config.pr_number}"

    run_git(["commit", "-m", commit_msg], cwd=commit_config.repo_path)
    run_git(["push", "origin", commit_config.branch_name], cwd=commit_config.repo_path)


def create_or_update_pr(
    target_repo: str, branch_name: str, repo_name: str, pr_number: str, repo_path: str
) -> None:
    """
    Create or update PR in target repo
    """
    stdout, stderr, return_code = run_gh(
        [
            "pr",
            "list",
            "--repo",
            f"QuietHellsPage/{target_repo}",
            "--head",
            branch_name,
            "--json",
            "number",
        ]
    )

    target_pr_number = None
    if return_code == 0 and stdout:
        pr_list = json.loads(stdout) if stdout else []
        if pr_list and len(pr_list) > 0:
            target_pr_number = pr_list[0].get("number")

    run_git(["fetch", "origin", "main"], cwd=repo_path)

    stdout, stderr, return_code = run_git(
        ["log", "--oneline", f"origin/main..{branch_name}"], cwd=repo_path
    )

    has_commits = return_code == 0 and bool(stdout and stdout.strip())

    if has_commits:
        if target_pr_number is None:
            stdout, stderr, return_code = run_gh(
                [
                    "pr",
                    "create",
                    "--repo",
                    f"QuietHellsPage/{target_repo}",
                    "--head",
                    branch_name,
                    "--base",
                    "main",
                    "--title",
                    f"[Automated] Sync from {repo_name} PR {pr_number}",
                    "--body",
                    f"Automated synchronization from {repo_name} PR #{pr_number}",
                    "--label",
                    "automated pr",
                    "--assignee",
                    "QuietHellsPage",
                    "--reviewer",
                    "QuietHellsPage",
                ]
            )

            if return_code == 0:
                logger.info("Created new PR in target repository")
            else:
                logger.error("Failed to create PR. Exit code: %s", return_code)
                logger.error("stdout: %s", stdout)
                logger.error("stderr: %s", stderr)
                sys.exit(1)
        else:
            stdout, stderr, return_code = run_gh(
                [
                    "pr",
                    "comment",
                    str(target_pr_number),
                    "--repo",
                    f"QuietHellsPage/{target_repo}",
                    "--body",
                    "Automatically updated",
                ]
            )

            if return_code != 0:
                logger.warning("Failed to update PR %s", target_pr_number)
    else:
        logger.info("No commits in branch %s - skipping PR creation", branch_name)


# Huge funcs to avoid lint ignores in main


def validate_and_process_inputs() -> Tuple[str, str, str, str, str]:
    """
    Validating input args and processing basic information for script work
    """
    parser = argparse.ArgumentParser(description="Process repo name and PR number")
    parser.add_argument("repo_name", help="Name of source repo")
    parser.add_argument("pr_number", help="№ of PR in source repo")
    args = parser.parse_args()

    repo_name = args.repo_name
    pr_number = args.pr_number
    target_repo = "Parent_repo_mirror"
    branch_name = f"auto-update-from-{repo_name}-pr-{pr_number}"

    gh_token = os.environ.get("GH_TOKEN")
    if not gh_token:
        logger.error("GH_TOKEN environment variable is not set")
        sys.exit(1)

    return repo_name, pr_number, target_repo, branch_name, gh_token


def prepare_target_repo(target_repo: str, branch_name: str, gh_token: str) -> None:
    """
    Prepare target repo for PR creation
    """
    clone_repo(target_repo, gh_token)
    setup_git_config(target_repo)
    check_and_create_label(target_repo)
    checkout_or_create_branch(branch_name, target_repo)


def get_pr_info(
    repo_name: str, pr_number: str, gh_token: str, target_repo: str
) -> Tuple[str, List[str], List[str]]:
    """
    Get info about changes in PR from source repo
    """
    pr_data = get_pr_data(repo_name, pr_number)

    if not pr_data:
        logger.error("PR data in source repo not found")
        sys.exit(0)

    pr_branch = pr_data.get("headRefName", "")
    if not pr_branch:
        logger.error("Could not get PR branch information")
        sys.exit(0)

    changed_files = []
    deleted_files = []

    if "files" in pr_data:
        changed_files = [f["path"] for f in pr_data["files"]]
        deleted_files = [f["path"] for f in pr_data["files"] if f.get("status") == "removed"]

    if not changed_files:
        logger.info("No changes found in PR %s", pr_number)
        sys.exit(0)

    add_remote_and_fetch(
        "parent-repo", f"https://{gh_token}@github.com/{repo_name}.git", target_repo
    )

    return pr_branch, changed_files, deleted_files


def run_sync(sync_config: SyncConfig) -> SyncResult:
    """
    Run final synchronization
    """
    has_changes = sync_config.json_changed
    files_to_sync_found = False

    sync_mapping = get_sync_mapping(sync_config.json_content) if sync_config.json_content else []

    sync_needed_files = []
    for file in sync_config.changed_files:
        if file == "autosync/test_files.json":
            continue
            
        for source, target in sync_mapping:
            if source == file:
                sync_needed_files.append((source, target))
                files_to_sync_found = True

    if sync_needed_files:
        has_synced = sync_files_from_pr(
            sync_config.target_repo,
            "parent-repo",
            sync_config.pr_branch,
            sync_needed_files
        )
        has_changes = has_changes or has_synced

    if sync_config.deleted_files and sync_mapping:
        has_deletions = handle_deleted_files(
            sync_config.target_repo, 
            sync_config.deleted_files, 
            sync_mapping
        )
        has_changes = has_changes or has_deletions
        if has_deletions:
            files_to_sync_found = True
    
    return SyncResult(
        has_changes=has_changes,
        files_to_sync_found=files_to_sync_found,
        json_changed=sync_config.json_changed
    )


def main() -> None:
    """
    Main function to create PR in target repo
    """
    repo_name, pr_number, target_repo, branch_name, gh_token = validate_and_process_inputs()

    prepare_target_repo(target_repo, branch_name, gh_token)

    pr_branch, changed_files, deleted_files = get_pr_info(
        repo_name, pr_number, gh_token, target_repo
    )

    json_content, json_changed = get_and_update_json_if_changed(
        target_repo, "parent-repo", pr_branch, changed_files
    )

    sync_mapping = get_sync_mapping(json_content)
    has_files_to_sync = any(
        file != "autosync/test_files.json" 
        and any(source == file for source, _ in sync_mapping)
        for file in changed_files
    )
    
    if not has_files_to_sync and not json_changed:
        logger.info("No files to sync and JSON not changed")
        sys.exit(0)

    sync_result = run_sync(
        SyncConfig(target_repo, changed_files, deleted_files, json_content, json_changed, pr_branch)
    )

    if sync_result.has_changes:
        commit_config = CommitConfig(
            target_repo, branch_name, repo_name, pr_number, 
            sync_result.json_changed, sync_result.files_to_sync_found
        )

        commit_and_push_changes(commit_config)
        create_or_update_pr(target_repo, branch_name, repo_name, pr_number, target_repo)
    else:
        logger.info("No changes to commit")
        sys.exit(0)


if __name__ == "__main__":
    main()
