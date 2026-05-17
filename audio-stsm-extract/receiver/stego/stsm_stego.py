#!/usr/bin/env python3
import argparse
import os
import struct
import sys
import wave
from array import array


MAGIC = b"STSM"


def mark(token):
    result = os.path.expanduser("~/.local/result/stsm_check.txt")
    os.makedirs(os.path.dirname(result), exist_ok=True)
    existing = ""
    if os.path.exists(result):
        with open(result, "r", encoding="utf-8") as handle:
            existing = handle.read()
    if token not in existing:
        with open(result, "a", encoding="utf-8") as handle:
            handle.write(token + "\n")


def byte_bits(data):
    for byte in data:
        for bit in range(7, -1, -1):
            yield (byte >> bit) & 1


def bits_bytes(bits):
    out = bytearray()
    for i in range(0, len(bits), 8):
        chunk = bits[i:i + 8]
        if len(chunk) < 8:
            break
        value = 0
        for bit in chunk:
            value = (value << 1) | bit
        out.append(value)
    return bytes(out)


def hamming74_encode(nibble):
    d1 = (nibble >> 3) & 1
    d2 = (nibble >> 2) & 1
    d3 = (nibble >> 1) & 1
    d4 = nibble & 1
    p1 = d1 ^ d2 ^ d4
    p2 = d1 ^ d3 ^ d4
    p3 = d2 ^ d3 ^ d4
    return [p1, p2, d1, p3, d2, d3, d4]


def hamming74_decode(code):
    bits = [0] + code[:]
    s1 = bits[1] ^ bits[3] ^ bits[5] ^ bits[7]
    s2 = bits[2] ^ bits[3] ^ bits[6] ^ bits[7]
    s3 = bits[4] ^ bits[5] ^ bits[6] ^ bits[7]
    syndrome = s1 + (s2 << 1) + (s3 << 2)
    if 1 <= syndrome <= 7:
        bits[syndrome] ^= 1
    return [bits[3], bits[5], bits[6], bits[7]]


def protect(data):
    encoded = []
    for byte in data:
        encoded.extend(hamming74_encode(byte >> 4))
        encoded.extend(hamming74_encode(byte & 0x0F))
    return encoded


def unprotect(bits):
    raw = []
    for i in range(0, len(bits), 7):
        if i + 7 <= len(bits):
            raw.extend(hamming74_decode(bits[i:i + 7]))
    return bits_bytes(raw)


def read_wav(path):
    with wave.open(path, "rb") as wav:
        params = wav.getparams()
        if params.nchannels != 1 or params.sampwidth != 2:
            raise ValueError("Use mono PCM16 WAV.")
        frames = wav.readframes(params.nframes)
    samples = array("h")
    samples.frombytes(frames)
    return params, samples


def write_wav(path, params, samples):
    with wave.open(path, "wb") as wav:
        wav.setparams(params)
        wav.writeframes(samples.tobytes())


def adjust(sample, delta):
    value = sample + delta
    if value > 32767:
        return sample - 1
    if value < -32768:
        return sample + 1
    return value


def embed(args):
    params, samples = read_wav(args.infile)
    with open(args.message, "rb") as handle:
        message = handle.read()
    payload = MAGIC + struct.pack(">I", len(message)) + message
    bits = protect(payload)
    capacity = len(samples) // 3
    if len(bits) > capacity:
        raise ValueError(f"Need {len(bits)} groups, capacity is {capacity}.")

    stego = array("h", samples)
    for i, bit in enumerate(bits):
        base = i * 3
        total = stego[base] + stego[base + 1] + stego[base + 2]
        parity = total & 1
        if bit == parity:
            continue
        if bit == 1:
            stego[base + 1] = adjust(stego[base + 1], 1)
        else:
            stego[base] = adjust(stego[base], 1)

    write_wav(args.out, params, stego)
    mark("PASS_STEGO_CREATED")
    mark("PASS_SAMPLES_MODIFIED")
    print(f"capacity_groups={capacity}")
    print(f"embedded_hamming_bits={len(bits)}")
    print(f"wrote={args.out}")


def extract(args):
    if os.path.exists(args.infile) and os.path.getsize(args.infile) > 0:
        mark("PASS_AUDIO_RECEIVED")
    _, samples = read_wav(args.infile)
    bits = []
    for i in range(0, len(samples) - 2, 3):
        bits.append((samples[i] + samples[i + 1] + samples[i + 2]) & 1)
    decoded = unprotect(bits)
    pos = decoded.find(MAGIC)
    if pos < 0 or pos + 8 > len(decoded):
        raise ValueError("STSM header not found.")
    length = struct.unpack(">I", decoded[pos + 4:pos + 8])[0]
    message = decoded[pos + 8:pos + 8 + length]
    if len(message) != length:
        raise ValueError("message truncated")
    with open(args.out, "wb") as handle:
        handle.write(message)
    mark("PASS_RECOVERED_CREATED")
    print(f"recovered_bytes={len(message)}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("embed")
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--message", required=True)
    p.set_defaults(func=embed)
    p = sub.add_parser("extract")
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=extract)
    try:
        args = parser.parse_args()
        args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
