import logging
import os
import hashlib
import json
import subprocess
import sys
import argparse
import platform
from datetime import datetime

# Add parent directory to path so we can import from other modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from update_server import UpdateServer
from extractor import Extractor

# Configure logging
logger = logging.getLogger("Updater")


class Updater:
    """
    Central component that coordinates the update process.
    - Takes inventory of files in its own directory
    - Sends framework version and file hashes to the Update Server
    - Downloads and extracts updates if needed
    - Starts the Extractor for installation
    """

    def __init__(self, current_version, update_server_url, framework_version="1.0"):
        self.current_version = current_version
        self.update_server = UpdateServer(update_server_url)
        self.framework_version = (
            framework_version  # Framework version the updater depends on
        )
        self.extractor = None
        self.temp_dir = "update_temp"
        self.hash_file = "file_hashes.json"

        # Set the working directory to where the updater resides
        self.updater_dir = os.path.dirname(os.path.abspath(__file__))
        logger.info(f"Updater directory: {self.updater_dir}")

        # Check if this is a first-time run
        self.is_first_run = self._check_first_run()
        if self.is_first_run:
            logger.info(
                "First-time run detected - will request full application package"
            )

    def _check_first_run(self):
        """
        Determine if this is a first-time run of the updater.
        Checks for the existence of essential application files.
        """
        # Define essential application files that should exist after first installation
        parent_dir = os.path.dirname(self.updater_dir)
        essential_files = [
            os.path.join(parent_dir, "lab_agent_core", "main.py"),
            os.path.join(parent_dir, "lab_agent_core", "command_listener.py"),
            os.path.join(parent_dir, "config", "agent_config.json"),
        ]

        # If any essential file is missing, this is considered a first run
        for file in essential_files:
            if not os.path.exists(file):
                logger.info(f"Essential file missing: {file}")
                return True

        # Check if hash file exists from previous runs
        hash_file_path = os.path.join(self.updater_dir, self.hash_file)
        if not os.path.exists(hash_file_path):
            logger.info("No previous hash file found")
            return True

        return False

    def create_file_hash_table(self):
        """
        Create hash table of all application files in the updater's directory.
        Uses SHA-256 for secure hashing.
        """
        logger.info("Creating hash table for current files...")

        # Save original working directory
        original_dir = os.getcwd()

        try:
            # Change to the updater directory to inventory files
            os.chdir(self.updater_dir)

            file_hashes = {}
            ignored_dirs = [".git", "__pycache__", "agent_env", self.temp_dir]
            ignored_files = [self.hash_file, "agent_new.zip", "updater_package.zip"]

            for root, dirs, files in os.walk("."):
                # Skip ignored directories
                dirs[:] = [d for d in dirs if d not in ignored_dirs]

                for file in files:
                    if file in ignored_files:
                        continue

                    file_path = os.path.join(root, file)
                    if os.path.isfile(file_path):
                        try:
                            file_hash = self._get_file_hash(file_path)
                            # Use relative path as key
                            rel_path = os.path.relpath(file_path)
                            file_hashes[rel_path] = file_hash
                        except Exception as e:
                            logger.error(f"Error hashing file {file_path}: {e}")

            # Save hash table to file
            hash_file_path = os.path.join(self.updater_dir, self.hash_file)
            with open(hash_file_path, "w") as f:
                json.dump(file_hashes, f, indent=2)

            logger.info(
                f"Created hashes for {len(file_hashes)} files and saved to {hash_file_path}"
            )
            return file_hashes

        finally:
            # Restore original working directory
            os.chdir(original_dir)

    def _get_file_hash(self, file_path):
        """Calculate SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def send_hash_table_to_server(self, file_hashes):
        """
        Send hash table and framework version to Update Server.
        This allows the server to determine if framework updates are needed.
        If this is the first run, also notifies the server so it can provide a full application package.
        """
        logger.info(
            f"Sending hash table to Update Server with framework version {self.framework_version}..."
        )
        return self.update_server.send_hash_table(
            file_hashes,
            self.current_version,
            framework_version=self.framework_version,
            is_first_run=self.is_first_run,
        )

    def download_update_package(self, package_info):
        """
        Download update package from Update Server.
        Could be a delta package or full application if this is first install.
        """
        logger.info(f"Downloading update package from Update Server...")

        # Save the update package in the updater's directory
        target_file = os.path.join(self.updater_dir, "agent_new.zip")
        return self.update_server.download_update(
            package_info["download_url"], target_file
        )

    def extract_update_package(self, update_file):
        """Extract update package to temporary directory."""
        logger.info("Extracting update package to temporary directory...")

        # Create temp directory in updater's directory if it doesn't exist
        extract_dir = os.path.join(self.updater_dir, self.temp_dir)
        if not os.path.exists(extract_dir):
            os.makedirs(extract_dir, exist_ok=True)

        # Create the Extractor instance
        self.extractor = Extractor()

        # Extract the update package
        return self.extractor.extract_update(update_file, extract_dir)

    def start_extractor(self):
        """
        Start the Extractor to complete the update.
        This is the handoff point where the updater delegates to the extractor.
        """
        logger.info("Starting Extractor...")

        if not self.extractor:
            self.extractor = Extractor()

        # Tell extractor to clean and install using path in the updater's directory
        extract_dir = os.path.join(self.updater_dir, self.temp_dir)
        return self.extractor.process_update(extract_dir)

    def start_application(self):
        """
        Start the main application.
        Tries multiple possible locations to find the main application entry point.
        """
        logger.info("Starting main application...")

        # Try multiple possible paths for the main application
        possible_paths = [
            # Try lab_agent_core directory
            os.path.join(
                os.path.dirname(self.updater_dir), "lab_agent_core", "main.py"
            ),
            # Try run.py at root
            os.path.join(os.path.dirname(self.updater_dir), "run.py"),
            # Try directly at parent level
            os.path.join(os.path.dirname(self.updater_dir), "main.py"),
        ]

        for main_script in possible_paths:
            if os.path.exists(main_script):
                logger.info(f"Starting application from {main_script}...")

                # Start the application in a new process
                subprocess.Popen(
                    [sys.executable, main_script], cwd=os.path.dirname(main_script)
                )

                # Exit the current process
                sys.exit(0)

        logger.error("Could not find main.py or run.py to start")
        return False

    def check_for_updates(self):
        """Check if updates are available."""
        # Update checking workflow:
        # 1. Generate hashes of all local files
        # 2. Send the hash table to the update server
        # 3. Server compares with latest version and responds with status
        # 4. Returns whether an update is needed and version information
        try:
            # Step 2: Create hash table
            file_hashes = self.create_file_hash_table()

            # Step 2: Send hash table to Update Server
            response = self.send_hash_table_to_server(file_hashes)

            if not response:
                logger.info("No response from Update Server.")
                return False, None, None

            if response.get("update_available", False):
                latest_version = response.get("version")
                logger.info(f"Update available: {latest_version}")
                return True, latest_version, response
            else:
                logger.info("No updates available, already on the latest version.")
                return False, response.get("version"), None
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            return False, None, None

    def perform_update(self):
        """Perform the entire update process."""
        # Main update orchestration function that:
        # 1. Checks for available updates using the update server
        # 2. Downloads the update package if a new version exists
        # 3. Extracts files to a temporary location
        # 4. Starts the extractor process to replace current files
        # 5. The extractor will restart the application when complete
        #
        # Note: This function handles the preparation phase of updates,
        # while the actual file replacement is managed by the Extractor
        try:
            # Step 2: Check for updates (includes creating and sending hash table)
            update_needed, latest_version, package_info = self.check_for_updates()

            if not update_needed:
                logger.info("No new updates available.")
                return False

            # Step 4: Download the update package
            logger.info(f"Downloading version {latest_version}...")
            update_file = self.download_update_package(package_info)

            # Step 5: Extract the update to a temp folder
            logger.info("Extracting update package...")
            self.extract_update_package(update_file)

            # Step 5: Start the Extractor
            logger.info("Starting Extractor to complete the update...")
            self.start_extractor()

            # Note: After this point, Extractor will handle the rest and restart Updater if needed
            # We won't reach the next line unless the Extractor didn't properly restart the process
            logger.warning("Extractor did not restart the Updater process as expected.")

            return True
        except Exception as e:
            logger.error(f"Update failed: {e}")
            return False


def configure_logging(debug=False):
    """Configure logging for the updater."""
    # Create logs directory if it doesn't exist
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # Create log file with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(logs_dir, f"updater_{timestamp}.log")

    # Set log level based on debug flag
    log_level = logging.DEBUG if debug else logging.INFO

    # Set up logging to file and console
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

    return log_file


def main():
    """
    Entry point for the updater.

    When called directly, this function will:
    1. Parse command-line arguments
    2. Configure logging
    3. Initialize the Updater with appropriate settings
    4. Perform the update process
    5. Handle startup based on update results
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Lab Agent Updater")
    parser.add_argument(
        "--version", default=CURRENT_VERSION, help="Current application version"
    )
    parser.add_argument(
        "--server-url", default=UPDATE_SERVER_URL, help="Update server URL"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check for updates without installing",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Configure logging
    log_file = configure_logging(debug=args.debug)

    logger.info("Starting Lab Agent Updater...")
    logger.info(f"Current version: {args.version}")
    logger.info(f"Update server: {args.server_url}")

    # Log system information for debugging
    logger.debug(f"System platform: {sys.platform}")
    logger.debug(f"Python version: {sys.version}")
    logger.debug(f"Platform details: {platform.platform()}")
    logger.debug(f"Current working directory: {os.getcwd()}")
    logger.debug(f"Script directory: {os.path.dirname(os.path.abspath(__file__))}")

    try:
        # List files in the current directory
        logger.debug(f"Files in current directory: {os.listdir()}")
    except Exception as e:
        logger.error(f"Failed to list current directory: {e}")

    # Initialize updater
    updater = Updater(args.version, args.server_url)

    if args.check_only:
        # Only check for updates
        logger.info("Running in check-only mode")
        update_needed, latest_version, _ = updater.check_for_updates()
        if update_needed:
            logger.info(f"Update available: {latest_version}")
            return
        else:
            logger.info("No updates available")
            return

    try:
        # Perform the full update process
        success = updater.perform_update()

        if not success:
            logger.info("No updates were installed. Starting application...")
            updater.start_application()
    except Exception as e:
        logger.error(f"Error during update process: {e}", exc_info=True)
        print(f"Update process failed. Please check the log file at: {log_file}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Unhandled exception in updater: {e}", exc_info=True)
        print(f"An unexpected error occurred in the updater. Check logs for details.")
