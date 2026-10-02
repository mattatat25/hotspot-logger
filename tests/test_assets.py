"""Check the shipped PNG, including data past its header."""
from pathlib import Path
import struct
import unittest
import zlib


class LogoTests(unittest.TestCase):
    def test_logo_has_complete_image_data(self):
        data = (Path(__file__).resolve().parents[1] / 'assets/hotspot-logger.png').read_bytes()
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        offset, compressed, header, ended = 8, bytearray(), None, False
        while offset < len(data):
            self.assertGreaterEqual(len(data) - offset, 12, 'Truncated PNG chunk')
            length = struct.unpack('>I', data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            end = offset + 8 + length
            self.assertLessEqual(end + 4, len(data), 'Truncated PNG data')
            payload = data[offset + 8:end]
            checksum = struct.unpack('>I', data[end:end + 4])[0]
            self.assertEqual(zlib.crc32(kind + payload) & 0xffffffff, checksum, kind)
            if kind == b'IHDR':
                header = struct.unpack('>IIBBBBB', payload)
            elif kind == b'IDAT':
                compressed.extend(payload)
            elif kind == b'IEND':
                ended = True
                self.assertEqual(end + 4, len(data))
                break
            offset = end + 4
        self.assertTrue(ended, 'Missing PNG end marker')
        self.assertIsNotNone(header)
        width, height, depth, color, compression, filtering, interlace = header
        self.assertEqual((width, height), (2172, 724))
        self.assertEqual((depth, color, compression, filtering, interlace), (8, 2, 0, 0, 0))
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(compressed)) + decoder.flush()
        self.assertTrue(decoder.eof, 'Incomplete compressed image')
        self.assertFalse(decoder.unused_data)
        self.assertEqual(len(pixels), height * (1 + width * 3))
