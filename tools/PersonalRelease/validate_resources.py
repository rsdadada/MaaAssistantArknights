"""Load the complete personal resource stack with the freshly built Debug core."""

import argparse
import ctypes
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll-dir", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--user-dir", required=True, type=Path)
    args = parser.parse_args()
    dll_dir = args.dll_dir.resolve()
    args.user_dir.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
    with os.add_dll_directory(str(dll_dir)):
        core = ctypes.WinDLL(str(dll_dir / "MaaCore.dll"))
        core.AsstSetUserDir.argtypes = [ctypes.c_char_p]
        core.AsstSetUserDir.restype = ctypes.c_bool
        core.AsstLoadResource.argtypes = [ctypes.c_char_p]
        core.AsstLoadResource.restype = ctypes.c_bool
        core.AsstCreate.restype = ctypes.c_void_p
        core.AsstDestroy.argtypes = [ctypes.c_void_p]
        assert core.AsstSetUserDir(str(args.user_dir.resolve()).encode("utf-8"))
        for root in (args.source.resolve(), args.source.resolve() / "personal"):
            if not core.AsstLoadResource(str(root).encode("utf-8")):
                raise RuntimeError(f"Debug resource validation failed: {root}")
        handle = core.AsstCreate()
        if not handle:
            raise RuntimeError(
                "Core instance could not be created after resource validation"
            )
        core.AsstDestroy(handle)
    print("Debug resource and personal overlay validation passed")


if __name__ == "__main__":
    main()
