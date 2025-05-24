import logging
import os
import shutil
import subprocess
import time
import zipfile
from datetime import datetime

# ===================== LOGGER =====================
logger = logging.getLogger("Agent")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("agent.log")],
)

SERVICE_NAME = "agent"
UPDATER_DIR = os.path.dirname(os.path.abspath(__file__))
FLAG_FILE = os.path.join(UPDATER_DIR, "restart.flag")
CHECK_INTERVAL = 3  # seconds - Reduced from 10 to 3 for better responsiveness
APP_URL = "http://host.docker.internal"
VERSION_FILE = "version.txt"
VERSION_FILE_PATH = os.path.join(UPDATER_DIR, VERSION_FILE)
VERSION_ENDPOINT = "/api/agent/version"
ZIP_FILE = os.path.join(UPDATER_DIR, "agent_new.zip")
EXTRACT_DIR = os.path.join(UPDATER_DIR, "update")
BACKUP_DIR = os.path.join(UPDATER_DIR, "backup")


def create_backup():
    """Create backup of current version before update"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(BACKUP_DIR, f"backup_{timestamp}")

        if not os.path.exists(BACKUP_DIR):
            os.makedirs(BACKUP_DIR)

        # Backup important files with absolute paths
        important_files = {
            "main.py": os.path.join(UPDATER_DIR, "main.py"),
            "version.txt": os.path.join(UPDATER_DIR, "version.txt"),
            "agent_config.json": os.path.join(UPDATER_DIR, "agent_config.json"),
            "restart_agent_service.py": os.path.join(
                UPDATER_DIR, "restart_agent_service.py"
            ),
        }

        os.makedirs(backup_path, exist_ok=True)

        for filename, filepath in important_files.items():
            if os.path.exists(filepath):
                dst = os.path.join(backup_path, filename)
                shutil.copy2(filepath, dst)
                logger.debug(f"Backed up: {filepath} -> {dst}")

        logger.info(f"Backup created at: {backup_path}")
        return backup_path
    except Exception as e:
        logger.error(f"Failed to create backup: {e}")
        return None


def validate_zip_file(zip_path):
    """Validate that the zip file is not corrupted"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # Test the zip file
            zip_ref.testzip()
            # Check if it contains expected files
            file_list = zip_ref.namelist()
            if "main.py" not in file_list:
                logger.warning("main.py not found in update package")
                return False
            return True
    except zipfile.BadZipFile:
        logger.error(f"{zip_path} is corrupted or not a valid zip file")
        return False
    except Exception as e:
        logger.error(f"Error validating zip file: {e}")
        return False


def extract_update_safely():
    """Safely extract update with validation"""
    try:
        # Remove existing extract directory
        if os.path.exists(EXTRACT_DIR):
            shutil.rmtree(EXTRACT_DIR)

        # Create extract directory
        os.makedirs(EXTRACT_DIR, exist_ok=True)

        # Extract the zip file
        with zipfile.ZipFile(ZIP_FILE, "r") as zip_ref:
            zip_ref.extractall(EXTRACT_DIR)

        logger.info(f"Update extracted to: {EXTRACT_DIR}")
        return True
    except Exception as e:
        logger.error(f"Failed to extract update: {e}")
        return False


