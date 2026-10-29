# Contributing to MovAI

Thank you for helping improve MovAI.

## Development workflow

1. Create a feature branch from `master`:

   ```text
   feature/short-description
   ```

2. Make focused changes related to one problem.
3. Run the relevant tests and checks locally.
4. Update documentation when behavior, configuration, or API contracts change.
5. Push the branch and open a pull request into `master`.

The `master` branch is protected. Direct pushes and force pushes should not be used.

## Backend guidelines

- Keep API routes, schemas, services, repositories, and workers separated by responsibility.
- Validate external input at the API boundary.
- Keep database access inside repository or service layers.
- Do not commit secrets or machine-specific configuration.
- Prefer small, testable changes over broad rewrites.

## Pull requests

Pull requests should explain:

- What changed
- Why it changed
- How it was tested
- Any database migration, environment variable, or deployment impact

Keep commits clear and avoid unrelated formatting changes. Resolve review conversations before merging.

## Reporting bugs

For ordinary bugs, open a GitHub issue with a minimal reproduction, expected behavior, actual behavior, and relevant logs. Do not include credentials or private user data.
