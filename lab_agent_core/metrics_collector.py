import pika
import json
import psutil
import platform
import time
import threading


class MetricsCollector:
    def __init__(
        self,
        computer_id,
        room_id,
        rabbitmq_url="amqp://guest:guest@localhost:5672/",
        interval=30,
    ):
        self.computer_id = computer_id
        self.room_id = room_id
        self.rabbitmq_url = rabbitmq_url
        self.interval = interval
        self.running = False

    def get_system_metrics(self):
        """Thu thập thông tin hệ thống."""
        try:
            return {
                "cpu_usage": psutil.cpu_percent(interval=1),
                "memory_total": psutil.virtual_memory().total,
                "memory_used": psutil.virtual_memory().used,
                "disk_total": psutil.disk_usage("/").total,
                "disk_used": psutil.disk_usage("/").used,
                "uptime": int(time.time() - psutil.boot_time()),
                "platform": platform.system(),
                "platform_version": platform.version(),
                "hostname": platform.node(),
            }
        except Exception as e:
            return {"error": str(e)}

    def send_status_update(self, status="online"):
        """Gửi trạng thái đến server."""
        try:
            connection = pika.BlockingConnection(pika.URLParameters(self.rabbitmq_url))
            channel = connection.channel()
            channel.queue_declare(queue="metrics", durable=True)

            print(f"[*] Sending status update: {status}")

            status_data = {
                "computer_id": self.computer_id,
                "room_id": self.room_id,
                "status": status,
                "timestamp": int(time.time()),
                "metrics": self.get_system_metrics(),
            }

            channel.basic_publish(
                exchange="",
                routing_key="metrics",
                body=json.dumps(status_data),
                properties=pika.BasicProperties(
                    delivery_mode=pika.DeliveryMode.Persistent,
                    content_type="application/json",
                ),
            )

            print(f"[*] Đã gửi trạng thái '{status}'")
            connection.close()
            return True
        except Exception as e:
            print(f"[!] Lỗi khi gửi trạng thái: {e}")
            return False

    def heartbeat(self):
        """Gửi heartbeat định kỳ."""
        self.send_status_update("online")
        while self.running:
            time.sleep(self.interval)
            if self.running:
                self.send_status_update("online")

    def start(self):
        """Bắt đầu thu thập và gửi metrics."""
        self.running = True
        self.send_status_update("online")
        threading.Thread(target=self.heartbeat, daemon=True).start()

    def stop(self):
        """Dừng thu thập metrics."""
        self.running = False
        self.send_status_update("offline")
