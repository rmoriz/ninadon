# Version Management

Ninadon uses [Semantic Versioning](https://semver.org/) for version management.

## Current Version

The current version is **2.0.0**, representing the major architectural refactoring from a monolithic structure to a modular architecture.

## Version Format

Versions follow the `MAJOR.MINOR.PATCH` format:

- **MAJOR**: Incompatible API changes or major architectural changes
- **MINOR**: New functionality in a backward-compatible manner
- **PATCH**: Backward-compatible bug fixes

## Version History

- **2.0.0**: Major architectural refactoring - modular structure, comprehensive test suite
- **1.x.x**: Original monolithic version (now in `src/main_original.py`)

## Version Storage

Version information is stored in two places:

1. **`src/__init__.py`**: Contains `__version__`, `__author__`, and `__description__`
2. **`VERSION`**: Plain text file with just the version number

## Updating Versions

### Using the Version Management Script

```bash
# View current version
python scripts/bump_version.py

# Bump patch version (e.g., 2.0.0 -> 2.0.1)
python scripts/bump_version.py patch

# Bump minor version (e.g., 2.0.1 -> 2.1.0)
python scripts/bump_version.py minor

# Bump major version (e.g., 2.1.0 -> 3.0.0)
python scripts/bump_version.py major

# Set specific version
python scripts/bump_version.py set 2.1.5
```

### Manual Updates

If updating manually, ensure both files are updated:

1. Update `__version__` in `src/__init__.py`
2. Update the `VERSION` file content

## Version Display

The version is displayed in:

- **CLI**: `python -m src.main --version` (shows "Ninadon X.Y.Z")
- **Web Interface**: Version shown on the main page
- **Package Import**: `from src import __version__`

## Testing

Version functionality is tested in `tests/test_version.py`:

```bash
# Run version tests
PYTHONPATH=. pytest tests/test_version.py -v
```

## Release Process

1. **Update version** using the bump script or manually
2. **Run all tests** to ensure everything still works:
   ```bash
   PYTHONPATH=. pytest tests/ -v
   ```
3. **Commit changes** with version bump
4. **Tag the release** in git:
   ```bash
   git tag v2.0.0
   git push origin v2.0.0
   ```
5. **Update documentation** if needed

## Version Validation

The test suite validates:
- ✅ Version exists and is a string
- ✅ Version follows semantic versioning format
- ✅ VERSION file matches `__init__.py`
- ✅ Package metadata is complete
- ✅ Major version indicates refactored architecture (≥2.0.0)