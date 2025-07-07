# TUI JXL Converter

![Python 3.6+](https://img.shields.io/badge/python-3.6+-blue.svg)
![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)
![Made with Curses](https://img.shields.io/badge/made%20with-curses-green.svg)

<!-- create a short GIF showcasing the UI and replace this placeholder -->
![TUI JXL Converter Demo](https://via.placeholder.com/800x450.png?text=placeholder)

A terminal-based user interface (TUI) for browsing, selecting, and converting images to the JPEG XL (`.jxl`) format. It's designed to be fast, interactive, and powerful, giving you full control over your batch conversions without leaving the terminal.

This tool is a single Python script built on the standard `curses` library and is distributed as free and open-source software.

## Why TUI JXL Converter?

While a simple shell loop like `for f in *.jpg; do ...` works, it lacks interactivity. You can't easily skip files, adjust quality on the fly, or handle failures gracefully. On the other hand, a full graphical application can be slow and overkill.

This TUI provides the best of both worlds:
-   **The speed and directness** of a command-line tool.
-   **The visual feedback and interactivity** of a GUI.

## Features

-   **Interactive File Browser**: Navigate your image files with smooth, buffered scrolling and full-line highlighting.
-   **Real-time Progress**: A dynamic header shows detailed progress during conversions, including files processed, total space saved, and elapsed time.
-   **Non-Blocking Conversions**: The UI remains fully responsive while conversions run in the background.
-   **Powerful Configuration**: Interactively set `cjxl` quality and effort, toggle recursive search, manage original file deletion, and specify a custom output directory.
-   **Smart "Sanitize & Retry"**: Automatically prompts to clean and re-convert any files that failed, using ImageMagick to strip problematic metadata.
-   **Advanced Filtering**: Instantly toggle a view to show only the files that have failed to convert, making it easy to diagnose issues.
-   **Conflict Resolution**: Automatically renames output files to prevent overwriting existing ones.
-   **Debug Logging**: Optional logging to a local file for easy troubleshooting.

## Requirements

#### Required
- **Python 3.6+**: No external Python packages are needed.
- **`cjxl`**: The command-line encoder from [`libjxl-tools`](https://github.com/libjxl/libjxl).
  - **On Debian/Ubuntu:** `sudo apt install libjxl-tools`
  - **On macOS (Homebrew):** `brew install jpeg-xl`
  - **On Windows (Scoop):** `scoop install libjxl`

#### Optional
- **ImageMagick**: Required for the **"Sanitize & Retry"** feature.
  - **On Debian/Ubuntu:** `sudo apt install imagemagick`
  - **On macOS (Homebrew):** `brew install imagemagick`
  - **On Windows (Scoop):** `scoop install imagemagick`

## Installation

1.  **Get the script:**
    -   Clone the repository:
        ```bash
        git clone https://github.com/your-username/your-repo-name.git
        cd your-repo-name
        ```
    -   Or just download the `convertjxl.py` file directly.

2.  **Make it executable (optional but recommended):**
    ```bash
    chmod +x convertjxl.py
    ```

## Usage

Run the script from your terminal.

-   **To process files in the current directory:**
    ```bash
    ./convertjxl.py
    ```

-   **To process files in a specific directory:**
    ```bash
    ./convertjxl.py /path/to/your/images
    ```

> **:warning: A Note on Deleting Originals**
>
> The `(D)elete Originals` feature is a destructive operation. It permanently deletes the source file after a *successful* conversion. While it will prompt for confirmation before the first conversion in a session, be absolutely sure you have backups if your data is important.

## Interface and Keybindings

| Keys                    | Action                                                                   | Details                                                                                                                                  |
| ----------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **Navigation**          |                                                                          |                                                                                                                                          |
| `↑` / `k`               | Move Up                                                                  | Move the cursor up one line.                                                                                                             |
| `↓` / `j`               | Move Down                                                                | Move the cursor down one line.                                                                                                           |
| `PageUp` / `PageDown`   | Scroll Page                                                              | Scroll up or down by a full page.                                                                                                        |
| `g` / `G`               | Go to Top / Bottom                                                       | Instantly jump to the first or last file in the list.                                                                                    |
| **File Selection**      |                                                                          |                                                                                                                                          |
| `Space`                 | Select / Deselect                                                        | Toggle selection for the file under the cursor. Selected files are marked with a `*`.                                                    |
| `a` / `A`               | Select All / None                                                        | Press `a` to select all visible files, `A` to deselect all files.                                                                        |
| **Conversion**          |                                                                          |                                                                                                                                          |
| `Enter`                 | **Start Conversion**                                                     | Begins converting all selected files using the current settings.                                                                         |
| `ESC` / `q`             | Quit                                                                     | Exits the application. Prompts for confirmation if a conversion is in progress.                                                          |
| **Configuration (Toggles & Settings)** |                                                                        |                                                                                                                                          |
| `Q`                     | Set **Q**uality                                                          | Opens a dialog to set the JPEG XL quality (1-100). Default: `90`.                                                                          |
| `E`                     | Set **E**ffort                                                           | Opens a dialog to set the encoding effort (1-9). Higher is slower but may produce smaller files. Default: `7` (Squirrel).                |
| `R`                     | Toggle **R**ecursive                                                     | Toggles recursive directory scanning on or off and reloads the file list.                                                                |
| `D`                     | Toggle **D**elete Originals                                              | Toggles whether original files are deleted after a *successful* conversion. See warning above.                                           |
| `O`                     | Set **O**utput Directory                                                 | Opens a dialog to set a custom output directory. Leave blank to save `.jxl` files in the same directory as their source.               |
| `F`                     | **F**ilter Failed                                                        | Toggles the view to show only files that have failed conversion. Only appears if there are failed files.                               |
| `B`                     | Toggle **B**ug Log                                                       | Toggles debug logging to `jxl_converter_debug.txt`. Useful for troubleshooting.                                                          |
| **System**              |                                                                          |                                                                                                                                          |
| `F5`                    | Refresh                                                                  | Reloads the file list from the source directory.                                                                                         |

---

## Power User Guide

### The "Sanitize & Retry" Feature

-   **Problem:** Some images, especially those downloaded from the web, contain corrupted or non-standard metadata chunks that can cause `cjxl` to fail.
-   **Solution:** When a batch conversion finishes with failures, the script will ask if you want to "Sanitize & Retry". If you agree, it uses **ImageMagick** to perform a clean-copy operation (`magick input.jpg -strip output.png`). This creates a temporary, standard PNG file with all non-essential metadata removed.
-   **Result:** The script then attempts to convert this "sanitized" temporary file, which has a much higher chance of success.

### Output Directory Logic

-   **Default:** `./converted/`
-   **Custom Directory (Non-Recursive):** Set an output path with `(O)`. All converted files will be placed in that directory.
-   **Custom Directory (Recursive):** When `(R)`ecursive mode is on and a custom output directory is set, the original directory structure is mirrored inside your output directory.
    -   `source/subdir/image.png` -> `output/subdir/image.jxl`
-   **"Same as Source":** By setting the output directory to a blank value, all `.jxl` files will be saved directly alongside their original counterparts.

### Debugging

If you encounter issues, enable the debug log by pressing `B`. This will create a `jxl_converter_debug.txt` file in the directory where you launched the script. This log contains detailed information about queued tasks, `cjxl` commands, and any internal errors.

## Troubleshooting

-   **`cjxl: command not found`**: The script cannot find the JPEG XL encoder. Make sure `libjxl-tools` is installed and `cjxl` is in your system's `PATH`.
-   **"Terminal too small"**: The application requires a minimum terminal size. Please make your terminal window larger.
-   **"A curses error occurred..."**: This can happen if the terminal is resized too quickly. Simply restart the script.

## Contributing

Contributions are welcome! If you have a feature request, find a bug, or have a suggestion for improvement, please open a GitHub Issue. Pull requests are also encouraged.

## License

This project is licensed under the **GNU General Public License v3.0**.

This means you are free to use, modify, and distribute this software. However, if you distribute a modified version or a program that incorporates this code, you must also license your entire program under the GPLv3 and make the complete source code available. This "share-alike" principle ensures that the software and its derivatives will always remain free and open-source.

See the [LICENSE](LICENSE) file for the full license text.
