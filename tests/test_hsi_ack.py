import struct
import unittest

from src.adapters.hsi_adapter import HSIPoller


class HsiAckValidationTests(unittest.TestCase):
    def test_direct_haip_16_byte_trigger_ack_is_accepted(self):
        packet = struct.pack("<bbhIIi", 1, 0, 8, 0, 0, 123456789)
        self.assertTrue(HSIPoller._is_successful_ack_packet(packet))

    def test_live_haip_direct_trigger_ack_is_accepted(self):
        packet = bytes.fromhex("00000800020000000000000000000000")
        self.assertTrue(HSIPoller._is_successful_ack_packet(packet))

    def test_trigger_ack_packet_is_accepted(self):
        packet = struct.pack("<i", 16) + struct.pack("<bbhIIi", 1, 0, 8, 0, 0, 123456789)
        self.assertTrue(HSIPoller._is_successful_ack_packet(packet))

    def test_trigger_ack_packet_rejects_non_trigger_response(self):
        packet = struct.pack("<i", 16) + struct.pack("<bbhIIi", 1, 0, 3, 0, 0, 123456789)
        self.assertFalse(HSIPoller._is_successful_ack_packet(packet))

    def test_trigger_ack_packet_rejects_invalid_length(self):
        self.assertFalse(HSIPoller._is_successful_ack_packet(b"short"))


if __name__ == "__main__":
    unittest.main()
