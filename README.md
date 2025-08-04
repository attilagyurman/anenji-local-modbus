# Anenji Local Modbus Interface
The aim of the project is to enable data to be extracted directly from Anenji inverters using Dessmonitor at any desired frequency.
The scanner is currently running, which queries a specific register range from the device.
```
python3 anenji_modbus_scan.py <device ip> <start register> <register count>
```
The essence of the operation is that the script listens on a TCP port and sends a message via UDP to the inverter, telling it which IP address and port to connect to.
MODBUS_RTU commands can be sent to the inverter via the established TCP connection.
*Example of the command and output*
```
python3 anenji_modbus_scan.py 192.168.99.146 200 10

 Register  |    Hex |      Dec
------------------------------
       200 |   9000 |   -28671
       201 |   0004 |        4
       202 |   0000 |        0
       203 |   138B |     5003
       204 |   0000 |        0
       205 |   0000 |        0
       206 |   0000 |        0
       207 |   0304 |      772
       208 |   0000 |        0
       209 |   0000 |        0
```
