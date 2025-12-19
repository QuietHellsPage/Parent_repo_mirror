"""
Useful constant variables.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PROJECT_CONFIG_PATH = PROJECT_ROOT / "project_config.json"
CONFIG_PACKAGE_PATH = PROJECT_ROOT / "config"
CORE_UTILS_PACKAGE_PATH = PROJECT_ROOT / "core_utils"
TRACKED_JSON_PATH_OBJ = str(PROJECT_ROOT/ "autosync" / "test_files.json")
# TRACKED_JSON_PATH = str(TRACKED_JSON_PATH_OBJ.relative_to(PROJECT_ROOT))
FLOAT_TOLERANCE = 4
