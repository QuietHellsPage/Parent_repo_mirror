"""
Python tool for synchronization between source and target repositories.
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast, Optional

from logging518.config import fileConfig
from tap import Tap

from config.cli_unifier import _run_console_tool, handles_console_error
from config.console_logging import get_child_logger
from config.constants import TRACKED_JSON_PATH

logger = get_child_logger(__file__)

class QualityControlArgumentsParser(Tap):
    """
    CLI for quality control.
    """

    toml_config_path: Optional[Path] = None
    root_dir: Optional[Path] = Path(os.getcwd())
    project_config_path: Optional[Path] = None


class SyncArgumentParser(QualityControlArgumentsParser):
    """
    Parser that gets args for sync tool
    """

    repo_name: str
    pr_number: str


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
    changed_files: list[str]
    json_content: Optional[dict]
    json_changed: bool
    commit_sha: str


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
def run_git(args: list[str], **kwargs: str) -> tuple[str, str, int]:
    """
    Run git command via imported function

    Args:
        args (list[str]): Arguments for git command.
        kwargs (str): Keyword arguments.

    Returns:
        tuple[str, str, int]: Result of git command.
    """
    return _run_console_tool("git", args, **kwargs)


@handles_console_error(ok_codes=(0, 1))
def run_gh(args: list[str]) -> tuple[str, str, int]:
    """
    Run gh command via imported function

    Args:
        args (list[str]): Arguments for gh command.

    Returns:
        tuple[str, str, int]: Result of gh command.
    """
    return _run_console_tool("gh", args)


@handles_console_error(ok_codes=(0,))
def run_mkdir(args: list[str], **kwargs: str) -> tuple[str, str, int]:
    """
    Create directory via imported function

    Args:
        args (list[str]): Arguments for mkdir command.
        kwargs (str): Keyword arguments.

    Returns:
        tuple[str, str, int]: Result of mkdir command.
    """
    return _run_console_tool("mkdir", args, **kwargs)


@handles_console_error(ok_codes=(0,))
def run_rm(args: list[str]) -> tuple[str, str, int]:
    """
    Remove anything via imported function

    Args:
        args (list[str]): Arguments for rm command.

    Returns:
        tuple[str, str, int]: Result of rm command.
    """
    return _run_console_tool("rm", args)


@handles_console_error(ok_codes=(0,))
def run_sleep(args: list[str]) -> tuple[str, str, int]:
    """
    Run sleep command via imported function

    Args:
        args (list[str]): Arguments for sleep command.

    Returns:
        tuple[str, str, int]: Result of sleep command.
    """
    return _run_console_tool("sleep", args)


def get_pr_data(repo_name: str, pr_number: str) -> dict[str, Any]:
    """
    Get PR data via gh

    Args:
        repo_name (str): Name of source repo.
        pr_number (str): Number of needed PR in source repo.

    Returns:
        dict[str, Any]: PR data.
    """
    stdout, stderr, return_code = run_gh(
        [
            "pr",
            "view",
            pr_number,
            "--repo",
            repo_name,
            "--json",
            "files,commits,mergedAt,headRefName,baseRefName",
        ]
    )

    if return_code != 0 or not stdout:
        logger.warning("Failed to get PR data: %s", stderr)
        return {}

    data = json.loads(stdout)
    return cast(dict[str, Any], data)


def check_branch_exists(branch_name: str, repo_path: str = ".") -> bool:
    """
    Check if branch in remote repo exists

    Args:
        branch_name (str): Name of needed branch.
        repo_path (str, optional): Path to repo. Defaults to ".".

    Returns:
        bool: True if needed branch exists in remote repo.
    """
    _, _, return_code = run_git(
        ["show-ref", "--quiet", f"refs/remotes/origin/{branch_name}"], cwd=repo_path
    )
    return bool(return_code == 0)


def clone_repo(target_repo: str, gh_token: str) -> None:
    """
    Clone target repo

    Args:
        target_repo (str): Name of target repo.
        gh_token (str): Token to process operations.
    """
    target_path = Path(target_repo)
    if target_path.exists():
        run_rm(["-rf", str(target_path)])

    run_git(["clone", f"https://{gh_token}@github.com/QuietHellsPage/{target_repo}.git"])


def setup_git_config(repo_path: str) -> None:
    """
    Setup config

    Args:
        repo_path (str): Path to repo.
    """
    run_git(["config", "user.name", "github-actions[bot]"], cwd=repo_path)
    run_git(
        ["config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        cwd=repo_path,
    )


def check_and_create_label(target_repo: str) -> None:
    """
    Check if label exists or create it

    Args:
        target_repo (str): Path to repo.
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
        run_sleep("2")


def checkout_or_create_branch(branch_name: str, repo_path: str) -> None:
    """
    Checkout on existing branch or create it

    Args:
        branch_name (str): Name of needed branch.
        repo_path (str): Path to repo.
    """
    if check_branch_exists(branch_name, repo_path):
        run_git(["checkout", branch_name], cwd=repo_path)
        run_git(["pull", "origin", branch_name], cwd=repo_path)
    else:
        run_git(["checkout", "-b", branch_name], cwd=repo_path)


