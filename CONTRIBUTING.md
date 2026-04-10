# Contribution guidelines

Contributing to this project should be as easy and transparent as possible,
whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## GitHub is used for everything

GitHub is used to host code, to track issues and feature requests, as well as
accept pull requests.

1. Fork the repo and create your branch from `main`.
2. If you've changed something, update the documentation.
3. Make sure your code lints (using ruff).
4. Test your contribution.
5. Issue that pull request!

## Development setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements_test.txt
```

## Running tests

```bash
pytest tests/ -v
```

## Pre-commit

This repository uses [pre-commit](https://pre-commit.com/) for code quality checks:

```bash
pre-commit install
pre-commit run --all-files
```

## Any contributions you make will be under the MIT Software License

When you submit code changes, your submissions are understood to be under the
same [MIT License](http://choosealicense.com/licenses/mit/) that covers the
project.

## Report bugs using GitHub's [issues](https://github.com/k3mpaxl/connectbox_integration/issues)

GitHub issues are used to track public bugs. Report a bug by
[opening a new issue](https://github.com/k3mpaxl/connectbox_integration/issues/new).

## Write bug reports with detail

Great bug reports tend to have:

- A quick summary and/or background
- Steps to reproduce (be specific!)
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening)
