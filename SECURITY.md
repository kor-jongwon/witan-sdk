# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub:
**[Report a vulnerability](https://github.com/kor-jongwon/witan-sdk/security/advisories/new)**, in this
repository's **Security** tab.

Do not open a public issue, pull request or discussion for a security problem.

Please include:

- the version (`wtn --version`, or the image tag and digest)
- what an attacker can do, and under which conditions
- the smallest reproduction you can share, with no real keys, tokens or wallet secrets in it
- whether you have told anyone else

## What happens next

- We aim to acknowledge a report within 5 business days, and to tell you then whether we can reproduce it.
- We fix confirmed issues in the latest minor release and publish a
  [GitHub security advisory](https://github.com/kor-jongwon/witan-sdk/security/advisories) with the
  fixed version. The [changelog](CHANGELOG.md) lists the fix under **Security**.
- We credit reporters in the advisory unless you ask us not to.

Please give us a reasonable time to ship a fix before you disclose anything publicly.

## Supported versions

Only the latest minor release receives fixes, including security fixes.

| Version | Supported |
|---|---|
| 0.21.x | yes |
| < 0.21 | no |

## Scope

In scope:

- the `witan-sdk` package on PyPI (the client, the `wtn` command line, `wtn serve` and bundles)
- the `witan-node` container image (`ghcr.io/kor-jongwon/witan-node`, `jongwon98/witan-node`)
- the Claude Code and Cursor plugins in this repository

Report problems with a WITAN origin (the hosted service) the same way. We route them to the service's
maintainers.

Out of scope: problems that need an already-compromised machine or leaked keys, and reports produced only by
automated scanners with no demonstrated impact.

## Handling keys safely

The SDK never transmits `WITAN_WALLET_KEY`: it signs locally. It checks every payment request against the
allowed asset, networks and price cap before signing. Keep agent keys (`km_...`), operator tokens (`wto_...`)
and node tokens in your secret store, not in code or images.
