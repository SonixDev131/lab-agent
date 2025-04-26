import os
import zipfile
import shutil
import logging
import importlib
import sys
import time

# Add parent directory to path so we can import from other modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logger = logging.getLogger("Extractor")


class Extractor:
    """
    Component responsible for extracting and installing updates.
    - Step 6: Extractor cleans installation and moves files into main folder
    - Step 7: Extractor starts Updater
    """

    def extract_update(self, update_file="agent_new.zip", extract_dir="agent_update"):
        """Extract the update package to a directory."""
        try:
            # Create the directory if it doesn't exist
            if not os.path.exists(extract_dir):
                os.makedirs(extract_dir, exist_ok=True)

            with zipfile.ZipFile(update_file, "r") as zip_ref:
                zip_ref.extractall(extract_dir)
            logger.info(f"Đã giải nén gói cập nhật vào: {extract_dir}")
            return extract_dir
        except Exception as e:
            logger.error(f"Lỗi khi giải nén gói cập nhật: {e}")
            raise

    def clean_installation(self):
        """Clean the installation before applying updates."""
        logger.info("Đang dọn dẹp cài đặt trước khi cập nhật...")

        # List of temporary files and directories to clean
        temp_files = [
            "agent_new.zip",
            "updater_package.zip",
            "file_hashes.json",
            "__pycache__",
        ]

        for item in temp_files:
            try:
                if os.path.isfile(item):
                    os.remove(item)
                    logger.info(f"Đã xóa tệp tạm: {item}")
                elif os.path.isdir(item):
                    shutil.rmtree(item, ignore_errors=True)
                    logger.info(f"Đã xóa thư mục tạm: {item}")
            except Exception as e:
                logger.warning(f"Không thể dọn dẹp {item}: {e}")

        return True

    def install_update(self, extract_dir="agent_update"):
        """Install extracted files to the current directory."""
        try:
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    src = os.path.join(root, file)
                    # Convert the path to be relative to extract_dir
                    rel_path = os.path.relpath(src, extract_dir)
                    dst = os.path.join(os.getcwd(), rel_path)

                    # Create directories if needed
                    os.makedirs(os.path.dirname(dst), exist_ok=True)

                    # Replace the file
                    os.replace(src, dst)
                    logger.info(f"Đã cài đặt: {rel_path}")

            logger.info("Hoàn tất cài đặt cập nhật")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi cài đặt cập nhật: {e}")
            raise

    def clean_up(self, update_file="agent_new.zip", extract_dir="agent_update"):
        """Clean up temporary files after update."""
        try:
            if os.path.exists(update_file):
                os.remove(update_file)

            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir, ignore_errors=True)

            logger.info("Đã dọn dẹp các tệp tạm")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi dọn dẹp: {e}")
            return False

    def start_updater(self):
        """Start the Updater component after installation."""
        logger.info("Khởi động lại Updater...")

        try:
            # Import the updater module with the correct path
            from update_system.updater import Updater
            from update_system.auto_updater import CURRENT_VERSION, UPDATE_SERVER_URL

            # Wait briefly to ensure all file operations are complete
            time.sleep(1)

            # Create and start the updater to launch the application
            updater = Updater(CURRENT_VERSION, UPDATE_SERVER_URL)
            updater.start_application()

            return True
        except ImportError as e:
            logger.error(f"Không thể tìm thấy module updater.py: {e}")
            return False
        except Exception as e:
            logger.error(f"Lỗi khi khởi động lại Updater: {e}")
            return False

    def process_update(self, extract_dir):
        """Process the update: clean installation, move files, start updater."""
        try:
            # Step 6: Clean installation
            self.clean_installation()

            # Step 6: Move files into main folder
            self.install_update(extract_dir)

            # Clean up temp files
            self.clean_up(extract_dir=extract_dir)

            # Step 7: Start Updater
            self.start_updater()

            return True
        except Exception as e:
            logger.error(f"Lỗi trong quá trình cập nhật: {e}")
            return False
