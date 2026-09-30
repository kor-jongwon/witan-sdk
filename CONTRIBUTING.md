# Contributing

Thanks for helping. This repository is the public mirror of `sdk/python` in the WITAN platform repository.
Releases are cut from here, but changes are made in the platform repository and synced into this one. A pull
request here cannot be merged as-is: a maintainer ports it, and it arrives in the next sync with you credited.

## License of contributions

A contribution is made under this repository's MIT License ([LICENSE](LICENSE)). By contributing you also
agree that it may be incorporated into the WITAN platform (a private repository) as well as here.

Certify the [Developer Certificate of Origin 1.1](https://developercertificate.org) for every commit by
adding a sign-off line (`git commit -s`):

```
Signed-off-by: Your Name <you@example.com>
```

## Issues

- **Bugs:** use the bug report form. Include the version (`wtn --version`), Python version, OS, the call or
  command, what you expected, and what happened. Remove keys and tokens from logs.
- **Features:** describe the problem first, then the change you have in mind.
- **Security problems:** never in an issue. See [SECURITY.md](SECURITY.md).

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q tests          # offline unit tests
python -m build                    # sdist and wheel
```

The container image builds from the wheel:

```bash
python -m build --wheel
docker build -t witan-node:dev .
bash docker/smoke.sh witan-node:dev "$(python -c 'import witan_sdk; print(witan_sdk.__version__)')"
```

End-to-end tests run against a WITAN origin from the platform repository.

## Documentation

The documentation site is built with MkDocs Material, one version per release (`mike`):

```bash
pip install -r requirements-docs.txt
mkdocs serve
```

User-visible changes go in [CHANGELOG.md](CHANGELOG.md), under Added, Changed, Deprecated, Removed, Fixed or
Security. Anything under Changed says what users must do.

## Releases

A maintainer bumps the version in `pyproject.toml` and `src/witan_sdk/__init__.py`, then tags `vX.Y.Z` here.
[`publish.yml`](.github/workflows/publish.yml) then takes over:

1. It tests, then publishes to PyPI through Trusted Publishing. No token is stored anywhere.
2. It builds the `witan-node` image from the same wheel.
3. It pushes the image to GHCR with provenance, and copies the same digest to Docker Hub.
