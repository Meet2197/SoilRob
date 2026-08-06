import paho.mqtt.client as mqtt
from influxdb import InfluxDBClient
import json

class MQTTInfluxBridge:
    def __init__(self, mqtt_broker, influx_host, influx_db):
        self.mqtt_client = mqtt.Client()
        self.influx_client = InfluxDBClient(host=influx_host, database=influx_db)
        
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.connect(mqtt_broker, 1883, 60)
        self.mqtt_client.subscribe("#")  # Subscribe to all topics
    
    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            
            # Create InfluxDB point
            point = {
                "measurement": msg.topic.replace("/", "_"),
                "tags": {
                    "source": msg.topic.split('/')[0]
                },
                "fields": self._flatten_dict(payload)
            }
            
            self.influx_client.write_points([point])
        except Exception as e:
            print(f"Error: {e}")
    
    def _flatten_dict(self, d, parent_key='', sep='_'):
        """Flatten nested dictionaries"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep).items())
            else:
                items.append((new_key, v))
        return dict(items)
    
    def start(self):
        self.mqtt_client.loop_forever()

# Usage
bridge = MQTTInfluxBridge('localhost', 'localhost', 'sensors')
bridge.start()