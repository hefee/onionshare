#!/usr/bin/env python3
import inspect
import os
from re import M
import sys
import hashlib
import shutil
import subprocess
import requests
import click

torbrowser_version_url = (
    "https://aus1.torproject.org/torbrowser/update_3/release/downloads.json"
)
torbrowser_root_url = "https://dist.torproject.org/torbrowser"

# Common paths
root_path = os.path.dirname(
    os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
)
working_path = os.path.join(root_path, "build", "tor")


def get_expected_platform_sha256(platform_filename, torbrowser_version):
    r = requests.get(
        f"{torbrowser_root_url}/{torbrowser_version}/sha256sums-signed-build.txt"
    )
    for checksum_item in r.content.decode().split("\n"):
        [checksum, filename] = checksum_item.split()
        if filename == platform_filename:
            return checksum

    return None


def get_latest_tor_version_urls(platform):
    r = requests.get(torbrowser_version_url)
    if r.status_code != 200 or platform not in r.json()["downloads"]:
        print("Tor browser version url not working")
        sys.exit(-1)

    torbrowser_version = r.json()["version"]
    platform_url = r.json()["downloads"][platform]["ALL"]["binary"]
    platform_filename = platform_url.split("/")[-1]
    expected_platform_sha256 = get_expected_platform_sha256(
        platform_filename, torbrowser_version
    )

    if not expected_platform_sha256:
        print(f"Expected sha256sum for {platform} not found")
        sys.exit(-1)

    return platform_url, platform_filename, expected_platform_sha256


def get_tor_windows(win_url, win_filename, expected_win_sha256):
    bin_filenames = ["tor.exe"]

    # Build paths
    win_path = os.path.join(working_path, win_filename)
    dist_path = os.path.join(root_path, "onionshare", "resources", "tor")

    # Make sure the working folder exists
    if not os.path.exists(working_path):
        os.makedirs(working_path)

    # Make sure Tor Browser is downloaded
    if not os.path.exists(win_path):
        print("Downloading {}".format(win_url))
        r = requests.get(win_url)
        open(win_path, "wb").write(r.content)
        win_sha256 = hashlib.sha256(r.content).hexdigest()
    else:
        print("Already downloaded: {}".format(win_path))
        win_data = open(win_path, "rb").read()
        win_sha256 = hashlib.sha256(win_data).hexdigest()

    # Compare the hash
    if win_sha256 != expected_win_sha256:
        print("ERROR! The sha256 doesn't match:")
        print("expected: {}".format(expected_win_sha256))
        print("  actual: {}".format(win_sha256))
        sys.exit(-1)

    # Extract the bits we need from the exe
    subprocess.Popen(
        [
            "7z",
            "e",
            "-y",
            win_path,
            "Browser\\TorBrowser\\Tor",
            "-o%s" % os.path.join(working_path, "Tor"),
        ]
    ).wait()
    subprocess.Popen(
        [
            "7z",
            "e",
            "-y",
            win_path,
            "Browser\\TorBrowser\\Data\\Tor\\geoip*",
            "-o%s" % os.path.join(working_path, "Data"),
        ]
    ).wait()

    # Copy into the onionshare resources
    if os.path.exists(dist_path):
        shutil.rmtree(dist_path)
    os.makedirs(dist_path)
    for filename in bin_filenames:
        shutil.copyfile(
            os.path.join(working_path, "Tor", filename),
            os.path.join(dist_path, filename),
        )
    for filename in ["geoip", "geoip6"]:
        shutil.copyfile(
            os.path.join(working_path, "Data", filename),
            os.path.join(dist_path, filename),
        )

    # Fetch the built-in bridges
    update_tor_bridges()


