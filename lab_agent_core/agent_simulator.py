import uuid
import multiprocessing
import receive_logs_topic
import time


class AgentSimulator:
    def __init__(self, num_agents=10, room_id="019619ce-04a4-717a-b349-726e8dd5e66b"):
        self.num_agents = num_agents
        self.room_id = room_id
        self.processes = []

    def start_agent(self):
        # Ghi đè các biến config cho mỗi agent
        receive_logs_topic.computer_id = str(uuid.uuid4())
        receive_logs_topic.room_id = self.room_id
        receive_logs_topic.HEARTBEAT_INTERVAL = 10  # Giảm interval để test
        receive_logs_topic.main()

    def start(self):
        print(f"[*] Khởi động {self.num_agents} agents...")

        for i in range(self.num_agents):
            process = multiprocessing.Process(
                target=self.start_agent, name=f"Agent-{i}"
            )
            self.processes.append(process)
            process.start()
            print(f"[+] Đã khởi động Agent {i}")
            time.sleep(0.5)  # Delay để tránh quá tải

    def stop(self):
        print("\n[*] Dừng tất cả agents...")
        for process in self.processes:
            process.terminate()
            process.join()
        print("[+] Đã dừng tất cả agents")


if __name__ == "__main__":
    try:
        simulator = AgentSimulator(num_agents=5)  # Thay đổi số lượng agents tại đây
        simulator.start()

        print("\n[*] Nhấn Ctrl+C để dừng tất cả agents...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        simulator.stop()
