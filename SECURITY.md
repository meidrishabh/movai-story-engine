# Security Policy

## Supported versions

MovAI is currently under active development. Security fixes are applied to the latest version on the `master` branch.

Older commits and development branches may not receive security fixes.

## Reporting a vulnerability

Please do not report security vulnerabilities in a public issue, pull request, or discussion.

Use GitHub's private vulnerability reporting feature for this repository, if enabled. If it is unavailable, contact the repository owner privately through GitHub and include:

- A clear description of the vulnerability
- The affected file, endpoint, or component
- Steps to reproduce the issue
- The potential impact
- Any suggested mitigation

Please avoid including secrets, personal data, or production credentials in the report.

We will acknowledge valid reports, investigate them, and coordinate disclosure after a fix is available.

## Security expectations for local development

- Never commit `.env` files, API keys, database passwords, SSH private keys, or access tokens.
- Keep PostgreSQL and other local services bound to trusted interfaces.
- Use separate development credentials rather than production credentials.
- Rotate any credential that may have been exposed.

## Story content and LLM providers

Story text is sent to the configured LLM provider during analysis. Free-tier hosted models may log prompts or use them to improve the vendor's products. Use them only with test or non-confidential stories, and use a paid or local provider for real manuscripts. Never paste API keys into issues, chats or commits; keep them in `backend/.env`, and rotate a key if it may have been exposed.
