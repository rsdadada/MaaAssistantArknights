"""Prepare reproducible personal builds and publish only complete verified artifacts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from generate_cultivation import generate

VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")
RESOURCE_TAG = re.compile(
    r"^personal-resource/(v\d+\.\d+\.\d+(?:-beta\.\d+)?)-r(\d+)/(\d+)$"
)
DATA_FILES = ("character_table", "gamedata_const", "building_data", "item_table")


def version_key(version: str) -> tuple[int, int, int, int, int]:
    match = VERSION.fullmatch(version)
    if not match:
        raise ValueError(f"Unsupported upstream version: {version}")
    major, minor, patch, beta = match.groups()
    return int(major), int(minor), int(patch), int(beta is None), int(beta or 0)


def select_versions(releases: list[dict]) -> list[str]:
    eligible = [
        r["tag_name"]
        for r in releases
        if not r.get("draft") and VERSION.fullmatch(r.get("tag_name", ""))
    ]
    stable = [v for v in eligible if "-" not in v]
    if not stable:
        raise ValueError("No upstream stable release found")
    # Beta users also receive a final release. Never select by publication time.
    return sorted(
        {max(stable, key=version_key), max(eligible, key=version_key)}, key=version_key
    )


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=4) + "\n", encoding="utf-8"
    )


def request_json(path: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MAA-PersonalRelease",
    }
    if token := os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com/{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def download(url: str, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        urllib.request.urlopen(url, timeout=180) as response,
        destination.open("wb") as output,
    ):
        shutil.copyfileobj(response, output)


def optional_json(path: str):
    try:
        return request_json(path)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def resume_pending_job(config: dict, job: dict) -> dict:
    repository = config["releaseRepository"]
    tag = urllib.parse.quote(job["tag"], safe="/")
    if optional_json(f"repos/{repository}/git/ref/tags/{tag}") is None:
        return job
    ref = urllib.parse.quote(job["tag"], safe="")
    content = request_json(
        f"repos/{repository}/contents/personal/source-identity.json?ref={ref}"
    )
    identity = json.loads(base64.b64decode(content["content"]))
    previous = identity.get("buildJob")
    if (
        not previous
        or previous.get("tag") != job["tag"]
        or previous.get("patchsetHash") != job["patchsetHash"]
    ):
        raise ValueError(
            f"Pending tag {job['tag']} does not match this patch series; inspect it before changing revision"
        )
    return {**previous, "resumeSourceTag": job["tag"]}


def releases(repository: str) -> list[dict]:
    result = []
    for page in range(1, 21):
        batch = request_json(f"repos/{repository}/releases?per_page=100&page={page}")
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise ValueError(
        "Release history exceeds supported pagination; archive old resource releases"
    )


def git(directory: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(directory), *args], text=True, encoding="utf-8"
    ).strip()


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def patch_paths(root: Path) -> list[Path]:
    directory = root / "personal/patches"
    series = directory / "series"
    if not series.exists():
        raise ValueError(
            "Patch series missing. Export the reviewed commits before enabling synchronization."
        )
    paths = []
    for line in series.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        path = (directory / line).resolve()
        if (
            path.parent != directory.resolve()
            or path.suffix != ".patch"
            or not path.is_file()
        ):
            raise ValueError(f"Invalid patch series entry: {line}")
        paths.append(path)
    if not paths:
        raise ValueError("Empty patch series would publish an unenhanced application")
    return paths


def patch_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in patch_paths(root):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def release_asset(release: dict, name: str):
    asset = next((a for a in release.get("assets", []) if a["name"] == name), None)
    if not asset:
        raise ValueError(f"Published release lacks {name}: {release['tag_name']}")
    with urllib.request.urlopen(asset["browser_download_url"], timeout=90) as response:
        return json.load(response)


def discover(root: Path, config: dict) -> list[dict]:
    versions = select_versions(releases(config["upstreamRepository"]))
    existing = {
        r["tag_name"]: r
        for r in releases(config["releaseRepository"])
        if not r.get("draft")
    }
    resource_commit = request_json(
        f"repos/{config['resourceRepository']}/commits/main"
    )["sha"]
    game_commit = request_json(f"repos/{config['gameDataRepository']}/commits/HEAD")[
        "sha"
    ]
    patchset = patch_digest(root)
    jobs = []
    for version in versions:
        app_tag = f"personal/{version}-r{config['revision']}"
        job = {
            "upstreamVersion": version,
            "revision": config["revision"],
            "resourceCommit": resource_commit,
            "gameDataCommit": game_commit,
            "patchsetHash": patchset,
            "appTag": app_tag,
        }
        if app_tag not in existing:
            jobs.append(
                resume_pending_job(config, {**job, "kind": "app", "tag": app_tag})
            )
            continue
        app = release_asset(existing[app_tag], "personal-release.json")
        if app.get("patchsetHash") != patchset:
            raise ValueError(
                f"Bump revision before changing the patches of published {app_tag}"
            )
        resource_releases = []
        for tag, release in existing.items():
            match = RESOURCE_TAG.fullmatch(tag)
            if match and match[1] == version and int(match[2]) == config["revision"]:
                resource_releases.append((int(match[3]), release))
        latest = (
            release_asset(
                max(resource_releases, key=lambda x: x[0])[1], "personal-resource.json"
            )
            if resource_releases
            else app
        )
        if (
            latest.get("resourceCommit") == resource_commit
            and latest.get("gameDataCommit") == game_commit
        ):
            continue
        revision = max((number for number, _ in resource_releases), default=0) + 1
        jobs.append(
            resume_pending_job(
                config,
                {
                    **job,
                    "kind": "resource",
                    "tag": f"personal-resource/{version}-r{config['revision']}/{revision}",
                    "resourceRevision": revision,
                },
            )
        )
    return jobs


def extract_repository(archive: Path, destination: Path):
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            parts = Path(info.filename).parts[1:]
            if not parts:
                continue
            relative = Path(*parts)
            target = (destination / relative).resolve()
            if (
                not target.is_relative_to(destination.resolve())
                or ".." in relative.parts
            ):
                raise ValueError("Unsafe repository archive path")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(info) as incoming, target.open("wb") as output:
                    shutil.copyfileobj(incoming, output)


def merge_resources(base: Path, overlay: Path):
    # MaaResource is a hot-update layer, not a complete installation: models and
    # other binary resources must remain pinned to the official application tag.
    if not base.is_dir() or not overlay.is_dir():
        raise ValueError(
            "Both the complete resource base and hot-update layer are required"
        )
    shutil.copytree(overlay, base, dirs_exist_ok=True)


def prepare(root: Path, config: dict, job: dict, workspace: Path):
    workspace.mkdir(parents=True, exist_ok=False)
    source = workspace / "source"
    source.mkdir()
    git(source, "init")
    repository = (
        config["upstreamRepository"]
        if job["kind"] == "app" and not job.get("resumeSourceTag")
        else config["releaseRepository"]
    )
    tag = job.get("resumeSourceTag") or (
        job["upstreamVersion"] if job["kind"] == "app" else job["appTag"]
    )
    git(source, "remote", "add", "origin", f"https://github.com/{repository}.git")
    git(source, "fetch", "--depth=1", "--no-tags", "origin", f"refs/tags/{tag}")
    git(source, "checkout", "--detach", "FETCH_HEAD")
    git(source, "config", "user.name", "MAA Personal Build")
    git(
        source,
        "config",
        "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com",
    )
    if job.get("resumeSourceTag"):
        identity = read(source / "personal/source-identity.json")
        identity["sourceCommit"] = git(source, "rev-parse", "HEAD")
        write(workspace / "personal-build.json", identity)
        write(workspace / "job.json", job)
        return
    upstream_commit = git(source, "rev-parse", "HEAD")
    if job["kind"] == "app":
        for patch in patch_paths(root):
            git(source, "am", "--committer-date-is-author-date", str(patch))
    else:
        upstream_commit = read(source / "personal/source-identity.json")[
            "upstreamCommit"
        ]
    resource_zip = workspace / "resources.zip"
    download(
        f"https://github.com/{config['resourceRepository']}/archive/{job['resourceCommit']}.zip",
        resource_zip,
    )
    extract_repository(resource_zip, workspace / "resource-source")
    # Overlay the hot-update snapshot onto the complete resources from the pinned
    # application tag. Resource-only builds use their compatible personal app tag.
    resource_dir = (source / "resource").resolve()
    if not resource_dir.is_relative_to(workspace.resolve()):
        raise ValueError("Resource destination escaped workspace")
    merge_resources(resource_dir, workspace / "resource-source/resource")
    data = workspace / "gamedata"
    for name in DATA_FILES:
        download(
            f"https://raw.githubusercontent.com/{config['gameDataRepository']}/{job['gameDataCommit']}/gamedata/excel/{name}.json",
            data / f"{name}.json",
        )
    cultivation = generate(data, resource_dir, job["gameDataCommit"])
    write(source / "personal/resource/cultivation.json", cultivation)
    identity = {
        "schemaVersion": 1,
        "architecture": config["architecture"],
        "upstreamVersion": job["upstreamVersion"],
        "upstreamCommit": upstream_commit,
        "revision": job["revision"],
        "resourceCommit": job["resourceCommit"],
        "gameDataCommit": job["gameDataCommit"],
        "patchsetHash": job["patchsetHash"],
        "buildJob": job,
    }
    write(source / "personal/source-identity.json", identity)
    git(source, "add", "resource", "personal/resource", "personal/source-identity.json")
    git(
        source,
        "commit",
        "--allow-empty",
        "-m",
        f"Pin personal build resources for {job['tag']}",
    )
    identity["sourceCommit"] = git(source, "rev-parse", "HEAD")
    write(workspace / "personal-build.json", identity)
    write(workspace / "job.json", job)


def package(workspace: Path):
    job = read(workspace / "job.json")
    identity = read(workspace / "personal-build.json")
    install = workspace / "install"
    output = workspace / "artifacts"
    output.mkdir(exist_ok=True)
    if job["kind"] == "app":
        required = (
            "MAA.exe",
            "MAA.dll",
            "MaaCore.dll",
            "MAA.Updater.exe",
            "MaaAdbControlUnit.dll",
            "MaaWin32ControlUnit.dll",
            "resource/tasks/tasks.json",
            "resource/version.json",
            "personal/resource/cultivation.json",
        )
        for name in required:
            if not (install / name).is_file():
                raise ValueError(f"Incomplete install: {name}")
        write(install / "personal-build.json", identity)
        files = sorted(
            p.relative_to(install).as_posix()
            for p in install.rglob("*")
            if p.is_file() and p.name != "filelist.txt"
        )
        (install / "filelist.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
        name = f"MAA-{identity['upstreamVersion']}-personal.{identity['revision']}-win-x64.zip"
        make_zip(install, output / name)
        write(
            output / "personal-release.json",
            {
                **identity,
                "packages": {
                    "win-x64": {"fileName": name, "sha256": sha256(output / name)}
                },
            },
        )
    else:
        name = f"MAA-resources-{identity['upstreamVersion']}-r{identity['revision']}-{job['resourceRevision']}.zip"
        make_zip(install, output / name, ("resource", "personal/resource"))
        write(
            output / "personal-resource.json",
            {
                "schemaVersion": 1,
                "upstreamVersion": identity["upstreamVersion"],
                "revision": identity["revision"],
                "resourceRevision": job["resourceRevision"],
                "resourceCommit": identity["resourceCommit"],
                "gameDataCommit": identity["gameDataCommit"],
                "patchsetHash": identity["patchsetHash"],
                "sourceCommit": identity["sourceCommit"],
                "package": {"fileName": name, "sha256": sha256(output / name)},
            },
        )
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha256(p)}  {p.name}\n" for p in sorted(output.glob("*.zip"))),
        encoding="utf-8",
    )


def make_zip(source: Path, output: Path, directories: tuple[str, ...] = (".",)):
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for directory in directories:
            for path in sorted((source / directory).rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(source).as_posix())


def publish(root: Path, config: dict, workspace: Path):
    job = read(workspace / "job.json")
    source = workspace / "source"
    artifacts = list((workspace / "artifacts").iterdir())
    if len(artifacts) != 3:
        raise ValueError("Expected ZIP, manifest and SHA256SUMS before publication")
    existing = optional_json(
        f"repos/{config['releaseRepository']}/releases/tags/{urllib.parse.quote(job['tag'], safe='/')}"
    )
    if existing is not None and not existing.get("draft"):
        raise ValueError("Refusing to replace an already published release")
    # Auth is inherited from actions/checkout or gh's credential helper, never
    # embedded in a command, Git remote, emitted log or downloadable artifact.
    remote = f"https://github.com/{config['releaseRepository']}.git"
    git(source, "push", remote, f"HEAD:refs/tags/{job['tag']}")
    notes = workspace / "release-notes.md"
    changes = (
        "### 新增 | New\n\n"
        "* Windows x64 国服 ｢干员培养｣ 增加指定等级和自动补料，按列表顺序推进升级、精英化、技能与专精。 @rsdadada\n"
        "* 可按缺口合成、刷取、信用采购和红票兑换芯片助剂；采购与用药额度跨重启保存。 @rsdadada\n"
        "* 程序、资源与修复统一使用个人发行源，自动跟进官方正式版和公测版。 @rsdadada\n"
        if job["kind"] == "app"
        else "### 改进 | Improved\n\n"
        "* 同步官方资源并重新生成培养数据，保留个人培养增强层。 @rsdadada\n"
    )
    notes.write_text(
        f"MAA 培养增强版，基于 {job['upstreamVersion']}，增强修订 {job['revision']}。\n\n"
        "首次使用请将完整包解压到独立目录；关闭 MAA 后可从旧目录复制 config 和 data。\n\n"
        "此培养增强属于测试功能，实际游戏流程随日常使用验证。遇到问题可通过 ｢设置 - 问题反馈｣ 导出日志，再交给个人版维护者排查。\n\n"
        + changes
        + "\n### 其他 | Other\n\n"
        "* 发布前执行 Debug 资源校验、补料规划与预算回归；完整包还验证实际安装器的升级和修复。\n\n"
        f"程序和资源源码：{git(source, 'rev-parse', 'HEAD')}\n",
        encoding="utf-8",
    )
    command = [
        "gh",
        "release",
        "create",
        job["tag"],
        "--repo",
        config["releaseRepository"],
        "--draft",
        "--title",
        job["tag"],
        "--notes-file",
        str(notes),
    ]
    if "-beta." in job["upstreamVersion"] or job["kind"] == "resource":
        command.append("--prerelease")
    if existing is None:
        subprocess.run(command, check=True)
    subprocess.run(
        [
            "gh",
            "release",
            "upload",
            job["tag"],
            "--repo",
            config["releaseRepository"],
            "--clobber",
            *map(str, artifacts),
        ],
        check=True,
    )
    subprocess.run(
        [
            "gh",
            "release",
            "edit",
            job["tag"],
            "--repo",
            config["releaseRepository"],
            "--draft=false",
        ],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("discover", "prepare", "package", "publish")
    )
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--workspace", type=Path, default=Path("build/personal-release")
    )
    parser.add_argument("--job", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    config = read(root / "personal/release-config.json")
    if args.command == "discover":
        jobs = discover(root, config)
        if args.output:
            write(args.output, {"include": jobs})
        print(json.dumps({"include": jobs}, separators=(",", ":")))
    elif args.command == "prepare":
        prepare(root, config, read(args.job), args.workspace.resolve())
    elif args.command == "package":
        package(args.workspace.resolve())
    else:
        publish(root, config, args.workspace.resolve())


if __name__ == "__main__":
    main()
