#!/usr/bin/env python3
"""Extract complete SQLite databases from a raw disk image.
SQLite DBs are stored contiguously (page-aligned); read from header page count.
Usage: extract_sqlite.py <raw-image> <dest-dir>
"""
import os, sys, struct, re

def extract_db(f, off, dest, label):
    f.seek(off)
    hdr = f.read(100)
    if len(hdr) < 100 or hdr[:16] != b'SQLite format 3\x00':
        return None
    page_size = struct.unpack('>H', hdr[16:18])[0]
    if page_size == 1:
        page_size = 65536
    pages = struct.unpack('>I', hdr[28:32])[0]
    if pages == 0 or pages > 100000:
        return None
    # read the db; some slack in case page count field is stale
    size = pages * page_size
    f.seek(off)
    data = f.read(size + page_size)  # +1 page slack
    # trim to actual: sqlite header may have free pages; keep as-is
    db = data[:size]
    # validate: check a few page headers (page 1 = header, page 2 should start with 0x0D or 0x0A or 0x05)
    if len(db) < page_size * 2:
        return None
    # sanity: page 2 first byte should be 0x0D/0x0A/0x05 (btree page type)
    p2 = db[page_size]
    if p2 not in (0x0D, 0x0A, 0x05):
        # could be freelist/overflow; still save
        pass
    # name from nearby filename strings
    f.seek(max(0, off - 2048))
    ctx = f.read(4096)
    names = re.findall(rb'[A-Za-z0-9_\-\.]+\.db', ctx)
    dbname = names[-1].decode('utf-8', errors='replace') if names else f'db_{off:x}.sqlite'
    # sanitize name
    dbname = re.sub(r'[^\w\.\-]', '_', dbname)
    out = os.path.join(dest, f'{off:x}_{dbname}')
    with open(out, 'wb') as o:
        o.write(db)
    return out, len(db)

def main():
    img, dest = sys.argv[1], sys.argv[2]
    os.makedirs(dest, exist_ok=True)
    f = open(img, 'rb')
    dbs = []
    pos = 0
    CH = 16 * 1024 * 1024
    while True:
        f.seek(pos)
        data = f.read(CH)
        if not data:
            break
        s = 0
        while True:
            i = data.find(b'SQLite format 3\x00', s)
            if i < 0:
                break
            dbs.append(pos + i)
            s = i + 1
        pos += CH
    print(f'Total SQLite headers: {len(dbs)}')
    n = 0
    for off in dbs:
        try:
            r = extract_db(f, off, dest, None)
            if r:
                n += 1
        except Exception as e:
            pass
    print(f'Extracted {n} databases to {dest}')

if __name__ == '__main__':
    main()
