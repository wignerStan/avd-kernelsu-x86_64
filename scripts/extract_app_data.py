#!/usr/bin/env python3
"""Extract an app's data directory from an ext4 image using the ext4 python lib.
Usage: extract_app_data.py <raw-image> <offset> <app-name> <dest-dir>
"""
import sys, os, stat as statmod

def walk_dir(fs, inode, path, out, app, found):
    """Recursively walk directory inode, dumping matching files."""
    if inode is None or not hasattr(inode, '_opendir'):
        return
    try:
        entries = list(inode._opendir())
    except Exception as e:
        print(f'  [skip] {path}: {e}')
        return
    for de in entries:
        name = getattr(de, 'name', None)
        if name in (None, '.', '..'):
            continue
        try:
            name = name.decode('utf-8', errors='replace')
        except Exception:
            pass
        child_path = f'{path}/{name}'
        try:
            child = inode.open(name)
        except Exception:
            continue
        child_path_full = os.path.join(out, child_path.lstrip('/'))
        if child is None:
            continue
        # Directory?
        if hasattr(child, '_opendir') or getattr(child, 'get_file_type', lambda: None)() == 2:
            os.makedirs(child_path_full, exist_ok=True)
            walk_dir(fs, child, child_path, out, app, found)
        else:
            # Regular file
            try:
                data = child._open().read() if hasattr(child, '_open') else None
                if data is None and hasattr(child, 'read'):
                    child.seek(0)
                    data = child.read()
            except Exception:
                data = None
            if data is None:
                continue
            os.makedirs(os.path.dirname(child_path_full), exist_ok=True)
            with open(child_path_full, 'wb') as f:
                f.write(data)
            print(f'  dumped {child_path} ({len(data)}B)')

def main():
    raw, offset, app, dest = sys.argv[1:5]
    import ext4
    fs = ext4.Volume(open(raw, 'rb'), offset=int(offset))
    print(f'Volume opened, block_size={fs.block_size}')
    root = fs.root
    os.makedirs(dest, exist_ok=True)
    # Walk /data/data and /data/user/0 to find the app
    for base in ['data/data', 'data/user/0']:
        print(f'=== {base} ===')
        # navigate manually
        node = root
        for part in base.split('/'):
            try:
                node = node.open(part)
            except Exception as e:
                print(f'  cannot open {part}: {e}')
                node = None
                break
        if node is None:
            continue
        # find app dir
        try:
            entries = list(node._opendir())
        except Exception as e:
            print(f'  opendir {base} failed: {e}')
            continue
        for de in entries:
            name = getattr(de, 'name', None)
            if name is None:
                continue
            try:
                name = name.decode('utf-8', errors='replace')
            except Exception:
                pass
            if name == app:
                print(f'FOUND {app} at {base}/{name}')
                try:
                    app_node = node.open(name)
                except Exception as e:
                    print(f'  open failed: {e}')
                    continue
                os.makedirs(os.path.join(dest, base), exist_ok=True)
                walk_dir(fs, app_node, f'{base}/{name}', dest, app, True)
                print(f'=== done {base}/{name} ===')

if __name__ == '__main__':
    main()
