import logging
import os
import hashlib
import json
import subprocess
import sys

# Add parent directory to path so we can import from other modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from update_server import UpdateServer
from extractor import Extractor

# Configure logging
logger = logging.getLogger("Updater")


class Updater:
    """
    Central component that coordinates the update process.
    - Step 2: Create hash table and send to Update Server
    - Step 4: Download new package
    - Step 5: Extract files into temp folder, start Extractor
    - Step 8: Start the Application
    """

    def __init__(self, current_version, update_server_url):
        self.current_version = current_version
        self.update_server = UpdateServer(update_server_url)
        self.extractor = None
        self.temp_dir = "update_temp"
        self.hash_file = "file_hashes.json"

    def create_file_hash_table(self):
        """Create hash table of all application files."""
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
        logger.info(f"Đang tải xuống gói cập nhật từ Update Server...")
        return self.update_server.download_update(package_info["download_url"])

    def extract_update_package(self, update_file):
        """Extract update package to temporary directory."""
        logger.info(f"Đang giải nén gói cập nhật vào thư mục tạm...")

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
