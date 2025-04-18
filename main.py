import threading
import time
from metrics_collector import MetricsCollector
from command_listener import CommandListener


def main():
    # Kiểm tra và đăng ký máy tính
    # ...
    computer_id = "866d0dd4-719d-4a75-8e99-bfba11f3bd2e"
    room_id = "019619ce-04a4-717a-b349-726e8dd5e66b"

    # Khởi tạo các module
    metrics = MetricsCollector(computer_id, room_id)
    listener = CommandListener(computer_id, room_id)

    # Chạy các luồng
    metrics_thread = threading.Thread(target=metrics.start)
    listener_thread = threading.Thread(target=listener.start)
    metrics_thread.start()
    listener_thread.start()

    # Vòng lặp chính, giữ chương trình chạy
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[*] Đang dừng agent...")
        metrics.stop()
        listener.stop()
        metrics_thread.join()
        listener_thread.join()
        print("[*] Agent đã dừng.")


if __name__ == "__main__":
    main()
