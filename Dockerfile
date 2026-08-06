version: '3.8'

services:
  mosquitto:
    image: eclipse-mosquitto:latest
    ports:
      - "1883:1883"
      - "9001:9001"
    volumes:
      - ./mosquitto.conf:/mosquitto/config/mosquitto.conf
  
  influxdb:
    image: influxdb:latest
    ports:
      - "8086:8086"
    environment:
      - INFLUXDB_DB=sensors
      - INFLUXDB_ADMIN_USER=admin
      - INFLUXDB_ADMIN_PASSWORD=password
  
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    depends_on:
      - influxdb
  
  ax8-bridge:
    build: ./ax8-bridge
    environment:
      - MQTT_BROKER=mosquitto
      - AX8_IP=192.168.7.1
    depends_on:
      - mosquitto
  
  lidar-bridge:
    build: ./lidar-bridge
    environment:
      - MQTT_BROKER=mosquitto
      - CAN_INTERFACE=can0
    depends_on:
      - mosquitto
    devices:
      - /dev/can0:/dev/can0