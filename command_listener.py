import pika
import json
import os
import platform
from metrics_collector import MetricsCollector


class CommandListener:
    def __init__(
        self, computer_id, room_id, rabbitmq_url="amqp://guest:guest@localhost:5672/"
    ):
        self.computer_id = computer_id
        self.room_id = room_id
        self.rabbitmq_url = rabbitmq_url
        self.running = False
        self.connection = None
        self.channel = None
        self.metrics_collector = MetricsCollector(computer_id, room_id, rabbitmq_url)

    def process_command(self, command_data):
        """Xử lý các lệnh từ server."""
        try:
            command_type = command_data.get("command", "")
            print(f"[*] Thực hiện lệnh: {command_type}")

            if command_type == "shutdown":
                self.metrics_collector.send_status_update("shutting_down")
                if platform.system() == "Windows":
                    os.system('shutdown /s /t 5 /c "Tắt máy theo yêu cầu"')
                else:
                    os.system('sudo shutdown -h +1 "Tắt máy theo yêu cầu"')
                return True

            elif command_type == "restart":
                self.metrics_collector.send_status_update("restarting")
                if platform.system() == "Windows":
                    os.system('shutdown /r /t 5 /c "Khởi động lại theo yêu cầu"')
                else:
                    os.system('sudo shutdown -r +1 "Khởi động lại theo yêu cầu"')
                return True

            elif command_type == "status_request":
                self.metrics_collector.send_status_update("online")
                return True

            elif command_type == "execute":
                command = command_data.get("data", {}).get("command", "")
                print(f"[*] Thực hiện lệnh hệ thống: {command}")
                return True

            else:
                print(f"[!] Lệnh không được hỗ trợ: {command_type}")
                return False

        except Exception as e:
            print(f"[!] Lỗi khi xử lý lệnh: {e}")
            return False

    def callback(self, ch, method, properties, body):
        """Xử lý message nhận được."""
        print(f"[x] Nhận được message - Routing key: {method.routing_key}")
        try:
            message = json.loads(body.decode("utf-8"))
            print(f"[x] Nội dung: {json.dumps(message, indent=2)}")
            if "command" in message:
                self.process_command(message)
        except json.JSONDecodeError:
            print(f"[!] Không thể giải mã JSON: {body.decode('utf-8')}")
        except Exception as e:
            print(f"[!] Lỗi xử lý message: {e}")
        ch.basic_ack(delivery_tag=method.delivery_tag)

    def start(self):
        """Bắt đầu lắng nghe lệnh."""
        self.running = True
        try:
            self.connection = pika.BlockingConnection(
                pika.URLParameters(self.rabbitmq_url)
            )
            self.channel = self.connection.channel()
            self.channel.exchange_declare(
                exchange="unilab.commands", exchange_type="topic", durable=True
            )

            queue_name = f"computer.{self.computer_id}"
            self.channel.queue_declare(queue=queue_name, durable=True)
            self.channel.queue_bind(
                exchange="unilab.commands",
                queue=queue_name,
                routing_key=f"room.{self.room_id}.computer.{self.computer_id}",
            )
            self.channel.queue_bind(
                exchange="unilab.commands",
                queue=queue_name,
                routing_key=f"room.{self.room_id}.*",
            )

            self.channel.basic_consume(
                queue=queue_name, on_message_callback=self.callback, auto_ack=False
            )
            print(f"[*] Đang lắng nghe lệnh cho computer_id={self.computer_id}")

            while self.running:
                self.connection.process_data_events(time_limit=1.0)

        except Exception as e:
            print(f"[!] Lỗi khi lắng nghe: {e}")
        finally:
            if self.connection and self.connection.is_open:
                self.connection.close()

    def stop(self):
        """Dừng lắng nghe lệnh."""
        self.running = False
