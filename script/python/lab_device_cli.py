"""Device-package CLI; pack and inspect work without a running Web backend."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys

from lab_errors import LabError
from lab_device_packages import inspect_package, load_descriptor, pack_device
from lab_paths import default_data_dir


@contextmanager
def library_lock(directory):
    """Use the backend lock so a CLI importer cannot race a running server."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".server.lock"
    if path.is_symlink():
        raise LabError("数据目录锁不能是符号链接")
    stream = path.open("a+b")
    try:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LabError("该数据目录正由后端或其他 CLI 使用；请通过 Web 导入，或停止该后端后重试") from exc
        yield
    finally:
        stream.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lwns device", description="制作、检查和导入 .rov 设备包")
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack", help="制作设备包，不部署设备")
    pack.add_argument("--descriptor", required=True, type=Path)
    sources = pack.add_mutually_exclusive_group()
    sources.add_argument("--image-tar", type=Path)
    sources.add_argument("--dockerfile", type=Path)
    sources.add_argument("--image", help="引用仓库镜像；制作时不拉取")
    pack.add_argument("--name", help="包内默认设备名称")
    pack.add_argument("--version", help="设备定义版本")
    pack.add_argument("--output", required=True, type=Path)
    pack.add_argument("--force", action="store_true", help="允许替换输出文件，不覆盖设备库版本")
    inspect = commands.add_parser("inspect", help="检查格式和资源完整性，不执行设备动作")
    inspect.add_argument("package", type=Path)
    importing = commands.add_parser("import", help="准备镜像并注册到本机设备库，不部署项目")
    importing.add_argument("package", type=Path)
    importing.add_argument("--name", default="", help="本机设备库显示名称")
    importing.add_argument("--data-dir", type=Path, default=default_data_dir())
    importing.add_argument("--docker-socket", default="/var/run/docker.sock")
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["device"]:
        arguments = arguments[1:]
    args = parser.parse_args(arguments)
    try:
        if args.command == "pack":
            descriptor = load_descriptor(args.descriptor)
            if args.name is not None:
                descriptor["name"] = args.name
            if args.version is not None:
                descriptor["version"] = args.version
            if args.image is not None:
                descriptor.update(image=args.image, source={"type": "repository"})
            result = pack_device(descriptor, args.output, image_tar=args.image_tar, dockerfile=args.dockerfile, overwrite=args.force)
        elif args.command == "inspect":
            result = inspect_package(args.package)
        else:
            # Import these only for mutations. Packaging and inspection require
            # neither FastAPI nor a Docker daemon and never execute package code.
            from lab_core import LabManager
            from lab_device_service import DevicePackageService
            with library_lock(args.data_dir):
                manager = LabManager(args.data_dir, docker_socket=args.docker_socket)
                service = DevicePackageService(manager)
                try:
                    result = service.import_file(args.package, name=args.name)
                finally:
                    service.wait()
                    service.images.wait()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (LabError, OSError) as exc:
        print("失败：" + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
