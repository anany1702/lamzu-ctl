import unittest

import lamzu_ctl as lamzu


class ProtocolTests(unittest.TestCase):
    def test_compx_battery_packet(self):
        packet = lamzu.build_compx_battery_packet()
        self.assertEqual(len(packet), 17)
        self.assertEqual(packet[:2], bytes([0x08, 0x04]))
        self.assertEqual(packet[16], (lamzu.compx_crc(packet[1:]) - 8) & 0xFF)

    def test_new_aurora_battery_response_with_report_id(self):
        response = bytes([0, 0xA1, 0, 0, 2, 0, 0x83, 1, 87])
        self.assertEqual(lamzu.parse_aurora_battery_response(response), (87, 1))

    def test_legacy_aurora_battery_response_without_report_id(self):
        response = bytes([0xA1, 2, 0x8F, 0, 0, 64])
        self.assertEqual(lamzu.parse_aurora_battery_response(response), (64, 0))

    def test_invalid_battery_response(self):
        self.assertIsNone(lamzu.parse_aurora_battery_response(bytes([0xA1])))

    def test_rejects_impossible_battery_percentage(self):
        response = bytes([0, 0xA1, 0, 0, 2, 0, 0x83, 0, 101])
        self.assertIsNone(lamzu.parse_aurora_battery_response(response))

    def test_aurora_battery_query_layouts(self):
        new = lamzu.build_aurora_get_battery_packet(new_protocol=True)
        legacy = lamzu.build_aurora_get_battery_packet(new_protocol=False)
        self.assertEqual(len(new), 65)
        self.assertEqual(new[3:7], bytes([2, 2, 0, 0x83]))
        self.assertEqual(legacy[2:5], bytes([2, 0x8F, 1]))


if __name__ == "__main__":
    unittest.main()
