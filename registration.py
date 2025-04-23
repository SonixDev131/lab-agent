import json
import os
import platform
import re
from typing import Union

import psutil
import requests

APP_URL = "http://localhost/api"


def get_mac_address() -> Union[str, bool]:
    """Lấy địa chỉ MAC của giao diện mạng chính."""
    try:
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        for interface in addrs:
            if any(
                keyword in interface.lower()
                for keyword in ["loopback", "virtual", "vmnet", "veth", "docker"]
            ):
                continue
            if interface in stats and stats[interface].isup:
                for addr in addrs[interface]:
                    if addr.family == psutil.AF_LINK:
                        mac = addr.address
                        if re.match(r"^([0-9A-Fa-f]{2}-){5}([0-9A-Fa-f]{2})$", mac):
                            if "ethernet" in interface.lower():
                                return mac
                            return mac
        return False
    except Exception as e:
        print(f"[ERROR] Lỗi khi lấy MAC: {e}")
        return False


def register_computer():
    """Đăng ký máy tính với server nếu chưa có computer_id."""
    config_file = "agent_config.json"

    # Kiểm tra file cấu hình
    try:
        if os.path.exists(config_file):
            with open(config_file, "r") as f:
                config = json.load(f)
                return config.get("computer_id"), config.get("room_id")
    except Exception as e:
        print(f"[!] Lỗi khi đọc cấu hình: {e}")

    # Nếu chưa có, gửi yêu cầu đăng ký
    try:
        register_data = {
            "mac_address": get_mac_address(),
            # "timestamp": int(time.time()),
            "hostname": platform.node(),
        }

        response = requests.post(f"{APP_URL}/agents/register", json=register_data)
        if response.status_code == 200:
            result = response.json()

            room_id = result.get("room_id")
            computer_id = result.get("computer_id")

            register_data["room_id"] = room_id
            register_data["computer_id"] = computer_id

            with open(config_file, "w") as f:
                json.dump(register_data, f)

            print(
                f"[*] Đã đăng ký thành công: computer_id={computer_id}, room_id={room_id}"
            )
            return computer_id, room_id
        else:
            print(f"[!] Đăng ký thất bại: {response.status_code} - {response.text}")
            return None, None

    except Exception as e:
        print(f"[!] Lỗi khi đăng ký: {e}")
        return None, None
