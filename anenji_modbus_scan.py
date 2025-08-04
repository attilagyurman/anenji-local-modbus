""" Anenji inverter modbus scanner """

import json
import socket
import struct
import sys
import time
from pathlib import Path

__author__ = "Attila Gyurman"
__licence__ = "MIT"
__maintainer = "Attila Gyurman"
__email__ = "attila.gyurman@gmail.com"

def crc16_modbus(data: bytes):
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

def hexstr_to_bytes(s):
    """Convert hex string (possibly with spaces) to bytes."""
    s = s.replace(" ", "").replace("\n", "")
    return bytes.fromhex(s)

def bytes_to_hexstr(b):
    return ' '.join(f'{x:02X}' for x in b)


def get_start_register_from_request(pkt: bytes):
    """Kinyeri a kezdő regisztert Modbus RTU requestből."""
    # Modbus RTU: [unit][func][reg_hi][reg_lo]...
    # index 2: reg_hi, index 3: reg_lo
    if len(pkt) < 4:
        return 0
    return pkt[2] << 8 | pkt[3]


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def send_udp_notify(devip, localip):
    port = 58899
    command = f"set>server={localip}:8899;"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(command.encode('utf-8'), (devip, port))
    sock.settimeout(2)
    try:
        data, addr = sock.recvfrom(1024)
        print(f"UDP response from {addr}: {data}")
    except socket.timeout:
        print("No UDP reply (this is normal if the device does not answer).")
    sock.close()

def modbus_rtu_command(unit_id, function_code, start_addr, count, data=None):
    """Build a MODBUS RTU frame: [unit][func][addr][count][data][CRC16]."""
    pkt = struct.pack('>B B H H', unit_id, function_code, start_addr, count)
    if data:
        pkt += data
    crc = crc16_modbus(pkt)
    pkt += struct.pack('<H', crc)
    return pkt    

def build_modbus_command(cmddef, args):
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

def parse_modbus_response(data, start_register=0):
    """Parse MODBUS RTU response and print table of register values."""
    # Typical response: [unit_id][func][byte_count][data...][CRC]
    if len(data) < 5:
        print("Response is too short!")
        return
    unit_id = data[0]
    function = data[1]
    byte_count = data[2]
    if len(data) < 3 + byte_count + 2:
        print("Invalid response length!")
        return
    regdata = data[3:3+byte_count]
    print(f"\nUnit ID: {unit_id}, Funkction: {function}, Number of registers: {byte_count//2}")
    print(f"{'Register':>10} | {'Hex':>6} | {'Dec':>8}")
    print("-"*30)
    for i in range(0, len(regdata), 2):
        reg = start_register + (i//2)
        reghex = f"{regdata[i]:02X}{regdata[i+1]:02X}"
        regval = regdata[i] << 8 | regdata[i+1]
        if regval >= 32768:
            regval = regval - 65535
        # marker = "*" if regval != 0 else ""
        print(f"{reg:10} | {reghex:>6} | {regval:8}")

def start_tcp_server(pkt_to_send, expect_bytes=1024, start_register=0):
    port = 8899
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # <-- EZ FONTOS!
    try:
        server.bind(('0.0.0.0', port))
        server.listen(1)
        print(f"\nTCP server running on port {port}, waiting for inverter to connect...")
        conn, addr = server.accept()
        print(f"TCP connection established: {addr}")

        print("Sending MODBUS command over TCP...")
        conn.sendall(pkt_to_send)

        data = conn.recv(expect_bytes)
        # print("\nRaw response (hex):")
        # print(bytes_to_hexstr(data))
        parse_modbus_response(data, start_register)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        server.close()

def main():
    args = sys.argv
    if len(args) < 2:
        print("Isahe: python anenji_modbus_scan.py <datalogger_ip> <register_number> <register_count> [localip=...]")
        sys.exit(1)

    # Parse localip argument
    custom_ip = ''
    for a in args:
        if a.startswith('localip='):
            custom_ip = a.split('=', 1)[1]

    devip = args[1]
    localip = custom_ip or get_local_ip()
    # print(f"Helyi IP (TCP szerverhez): {localip}")

    regCount = 1
    if len(args) > 3:
        regCount = int(args[3])
    
    startRegister = int(args[2])

    pkt = modbus_rtu_command(1, 3, startRegister, regCount)

    requestStr = bytes_to_hexstr(pkt)
    print(f"MODBUS command to send (hex): {requestStr}")


    send_udp_notify(devip, localip)
    start_tcp_server(pkt_to_send=pkt, expect_bytes=1024, start_register=startRegister)
if __name__ == "__main__":
    main()