# Anenji Local Modbus Interface

Read data directly from Anenji inverters (using the Dessmonitor Wi-Fi module) over your local network via Modbus RTU over TCP — at any desired polling frequency, without relying on the cloud.

## How it works

The Dessmonitor Wi-Fi module embedded in the inverter normally pushes data to `dessmonitor.com`. This project hijacks that connection: a UDP message is sent to the inverter telling it to connect back to your machine on port 8899. Once connected, standard Modbus RTU commands are exchanged over the TCP socket to read holding registers.

---

## anenji2mqtt.py — MQTT Publisher

Reads configured registers from the inverter on a fixed interval and publishes each value to an MQTT broker. Designed to run unattended as a long-running service.

### Prerequisites

```bash
pip install pyyaml paho-mqtt
```

### Setup

1. Copy the example config and fill in your details:
   ```bash
   cp conf.yaml.example config.yaml
   ```

2. Define the registers you want to read in `registers.json` (see [Register map](#register-map) below).

3. Run the script:
   ```bash
   python3 anenji2mqtt.py
   ```

### Configuration (`config.yaml`)

```yaml
debug: false  # true = print register values and cycle timing to console

mqtt:
  host: <mqtt_broker_ip>
  port: 1883
  topic: power/anenji   # Values are published as <topic>/<name>

inverter:
  ip: <inverter_ip>
  max_gap: 20           # Max. address gap between registers to group into one Modbus request.
                        # 0 = query each register individually (original single-register behaviour)
  max_batch: 50         # Max. number of registers per single Modbus request (hard limit: 125)
  reconnect_delay: 10   # Seconds to wait before reconnecting after a connection loss
```

### Register map (`registers.json`)

Each entry defines one value to read and publish:

```json
[
  {
    "register": 277,   // Modbus holding register address
    "name": "battery_voltage",  // MQTT sub-topic name, published as <topic>/<name>
    "division": 10     // Raw register value is divided by this before publishing
  }
]
```

The raw 16-bit register value is divided by `division` to produce the final value (e.g. `division: 10` turns `2770` into `277.0`).

### Batch reading

Registers are grouped into batches before querying to minimise the number of Modbus requests per cycle. Two registers are placed in the same batch when:
- their address gap ≤ `max_gap`, **and**
- the total span of the batch ≤ `max_batch`

This can reduce cycle time significantly compared to querying registers one by one. With `debug: true`, the grouping and per-cycle timing are printed on startup.

Example with the default `registers.json` and `max_gap: 20`:

| Batch | Address range | Registers read |
|-------|--------------|----------------|
| 1 | 203 | grid_freq |
| 2 | 252–254 | total_output_current, total_output_active/apparent_power |
| 3 | 277–281 | battery_voltage, current, power, soc, temp_dc_modul |
| 4 | 305 | temp_pv_modul |
| 5 | 338–342 | voltage_unknown_1, voltage_unknown_2 |
| 6 | 351 | pv1_voltage |

### Connection resilience

- If the inverter drops the TCP connection, the error is detected immediately (empty `recv`, socket timeout, or `SO_ERROR`).
- The script waits `reconnect_delay` seconds, then sends a new UDP notify and waits (indefinitely, with retries) for the inverter to reconnect.
- Partial data from a failed cycle is never published to MQTT.
- OS-level `SO_KEEPALIVE` is enabled on the accepted socket to detect half-open (zombie) connections.

---

## anenji_modbus_scan.py — Register Scanner

A diagnostic tool to scan and display raw register values from the inverter.

```
python3 anenji_modbus_scan.py <device_ip> <start_register> <register_count>
```

**Example:**

```
python3 anenji_modbus_scan.py 192.168.99.10 200 10

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

Use this tool to discover register addresses and raw values before adding them to `registers.json`. A partial register map is available in `register_map.txt`.
