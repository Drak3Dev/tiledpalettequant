# Tiled Palette Quantization

Quantizes an image into tiles where every tile uses one of several small palettes, as on retro consoles
(NES, SNES, GBC, GBA, Mega Drive...).

This repository has two versions:

- **Web version** (the files in the repository root): the original JavaScript app by
  [rilden](https://github.com/rilden), from [rilden/tiledpalettequant](https://github.com/rilden/tiledpalettequant).
- **Desktop version in Python** ([`python/`](python/)): an offline port with a tkinter GUI that runs on Linux,
  macOS and Windows. Written by Claude (an AI model by [Anthropic](https://www.anthropic.com)).
  Documentation (in Russian): [python/README.md](python/README.md).

## Install the desktop version with one command

**Linux / macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/Drak3Dev/tiledpalettequant/main/python/install.sh | bash
```

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Drak3Dev/tiledpalettequant/main/python/install.ps1 | iex"
```

## Credits

- Original algorithm and web version: [rilden](https://github.com/rilden)
- Python port: Claude (Anthropic), for [Drak3Dev](https://github.com/Drak3Dev)

MIT license, see [LICENSE](LICENSE).
