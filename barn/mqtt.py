"""Small MQTT helper shared by the barn publishers. Reads MQTT_* from the environment / .env."""

import os
from pathlib import Path


def connect(client_id: str):
    import paho.mqtt.client as mqtt

    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    c.username_pw_set(os.environ.get("MQTT_USER", ""), os.environ.get("MQTT_PASSWORD", ""))
    c.reconnect_delay_set(1, 60)
    c.connect_async(os.environ.get("MQTT_HOST", "127.0.0.1"), int(os.environ.get("MQTT_PORT", 1883)))
    c.loop_start()
    return c
