import os
import shutil
import subprocess
import time
import zipfile
from datetime import datetime

SERVICE_NAME = "agent"
FLAG_FILE = "restart.flag"
CHECK_INTERVAL = 3  # seconds - Reduced from 10 to 3 for better responsiveness
APP_URL = "http://host.docker.internal"
VERSION_FILE = "version.txt"
UPDATER_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE_PATH = os.path.join(UPDATER_DIR, VERSION_FILE)
VERSION_ENDPOINT = "/api/agent/version"
ZIP_FILE = "agent_new.zip"
EXTRACT_DIR = "update"
BACKUP_DIR = "backup"


def create_backup():
    """Create backup of current version before update"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{BACKUP_DIR}/backup_{timestamp}"

        if not os.path.exists(BACKUP_DIR):
            os.makedirs(BACKUP_DIR)

        # Backup important files
        important_files = ["main.py", "version.txt", "agent_config.json"]

        os.makedirs(backup_path, exist_ok=True)

        for file in important_files:
            if os.path.exists(file):
                shutil.copy2(file, backup_path)

        print(f"Backup created at: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"Failed to create backup: {e}")
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
                print("Warning: main.py not found in update package")
                return False
            return True
    except zipfile.BadZipFile:
        print(f"Error: {zip_path} is corrupted or not a valid zip file")
        return False
    except Exception as e:
        print(f"Error validating zip file: {e}")
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

        print(f"Update extracted to: {EXTRACT_DIR}")
        return True
    except Exception as e:
        print(f"Failed to extract update: {e}")
        return False


def apply_update_safely():
    """Safely apply update by moving files"""
    try:
        if not os.path.exists(EXTRACT_DIR):
            print(f"Extract directory {EXTRACT_DIR} not found")
            return False

        # Move all files from update folder to current directory
        for item in os.listdir(EXTRACT_DIR):
            src = os.path.join(EXTRACT_DIR, item)
            dst = os.path.join(".", item)

            if os.path.isfile(src):
                # Remove destination if exists, then move
                if os.path.exists(dst):
                    os.remove(dst)
                shutil.move(src, dst)
                print(f"Updated: {item}")

        # Clean up extract directory
        shutil.rmtree(EXTRACT_DIR)
        print("Update applied successfully")
        return True
    except Exception as e:
        print(f"Failed to apply update: {e}")
        return False


def main():
    print(f"Restart agent service monitor started (check interval: {CHECK_INTERVAL}s)")
    print(f"Working directory: {os.getcwd()}")
    print(f"Version file path: {VERSION_FILE_PATH}")

    # Debug: Check initial version file
    try:
        if os.path.exists(VERSION_FILE_PATH):
            with open(VERSION_FILE_PATH, "r") as f:
                initial_version = f.read().strip()
            print(f"Initial version detected: {initial_version}")
        else:
            print(f"Warning: Version file {VERSION_FILE_PATH} does not exist")
    except Exception as e:
        print(f"Error reading initial version: {e}")

    while True:
        if os.path.exists(FLAG_FILE):
            print("Update flag detected. Starting update process...")

            # Read target version from flag file
            try:
                with open(FLAG_FILE, "r") as f:
                    target_version = f.read().strip()
                print(f"Target version: {target_version}")
            except Exception as e:
                print(f"Failed to read flag file: {e}")
                os.remove(FLAG_FILE)
                continue

            # Validate zip file exists and is valid
            if not os.path.exists(ZIP_FILE):
                print(f"Error: Update file {ZIP_FILE} not found")
                os.remove(FLAG_FILE)
                continue

            if not validate_zip_file(ZIP_FILE):
                print("Error: Invalid or corrupted update file")
                os.remove(ZIP_FILE)
                os.remove(FLAG_FILE)
                continue

            # Create backup before update
            backup_path = create_backup()
            if not backup_path:
                print("Warning: Failed to create backup, continuing anyway...")

            try:
                # Stop the agent service using nssm
                print("Stopping agent service...")
                subprocess.run(["nssm", "stop", SERVICE_NAME], check=True)
                print("Agent service stopped")

                # Wait a moment for service to fully stop
                time.sleep(2)

                # Extract update safely
                if not extract_update_safely():
                    print("Failed to extract update. Aborting.")
                    subprocess.run(["nssm", "start", SERVICE_NAME], check=True)
                    continue

                # ⚠️ CRITICAL: Update version file BEFORE applying files
                # This prevents infinite loop if update package contains version.txt
                try:
                    with open(VERSION_FILE_PATH, "w") as f:
                        f.write(target_version)
                    print(f"Version updated to: {target_version} (before file apply)")
                except Exception as e:
                    print(f"Failed to update version file: {e}")
                    # Continue anyway, but this is risky

                # Apply update safely
                if not apply_update_safely():
                    print("Failed to apply update. Aborting.")
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
                        print("Warning: Version file was overwritten. Fixing it...")
                        with open(VERSION_FILE_PATH, "w") as f:
                            f.write(target_version)
                        print(f"Version corrected to: {target_version}")
                    else:
                        print(f"Version file confirmed: {target_version}")
                except Exception as e:
                    print(f"Error checking version file: {e}")

                # Wait before starting service to ensure all file operations complete
                time.sleep(3)

                # Start the agent service using nssm
                print("Starting agent service...")
                subprocess.run(["nssm", "start", SERVICE_NAME], check=True)
                print("Agent service started successfully")
                print("Update completed successfully!")

            except subprocess.CalledProcessError as e:
                print(f"Service control error: {e}")
                # Try to start service anyway
                try:
                    subprocess.run(["nssm", "start", SERVICE_NAME], check=True)
                except:
                    print("Failed to restart service. Manual intervention required.")
            except Exception as e:
                print(f"Update process failed: {e}")
                # Try to start service anyway
                try:
                    subprocess.run(["nssm", "start", SERVICE_NAME], check=True)
                except:
                    print("Failed to restart service. Manual intervention required.")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
