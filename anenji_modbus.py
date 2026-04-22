""" Anenjo Modbus local network implementation """

import json
import socket
import struct
import sys
import time
import datetime
from pathlib import Path
from pprint import pprint

__author__ = "Attila Gyurman"
__licence__ = "MIT"
__maintainer = "Attila Gyurman"
__email__ = "attila.gyurman@gmail.com"


class AnenjiModbus:
	def __init__(self, devip):
		self.deviceIP = devip
		self.localIP = self.get_local_ip()
		# Initialize Modbus connection here
		self.send_udp_notify()
		self.start_tcp_server()

	def crc16_modbus(self, data: bytes):
		"""Calculate CRC16/MODBUS CRC."""
		crc = 0xFFFF
		for b in data:
			crc ^= b
			for _ in range(8):
				if (crc & 1):
					crc = (crc >> 1) ^ 0xA001
				else:
					crc >>= 1
		return crc

	def hexstr_to_bytes(self, s):
		"""Convert hex string (possibly with spaces) to bytes."""
		s = s.replace(" ", "").replace("\n", "")
		return bytes.fromhex(s)

	def bytes_to_hexstr(self, b):
		return ' '.join(f'{x:02X}' for x in b)


	def get_start_register_from_request(pkt: bytes):
		"""Kinyeri a kezdő regisztert Modbus RTU requestből."""
		# Modbus RTU: [unit][func][reg_hi][reg_lo]...
		# index 2: reg_hi, index 3: reg_lo
		if len(pkt) < 4:
			return 0
		return pkt[2] << 8 | pkt[3]


	def get_local_ip(self):
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		try:
			s.connect(('8.8.8.8', 80))
			ip = s.getsockname()[0]
		except Exception:
			ip = '127.0.0.1'
		finally:
			s.close()
		return ip

	def send_udp_notify(self):
		port = 58899
		command = f"set>server={self.localIP}:8899;"
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.sendto(command.encode('utf-8'), (self.deviceIP, port))
		sock.settimeout(2)
		try:
			data, addr = sock.recvfrom(1024)
			print(f"UDP response from {addr}: {data}")
		except socket.timeout:
			print("No UDP reply (this is normal if the device does not answer).")
		sock.close()

	def modbus_rtu_command(self, unit_id, function_code, start_addr, count, data=None):
		"""Build a MODBUS RTU frame: [unit][func][addr][count][data][CRC16]."""
		pkt = struct.pack('>B B H H', unit_id, function_code, start_addr, count)
		if data:
			pkt += data
		crc = self.crc16_modbus(pkt)
		pkt += struct.pack('<H', crc)
		return pkt	

	def build_modbus_command(self, cmddef, args):
		"""Build full MODBUS RTU command from the definition and arguments."""
		if cmddef.get('raw', False):
			# For raw mode, user supplies full hex string
			return hexstr_to_bytes(args[3])
		cmdstr = cmddef['cmd']
		# Find placeholders and replace as needed (simple implementation)
		for i, arg in enumerate(args[2:]):
			hexarg = arg.encode('utf-8').hex()
			cmdstr = cmdstr.replace(f'{{ARG{i+2}}}', hexarg)
		# If there are special placeholders (PARAM, CRC etc.), handle them here if needed
		# For now, only support {CRC} at the end
		if '{CRC}' in cmdstr:
			# Find part before {CRC}, compute CRC, replace
			before_crc = cmdstr.split('{CRC}')[0]
			pkt = hexstr_to_bytes(before_crc)
			crc = crc16_modbus(pkt)
			crc_hex = f"{crc:04x}"
			cmdstr = before_crc + crc_hex[2:] + crc_hex[:2]  # little endian
		return hexstr_to_bytes(cmdstr)

	def parse_modbus_response(self, data, start_register=0):
		"""Parse MODBUS RTU response and return a single register value."""
		# Typical response: [unit_id][func][byte_count][data...][CRC]
		if len(data) < 5:
			self.force_reconnect()
			print(f"Response is too short!")
			return
		unit_id = data[0]
		function = data[1]
		byte_count = data[2]
		if len(data) < 3 + byte_count + 2:
			print(f"Invalid response length!")
			return
		regdata = data[3:3+byte_count]
		for i in range(0, len(regdata), 2):
			reg = start_register + (i//2)
			reghex = f"{regdata[i]:02X}{regdata[i+1]:02X}"
			regval = regdata[i] << 8 | regdata[i+1]
			if regval >= 32768:
				regval = regval - 65535
			# marker = "*" if regval != 0 else ""
			# print(f"{reg:10} | {reghex:>6} | {regval:8}")
			return regval

	def parse_modbus_response_batch(self, data, start_register=0):
		"""Parse MODBUS RTU response for a batch read.
		Returns dict {register_address: value} for all registers in the response."""
		result = {}
		if len(data) < 5:
			self.force_reconnect()
			print(f"Response is too short!")
			return result
		byte_count = data[2]
		if len(data) < 3 + byte_count + 2:
			print(f"Invalid response length!")
			return result
		regdata = data[3:3+byte_count]
		for i in range(0, len(regdata), 2):
			reg = start_register + (i // 2)
			regval = regdata[i] << 8 | regdata[i+1]
			if regval >= 32768:
				regval = regval - 65535
			result[reg] = regval
		return result

	def start_tcp_server(self, accept_timeout=30, retry_delay=5):
		"""Bind a TCP server on port 8899 and wait for the inverter to connect.

		Retries forever until the inverter connects:
		  accept_timeout – seconds to wait for a single accept() attempt
		  retry_delay    – seconds to sleep between retries
		"""
		port = 8899
		# Clean up a potentially stale server socket first
		try:
			if hasattr(self, 'server') and self.server:
				self.server.close()
		except Exception:
			pass

		while True:
			try:
				self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
				self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
				self.server.bind(('0.0.0.0', port))
				self.server.listen(1)
				self.server.settimeout(accept_timeout)
				print(f"TCP server is running on port {port}, waiting for the inverter to connect...")
				self.conn, addr = self.server.accept()
				# Enable OS-level keepalive so half-open connections are detected
				self.conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
				self.conn.settimeout(10)  # recv() timeout
				print(f"TCP connection established: {addr}")
				return  # Success
			except socket.timeout:
				print(f"Inverter not connected within {accept_timeout}s, retrying...")
				try:
					self.server.close()
				except Exception:
					pass
				time.sleep(retry_delay)
			except OSError as e:
				print(f"TCP server error: {e} - retrying in {retry_delay}s...")
				try:
					self.server.close()
				except Exception:
					pass
				time.sleep(retry_delay)

	def _is_connected(self):
		"""Return True if the current client socket appears to be alive."""
		if not hasattr(self, 'conn') or self.conn is None:
			return False
		try:
			if self.conn.fileno() == -1:
				return False
			# SO_ERROR = 0 means no pending socket error
			err = self.conn.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
			return err == 0
		except Exception:
			return False

	def reconnect_if_necessary(self):
		"""Check socket health and reconnect if needed."""
		if not self._is_connected():
			print(f"Kapcsolat elveszett, újracsatlakozás...")
			self.force_reconnect()

	def force_reconnect(self):
		"""Close the current connection cleanly, then wait for the inverter to reconnect."""
		# Close existing client connection quietly
		try:
			if hasattr(self, 'conn') and self.conn:
				self.conn.close()
		except Exception:
			pass
		self.conn = None
		self.send_udp_notify()
		self.start_tcp_server()

	def read_register(self, address):
		self.reconnect_if_necessary()
		try:
			pkt = self.modbus_rtu_command(1, 3, address, 1)
			self.conn.sendall(pkt)
			data = self.conn.recv(1024)
			return self.parse_modbus_response(data, address)
		except Exception as e:
			self.force_reconnect()
			print(e)

	def read_registers_batch(self, start_addr, count):
		"""Read `count` consecutive registers starting at `start_addr` in a single Modbus request.
		Returns dict {register_address: value}.
		Raises ConnectionError if the connection is lost so the caller can handle it.
		"""
		self.reconnect_if_necessary()
		try:
			pkt = self.modbus_rtu_command(1, 3, start_addr, count)
			self.conn.sendall(pkt)
			data = self.conn.recv(1024)
			if not data:
				# Empty recv = inverter closed the connection
				self.conn = None
				raise ConnectionError("The inverter closed the TCP connection (empty recv).")
			return self.parse_modbus_response_batch(data, start_addr)
		except (socket.timeout, socket.error, OSError) as e:
			self.conn = None
			raise ConnectionError(f"Modbus read error [{start_addr}+{count}]: {e}") from e

	def write_register(self, address, value):
		# Code to write a value to a register on the Modbus device
		pass

	def close(self):
		# Close the Modbus connection
		try:
			self.conn.close()
		except Exception:
			pass
		self.server.close()	

