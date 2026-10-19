import struct
import sys
import types
import unittest
from unittest.mock import patch

from src.adapters.thermal_adapter import ThermalPoller


def _float_registers(value: float) -> list[int]:
    bits = struct.unpack(">I", struct.pack(">f", value))[0]
    return [bits & 0xFFFF, bits >> 16]


class _ModbusException(Exception):
    pass


class ThermalModbusTests(unittest.TestCase):
    def _install_modbus_client(self, client_factory):
        package = types.ModuleType("pymodbus")
        package.__path__ = []
        client_module = types.ModuleType("pymodbus.client")
        client_module.ModbusTcpClient = client_factory
        exceptions_module = types.ModuleType("pymodbus.exceptions")
        exceptions_module.ModbusException = _ModbusException
        return patch.dict(
            sys.modules,
            {
                "pymodbus": package,
                "pymodbus.client": client_module,
                "pymodbus.exceptions": exceptions_module,
            },
        )

    def test_modbus_poller_decodes_temperatures_for_fusion(self):
        registers = sum(
            (_float_registers(value) for value in (24.5, 20.0, 30.0, 25.0)),
            [],
        )
        calls = {}

        class Response:
            def __init__(self):
                self.registers = registers

            def isError(self):
                return False

        class Client:
            def __init__(self, ip, port, timeout):
                calls["connection"] = (ip, port, timeout)

            def connect(self):
                return True

            def read_holding_registers(self, address, *, count, device_id):
                calls["read"] = (address, count, device_id)
                return Response()

            def close(self):
                calls["closed"] = True

        poller = ThermalPoller(
            "site_A",
            "169.254.79.239",
            502,
            1,
            callback=lambda *_: None,
            protocol="modbus_tcp",
        )
        with self._install_modbus_client(Client):
            reading = poller._read_spot_temperature()

        self.assertEqual(calls["connection"], ("169.254.79.239", 502, 2.0))
        self.assertEqual(calls["read"], (1018, 8, 1))
        self.assertTrue(calls["closed"])
        self.assertAlmostEqual(reading["thermal_temperature"], 24.5)
        self.assertEqual(reading["box1_min_c"], 20.0)
        self.assertEqual(reading["box1_max_c"], 30.0)
        self.assertEqual(reading["box1_avg_c"], 25.0)
        self.assertIn("timestamp_utc", reading)

    def test_modbus_error_response_is_reported_and_connection_closed(self):
        calls = []

        class Response:
            def isError(self):
                return True

        class Client:
            def __init__(self, *_args, **_kwargs):
                pass

            def connect(self):
                return True

            def read_holding_registers(self, address, count):
                calls.append((address, count))
                return Response()

            def close(self):
                calls.append("closed")

        poller = ThermalPoller(
            "site_A", "camera", 502, 1, callback=lambda *_: None,
            protocol="modbus_tcp",
        )
        with self._install_modbus_client(Client):
            reading = poller._read_spot_temperature()

        self.assertIsNone(reading)
        self.assertEqual(calls, [(1018, 8), "closed"])
        self.assertEqual(poller._failure_count, 1)

    def test_http_remains_the_default_protocol(self):
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"spot_temp_f": 77.0}

        poller = ThermalPoller("site_A", "camera", 80, 1, callback=lambda *_: None)
        with patch("src.adapters.thermal_adapter.requests.get", return_value=Response()):
            reading = poller._read_spot_temperature()

        self.assertEqual(poller.protocol, "http")
        self.assertEqual(reading["temp_f"], 77.0)


if __name__ == "__main__":
    unittest.main()
