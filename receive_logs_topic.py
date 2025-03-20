#!/usr/bin/env python
"""
UniLab Agent - Phiên bản cơ bản nhất
Kết nối đến RabbitMQ và in ra message nhận được
"""
import json
import pika
import sys

# Cấu hình kết nối RabbitMQ
rabbitmq_url = "amqps://aizfhyyx:LZhALcBsyDLc1pqBJNowAzFWJ_GsaSBw@armadillo.rmq.cloudamqp.com/aizfhyyx"
computer_id = (
    "9e6af32e-5342-446f-9414-4c2d86406d4e"  # Thay thế với ID thực tế của máy tính
)
room_id = "9e6a2b9a-24f1-4b97-a038-362d9ffcf1d5"  # Thay thế với ID thực tế của phòng


# Hàm callback để xử lý message nhận được
def callback(ch, method, properties, body):
    print(f"[x] Nhận được message - Routing key: {method.routing_key}")
    try:
        # Giải mã JSON
        message = json.loads(body.decode("utf-8"))
        print(f"[x] Nội dung: {json.dumps(message, indent=2)}")
    except json.JSONDecodeError:
        print(f"[!] Không thể giải mã JSON: {body.decode('utf-8')}")

    # Xác nhận đã nhận message
    ch.basic_ack(delivery_tag=method.delivery_tag)
    print("-" * 50)


def main():
    try:
        # Thiết lập kết nối
        print("[*] Đang kết nối đến RabbitMQ...")
        connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        channel = connection.channel()

        # Khai báo exchange
        print("[*] Khai báo exchange 'unilab.commands'...")
        channel.exchange_declare(
            exchange="unilab.commands", exchange_type="topic", durable=True
        )

        # Tạo queue tạm thời
        print("[*] Tạo queue cho máy tính này...")
        queue_name = f"command.computer.{computer_id}"
        channel.queue_declare(queue=queue_name, durable=True)

        # Binding queue với routing key
        # 1. Lệnh cho máy tính cụ thể
        print(f"[*] Binding queue với routing key cho máy tính {computer_id}")
        channel.queue_bind(
            exchange="unilab.commands",
            queue=queue_name,
            routing_key=f"command.room_{room_id}.computer_{computer_id}",
        )

        # 2. Lệnh cho toàn bộ phòng
        print(f"[*] Binding queue với routing key cho phòng {room_id}")
        channel.queue_bind(
            exchange="unilab.commands",
            queue=queue_name,
            routing_key=f"command.room_{room_id}.*",
        )

        # Thiết lập consumer
        print("[*] Bắt đầu lắng nghe các message...")
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=callback,
            auto_ack=False,  # Tự quản lý acknowledgment
        )

        print(f"[*] Agent đang chạy. Ấn CTRL+C để thoát.")
        print(
            f"[*] Đang lắng nghe lệnh cho máy tính {computer_id} trong phòng {room_id}"
        )

        # Bắt đầu lắng nghe message
        channel.start_consuming()

    except pika.exceptions.AMQPConnectionError as error:
        print(f"[!] Lỗi kết nối: {error}")
        return 1
    except KeyboardInterrupt:
        print("[*] Đã ngắt bởi người dùng")
        return 0
    except Exception as error:
        print(f"[!] Lỗi không xác định: {error}")
        return 1
    finally:
        if "connection" in locals() and connection.is_open:
            connection.close()
            print("[*] Đã đóng kết nối")


if __name__ == "__main__":
    sys.exit(main())
