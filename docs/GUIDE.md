# Getting started

mkjxl converts images to JPEG XL from the terminal. It needs `cjxl` from libjxl.

Install steps and the full key list are in the [README](../README.md).

## First run

Open the folder you started in:

```bash
mkjxl
```

Or name a folder:

```bash
mkjxl /path/to/images
```

If `cjxl` is missing, a dialog shows the install command for a package manager mkjxl can see. Run that command in a terminal, then press `s` to look again. On this dialog, `q` closes the dialog.

## Pick files

![mkjxl with one file selected](screenshot.png)

Space selects the highlighted file. `a` selects every visible file. You can also click a row. `A` clears the selection.

## Settings

Quality runs from 1 to 100. The default is 90. Effort runs from 1 to 9. The default is 7.

The output directory starts as `converted`. Recursive is off, so the list is only the top folder. Turn it on to include folders inside that folder.

Delete originals is off until you turn it on. The app asks before a batch that will delete source files, and it only deletes a file after `cjxl` succeeds.

## Convert

Press Enter, or use the Convert button. The status column on each row moves from Queued to Converting, then to Success or Failed.

## Where the files go

The default folder is `./converted`, relative to the directory you started mkjxl in. Clear the output field to write each `.jxl` next to its source file.

The [README](../README.md) has the rest of the path rules: one flat folder, mirrored folders when recursive is on, and `name-1.jxl` when the target name is already taken.

## Sanitize and retry

When a batch finishes with failures, mkjxl asks if you want to sanitize those files and try again. Press `S` to start that step yourself.

Sanitize rewrites the failed file as a plain PNG, then converts the PNG with your quality and effort. Pillow does the rewrite, and it is installed with mkjxl. ImageMagick (`magick`) is optional. mkjxl uses it only when Pillow cannot read the file.

Press `q` to quit. If a conversion is still running, the app asks first.
