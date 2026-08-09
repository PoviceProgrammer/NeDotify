import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger("migrate_secrets")


def get_appdata_env_path() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            base_dir = Path(appdata) / "AURA Music"
        else:
            base_dir = Path.home() / "AppData" / "Roaming" / "AURA Music"
    else:
        base_dir = Path.home() / ".config" / "aura-music"
    return base_dir / ".env"


def migrate_secrets(project_root: Path | None = None) -> bool:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    root_env = project_root / ".env"
    target_env = get_appdata_env_path()

    logger.info(f"Checking for root .env at: {root_env}")

    if not root_env.exists():
        logger.info("No root .env found to migrate.")
    else:
        target_env.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Migrating .env from {root_env} to {target_env}")
        shutil.copy2(root_env, target_env)
        root_env.unlink()
        logger.info("Original .env deleted successfully.")

    gitignore_path = project_root / ".gitignore"

    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        lines = [line.strip() for line in content.splitlines()]
        if ".env" not in lines and ".env\n" not in content:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                if content and not content.endswith("\n"):
                    f.write("\n")
                f.write(".env\n")
            logger.info("Added .env to .gitignore")
    else:
        gitignore_path.write_text(".env\n", encoding="utf-8")
        logger.info("Created .gitignore with .env")

    return True


if __name__ == "__main__":
    migrate_secrets()
