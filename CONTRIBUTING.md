# Contributing

> [!NOTE]
> Please prefer English language for all communication.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager

## Setup

```sh
git clone https://github.com/YOUR_USERNAME/verse-translator.git
cd verse-translator
uv sync
```

This installs all dependencies including dev tools (ruff, pytest, mypy, lefthook).

Install git hooks:

```sh
uv run lefthook install
```

## How to Contribute

1. **Fork and Clone the Repository**

   ```sh
   git clone https://github.com/sc-localization/verse-translator.git
   cd verse-translator
   git remote add upstream https://github.com/sc-localization/verse-translator.git
   ```

2. **Create a New Branch**

   ```sh
   git checkout -b feature/short-description
   ```

3. **Make Changes**

   Implement your feature or fix the bug. Follow the coding style and add tests if necessary.

4. **Check Your Code**

   ```sh
   uv run ruff check .          # linting
   uv run ruff check --fix .    # linting with autofix
   uv run ruff format .         # formatting
   uv run mypy translator/      # type checking
   uv run pytest tests/         # tests
   ```

   Lefthook runs lint and format automatically on commit.

5. **Commit Changes**

   ```sh
   git add .
   git commit -m "feat: add new feature"
   ```

6. **Keep Your Branch Up to Date**

   ```sh
   git fetch upstream
   git rebase upstream/main
   ```

7. **Push and Create a Pull Request**

   ```sh
   git push -u origin feature/short-description
   ```

## Commit Messages

Follow the [Conventional Commits](https://conventionalcommits.org) specification:

```
<type>[optional scope]: <description>
```

### Allowed `<type>`

- `feat`: new feature
- `fix`: bug fix
- `perf`: performance improvement
- `refactor`: code change that is neither a feature nor a fix
- `docs`: documentation only changes
- `ci`: CI configuration changes
- `chore`: repository maintenance
- `style`: cosmetic code change
- `test`: adding or correcting tests
- `revert`: reverts previous commits

## Personal Config

Copy the example config and fill in your paths:

```sh
cp verse-translator.example.toml verse-translator.toml
```

`verse-translator.toml` is gitignored — it stores your local paths and is not committed.

If you have any questions, feel free to open an issue.