def add_remote_and_fetch(remote_name: str, repo_url: str, repo_path: str) -> None:
    """
    Add remote and fetch.

    Args:
        remote_name (str): Name of remote repo.
        repo_url (str): Link to remote repo.
        repo_path (str): Path to remote repo.
    """
    stdout, _, _ = run_git(["remote"], cwd=repo_path)
    remotes = stdout.split()

    if remote_name not in remotes:
        run_git(["remote", "add", remote_name, repo_url], cwd=repo_path)

    run_git(["fetch", remote_name], cwd=repo_path)


def get_json_from_source(source_ref: str, target_repo: str) -> tuple[Optional[dict], bool]:
    """
    Get JSON content from source reference and update local file if changed.

    Args:
        source_ref (str): Reference in source repo.
        target_repo (str): Path to target repository.

    Returns:
        tuple[Optional[dict], bool]: JSON content and whether it was changed.
    """
    json_path = Path(target_repo) / TRACKED_JSON_PATH
    source_sha = None
    target_sha = None

    stdout, _, rc = _run_console_tool(
        "git",
        ["rev-parse", f"{source_ref}:{TRACKED_JSON_PATH}"],
        cwd=target_repo
    )
    if rc == 0:
        source_sha = stdout.strip()
    else:
        logger.info("JSON file not found in source ref %s", source_ref)

    stdout, _, rc = _run_console_tool(
        "git",
        ["rev-parse", f"origin/main:{TRACKED_JSON_PATH}"],
        cwd=target_repo
    )
    if rc == 0:
        target_sha = stdout.strip()
    else:
        logger.info("JSON file not found in target main")

    if source_sha == target_sha:
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                json_content = json.load(f)
        else:
            json_content = None
        return json_content, False

    json_changed = True
    if source_sha is not None:
        stdout, _, rc = _run_console_tool(
            "git",
            ["show", f"{source_ref}:{TRACKED_JSON_PATH}"],
            cwd=target_repo
        )
        if rc == 0 and stdout:
            json_content = json.loads(stdout)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(stdout)
            run_git(["add", TRACKED_JSON_PATH], cwd=target_repo)
        else:
            logger.error("Failed to read JSON from source")
            json_content = None
    else:
        if json_path.exists():
            run_git(["rm", TRACKED_JSON_PATH], cwd=target_repo)
        json_content = None

    return json_content, json_changed


def get_sync_mapping(json_content: Optional[dict]) -> list[tuple[str, str]]:
    """
    Extract sync mapping from JSON.

    Args:
        json_content (Optional[dict]): Content of JSON file.

    Returns:
        list[tuple[str, str]]: Mapping of source/target files from JSON.
    """
    sync_mapping: list[tuple[str, str]] = []

    if not json_content:
        return []

    for item in json_content:
        source = item.get("source")
        target = item.get("target")
        if source and target:
            sync_mapping.append((source, target))
    return sync_mapping


def sync_files_from_source(
    repo_path: str, source_ref: str, sync_list: list[tuple[str, str]]
) -> bool:
    """
    Sync files from source reference into target repo according to mapping.

    Args:
        repo_path (str): Path to target repo.
        source_ref (str): Reference in source repo.
        sync_list (list[tuple[str, str]]): List of (source_path, target_path).

    Returns:
        bool: True if any file was updated/added/removed.
    """
    has_changes = False
    for source_path, target_path in sync_list:
        stdout, _, rc = _run_console_tool(
            "git",
            ["show", f"{source_ref}:{source_path}"],
            cwd=repo_path
        )
        full_target_path = Path(repo_path) / target_path

        if rc == 0 and stdout:
            full_target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_target_path, "w", encoding="utf-8") as f:
                f.write(stdout)
            run_git(["add", target_path], cwd=repo_path)
            has_changes = True
        else:
            if full_target_path.exists():
                run_git(["rm", target_path], cwd=repo_path)
                has_changes = True
            else:
                logger.info(
                    "File %s not found in source and not present in target, nothing to do",
                    source_path,
                )
    return has_changes


def run_sync(
    target_repo: str, source_ref: str, json_content: Optional[dict], json_changed: bool
) -> SyncResult:
    """
    Run synchronization: compare files from mapping and update if needed.

    Args:
        target_repo (str): Path to target repository.
        source_ref (str): Reference in source repository.
        json_content (Optional[dict]): Parsed JSON content.
        json_changed (bool): Whether JSON file itself changed.

    Returns:
        SyncResult: Result of sync operation.
    """
    has_changes = json_changed
    files_to_sync_found = False

    if json_content:
        sync_mapping = get_sync_mapping(json_content)
        files_to_sync = []

        for source_path, target_path in sync_mapping:
            stdout, _, rc_src = _run_console_tool(
                "git",
                ["rev-parse", f"{source_ref}:{source_path}"],
                cwd=target_repo
            )
            source_sha = stdout.strip() if rc_src == 0 else None

            stdout, _, rc_tgt = _run_console_tool(
                "git",
                ["rev-parse", f"origin/main:{target_path}"],
                cwd=target_repo
            )
            target_sha = stdout.strip() if rc_tgt == 0 else None

            if source_sha != target_sha:
                files_to_sync.append((source_path, target_path))
                files_to_sync_found = True

        if files_to_sync:
            synced = sync_files_from_source(target_repo, source_ref, files_to_sync)
            has_changes = has_changes or synced

    return SyncResult(
        has_changes=has_changes,
        files_to_sync_found=files_to_sync_found,
        json_changed=json_changed,
    )


