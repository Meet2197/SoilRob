import paho.mqtt.client as mqtt
import requests
import threading
import time

class AX8MQTTBridge:
    def __init__(self, mqtt_broker='localhost', mqtt_port=1883):
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.connect(mqtt_broker, mqtt_port, 60)
        self.ax8_ip = '192.168.7.1'
        self.ax8_auth = ('admin', 'admin')
    
    def on_connect(self, client, userdata, flags, rc):
        print(f"Connected to MQTT: {rc}")
        client.subscribe("ax8/commands/#")
    
    def on_message(self, client, userdata, msg):
        """Handle incoming MQTT commands"""
        topic = msg.topic
        payload = msg.payload.decode()
        
        if 'alarm' in topic:
            self.set_alarm_via_rest(payload)
        elif 'config' in topic:
            self.update_config(payload)
    
    def publish_camera_metrics(self):
        """Periodically publish camera metrics"""
        while True:
            try:
                response = requests.get(
                    f'http://{self.ax8_ip}/axis-cgi/param.cgi?action=list',
                    auth=self.ax8_auth
                )
                # Parse temperature and other metrics
                metrics = self.parse_metrics(response.text)
                
                self.client.publish('ax8/temperature', metrics['temp'])
                self.client.publish('ax8/status', metrics['status'])
                self.client.publish('ax8/metrics', json.dumps(metrics))
                
            except Exception as e:
                print(f"Error: {e}")
            
            time.sleep(30)  # Publish every 30 seconds
    
    def start(self):
        self.client.on_message = self.on_message
        self.client.loop_start()
        
        # Start metrics publishing in background
        thread = threading.Thread(target=self.publish_camera_metrics, daemon=True)
        thread.start()