def apply_update_safely():
    """Safely apply update by moving files"""
    try:
        if not os.path.exists(EXTRACT_DIR):
            logger.error(f"Extract directory {EXTRACT_DIR} not found")
            return False

        # Move all files from update folder to UPDATER_DIR (absolute path)
        for item in os.listdir(EXTRACT_DIR):
            src = os.path.join(EXTRACT_DIR, item)
            dst = os.path.join(UPDATER_DIR, item)

            if os.path.isfile(src):
                # Remove destination if exists, then move
                if os.path.exists(dst):
                    os.remove(dst)
                shutil.move(src, dst)
                logger.info(f"Updated: {item} -> {dst}")

        # Keep extract directory for debugging/backup purposes
        logger.info(
            f"Update applied successfully. Extract directory preserved at: {EXTRACT_DIR}"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to apply update: {e}")
        return False


def ensure_correct_working_directory():
    """Ensure we're running from the correct directory"""
    try:
        # Change to the script's directory
        os.chdir(UPDATER_DIR)
        logger.info(f"Working directory changed to: {UPDATER_DIR}")
    except Exception as e:
        logger.error(f"Failed to change working directory: {e}")


def main():
    # First, ensure we're in the correct directory
    ensure_correct_working_directory()

    logger.info(
        f"Restart agent service monitor started (check interval: {CHECK_INTERVAL}s)"
    )
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"Script directory: {UPDATER_DIR}")
    logger.info(f"Version file path: {VERSION_FILE_PATH}")

    # Debug: Check initial version file
    try:
        if os.path.exists(VERSION_FILE_PATH):
            with open(VERSION_FILE_PATH, "r") as f:
                initial_version = f.read().strip()
            logger.info(f"Initial version detected: {initial_version}")
        else:
            logger.warning(f"Version file {VERSION_FILE_PATH} does not exist")
    except Exception as e:
        logger.error(f"Error reading initial version: {e}")

    while True:
        if os.path.exists(FLAG_FILE):
            logger.info("Update flag detected. Starting update process...")

            # Read target version from flag file
            try:
                with open(FLAG_FILE, "r") as f:
                    target_version = f.read().strip()
                logger.info(f"Target version: {target_version}")
            except Exception as e:
                logger.error(f"Failed to read flag file: {e}")
                os.remove(FLAG_FILE)
                continue

            # Validate zip file exists and is valid
            if not os.path.exists(ZIP_FILE):
                logger.error(f"Update file {ZIP_FILE} not found")
                os.remove(FLAG_FILE)
                continue

            if not validate_zip_file(ZIP_FILE):
                logger.error("Invalid or corrupted update file")
                os.remove(ZIP_FILE)
                os.remove(FLAG_FILE)
                continue

            # Create backup before update
            backup_path = create_backup()
            if not backup_path:
                logger.warning("Failed to create backup, continuing anyway...")

            try:
                # Stop the agent service using nssm
                logger.info("Stopping agent service...")
                subprocess.run(["nssm", "stop", SERVICE_NAME], check=True)
                logger.info("Agent service stopped")

                # Wait a moment for service to fully stop
                time.sleep(2)

                # Extract update safely
                if not extract_update_safely():
                    logger.error("Failed to extract update. Aborting.")
                    subprocess.run(["nssm", "start", SERVICE_NAME], check=True)
                    continue

                # ⚠️ CRITICAL: Update version file BEFORE applying files
                # This prevents infinite loop if update package contains version.txt
                try:
                    with open(VERSION_FILE_PATH, "w") as f:
                        f.write(target_version)
                    logger.info(
                        f"Version updated to: {target_version} (before file apply)"
                    )
                except Exception as e:
                    logger.error(f"Failed to update version file: {e}")
                    # Continue anyway, but this is risky

                # Apply update safely
                if not apply_update_safely():
                    logger.error("Failed to apply update. Aborting.")
                    subprocess.run(["nssm", "start", SERVICE_NAME], check=True)
                    continue

                # Remove the zip file after successful extraction
                os.remove(ZIP_FILE)

                # Remove flag file
                os.remove(FLAG_FILE)

                # Double-check version file is correct (in case it was overwritten)
                try:
                    with open(VERSION_FILE_PATH, "r") as f:
                        current_version = f.read().strip()
                    if current_version != target_version:
                        logger.warning(
                            "Warning: Version file was overwritten. Fixing it..."
                        )
                        with open(VERSION_FILE_PATH, "w") as f:
                            f.write(target_version)
                        logger.info(f"Version corrected to: {target_version}")
                    else:
                        logger.info(f"Version file confirmed: {target_version}")
                except Exception as e:
                    logger.error(f"Error checking version file: {e}")

                # Wait before starting service to ensure all file operations complete
                time.sleep(3)

                # Start the agent service using nssm
                logger.info("Starting agent service...")
                subprocess.run(["nssm", "start", SERVICE_NAME], check=True)
                logger.info("Agent service started successfully")
                logger.info("Update completed successfully!")

            except subprocess.CalledProcessError as e:
                logger.error(f"Service control error: {e}")
                # Try to start service anyway
                try:
                    subprocess.run(["nssm", "start", SERVICE_NAME], check=True)
                except:
                    logger.error(
                        "Failed to restart service. Manual intervention required."
                    )
            except Exception as e:
                logger.error(f"Update process failed: {e}")
                # Try to start service anyway
                try:
                    subprocess.run(["nssm", "start", SERVICE_NAME], check=True)
                except:
                    logger.error(
                        "Failed to restart service. Manual intervention required."
                    )

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
