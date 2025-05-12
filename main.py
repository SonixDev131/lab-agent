import hashlib
import json
import logging
import os
import platform
import re
import shutil
import sys
import threading
import time
import zipfile
from typing import Any, Optional, Tuple

import psutil
import requests
import subprocess
import signal

# ===================== LOGGER =====================
logger = logging.getLogger("Agent")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("agent.log")],
)

# ===================== CONSTANTS =====================
AGENT_ZIP = "agent_new.zip"
UPDATE_TEMP = "update_temp"
CONFIG_FILE = "agent_config.json"
HASH_FILE = "file_hashes.json"
APP_URL = "http://host.docker.internal/api"
UPDATE_ENDPOINT = "/api/agent/delta-package"
RABBITMQ_URL = "amqp://guest:guest@host.docker.internal:5672/"
SERVICE_NAME = "LabAgentService"  # or your actual service name

# ===================== CONFIG LOADER =====================
def get_value(key: str, default: Any = None) -> Any:
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return data.get(key, default)
    except Exception as e:
        logger.error(f"[get_value] Config read error: {e}")
        return default


def set_value(key: str, value: str) -> None:
    try:
        data = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    pass
        data[key] = value
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=4)
        logger.info(f"[set_value] Updated config: set {key} = {value}")
    except Exception as e:
        logger.error(f"[set_value] Failed to update config: {e}")


# ===================== REGISTRATION =====================
def get_mac_address() -> Optional[str]:
    try:
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        for interface in addrs:
            if any(
                k in interface.lower()
                for k in ["loopback", "virtual", "vmnet", "veth", "docker"]
            ):
                continue
            if interface in stats and stats[interface].isup:
                for addr in addrs[interface]:
                    if addr.family == psutil.AF_LINK:
                        mac = addr.address
                        if re.match(r"^([0-9A-Fa-f]{2}-){5}([0-9A-Fa-f]{2})$", mac):
                            return mac
        return None
    except Exception as e:
        logger.error(f"[get_mac_address] MAC address error: {e}")
        return None


def register_computer() -> Tuple[Optional[str], Optional[str]]:
    computer_id = get_value("computer_id")
    room_id = get_value("room_id")
    if computer_id and room_id:
        logger.info(f"Already registered: computer_id={computer_id}, room_id={room_id}")
        return computer_id, room_id
    try:
        register_data = {
            "mac_address": get_mac_address(),
            "hostname": platform.node(),
        }
        logger.info(f"Registering computer: {register_data}")
        response = requests.post(f"{APP_URL}/agents/register", json=register_data)
        if response.status_code == 200:
            result = response.json()
            room_id = result.get("room_id")
            computer_id = result.get("computer_id")
            if room_id and computer_id:
                register_data["room_id"] = room_id
                register_data["computer_id"] = computer_id
                try:
                    with open(CONFIG_FILE, "r+") as f:
                        try:
                            existing_data = json.load(f)
                            existing_data.update(register_data)
                            register_data = existing_data
                        except json.JSONDecodeError:
                            pass
                        f.seek(0)
                        json.dump(register_data, f, indent=4)
                        f.truncate()
                except FileNotFoundError:
                    with open(CONFIG_FILE, "w") as f:
                        json.dump(register_data, f, indent=4)
                logger.info(
                    f"Registration successful: computer_id={computer_id}, room_id={room_id}"
                )
                return computer_id, room_id
            else:
                logger.error(
                    "[register_computer] Registration failed: Missing room_id or computer_id"
                )
        else:
            logger.error(
                f"[register_computer] Registration failed: {response.status_code} - {response.text}"
            )
    except Exception as e:
        logger.error(f"[register_computer] Registration error: {e}")
    return None, None


# ===================== METRICS =====================
def get_system_metrics() -> dict:
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
        logger.error(f"[get_system_metrics] Error collecting system metrics: {e}")
        return {"error": str(e)}


