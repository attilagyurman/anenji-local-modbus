#!/usr/bin/env python3

__author__ = "Attila Gyurman"
__licence__ = "MIT"
__maintainer = "Attila Gyurman"
__email__ = "attila.gyurman@gmail.com"

import json
import time
from pathlib import Path
import yaml
import paho.mqtt.client as mqtt
import datetime
from anenji_modbus import AnenjiModbus



# Loading Config
def load_config(config_path='config.yaml'):
	try:
		with open(config_path, 'r') as config_file:
			config = yaml.safe_load(config_file)
		print(f"config.yaml loaded successfully.")
		return config
	except Exception as e:
		print(f"Error occured loading config.yaml: {e}")
		exit()


def on_mqtt_connect(client, userdata, flags, rc, properties=None):
	print(f"MQTT Connected with result code {rc}")
	# Subscribing in on_connect() means that if we lose the connection and
	# reconnect then subscriptions will be renewed.
	# client.subscribe("$SYS/#")


def group_registers(registers, max_gap=20, max_batch=50):
	"""Group sorted registers into Modbus batches.

	Two registers land in the same batch when:
	  - the gap to the previous register <= max_gap, AND
	  - the span from the first to the last register in the group <= max_batch.

	Setting max_gap=0 effectively gives individual per-register queries
	(same behaviour as the original single-register loop).

	Returns a list of groups, each being a list of register dicts.
	"""
	if not registers:
		return []
	sorted_regs = sorted(registers, key=lambda r: r['register'])
	groups = []
	current_group = [sorted_regs[0]]
	for reg in sorted_regs[1:]:
		prev_addr = current_group[-1]['register']
		curr_addr = reg['register']
		span = curr_addr - current_group[0]['register'] + 1
		if (curr_addr - prev_addr <= max_gap) and (span <= max_batch):
			current_group.append(reg)
		else:
			groups.append(current_group)
			current_group = [reg]
	groups.append(current_group)
	return groups

# The callback for when a PUBLISH message is received from the server.
def on_mqtt_message(client, userdata, msg):
	pass
	# print(msg.topic+" "+str(msg.payload))

if __name__ == "__main__":
	config = load_config()
	if config:
		
		mqttc = mqtt.Client()
		mqttc.on_connect = on_mqtt_connect
		mqttc.on_message = on_mqtt_message
		mqttc.reconnect_delay_set(min_delay=1, max_delay=30)
		mqttc.connect(config['mqtt'].get('host', 'localhost'), config['mqtt'].get('port', 1883), 60)
		mqttTopic = config['mqtt'].get('topic', 'power/anenji')

		# Json register config
		try:
			with open('registers.json', 'r', encoding='utf-8') as f:
				registers = json.load(f)
			print(f"registers.json loaded successfully.")
		except Exception as e:
			print(f"Error occured loading registers.json: {e}")
			exit()

		mqttc.loop_start()

		try:
			anenji = AnenjiModbus(config['inverter'].get('ip'))
			max_gap = config['inverter'].get('max_gap', 20)
			max_batch = config['inverter'].get('max_batch', 50)
			reconnect_delay = config['inverter'].get('reconnect_delay', 10)
			debug = config.get('debug', False)
			groups = group_registers(registers, max_gap=max_gap, max_batch=max_batch)
			if debug:
				print(f"Register groups (max_gap={max_gap}, max_batch={max_batch}):")
				for g in groups:
					start = g[0]['register']
					end = g[-1]['register']
					count = end - start + 1
					names = [r['name'] for r in g]
					print(f"  [{start}..{end}] ({count} reg, {len(g)} érték): {names}")

			while True:
				cycle_start = time.time()
				all_values = {}
				connection_ok = True

				for group in groups:
					start_addr = group[0]['register']
					end_addr = group[-1]['register']
					count = end_addr - start_addr + 1
					try:
						batch = anenji.read_registers_batch(start_addr, count)
						all_values.update(batch)
					except ConnectionError as e:
						print(f"Network connection disconnected: {e}")
						print(f"Reconnecting in {reconnect_delay}s...")
						time.sleep(reconnect_delay)
						anenji.force_reconnect()
						connection_ok = False
						break  # Hagyja abba a ciklust, kezdje elölről

				if not connection_ok:
					continue  # Ugrik vissza a while True-ra, nem publikál részleges adatot

				for reg in registers:
					regValue = all_values.get(reg['register'])
					if isinstance(regValue, (int, float)):
						regValue = regValue / reg['division']
						if debug:
							print(f"{reg['name']} = {regValue}")
						msg = mqttc.publish(mqttTopic + "/" + reg['name'], regValue, qos=1)
						msg.wait_for_publish()

				if debug:
					cycle_ms = (time.time() - cycle_start) * 1000
					print(f"Cycle time: {cycle_ms:.0f} ms ({len(groups)} Modbus requests, {len(registers)} registers)")
				time.sleep(30)
		except KeyboardInterrupt:
			anenji.close();
			print("Exiting...")		

		mqttc.disconnect()
		mqttc.loop_stop()

