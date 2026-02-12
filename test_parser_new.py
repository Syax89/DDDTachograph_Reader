import struct
from ddd_parser import TachoParser
import json

def create_mock_ddd(filename):
    # Header 76 21 (G2)
    data = b'\x76\x21'
    
    # Tag 0x0502: CardIdentification
    # Length: 101 bytes (23 + 36 + 36 + 4 + 2)
    tag_0502 = b'\x05\x02\x01\x00\x65' # Tag 0502, Type 01, Len 101
    val_0502 = bytearray(101)
    # Member State (1)
    val_0502[0] = 0x01
    # Card Number (16)
    val_0502[1:17] = b'E123456789012345'
    # Expiry 2030 (4 bytes TS) -> 1900000000 approx
    val_0502[19:23] = struct.pack(">I", 1900000000)
    # Surname (36 bytes)
    surname = b'\x01ROSSI' + (b'\x00' * 30)
    val_0502[23:23+36] = surname
    # Firstname (36 bytes)
    firstname = b'\x01MARIO' + (b'\x00' * 30)
    val_0502[59:59+36] = firstname
    # Birth date 1980 (4 bytes TS) -> 315532800
    val_0502[95:99] = struct.pack(">I", 315532800)
    # Language (2 bytes)
    val_0502[99:101] = b'IT'
    data += tag_0502 + val_0502
    
    # Tag 0x0001: VehicleIdentification
    tag_0001 = b'\x00\x01\x01\x00\x11' # Tag 0001, Type 01, Len 17
    val_0001 = b'VF312345678901234' # VIN
    data += tag_0001 + val_0001
    
    # Tag 0x0103: CardCertificate (Mocking a signature)
    tag_0103 = b'\x01\x03\x01\x00\x40' # Tag 0103, Len 64
    val_0103 = b'S' * 64 # Mock signature
    data += tag_0103 + val_0103

    with open(filename, 'wb') as f:
        f.write(data)

if __name__ == "__main__":
    create_mock_ddd("mock.ddd")
    parser = TachoParser("mock.ddd")
    res = parser.parse()
    print(json.dumps(res, indent=2))