def get_tor_macos(macos_url, macos_filename, expected_macos_sha256):
    # Build paths
    dmg_tor_path = os.path.join(
        "/Volumes", "Tor Browser", "Tor Browser.app", "Contents"
    )
    dmg_path = os.path.join(working_path, macos_filename)
    dist_path = os.path.join(root_path, "onionshare", "resources", "tor")
    if not os.path.exists(dist_path):
        os.makedirs(dist_path, exist_ok=True)

    # Make sure the working folder exists
    if not os.path.exists(working_path):
        os.makedirs(working_path)

    # Make sure the zip is downloaded
    if not os.path.exists(dmg_path):
        print("Downloading {}".format(macos_url))
        r = requests.get(macos_url)
        open(dmg_path, "wb").write(r.content)
        dmg_sha256 = hashlib.sha256(r.content).hexdigest()
    else:
        dmg_data = open(dmg_path, "rb").read()
        dmg_sha256 = hashlib.sha256(dmg_data).hexdigest()

    # Compare the hash
    if dmg_sha256 != expected_macos_sha256:
        print("ERROR! The sha256 doesn't match:")
        print("expected: {}".format(expected_macos_sha256))
        print("  actual: {}".format(dmg_sha256))
        sys.exit(-1)

    # Mount the dmg, copy data to the working path
    subprocess.call(["hdiutil", "attach", dmg_path])

    # Copy into dist
    shutil.copyfile(
        os.path.join(dmg_tor_path, "Resources", "TorBrowser", "Tor", "geoip"),
        os.path.join(dist_path, "geoip"),
    )
    shutil.copyfile(
        os.path.join(dmg_tor_path, "Resources", "TorBrowser", "Tor", "geoip6"),
        os.path.join(dist_path, "geoip6"),
    )
    shutil.copyfile(
        os.path.join(dmg_tor_path, "MacOS", "Tor", "tor.real"),
        os.path.join(dist_path, "tor"),
    )
    os.chmod(os.path.join(dist_path, "tor"), 0o755)
    shutil.copyfile(
        os.path.join(dmg_tor_path, "MacOS", "Tor", "libevent-2.1.7.dylib"),
        os.path.join(dist_path, "libevent-2.1.7.dylib"),
    )

    # Eject dmg
    subprocess.call(["diskutil", "eject", "/Volumes/Tor Browser"])

    # Fetch the built-in bridges
    update_tor_bridges()


def get_tor_linux64(linux64_url, linux64_filename, expected_linux64_sha256):
    # Build paths
    tarball_path = os.path.join(working_path, linux64_filename)
    dist_path = os.path.join(root_path, "onionshare", "resources", "tor")

    # Make sure dirs exist
    if not os.path.exists(working_path):
        os.makedirs(working_path, exist_ok=True)

    if not os.path.exists(dist_path):
        os.makedirs(dist_path, exist_ok=True)

    # Make sure the tarball is downloaded
    if not os.path.exists(tarball_path):
        print("Downloading {}".format(linux64_url))
        r = requests.get(linux64_url)
        open(tarball_path, "wb").write(r.content)
        tarball_sha256 = hashlib.sha256(r.content).hexdigest()
    else:
        tarball_data = open(tarball_path, "rb").read()
        tarball_sha256 = hashlib.sha256(tarball_data).hexdigest()

    # Compare the hash
    if tarball_sha256 != expected_linux64_sha256:
        print("ERROR! The sha256 doesn't match:")
        print("expected: {}".format(expected_linux64_sha256))
        print("  actual: {}".format(tarball_sha256))
        sys.exit(-1)

    # Delete extracted tarball, if it's there
    shutil.rmtree(os.path.join(working_path, "tor-browser_en-US"), ignore_errors=True)

    # Extract the tarball
    subprocess.call(["tar", "-xvf", tarball_path], cwd=working_path)
    tarball_tor_path = os.path.join(
        working_path, "tor-browser_en-US", "Browser", "TorBrowser"
    )

    # Copy into dist
    shutil.copyfile(
        os.path.join(tarball_tor_path, "Data", "Tor", "geoip"),
        os.path.join(dist_path, "geoip"),
    )
    shutil.copyfile(
        os.path.join(tarball_tor_path, "Data", "Tor", "geoip6"),
        os.path.join(dist_path, "geoip6"),
    )
    shutil.copyfile(
        os.path.join(tarball_tor_path, "Tor", "tor"),
        os.path.join(dist_path, "tor"),
    )
    os.chmod(os.path.join(dist_path, "tor"), 0o755)
    shutil.copyfile(
        os.path.join(tarball_tor_path, "Tor", "libcrypto.so.1.1"),
        os.path.join(dist_path, "libcrypto.so.1.1"),
    )
    shutil.copyfile(
        os.path.join(tarball_tor_path, "Tor", "libevent-2.1.so.7"),
        os.path.join(dist_path, "libevent-2.1.so.7"),
    )
    shutil.copyfile(
        os.path.join(tarball_tor_path, "Tor", "libssl.so.1.1"),
        os.path.join(dist_path, "libssl.so.1.1"),
    )
    shutil.copyfile(
        os.path.join(tarball_tor_path, "Tor", "libstdc++", "libstdc++.so.6"),
        os.path.join(dist_path, "libstdc++.so.6"),
    )

    print(f"Tor binaries extracted to: {dist_path}")

    # Fetch the built-in bridges
    update_tor_bridges()