def commit_and_push_changes(commit_config: CommitConfig) -> None:
    """
    Commit and push changes

    Args:
        commit_config (CommitConfig): Schema of Commit.
    """
    if commit_config.json_changed and not commit_config.files_to_sync_found:
        commit_msg = (
            f"Update sync mapping from {commit_config.repo_name} "
            f"PR {commit_config.pr_number}"
        )
    else:
        commit_msg = (
            f"Sync changes from {commit_config.repo_name} PR {commit_config.pr_number}"
        )

    run_git(["commit", "-m", commit_msg], cwd=commit_config.repo_path)
    run_git(["push", "origin", commit_config.branch_name], cwd=commit_config.repo_path)


def create_or_update_pr(
    target_repo: str, branch_name: str, repo_name: str, pr_number: str, repo_path: str
) -> None:
    """
    Create or update PR in target repo

    Args:
        target_repo (str): Name of source repo.
        branch_name (str): Name of needed branch.
        repo_name (str): Name of target repo
        pr_number (str): Number of source PR.
        repo_path (str): Path to repo.
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
                ]
            )

            if return_code == 1:
                logger.error("Failed to create PR. Exit code: %s", return_code)
                logger.error("stdout: %s", stdout)
                logger.error("stderr: %s", stderr)
                sys.exit(1)

            logger.info("Created new PR in target repository")

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


def validate_and_process_inputs() -> tuple[str, ...]:
    """
    Validating input args and processing basic information for script work

    Returns:
        tuple[str, ...]: Needed data from source repo
    """
    parser = SyncArgumentParser(underscores_to_dashes=True)
    args = parser.parse_args()

    repo_name = args.repo_name
    pr_number = args.pr_number
    target_repo = "Child_repo_mirror"
    branch_name = f"auto-update-from-{repo_name}-pr-{pr_number}"
    root_dir = args.root_dir.resolve()
    toml_config = (args.toml_config_path or (root_dir / "pyproject.toml")).resolve()
    fileConfig(toml_config)

    gh_token = os.environ.get("GH_TOKEN")
    if not gh_token:
        logger.error("GH_TOKEN environment variable is not set")
        sys.exit(1)

    return repo_name, pr_number, target_repo, branch_name, gh_token


def prepare_target_repo(target_repo: str, branch_name: str, gh_token: str) -> None:
    """
    Prepare target repo for PR creation

    Args:
        target_repo (str): Name of target repo.
        branch_name (str): Name of branch in target repo.
        gh_token (str): Token to process operations.
    """
    clone_repo(target_repo, gh_token)
    setup_git_config(target_repo)
    check_and_create_label(target_repo)
    checkout_or_create_branch(branch_name, target_repo)


def main() -> None:
    """
    Main function to create PR in target repo
    """
    repo_name, pr_number, target_repo, branch_name, gh_token = validate_and_process_inputs()

    prepare_target_repo(target_repo, branch_name, gh_token)

    pr_data = get_pr_data(repo_name, pr_number)
    if not pr_data:
        logger.error("PR data in source repo not found")
        sys.exit(0)

    merged_at = pr_data.get("mergedAt")
    head_ref = pr_data.get("headRefName")
    base_ref = pr_data.get("baseRefName", "main")

    if not head_ref:
        logger.error("Could not get head branch name from PR")
        sys.exit(0)

    add_remote_and_fetch(
        "parent-repo", f"https://{gh_token}@github.com/{repo_name}.git", target_repo
    )

    if merged_at:
        source_ref = f"parent-repo/{base_ref}"
        logger.info("PR is merged, comparing %s with target main", source_ref)
    else:
        source_ref = f"parent-repo/{head_ref}"
        logger.info("PR is open, comparing %s with target main", source_ref)

    run_git(["fetch", "origin", "main"], cwd=target_repo)

    json_content, json_changed = get_json_from_source(source_ref, target_repo)

    sync_result = run_sync(target_repo, source_ref, json_content, json_changed)

    if sync_result.has_changes:
        commit_config = CommitConfig(
            target_repo,
            branch_name,
            repo_name,
            pr_number,
            sync_result.json_changed,
            sync_result.files_to_sync_found,
        )

        commit_and_push_changes(commit_config)
        create_or_update_pr(target_repo, branch_name, repo_name, pr_number, target_repo)
    else:
        logger.info("No changes to commit")
        sys.exit(0)


if __name__ == "__main__":
    main()
