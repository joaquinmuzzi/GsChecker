# GsChecker

## Feature Summary

- GearScore calculation.
- ICC 10/25 progression per boss (Normal and Heroic) using Armory statistics.
- Ruby Sanctum (Halion) progression via The Twilight Destroyer achievements (10/25, Normal/Heroic).
- Trial of the Crusader (TOC) 10/25 Normal/Heroic via Call of the Crusade / Grand Crusade achievements.

## Example

![Ejemplo del bot](docs/ejemplo.png)

## Requirements

- Python 3.10+
- Discord bot token

## Installation

1. Clone and enter the repository

```python
  1. git clone <https://github.com/yourusername/GsChecker.git>
  2. cd GsChecker
```

2. Create a .env file and add:

```python
DISCORD_TOKEN=your_token_here
```

3. Install dependencies

### Option A: Script

```Python
./run.sh
```

### Option B: Pip

```Python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

### Option C: Poetry

```Python
poetry install
poetry run python main.py
```

#### Usage

Prefix: `/`

##### Commands

`/p <name>`: general summary (GS, ICC, RS, enchants/gems, and links).

`/ptoc <name>`: shows only TOC 10/25 NM/HC achievements.

### Code Reuse

This project is based on the logic and achievement ID mappings from the WarmaneProfileParser project (MIT).

The original repository is not included in this project; only ideas and achievement mapping data were reused.

Original repository:
<https://github.com/Ridepad/WarmaneProfileParser>

Original project license (MIT):

```bash
MIT License

Copyright (c) 2020 Ridepad

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
