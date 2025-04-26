import logging
import os
import sys

# Add parent directory to path so we can import from other modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from installer import Installer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('update.log')
    ]
)
logger = logging.getLogger("AutoUpdater")

# Constants
CURRENT_VERSION = "1.0.0"
# Thay đổi từ GitHub API sang API tùy chỉnh
UPDATE_SERVER_URL = "https://yourdomain.com"  # Thay bằng domain thực tế của bạn

def check_and_update():
    """
    Kiểm tra và cài đặt bản cập nhật từ máy chủ cập nhật.
    Sử dụng mô hình cập nhật theo quy trình:
    Installer -> Updater -> Update Server -> Updater -> Extractor -> Updater -> Application
    """
    try:
        logger.info(f"Bắt đầu quá trình kiểm tra cập nhật. Phiên bản hiện tại: {CURRENT_VERSION}")
        
        # Tạo đối tượng Installer để khởi động quá trình cập nhật
        installer = Installer(CURRENT_VERSION, UPDATE_SERVER_URL)
        
        # Khởi động quá trình cập nhật
        result = installer.check_and_install_updates()
        
        if result:
            logger.info("Quá trình cập nhật đã hoàn tất hoặc đã được khởi động.")
            return True
        else:
            logger.warning("Không có cập nhật mới hoặc quá trình cập nhật không thành công.")
            return False
    except Exception as e:
        logger.error(f"Lỗi không xác định trong quá trình cập nhật: {e}")
        return False

if __name__ == "__main__":
    check_and_update()
