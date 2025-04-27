<<<<<<< HEAD
from _typeshed import Self
import logging
import os
import hashlib
import json
import subprocess
import sys
=======
import logging
import os
import hashlib
import json
import subprocess
import sys
import argparse
import platform
from datetime import datetime
>>>>>>> Snippet
from update_server import UpdateServer
from extractor import Extractor


# Constants
CURRENT_VERSION = "1.0.0"
# Thay đổi từ GitHub API sang API tùy chỉnh
UPDATE_SERVER_URL = "https://yourdomain.com"  # Thay bằng domain thực tế của bạn

""""
This module implements the core update mechanism for the Lab Agent application.
The Updater class coordinates the update process by:
1. Checking for available updates by comparing file hashes with the update server
2. Downloading update packages when a new version is available
3. Extracting updates to a temporary location
4. Coordinating with the Extractor to replace current files
5. Restarting the application after updates are complete

The update process is designed to be resilient, with logging and error handling
at each step to ensure the application remains functional even if updates fail.
"""

# Add parent directory to path so we can import from other modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Configure logging
logger = logging.getLogger("Updater")


class Updater:
    """
    Central component that coordinates the update process.
    - Step 2: Create hash table and send to Update Server
    - Step 4: Download new package
    - Step 5: Extract files into temp folder, start Extractor
    - Step 8: Start the Application

    The Updater follows a careful sequence to ensure safe application updates:
    1. Generate hashes of existing files to identify what needs updating
    2. Compare local state with the update server to determine if updates exist
    3. Download and verify update packages when available
    4. Hand off to the Extractor for the actual file replacement
    5. Restart the application with the new version
    """

    def __init__(self, current_version, update_server_url):
        self.current_version = current_version
        self.update_server = UpdateServer(update_server_url)
        self.extractor = None
        self.temp_dir = "update_temp"
        self.hash_file = "file_hashes.json"

    def create_file_hash_table(self):
        """Create hash table of all application files."""
        # File hashing is a critical part of the update process:
        # 1. Creates SHA-256 hashes of all application files
        # 2. Ignores temporary files and directories that shouldn't be included
        # 3. Produces a JSON manifest that can be compared with server versions
        logger.info("Đang tạo bảng hash cho các tệp hiện tại...")

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
                        logger.error(f"Lỗi khi tạo hash cho tệp {file_path}: {e}")

        # Save hash table to file
        with open(self.hash_file, "w") as f:
            json.dump(file_hashes, f, indent=2)

        logger.info(
            f"Đã tạo hash cho {len(file_hashes)} tệp và lưu vào {self.hash_file}"
        )
        return file_hashes

    def _get_file_hash(self, file_path):
        """Calculate SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def send_hash_table_to_server(self, file_hashes):
        """Send hash table to Update Server."""
        logger.info("Đang gửi bảng hash đến Update Server...")
        return self.update_server.send_hash_table(file_hashes, self.current_version)

    def download_update_package(self, package_info):
        """Download update package from Update Server."""
        logger.info("Đang tải xuống gói cập nhật từ Update Server...")
        return self.update_server.download_update(package_info["download_url"])

    def extract_update_package(self, update_file):
        """Extract update package to temporary directory."""
        logger.info("Đang giải nén gói cập nhật vào thư mục tạm...")

        # Create temp directory if it doesn't exist
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir, exist_ok=True)

        # Create the Extractor instance
        self.extractor = Extractor()

        # Extract the update package
        return self.extractor.extract_update(update_file, self.temp_dir)

    def start_extractor(self):
        """Start the Extractor to complete the update."""
        logger.info("Khởi động Extractor...")

        if not self.extractor:
            self.extractor = Extractor()

        # Tell extractor to clean and install
        return self.extractor.process_update(self.temp_dir)

    def start_application(self):
        """Start the main application."""
        # Application restart process:
        # 1. Locates the main entry point (main.py) in the lab-agent-core directory
        # 2. Launches it in a new process using the current Python interpreter
        # 3. Exits the current process to allow the new instance to take over
        #
        # This approach ensures a clean restart after updates are applied
        logger.info("Khởi động lại ứng dụng...")

        # Get the path to the main script in the lab-agent-core folder
        main_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "lab-agent-core",
            "main.py",
        )

        if os.path.exists(main_script):
            logger.info(f"Khởi động main.py từ {main_script}...")

            # Start the application in a new process
            subprocess.Popen([sys.executable, main_script])

            # Exit the current process
            sys.exit(0)
        else:
            logger.error(f"Không tìm thấy tệp main.py tại đường dẫn: {main_script}")
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
                logger.info("Không nhận được phản hồi từ Update Server.")
                return False, None, None

            if response.get("update_available", False):
                latest_version = response.get("version")
                logger.info(f"Phát hiện phiên bản mới: {latest_version}")
                return True, latest_version, response
            else:
                logger.info("Đã ở phiên bản mới nhất.")
                return False, response.get("version"), None
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra cập nhật: {e}")
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
                logger.info("Không có cập nhật mới.")
                return False

            # Step 4: Download the update package
            logger.info(f"Đang tải về phiên bản {latest_version}...")
            update_file = self.download_update_package(package_info)

            # Step 5: Extract the update to a temp folder
            logger.info("Đang giải nén gói cập nhật...")
            self.extract_update_package(update_file)

            # Step 5: Start the Extractor
            logger.info("Khởi động Extractor để hoàn tất cập nhật...")
            self.start_extractor()

            # Note: After this point, Extractor will handle the rest and restart Updater if needed
            # We won't reach the next line unless the Extractor didn't properly restart the process
            logger.warning(
                "Extractor không khởi động lại quy trình Updater như dự kiến."
            )

            return True
        except Exception as e:
            logger.error(f"Cập nhật thất bại: {e}")
            return False


<<<<<<< HEAD
def configure_logging():
    """Configure logging for the updater."""
    # Set up logging to file and console
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[logging.FileHandler("updater.log"), logging.StreamHandler()],
    )
=======
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
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    return log_file
>>>>>>> Snippet


def main():
    """
    Entry point for the updater.
<<<<<<< HEAD
    """

    # Configure logging
    configure_logging()

    logger.info("Starting Lab Agent Updater...")
    logger.info(f"Current version: {CURRENT_VERSION}")
    logger.info(f"Update server: {UPDATE_SERVER_URL}")

    # Initialize updater
    updater = Updater(CURRENT_VERSION, UPDATE_SERVER_URL)

    # Perform the full update process
    success = updater.perform_update()

    if not success:
        logger.info("No updates were installed. Starting application...")
        updater.start_application()
=======
    
    When called directly, this function will:
    1. Parse command-line arguments
    2. Configure logging
    3. Initialize the Updater with appropriate settings
    4. Perform the update process
    5. Handle startup based on update results
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Lab Agent Updater")
    parser.add_argument("--version", default=CURRENT_VERSION, help="Current application version")
    parser.add_argument("--server-url", default=UPDATE_SERVER_URL, help="Update server URL")
    parser.add_argument("--check-only", action="store_true", help="Only check for updates without installing")
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
>>>>>>> Snippet


if __name__ == "__main__":
<<<<<<< HEAD
    main()
=======
    try:
        main()
    except Exception as e:
        logger.critical(f"Unhandled exception in updater: {e}", exc_info=True)
        print(f"An unexpected error occurred in the updater. Check logs for details.")
>>>>>>> Snippet
