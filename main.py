import threading
import time
from metrics_collector import MetricsCollector
from command_listener import CommandListener
from registration import register_computer


def main():
    # Kiểm tra và đăng ký máy tính
    computer_id, room_id = register_computer()
    if not computer_id or not room_id:
        print("[!] Không thể đăng ký máy tính. Đang thoát...")
        exit(1)

    # Khởi tạo các module
    # metrics = MetricsCollector(computer_id, room_id)
    listener = CommandListener(computer_id, room_id)

    # Chạy các luồng
    # metrics_thread = threading.Thread(target=metrics.start)
    listener_thread = threading.Thread(target=listener.start)
    # metrics_thread.start()
    listener_thread.start()

    # Vòng lặp chính, giữ chương trình chạy
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[*] Đang dừng agent...")
        # metrics.stop()
        listener.stop()
        # metrics_thread.join()
        listener_thread.join()
        print("[*] Agent đã dừng.")


if __name__ == "__main__":
    main()
