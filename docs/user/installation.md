# Installation Guide

## Windows

1. Go to the [GitHub Releases page](https://github.com/Syax89/DDDTachograph_Reader/releases/latest).
2. Download **`TachoReader-v<version>-windows-x64.zip`**.
3. Extract the ZIP file to a folder of your choice.
4. Double-click **`TachoReader.exe`** to launch.

> **Note**: Windows SmartScreen may show a warning because the executable is not code-signed. Click "More info" → "Run anyway" to proceed.

## macOS

1. Go to the [GitHub Releases page](https://github.com/Syax89/DDDTachograph_Reader/releases/latest).
2. Download **`TachoReader-v<version>-macos.dmg`**.
3. Open the disk image and drag `TachoReader.app` to Applications.
4. **Right-click** the `TachoReader` app and select **Open** (this bypasses Gatekeeper on first run).
5. If prompted, confirm you want to open the application.

> **Why right-click?** macOS Gatekeeper blocks unsigned applications. The right-click → Open method allows you to run the app after confirming.

## Linux (Flatpak, x86_64)

The Linux build ships as a Flatpak bundle. Install your distribution's `flatpak`
package first if Flatpak is not already available.

1. Go to the [GitHub Releases page](https://github.com/Syax89/DDDTachograph_Reader/releases/latest).
2. Download **`TachoReader-v<version>-linux-x86_64.flatpak`**.
3. Install and run it:

   ```bash
   flatpak install --user ./TachoReader-vX.Y.Z-linux-x86_64.flatpak
   flatpak run io.github.Syax89.TachoReader
   ```

   Replace `vX.Y.Z` with the version in the downloaded filename. For a CI build,
   use `./TachoReader-linux-x86_64.flatpak` instead.

The application ID is `io.github.Syax89.TachoReader`. The bundle is
self-contained — Python, Tk and every Python dependency are inside it — and only
the `org.freedesktop.Platform` 25.08 runtime is fetched, from Flathub, as its
dependency. There is one bundle per release and it is **x86_64 only**: no
aarch64/ARM build exists.

> **Availability:** the Flatpak is not part of the already-published `v2.7.1`
> release. It is available now as a build artifact from the branch CI runs, and
> as a proper release asset from the next `v*` tag that includes the Linux
> packaging job. See [Downloading a build from CI](#downloading-a-build-from-ci)
> below and the [CI section of the README](../../README.md#continuous-integration).

**Sandbox:** the app gets read/write access to your home directory and no
network access, so `.ddd` files and exports work inside your home. Files
elsewhere (USB sticks, `/mnt`, `/run/media`) need an explicit override, for
example:

```bash
flatpak override --user --filesystem=/run/media/$USER io.github.Syax89.TachoReader
```

**Wayland:** Tk only talks X11, so on a Wayland session the app runs through
XWayland (`xorg-xwayland`, shipped by default by current desktops).

**Updates:** the project is not listed on Flathub and is **not updated
automatically** — download and install a
newer release file when you want to update. It is an unsigned local bundle, so
Flatpak installs it as a sideload rather than from a verified remote.

### Downloading a build from CI

If the release page has no Flatpak yet, a recent build can be taken from the
Actions tab: open the **Build TachoReader** run for the branch or commit you
want, then download the `TachoReader-linux-x86_64` artifact. Extract the artifact
ZIP: it contains `TachoReader-linux-x86_64.flatpak`, which you can install with
`flatpak install --user ./TachoReader-linux-x86_64.flatpak`. Windows/macOS
artifacts hold frozen build output rather than release zip/dmg installers.
Artifacts expire after a retention period and
downloading them may require a GitHub login. See
[Build artifacts vs release assets](../developer/testing.md#build-artifacts-vs-release-assets)
for the differences between CI artifacts and release assets.

## From Source (Developers)

If you prefer to run the tool from Python source:

```bash
git clone https://github.com/Syax89/DDDTachograph_Reader.git
cd DDDTachograph_Reader
pip install -r requirements.txt
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `cryptography` | Digital signature verification (ERCA/MSCA certificate chain) |
| `reportlab` | PDF report generation |
| `openpyxl` | Excel file export (.xlsx) |
| `tkinterdnd2` | Dropping a `.ddd` file onto the window (optional: the GUI starts without it, DnD disabled) |
| `pytest` | Test suite (development only) |
| `pyinstaller` | Building the standalone executable (development only) |

The GUI is built on Python's built-in `tkinter`; the only extra GUI package is the optional `tkinterdnd2`, which adds drag & drop of a file onto the window and is disabled silently when it (or its platform binary) is unavailable. Parsing itself has **no third-party dependencies**: `cryptography`, `reportlab`, and `openpyxl` are only needed for signature verification and PDF/Excel export.

**Python 3.10 or later is required.**

### Launching

```bash
# GUI
python app/gui.py

# CLI
python app/main.py file.ddd
```

## Verification

The commands below check a **source checkout**; they do not apply to the
packaged builds. After installation, verify everything works:

```bash
python app/main.py --help
```

Or with the advanced CLI:

```bash
python app/cli.py --help
```

The help text should display the available options and example commands without errors.

For the released builds, verify the installed app instead:

- **Linux Flatpak** — `flatpak run io.github.Syax89.TachoReader --version`
  prints the version, then launch it once from the desktop menu or with
  `flatpak run io.github.Syax89.TachoReader` to confirm the window opens.
- **Windows / macOS** — start `TachoReader.exe` / `TachoReader.app` and open a
  `.ddd` file to check the installed GUI.
