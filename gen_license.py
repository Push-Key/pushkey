import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime

TIER_CODES = {
    "free": "FREE",
    "starter": "STRT",
    "pro": "PRO",
    "team": "TEAM",
    "enterprise": "ENT",
}

LTD_CODES = {
    "pro": "LTDP",
    "team": "LTDT",
}


def build_key(tier: str, email: str, seats: int, expires, ltd: bool, salt: bytes = None) -> str:
    if ltd:
        prefix = LTD_CODES.get(tier)
        if prefix is None:
            raise ValueError(f"--ltd only supports pro or team, got '{tier}'")
        expiry = None
    else:
        prefix = TIER_CODES[tier]
        expiry = expires

    payload = {"expires": expiry, "seats": seats, "email": email}
    if salt:
        # embed random bytes so --count N produces distinct keys
        payload["_r"] = salt.hex()

    raw = json.dumps(payload, separators=(",", ":")).encode()
    encoded = base64.b32encode(raw).decode().rstrip("=")

    chunks = [encoded[i:i+8] for i in range(0, len(encoded), 8)]
    checksum = hashlib.sha256("-".join(chunks).encode()).hexdigest()[:8].upper()

    return f"{prefix}-{'-'.join(chunks)}-{checksum}"


def verify_key(key: str):
    parts = key.strip().upper().split("-")
    tier_code = parts[0].lower()
    tier_map = {
        "free": "free", "strt": "starter", "pro": "pro",
        "team": "team", "ent": "enterprise",
        "ltdp": "pro", "ltdt": "team",
    }
    tier = tier_map.get(tier_code)

    payload_parts = parts[1:-1]
    checksum = parts[-1]
    expected = hashlib.sha256("-".join(payload_parts).encode()).hexdigest()[:8].upper()
    if checksum != expected:
        return None, f"CHECKSUM MISMATCH (got {checksum}, expected {expected})"

    padded = "".join(payload_parts)
    # b32decode requires padding to multiple of 8
    padded += "=" * ((8 - len(padded) % 8) % 8)
    try:
        raw_payload = base64.b32decode(padded)
        payload = json.loads(raw_payload)
    except Exception as e:
        return None, f"DECODE ERROR: {e}"

    return tier, payload


def print_key(key: str, tier: str, payload: dict):
    expiry = payload.get("expires")
    seats = payload.get("seats", 1)
    email = payload.get("email", "")
    lifetime = expiry is None
    print(f"Generated key: {key}")
    print(f"Tier: {tier} | Email: {email} | Seats: {seats} | Expires: {expiry or 'N/A'} | Lifetime: {lifetime}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Pushkey admin license key generator")
    parser.add_argument("--tier", required=True, choices=["free", "starter", "pro", "team", "enterprise"])
    parser.add_argument("--email", default="")
    parser.add_argument("--seats", type=int, default=1)
    parser.add_argument("--expires", default="lifetime",
                        help="YYYY-MM-DD expiry date or 'lifetime'")
    parser.add_argument("--ltd", action="store_true",
                        help="Lifetime deal (LTDP/LTDT prefix, no expiry)")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of unique keys to generate")
    args = parser.parse_args()

    if args.expires.lower() == "lifetime":
        expiry = None
    else:
        try:
            datetime.strptime(args.expires, "%Y-%m-%d")
        except ValueError:
            print(f"Invalid --expires value '{args.expires}'. Use YYYY-MM-DD or 'lifetime'.", file=sys.stderr)
            sys.exit(1)
        expiry = args.expires

    if args.ltd:
        expiry = None

    for i in range(args.count):
        salt = os.urandom(4) if args.count > 1 else None
        key = build_key(args.tier, args.email, args.seats, expiry, args.ltd, salt)
        tier, payload = verify_key(key)
        if tier is None:
            print(f"ERROR: {payload}", file=sys.stderr)
            sys.exit(1)
        print_key(key, tier, payload)


if __name__ == "__main__":
    main()
