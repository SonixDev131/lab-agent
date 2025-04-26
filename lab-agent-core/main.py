import threading
import time
import sys
import os
import logging

# Add parent directory to path so we can import from other modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import from lab-agent-core
from metrics_collector import MetricsCollector
from command_listener import CommandListener
from registration import register_computer

# Import from update-system
from update_system.auto_updater import check_and_update

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("agent.log")],
)
logger = logging.getLogger("LabAgent")


def main():
    logger.info("Khởi động Lab Agent...")

    # Kiểm tra cập nhật trước khi khởi động
    logger.info("Kiểm tra cập nhật...")
    try:
        update_result = check_and_update()
        if update_result:
            logger.info(
                "Đã khởi tạo quá trình cập nhật, ứng dụng sẽ khởi động lại sau khi hoàn tất."
            )
            # Quá trình cập nhật sẽ tự động khởi động lại ứng dụng sau khi hoàn tất
            return
        logger.info(
            "Không có cập nhật mới hoặc cập nhật không thành công. Tiếp tục khởi động ứng dụng."
        )
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra cập nhật: {e}")
        logger.info("Bỏ qua quá trình cập nhật và tiếp tục khởi động ứng dụng.")

    # Kiểm tra và đăng ký máy tính
    computer_id, room_id = register_computer()
    if not computer_id or not room_id:
        logger.error("Không thể đăng ký máy tính. Đang thoát...")
        exit(1)

    # Khởi tạo các module
    logger.info(f"Khởi tạo modules với computer_id={computer_id}, room_id={room_id}")
    metrics = MetricsCollector(computer_id, room_id)
    listener = CommandListener(computer_id, room_id)

    # Chạy các luồng
    metrics_thread = threading.Thread(target=metrics.start, name="MetricsThread")
    listener_thread = threading.Thread(
        target=listener.start, name="CommandListenerThread"
    )
    metrics_thread.daemon = True
    listener_thread.daemon = True

    metrics_thread.start()
    listener_thread.start()

    logger.info("Tất cả các modules đã được khởi động.")

    # Vòng lặp chính, giữ chương trình chạy
    try:
        # Kiểm tra cập nhật định kỳ (mỗi 12 giờ)
        update_interval = 12 * 60 * 60  # 12 giờ tính bằng giây
        last_update_check = time.time()

        while True:
            current_time = time.time()

            # Kiểm tra cập nhật định kỳ
            if current_time - last_update_check > update_interval:
                logger.info("Đang kiểm tra cập nhật theo lịch...")
                check_and_update()
                last_update_check = current_time

            time.sleep(60)  # Kiểm tra mỗi phút

    except KeyboardInterrupt:
        logger.info("Đã nhận được tín hiệu ngắt. Đang dừng agent...")
        metrics.stop()
        listener.stop()
        metrics_thread.join(timeout=3)
        listener_thread.join(timeout=3)
        logger.info("Agent đã dừng.")


if __name__ == "__main__":
    main()
