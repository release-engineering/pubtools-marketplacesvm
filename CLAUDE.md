# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pubtools-marketplacesvm is a CLI tool for publishing VM images (AMI, VHD) to cloud marketplaces (AWS, Azure). Part of Red Hat's release-engineering publishing toolchain.

## Commands

### Testing
```bash
# Run all tests (uses shared tox environment)
tox -e py310      # or py311, py312, py313

# Run a single test file
tox -e py310 -- tests/push/test_push.py

# Run a single test
tox -e py310 -- tests/push/test_push.py::test_name -k "test_name"

# Run with verbose output
tox -e py310 -- -vv tests/push/test_push.py
```

### Linting & Formatting
```bash
tox -e lint         # Check: black, flake8, isort
tox -e autoformat   # Fix: black + isort
tox -e mypy         # Type checking
```

### Style Rules
- Line length: 100
- Black with `-S` (no string normalization), target py310
- isort with `--profile black`
- flake8 ignores: D100, D104, D105 (missing docstrings for modules/packages); tests also ignore D101, D102, D103, D107

### Other
```bash
tox -e docs         # Build Sphinx docs
tox -e security     # Bandit + safety checks
tox -e coverage     # HTML/XML coverage reports
```

## Architecture

### Source Layout
All source lives under `src/pubtools/_marketplacesvm/` (namespace package pattern via `find_namespace_packages`).

### Task System
Each CLI command is a **task** class inheriting from `MarketplacesVMTask` (in `task.py`) which provides argument parsing, logging, and a `run()` entry point. Tasks compose behavior by mixing in **service classes** (`CloudService`, `CollectorService`, `StarmapService`, `AwsRHSMClientService`) that each inject their own CLI arguments and service accessors.

Entry points in `setup.py` map CLI commands to `entry_point()` functions in each task's `__init__.py`.

### Four CLI Commands
| Command | Task Class | Purpose |
|---------|-----------|---------|
| `pubtools-marketplacesvm-push` | `CombinedVMPush` | Combined marketplace + community push |
| `pubtools-marketplacesvm-marketplace-push` | `MarketplacesVMPush` | Marketplace-only push |
| `pubtools-marketplacesvm-community-push` | `CommunityVMPush` | Community-only push |
| `pubtools-marketplacesvm-delete` | `VMDelete` | Delete/unpublish images |

### Step Decorator
The `@step` decorator (`step.py`) wraps workflow methods with logging, timing, and skip logic. It handles both synchronous returns and `Future`/generator patterns from `more_executors`.

### Cloud Providers
`cloud_providers/base.py` defines `CloudProvider[T, C]` (generic abstract base) and `CloudCredentials` (frozen attrs class). Concrete implementations: `AWSProvider` (`aws.py`) and `AzureProvider` (`ms_azure.py`). Factory method: `get_provider()` dispatches by push item type.

### Key Dependencies
- **pushsource** / **pushcollector**: Load push items and record push results
- **starmap-client**: Query StArMap for image destination mappings
- **cloudpub** / **cloudimg**: Cloud publishing and image management libraries
- **more_executors**: Provides Futures-based concurrency patterns

## Testing Patterns

- 100% code coverage is enforced (`.coveragerc` `fail_under = 100`)
- Tests use `requests-mock` for HTTP mocking, not live services
- `tests/conftest.py` has session-scoped autouse fixtures that set `PYTHONHASHSEED`, mock HOME, reset pushsource, and inject a `FakeCollector`
- `CommandTester` (in `tests/command.py`) simulates CLI invocations by calling `entry_point()` directly
- Test data fixtures live in `tests/data/`
