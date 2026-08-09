#!/usr/bin/env python3
"""Inject ksuinit into AVD ramdisk cpio, preserving device nodes (rdev).
Usage: python3 inject_ksuinit.py <stock-ramdisk.img> <ksuinit> <output-ramdisk.img>
"""
import sys, os, io, struct, gzip, lz4.frame

def read_cpio_full(data):
    """Parse cpio newc archive with full header (incl. rdev for device nodes)."""
    entries = []
    pos = 0
    while pos + 110 <= len(data):
        if data[pos:pos+6] != b'070701':
            break
        fields = [int(data[pos+6+i*8:pos+14+i*8], 16) for i in range(13)]
        ino, mode, uid, gid, nlink, mtime, filesize, devmajor, devminor, rdevmajor, rdevminor, namesize, check = fields
        hdr_end = pos + 110
        name_end = hdr_end + namesize
        name_end_aligned = (name_end + 3) & ~3
        name = data[hdr_end:hdr_end+namesize-1].decode('utf-8', errors='replace')
        data_start = name_end_aligned
        data_end = data_start + filesize
        data_end_aligned = (data_end + 3) & ~3
        content = data[data_start:data_end]
        if name == 'TRAILER!!!':
            break
        entries.append({
            'name': name, 'mode': mode, 'ino': ino, 'uid': uid, 'gid': gid,
            'nlink': nlink, 'mtime': mtime, 'filesize': filesize,
            'devmajor': devmajor, 'devminor': devminor,
            'rdevmajor': rdevmajor, 'rdevminor': rdevminor,
            'content': content,
        })
        pos = data_end_aligned
    return entries

def write_cpio_full(entries):
    """Write cpio newc archive preserving device node metadata."""
    out = io.BytesIO()
    for i, e in enumerate(entries, 1):
        name_bytes = e['name'].encode('utf-8') + b'\x00'
        namesize = len(name_bytes)
        filesize = len(e['content'])
        mode = e['mode']
        if (mode & 0o170000) == 0o020000:  # char device
            # device nodes have no data; keep rdev
            pass
        hdr = (f'070701{i:08X}{mode:08X}{e["uid"]:08X}{e["gid"]:08X}'
               f'{e["nlink"]:08X}{e["mtime"]:08X}{filesize:08X}'
               f'{e["devmajor"]:08X}{e["devminor"]:08X}'
               f'{e["rdevmajor"]:08X}{e["rdevminor"]:08X}'
               f'{namesize:08X}00000000').encode()
        assert len(hdr) == 110, f'header len {len(hdr)}'
        out.write(hdr)
        out.write(name_bytes)
        pad = (4 - (110 + namesize) % 4) % 4
        out.write(b'\x00' * pad)
        out.write(e['content'])
        pad = (4 - filesize % 4) % 4
        out.write(b'\x00' * pad)
    # trailer
    trailer = b'TRAILER!!!\x00'
    namesize = len(trailer)
    hdr = (f'07070100000000000000000000000000000000000000010000000000000000'
           f'00000000000000000000000000000000{namesize:08X}00000000').encode()
    out.write(hdr)
    out.write(trailer)
    pad = (4 - (110 + namesize) % 4) % 4
    out.write(b'\x00' * pad)
    return out.getvalue()

def main():
    if len(sys.argv) < 4:
        print("Usage: inject_ksuinit.py <stock-ramdisk.img> <ksuinit> <output-ramdisk.img>")
        sys.exit(1)
    ramdisk_path, ksuinit_path, output_path = sys.argv[1:4]
    # Decompress with lz4 CLI (handles all lz4 variants reliably)
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile(suffix='.cpio', delete=False) as tf:
        cpio_tmp = tf.name
    subprocess.run(['lz4', '-d', '-f', ramdisk_path, cpio_tmp],
                   check=True, capture_output=True)
    cpio_data = open(cpio_tmp, 'rb').read()
    os.unlink(cpio_tmp)
    compress = 'lz4legacy'

    # Preserve trailing bootconfig payload (after cpio TRAILER) - holds fstab etc.
    def find_cpio_end(data):
        pos = 0
        while pos + 110 <= len(data):
            if data[pos:pos+6] != b'070701':
                break
            filesize = int(data[pos+54:pos+62], 16)
            namesize = int(data[pos+94:pos+102], 16)
            name = data[pos+110:pos+110+namesize-1].decode('utf-8', errors='replace')
            name_end_aligned = (pos + 110 + namesize + 3) & ~3
            data_end = name_end_aligned + filesize
            data_end_aligned = (data_end + 3) & ~3
            if name == 'TRAILER!!!':
                return data_end_aligned
            pos = data_end_aligned
        return 0
    cpio_end = find_cpio_end(cpio_data)
    bootconfig_payload = cpio_data[cpio_end:]
    print(f'Trailing bootconfig payload: {len(bootconfig_payload)} bytes')

    entries = read_cpio_full(cpio_data)
    print(f'Parsed {len(entries)} entries')
    for e in entries:
        print(f'  {e["mode"]:06o} {e["name"]} ({len(e["content"])}B) rdev={e["rdevmajor"]}:{e["rdevminor"]}')

    # inject ksuinit
    ksuinit = open(ksuinit_path, 'rb').read()
    new_entries = []
    init_done = False
    for e in entries:
        if e['name'] == 'init' and (e['mode'] & 0o170000) == 0o100000:  # regular file init
            # backup original init as init.real
            orig = dict(e)
            orig['name'] = 'init.real'
            new_entries.append(orig)
            # replace init with ksuinit
            ne = dict(e)
            ne['content'] = ksuinit
            ne['filesize'] = len(ksuinit)
            ne['mode'] = (e['mode'] & ~0o7777) | 0o755
            new_entries.append(ne)
            init_done = True
            print(f'  -> init replaced with ksuinit ({len(ksuinit)}B), original kept as init.real')
        else:
            new_entries.append(e)

    if not init_done:
        print('WARNING: no init found, adding ksuinit as init')
        new_entries.insert(0, {
            'name': 'init', 'mode': 0o100755, 'ino': 1, 'uid': 0, 'gid': 0,
            'nlink': 1, 'mtime': 0, 'filesize': len(ksuinit),
            'devmajor': 0, 'devminor': 0, 'rdevmajor': 0, 'rdevminor': 0,
            'content': ksuinit,
        })

    new_cpio = write_cpio_full(new_entries)
    # Re-append bootconfig payload so init can read fstab from it
    new_cpio = new_cpio + bootconfig_payload
    print(f'New cpio + bootconfig: {len(new_cpio)} bytes')

    if compress == 'lz4legacy':
        # compress with lz4 CLI legacy mode: lz4 -l -9
        import subprocess
        with tempfile.NamedTemporaryFile(suffix='.cpio', delete=False) as tf:
            tf.write(new_cpio)
            cpio_tmp = tf.name
        subprocess.run(['lz4', '-l', '-9', '-f', cpio_tmp, output_path],
                       check=True, capture_output=True)
        os.unlink(cpio_tmp)
        out_data = open(output_path, 'rb').read()
        print(f'Compressed lz4-legacy via CLI: {len(out_data)} bytes')
        print(f'Output: {output_path} ({len(out_data)} bytes, {compress})')
        return

    with open(output_path, 'wb') as f:
        f.write(out_data)
    print(f'Output: {output_path} ({len(out_data)} bytes, {compress})')

if __name__ == '__main__':
    main()
