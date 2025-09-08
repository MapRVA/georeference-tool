# Import Scripts

This directory contains scripts for importing images from various sources into the georeferencing database.

## Directory Structure

```
scripts/
├── README.md           # This file
├── __init__.py         # Python package marker
└── importers/          # Individual source importers
    ├── __init__.py
    └── library_of_virginia.py
```

## Available Importers

### Library of Virginia (`library_of_virginia.py`)

Richmond Esthetic Survey (RES) scraper that handles the 3-level structure:
1. Hard-coded area links (A, B, C, D)
2. Parse area pages for neighborhood dropdown URLs  
3. Parse neighborhood pages for image data

**Usage:**
```bash
cd georef
uv run python scripts/importers/library_of_virginia.py \
    --area A \
    --dry-run
```

**Options:**
- `--area`: Area to scrape (A, B, C, D, or ALL)
- `--max-neighborhoods`: Limit neighborhoods per area (for testing)
- `--max-images`: Limit images per neighborhood (for testing)
- `--dry-run`: Show what would be imported without actually importing

**Examples:**
```bash
# Test run on Area A with limited data
uv run python scripts/importers/library_of_virginia.py \
    --area A \
    --max-neighborhoods 2 \
    --max-images 3 \
    --dry-run

# Import all of Area A
uv run python scripts/importers/library_of_virginia.py \
    --area A

# Import all areas (A, B, C, D)
uv run python scripts/importers/library_of_virginia.py \
    --area ALL \
    --dry-run
```

**What it scrapes:**
- **Area A**: Fan District, VCU area, Oregon Hill neighborhoods
- **Area B**: Jackson Ward, MCV area, Navy Hill, Carver, Gilpin Court  
- **Area C**: Capitol Square, Financial District, Shockoe Slip, Monroe Ward
- **Area D**: Church Hill, Shockoe Bottom, Shockoe Valley, Fulton

Each neighborhood becomes a Collection with historical survey photographs.

## Development Notes

- Each importer is a standalone Python script that sets up Django
- All scripts use the existing Django models (`Source`, `Collection`, `Image`)
- Be respectful with scraping - add delays between requests
- Always test with `--dry-run` and `--max-pages` first
- Check for duplicate images using the `permalink` field

## Adding New Importers

1. Create a new Python file in `importers/`
2. Follow the pattern of `library_of_virginia.py`
3. Include proper error handling and logging
4. Support dry-run mode for testing
5. Add documentation to this README

## Requirements

The importers require:
- `beautifulsoup4` - HTML parsing
- `requests` - HTTP requests
- Django project setup (automatically handled)