def send_status_update(
    computer_id: str, room_id: str, rabbitmq_url: str, status: str = "online"
) -> bool:
    try:
        import pika
        logger.debug(f"Connecting to RabbitMQ at {rabbitmq_url}")
        connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        logger.debug("RabbitMQ connection established")
        
        channel = connection.channel()
        logger.debug("RabbitMQ channel created")
        
        channel.queue_declare(queue="metrics", durable=True)
        logger.debug("Queue 'metrics' declared")
        
        status_data = {
            "computer_id": computer_id,
            "room_id": room_id,
            "status": status,
            "timestamp": int(time.time()),
            "metrics": get_system_metrics(),
        }
        logger.debug(f"Preparing to send status data: {json.dumps(status_data, indent=2)}")
        
        channel.basic_publish(
            exchange="",
            routing_key="metrics",
            body=json.dumps(status_data),
            properties=pika.BasicProperties(
                delivery_mode=pika.DeliveryMode.Persistent,
                content_type="application/json",
            ),
        )
        logger.debug("Message published successfully")
        
        connection.close()
        logger.debug("RabbitMQ connection closed")
        logger.info(f"Status update sent: {status}")
        return True
    except Exception as e:
        logger.error(f"[send_status_update] Error sending status update: {e}", exc_info=True)
        return False


def metrics_heartbeat(
    computer_id: str, room_id: str, rabbitmq_url: str, interval: int, running_flag: list
) -> None:
    logger.debug(f"Starting metrics heartbeat with interval: {interval} seconds")
    send_status_update(computer_id, room_id, rabbitmq_url, "online")
    while running_flag[0]:
        time.sleep(interval)
        if running_flag[0]:
            logger.debug("Sending periodic status update")
            send_status_update(computer_id, room_id, rabbitmq_url, "online")


def start_metrics_thread(
    computer_id: str, room_id: str, rabbitmq_url: str, interval: int, running_flag: list
) -> threading.Thread:
    thread = threading.Thread(
        target=metrics_heartbeat,
        args=(computer_id, room_id, rabbitmq_url, interval, running_flag),
        daemon=True,
    )
    thread.start()
    return thread


# ===================== COMMAND LISTENER =====================
def process_command(command_data: dict) -> bool:
    try:
        command_type = command_data.get("command", "")
        logger.info(f"Processing command: {command_type}")

        if command_type == "UPDATE":
            logger.info("Received update command. Initiating update process in a new thread...")
            threading.Thread(target=check_for_updates, daemon=True).start()
            return True

        # Implement other command handling here

        return True
    except Exception as e:
        logger.error(f"[process_command] Error processing command: {e}")
        return False


def command_callback(
    ch, method, properties, body, computer_id: str, room_id: str
) -> None:
    try:
        message = json.loads(body.decode("utf-8"))
        source = "default"
        if method.exchange == "cmd.direct":
            source = f"CMD (room.{room_id})"
        elif method.exchange == "broadcast.fanout":
            source = "BROADCAST"
        elif method.exchange == "":
            source = "DIRECT (MAC)"
        logger.info(f"Received message from {source}: {json.dumps(message, indent=2)}")
        if "command" in message:
            process_command(message)
    except json.JSONDecodeError:
        logger.error(f"[command_callback] Cannot decode JSON: {body.decode('utf-8')}")
    except Exception as e:
        logger.error(f"[command_callback] Error handling message: {e}")
    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_command_listener(
    computer_id: str, room_id: str, rabbitmq_url: str, running_flag: list
) -> None:
    import pika

    try:
        logger.debug(f"Starting command listener with RabbitMQ URL: {rabbitmq_url}")
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
            mac_address = data["mac_address"]
        queue_name = mac_address
        logger.debug(f"Using queue name: {queue_name}")
        
        logger.debug("Establishing RabbitMQ connection for command listener")
        connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        channel = connection.channel()
        logger.debug("RabbitMQ channel created for command listener")
        
        channel.queue_declare(queue=queue_name, durable=True)
        logger.debug(f"Queue declared: {queue_name}")
        
        channel.exchange_declare(
            exchange="cmd.direct", exchange_type="direct", durable=True
        )
        logger.debug("Direct exchange declared: cmd.direct")
        
        channel.queue_bind(
            exchange="cmd.direct",
            queue=queue_name,
            routing_key=f"room.{room_id}",
        )
        logger.debug(f"Queue bound to direct exchange with routing key: room.{room_id}")
        
        channel.exchange_declare(
            exchange="broadcast.fanout", exchange_type="fanout", durable=True
        )
        logger.debug("Fanout exchange declared: broadcast.fanout")
        
        channel.queue_bind(exchange="broadcast.fanout", queue=queue_name)
        logger.debug(f"Queue bound to fanout exchange")
        
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=lambda ch, method, properties, body: command_callback(
                ch, method, properties, body, computer_id, room_id
            ),
            auto_ack=False,
        )
        logger.debug(f"Basic consume set up for queue: {queue_name}")
        
        logger.info(
            f"Listening for commands for MAC={mac_address}, room={room_id}, computer_id={computer_id}"
        )
        while running_flag[0]:
            connection.process_data_events(time_limit=1.0)
            
        logger.debug("Command listener loop ended, closing connection")
        connection.close()
    except Exception as e:
        logger.error(f"[start_command_listener] Error in command listener: {e}", exc_info=True)