def update_tor_bridges():
    """
    Update the built-in Tor Bridges in OnionShare's torrc templates.
    """
    torrc_template_dir = os.path.join(
        root_path, os.pardir, "cli/onionshare_cli/resources"
    )
    endpoint = "https://bridges.torproject.org/moat/circumvention/builtin"
    r = requests.post(
        endpoint,
        headers={"Content-Type": "application/vnd.api+json"},
    )
    if r.status_code != 200:
        print(
            f"There was a problem fetching the latest built-in bridges: status_code={r.status_code}"
        )
        sys.exit(1)

    result = r.json()
    print(f"Built-in bridges: {result}")

    if "errors" in result:
        print(
            f"There was a problem fetching the latest built-in bridges: errors={result['errors']}"
        )
        sys.exit(1)

    for bridge_type in ["meek-azure", "obfs4", "snowflake"]:
        if bridge_type in result and result[bridge_type]:
            if bridge_type == "meek-azure":
                torrc_template_extension = "meek_lite_azure"
            else:
                torrc_template_extension = bridge_type
            torrc_template = os.path.join(
                root_path,
                torrc_template_dir,
                f"torrc_template-{torrc_template_extension}",
            )

            with open(torrc_template, "w") as f:
                f.write(f"# Enable built-in {bridge_type} bridge\n")
                bridges = result[bridge_type]
                # Sorts the bridges numerically by IP, since they come back in
                # random order from the API each time, and create noisy git diff.
                bridges.sort(key=lambda s: s.split()[1])
                for item in bridges:
                    f.write(f"Bridge {item}\n")


@click.command()
@click.argument("platform")
def main(platform):
    """
    Download Tor Browser and extract tor binaries
    """
    valid_platforms = ["win32", "win64", "macos", "linux64"]
    if platform not in valid_platforms:
        click.echo(f"platform must be one of: {valid_platforms}")
        return

    global platform_url, platform_filename, expected_platform_sha256
    (
        platform_url,
        platform_filename,
        expected_platform_sha256,
    ) = get_latest_tor_version_urls(platform)

    if platform == "win32":
        get_tor_windows(platform_url, platform_filename, expected_platform_sha256)
    elif platform == "win64":
        get_tor_windows(platform_url, platform_filename, expected_platform_sha256)
    elif platform == "macos":
        get_tor_macos(platform_url, platform_filename, expected_platform_sha256)
    elif platform == "linux64":
        get_tor_linux64(platform_url, platform_filename, expected_platform_sha256)
    else:
        click.echo("invalid platform")


if __name__ == "__main__":
    main()
