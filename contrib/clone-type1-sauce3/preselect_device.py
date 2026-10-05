#!/usr/bin/env python3
"""Pre-select a device inside an ArkOS4Clone .img (macOS).

Does what dtb_selector does on the BOOT (FAT) partition, without the menus:
  1. remove stale *.dtb / *.ini / *.orig / *.tony / .cn / BMPs from the root
  2. copy consoles/<device>/*            -> root   (boot.ini + dtb)
  3. copy consoles/kernel/<battery>/Image -> root/Image
  4. copy consoles/logo/<logo>/*          -> root   (logo.bmp)

Usage: preselect_device.py <image.img> [--device NAME] [--battery NAME] [--logo NAME]
                           [--add-console NAME=DIR ...]
"""
import argparse
import glob
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def attach(img, mount_root, readonly=False):
    cmd = ["hdiutil", "attach", "-imagekey", "diskimage-class=CRawDiskImage",
           "-nobrowse", "-mountrandom", mount_root, "-plist"]
    if readonly:
        cmd.append("-readonly")
    out = subprocess.run(cmd + [img], check=True, capture_output=True).stdout
    entities = plistlib.loads(out)["system-entities"]
    disk = min((e["dev-entry"] for e in entities), key=len)
    boot = None
    for e in entities:
        mp = e.get("mount-point")
        if mp and os.path.isdir(os.path.join(mp, "consoles")):
            boot = mp
    return disk, boot


def detach(disk):
    subprocess.run(["hdiutil", "detach", disk], check=True, capture_output=True)


def copy_tree_flat(src, dst):
    copied = []
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for name in files:
            if name.startswith("._"):
                continue
            shutil.copyfile(os.path.join(root, name), os.path.join(target, name))
            copied.append(os.path.normpath(os.path.join(rel, name)))
    return copied


def scrub_macos_droppings(boot):
    for name in (".fseventsd", ".Spotlight-V100", ".Trashes", ".TemporaryItems"):
        shutil.rmtree(os.path.join(boot, name), ignore_errors=True)
    for root, _dirs, files in os.walk(boot):
        for name in files:
            if name.startswith("._") or name == ".DS_Store":
                os.remove(os.path.join(root, name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--device", default="clone type1 sauce3 spk")
    ap.add_argument("--battery", default="arkos4clone_fix",
                    choices=["arkos4clone_fix", "original"])
    ap.add_argument("--logo", default="480P")
    ap.add_argument("--add-console", action="append", default=[], metavar="NAME=DIR",
                    help="copy local DIR into consoles/NAME before selecting")
    args = ap.parse_args()

    img = os.path.abspath(args.image)
    mount_root = tempfile.mkdtemp(prefix="arkboot.")

    disk, boot = attach(img, mount_root)
    try:
        if not boot:
            sys.exit("BOOT partition with consoles/ not found in image")
        for spec in args.add_console:
            name, src = spec.split("=", 1)
            dst = os.path.join(boot, "consoles", name)
            os.makedirs(dst, exist_ok=True)
            copy_tree_flat(src, dst)
        dev_dir = os.path.join(boot, "consoles", args.device)
        kernel = os.path.join(boot, "consoles", "kernel", args.battery, "Image")
        logo_dir = os.path.join(boot, "consoles", "logo", args.logo)
        for p in (dev_dir, kernel, logo_dir):
            if not os.path.exists(p):
                sys.exit(f"missing in image: {p}")

        for pat in ("*.dtb", "*.ini", "*.orig", "*.tony", ".cn"):
            for f in glob.glob(os.path.join(boot, pat)):
                os.remove(f)
        shutil.rmtree(os.path.join(boot, "BMPs"), ignore_errors=True)

        expected = {}
        for name in copy_tree_flat(dev_dir, boot):
            expected[name] = md5(os.path.join(dev_dir, name))
        shutil.copyfile(kernel, os.path.join(boot, "Image"))
        expected["Image"] = md5(kernel)
        for name in copy_tree_flat(logo_dir, boot):
            expected[name] = md5(os.path.join(logo_dir, name))

        scrub_macos_droppings(boot)
        subprocess.run(["sync"], check=True)
    finally:
        detach(disk)

    # Re-attach read-only and verify what actually landed on the partition.
    disk, boot = attach(img, mount_root, readonly=True)
    try:
        ok = True
        for name, want in sorted(expected.items()):
            got = md5(os.path.join(boot, name))
            flag = "OK " if got == want else "BAD"
            ok &= got == want
            print(f"  {flag} {name}  {got}")
        ini = open(os.path.join(boot, "boot.ini")).read()
        dtbs = [os.path.basename(p) for p in glob.glob(os.path.join(boot, "*.dtb"))]
        print("  dtb in root:", dtbs)
        for dtb in dtbs:
            if dtb not in ini:
                ok = False
                print(f"  BAD boot.ini does not load {dtb}")
        print("  root listing:", sorted(os.listdir(boot)))
    finally:
        detach(disk)
        shutil.rmtree(mount_root, ignore_errors=True)
    if not ok:
        sys.exit("verification FAILED")
    print("verification passed")


if __name__ == "__main__":
    main()