# ===================== FILE HELPERS =====================
def safe_remove(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
            logger.info(f"Removed file: {path}")
        elif os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            logger.info(f"Removed directory: {path}")
    except Exception as e:
        logger.warning(f"[safe_remove] Failed to remove {path}: {e}")


# ===================== UPDATER =====================
def get_latest_version(current_version: str, update_server_url: str) -> Optional[dict]:
    try:
        response = requests.post(
            f"{APP_URL}/agent/latest",
            json={"agent_version": current_version},
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"[get_latest_version] Error getting latest version: {e}")
        return None


def create_file_hash_table(updater_dir: str, hash_file: str) -> dict:
    logger.info("Creating hash table for current directory files only...")
    original_dir = os.getcwd()
    try:
        os.chdir(updater_dir)
        file_hashes = {}
        ignored_files = [hash_file, AGENT_ZIP, "updater_package.zip", "agent.log"]
        for file in os.listdir("."):
            if file in ignored_files:
                continue
            file_path = file
            if os.path.isfile(file_path):
                try:
                    file_hash = get_file_hash(file_path)
                    file_hashes[file] = file_hash
                except Exception as e:
                    logger.error(
                        f"[create_file_hash_table] Error hashing file {file_path}: {e}"
                    )
        hash_file_path = os.path.join(updater_dir, hash_file)
        with open(hash_file_path, "w") as f:
            json.dump(file_hashes, f, indent=2)
        logger.info(
            f"Created hashes for {len(file_hashes)} files and saved to {hash_file_path}"
        )
        return file_hashes
    finally:
        os.chdir(original_dir)


def get_file_hash(file_path: str) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def send_hash_table_to_server(
    update_server_url: str, file_hashes: dict, save_path: str
) -> Optional[str]:
    try:
        response = requests.post(
            f"{update_server_url}",
            json={"hash_table": file_hashes},
            stream=True,
        )
        if response.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            logger.info(f"Delta package zip file saved to {save_path}")
            return save_path
        else:
            logger.error(
                f"[send_hash_table_to_server] Failed to download delta package: {response.status_code} - {response.text}"
            )
            return None
    except Exception as e:
        logger.error(
            f"[send_hash_table_to_server] Error downloading delta package: {e}"
        )
        return None


def check_for_updates_proc(
    current_version: str, update_server_url: str, updater_dir: str, hash_file: str
) -> Tuple[bool, Optional[str], Optional[str]]:
    response = get_latest_version(current_version, update_server_url)
    if not response or response.get("is_latest"):
        return False, current_version, None
    file_hashes = create_file_hash_table(updater_dir, hash_file)
    zip_path = os.path.join(updater_dir, AGENT_ZIP)
    zip_file = send_hash_table_to_server(update_server_url, file_hashes, zip_path)
    if not zip_file:
        logger.info("No delta package received from Update Server.")
        return False, None, None
    return True, response.get("latest_version"), zip_file


def build_main_exe(install_dir):
    """Build main.exe from main.py using PyInstaller."""
    import shutil
    import subprocess
    import os
    logger.info("Building main.exe from updated main.py...")
    main_py_path = os.path.join(install_dir, "main.py")
    if not os.path.exists(main_py_path):
        raise FileNotFoundError(f"main.py not found in {install_dir}")
    dist_path = os.path.join(install_dir, "dist")
    build_path = os.path.join(install_dir, "build")
    # Clean output directories
    shutil.rmtree(dist_path, ignore_errors=True)
    shutil.rmtree(build_path, ignore_errors=True)
    os.makedirs(dist_path, exist_ok=True)
    result = subprocess.run([
        "pyinstaller",
        "-F",
        main_py_path,
        "--distpath", dist_path,
        "--workpath", build_path,
        "--specpath", install_dir
    ], capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"PyInstaller build failed: {result.stderr}")
        raise RuntimeError("PyInstaller build failed")
    main_exe = os.path.join(dist_path, "main.exe")
    if not os.path.exists(main_exe):
        raise FileNotFoundError(f"main.exe not found at {main_exe}")
    logger.info(f"main.exe built successfully at {main_exe}")
    return main_exe


def perform_update_proc(
    current_version: str, update_server_url: str, updater_dir: str, hash_file: str
) -> bool:
    update_needed, latest_version, zip_file = check_for_updates_proc(
        current_version, update_server_url, updater_dir, hash_file
    )
    if not update_needed:
        logger.info("No new updates available.")
        return False
    logger.info(f"Delta package zip file ready at {zip_file}")
    extract_dir = os.path.join(updater_dir, UPDATE_TEMP)
    try:
        extract_update(zip_file, extract_dir)
        logger.info(f"Update extracted to {extract_dir}.")
        clean_installation()
        install_update(extract_dir)
        # === Build lại main.exe sau khi update ===
        try:
            build_main_exe(os.getcwd())
        except Exception as e:
            logger.error(f"[perform_update_proc] Build main.exe failed after update: {e}")
            return False
        clean_up(update_file=zip_file, extract_dir=extract_dir)
        set_value("agent_version", latest_version)
        start_updater()
        restart_nssm_service()
        logger.info(
            f"Update process completed. Version updated to {latest_version}. Application should restart if needed."
        )
        return True
    except Exception as e:
        logger.error(f"[perform_update_proc] Update installation failed: {e}")
        return False


def check_for_updates() -> bool:
    current_version = get_value("agent_version", "1.0.0")
    update_server_url = get_value("update_server_url", "https://yourdomain.com")
    updater_dir = os.path.dirname(os.path.abspath(__file__))
    hash_file = HASH_FILE
    if not current_version or not update_server_url:
        logger.error(
            "[check_for_updates] Missing configuration values for update check."
        )
        return False
    logger.info(f"Checking for updates. Current version: {current_version}")
    return perform_update_proc(
        current_version, update_server_url, updater_dir, hash_file
    )


# ===================== EXTRACTOR LOGIC =====================
def extract_update(update_file: str = AGENT_ZIP, extract_dir: str = UPDATE_TEMP) -> str:
    try:
        if not os.path.exists(extract_dir):
            os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(update_file, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
        logger.info(f"Đã giải nén gói cập nhật vào: {extract_dir}")
        return extract_dir
    except Exception as e:
        logger.error(f"[extract_update] Lỗi khi giải nén gói cập nhật: {e}")
        raise


def clean_installation() -> bool:
    logger.info("Đang dọn dẹp cài đặt trước khi cập nhật...")
    temp_files = [AGENT_ZIP, "updater_package.zip", HASH_FILE, "__pycache__"]
    for item in temp_files:
        safe_remove(item)
    return True


def install_update(extract_dir: str = UPDATE_TEMP) -> bool:
    try:
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                src = os.path.join(root, file)
                rel_path = os.path.relpath(src, extract_dir)
                dst = os.path.join(os.getcwd(), rel_path)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.replace(src, dst)
                logger.info(f"Đã cài đặt: {rel_path}")
        logger.info("Hoàn tất cài đặt cập nhật")
        return True
    except Exception as e:
        logger.error(f"[install_update] Lỗi khi cài đặt cập nhật: {e}")
        raise


def clean_up(update_file: str = AGENT_ZIP, extract_dir: str = UPDATE_TEMP) -> bool:
    try:
        safe_remove(update_file)
        safe_remove(extract_dir)
        logger.info("Đã dọn dẹp các tệp tạm")
        return True
    except Exception as e:
        logger.error(f"[clean_up] Lỗi khi dọn dẹp: {e}")
        return False


def start_updater() -> bool:
    import subprocess
    import sys

    logger.info("Khởi động ứng dụng chính thay vì khởi động lại Updater...")
    try:
        # Get the directory where this script is located
        agent_dir = os.path.dirname(os.path.abspath(__file__))

        main_script = os.path.join(agent_dir, "main.py")
        if os.path.exists(main_script):
            logger.info(f"Khởi động main.py từ {main_script}...")
            subprocess.Popen([sys.executable, main_script], cwd=agent_dir)
            return True
        else:
            run_script = os.path.join(agent_dir, "run.py")
            if os.path.exists(run_script):
                logger.info(f"Khởi động run.py từ {run_script}...")
                subprocess.Popen([sys.executable, run_script], cwd=agent_dir)
                return True
            else:
                logger.error(
                    "[start_updater] Không tìm thấy tệp main.py hoặc run.py để khởi động lại."
                )
                return False
    except Exception as e:
        logger.error(f"[start_updater] Lỗi khi khởi động ứng dụng: {e}")
        return False


def restart_nssm_service(service_name=SERVICE_NAME):
    try:
        subprocess.run(["nssm", "stop", service_name], check=True)
        subprocess.run(["nssm", "start", service_name], check=True)
        logger.info(f"Service '{service_name}' restarted successfully.")
    except Exception as e:
        logger.error(f"Failed to restart service '{service_name}': {e}")


# ===================== MAIN LOGIC =====================
def handle_shutdown_signal(signum=None, frame=None):
    logger.info("Received shutdown signal, sending offline status...")
    computer_id = get_value("computer_id")
    room_id = get_value("room_id")
    send_status_update(computer_id, room_id, RABBITMQ_URL, status="offline")
    sys.exit(0)


def main() -> None:
    logger.info("Starting Lab Agent...")
    logger.info(f"Current version: {get_value('app_version', '1.0.0')}")
    logger.info("Checking for updates...")
    try:
        update_initiated = check_for_updates()
        if update_initiated:
            logger.info(
                "Update process initiated. Application will exit and restart after update."
            )
            sys.exit(0)
        logger.info(
            "No new updates or update check failed. Continuing with application startup."
        )
    except Exception as e:
        logger.error(f"[main] Error during update check: {e}")
        logger.info("Skipping update process and continuing with application startup.")
    computer_id, room_id = register_computer()
    if not computer_id or not room_id:
        logger.error("Cannot register computer. Exiting...")
        sys.exit(1)
    logger.info(
        f"Initializing modules with computer_id={computer_id}, room_id={room_id}"
    )
    metrics_running = [True]
    command_running = [True]
    start_metrics_thread(computer_id, room_id, RABBITMQ_URL, 30, metrics_running)
    command_thread = threading.Thread(
        target=start_command_listener,
        args=(computer_id, room_id, RABBITMQ_URL, command_running),
        daemon=True,
    )
    command_thread.start()
    logger.info("All modules have been started.")
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down agent...")
        metrics_running[0] = False
        command_running[0] = False
        # Send offline status before exiting
        send_status_update(computer_id, room_id, RABBITMQ_URL, status="offline")


if __name__ == "__main__":
    main()
