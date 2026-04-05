#!/usr/bin/env python3
import dataclasses
import datetime
import github
import logging
import pathlib
import re
from urllib.parse import urlparse

import requests
import zoneinfo


logger = logging.getLogger(__name__)
SOURCE_PAGE_URL = "https://www.asus.com/us/supportonly/prime%20b650m-k/helpdesk_bios/"


@dataclasses.dataclass
class BIOSRelease:
    date: datetime.date
    version: str
    title: str
    description: str
    download_path: str
    file_size: str
    sha256: str | None


def fetch() -> list[BIOSRelease]:
    url = "https://www.asus.com/support/api/product.asmx/GetPDBIOS?website=global&pdid=24005"
    rsp = requests.get(url, headers={"User-Agent": "Mozilla"})
    assert rsp.status_code == 200, f"HTTP {rsp.status_code} {rsp.reason}\n{rsp.text}"
    body = rsp.json()
    assert body["Status"] == "SUCCESS", rsp.text
    obj = body["Result"]["Obj"][0]
    assert obj["Name"] == "BIOS", rsp.text

    result = []
    for bios_file in obj["Files"]:
        description = bios_file.get("Description", "").strip('"').replace("<br/>", "\n")
        description = re.sub(
            r"\n*Before running the USB BIOS Flashback tool, please rename the BIOS file ?"
            r"\(A5458\.CAP\) using BIOSRenamer\.\n*",
            "",
            description,
        ).strip()
        raw_url = str(bios_file["DownloadUrl"]["Global"]).split("?", 1)[0]
        result.append(
            BIOSRelease(
                date=datetime.date.fromisoformat(bios_file["ReleaseDate"].replace("/", "-")),
                version=str(bios_file.get("Version", "")).strip(),
                title=str(bios_file.get("Title", "")).strip(),
                description=description,
                download_path=urlparse(raw_url).path or raw_url,
                file_size=str(bios_file.get("FileSize", "")).strip(),
                sha256=str(bios_file.get("sha256", "")).strip() or None,
            )
        )
    result.sort(key=lambda item: item.date)
    return result


def build_release_body(bios: BIOSRelease) -> str:
    lines = [
        f"Title: {bios.title}",
        f"Version: {bios.version or 'N/A'}",
        f"Release date: {bios.date.isoformat()}",
        f"File size: {bios.file_size or 'N/A'}",
    ]
    if bios.sha256:
        lines.append(f"SHA-256: {bios.sha256}")
    lines.extend(
        [
            f"Source page: {SOURCE_PAGE_URL}",
            f"ASUS download path: {bios.download_path}",
            "",
            "Description:",
            bios.description or "No description provided.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def process(bios: BIOSRelease) -> None:
    release = github.github_release_ensure(
        tag_name=bios.title.replace(" ", "_"),
        name=bios.title,
        timestamp=datetime.datetime.combine(
            bios.date,
            datetime.time(),
            tzinfo=zoneinfo.ZoneInfo("Asia/Shanghai"),
        ),
    )
    github.github_release_patch(release, name=bios.title, body=build_release_body(bios))
    github.github_release_delete_all_assets(release)


state_file = pathlib.Path("state.txt")


def load_state() -> set[str]:
    if not state_file.exists():
        return set()
    return {line for line in state_file.read_text().splitlines() if line}


def save_state(state: set[str]) -> None:
    state_file.write_text("".join(item + "\n" for item in sorted(state)))


def main() -> None:
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.INFO)
    state = load_state()
    new_count = 0

    for bios in fetch():
        if re.fullmatch(r"\d+", bios.version) and bios.title == "":
            bios.title = f"PRIME B650M-K BIOS {bios.version}"
        assert bios.title.strip(), bios

        if bios.title in state:
            logger.info("reconciling %s", bios.title)
        else:
            logger.info("processing %s", bios.title)
            new_count += 1

        process(bios)
        state.add(bios.title)
        save_state(state)

    logger.info(
        "Sync complete: %d BIOS releases tracked, %d new releases detected.",
        len(state),
        new_count,
    )


if __name__ == "__main__":
    main()
