import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from pydantic import BaseModel, RootModel # type: ignore

class ModelItem(BaseModel):
    source: str
    target: str


class Model(RootModel[List[ModelItem]]):
    pass


def load_json(json_path: str) -> List[ModelItem]:
    with open(json_path, 'r', encoding='utf-8') as f:
        raw_json = json.load(f)
    model_instance = Model.model_validate(raw_json)
    return model_instance.root


def clone_repo(repo_url: str, local_path: str, github_token: str) -> None:
    auth_url = repo_url.replace('https://', f'https://oauth2:{github_token}@')
    subprocess.run(['git', 'clone', auth_url, local_path], check=True)


def setup_git_user(repo_path: str) -> None:
    subprocess.run(['git', '-C', repo_path, 'config',
                    'user.name', 'Auto-Sync Bot'], check=True)
    subprocess.run(['git', '-C', repo_path, 'config',
                    'user.email', 'auto-sync@users.noreply.github.com'], check=True)


def copy_files(source_repo_path: str, target_repo_path: str, files: List[ModelItem]) -> None:
    for item in files:
        full_source_path = Path(source_repo_path) / item.source
        full_target_path = Path(target_repo_path) / item.target / Path(item.source).name
        
        if full_target_path.parent.exists() and full_target_path.parent.is_file():
            full_target_path.parent.unlink()

        full_target_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            shutil.copy2(full_source_path, full_target_path)
        except FileNotFoundError:
            print(f'File is not found: {full_source_path}')


def commit_and_push_changes(repo_path: str, repo_url: str, github_token: str) -> bool:
    subprocess.run(['git', '-C', repo_path, 'add', '.'], check=True)
    
    status_result = subprocess.run(['git', '-C', repo_path, 'status', '--porcelain'], 
                                 capture_output=True, text=True)
    
    if not status_result.stdout.strip():
        return False
    
    subprocess.run(['git', '-C', repo_path, 'commit', '-m', 'Auto-sync files'], check=True)
    
    push_url = repo_url.replace('https://', f'https://oauth2:{github_token}@')
    subprocess.run(['git', '-C', repo_path, 'push', push_url, 'HEAD:main'], check=True)
    
    return True


def sync_repositories(source_repo: str, target_repo: str, token: str, file_mappings: List[ModelItem]) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        source_dir = Path(temp_dir) / "source"
        target_dir = Path(temp_dir) / "target"
        
        clone_repo(source_repo, str(source_dir), token)
        clone_repo(target_repo, str(target_dir), token)
        
        setup_git_user(str(target_dir))
        copy_files(str(source_dir), str(target_dir), file_mappings)
        commit_and_push_changes(str(target_dir), target_repo, token)


def main() -> None:
    source_repo = os.getenv('SOURCE_REPO_URL', 'https://github.com/QuietHellsPage/Parent_repo_mirror.git')
    target_repo = os.getenv('TARGET_REPO_URL', 'https://github.com/QuietHellsPage/Child_repo_mirror.git')
    token = os.getenv('GITHUB_TOKEN')
    config_path = os.getenv('JSON_PATH', 'autosync/test_files.json')
    
    if not token:
        raise ValueError("GITHUB_TOKEN must be set")

    sync_repositories(source_repo, target_repo, token, load_json(config_path))


if __name__ == '__main__':
    main()
