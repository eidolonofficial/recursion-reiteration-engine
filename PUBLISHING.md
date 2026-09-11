# Publish a new Recursive Reiteration Engine repository

Target: `eidolonofficial/recursion-reiteration-engine`.

The helper is **create-only**. It never renames, transfers, forks, overwrites, or
force-pushes an existing repository. It publishes only the byte-verified source
allowlist, not local research files or inherited Git objects.

## Verify without network access

```sh
python -B -S scripts/publish.py
```

The manifest checks content consistency. It is not a cryptographic signature or
proof of the publisher's identity. Unlisted local files are not exported.

## Create the repository and push

The machine must have `git` and an authenticated `gh` whose account has permission
to create repositories for the target owner. For a public repository:

```sh
python -B -S scripts/publish.py --publish --public
```

Omit `--public` to create a private repository instead. Without `--publish`, no
remote change is attempted. The helper creates a temporary repository with one
root commit and uses `gh repo create OWNER/REPO --source ... --remote origin --push`.
GitHub CLI's authoritative command reference is `https://cli.github.com/manual/gh_repo_create`.
Publication is separate from model inference; it does not add an inference-service
dependency to the runtime.

A successful creation followed by a failed push can leave an empty remote. This
helper will not overwrite it on retry. Inspect the remote state before recovery.
It uses the configured Git commit identity if present, or a neutral local fallback.
Tests mock remote writes; they do not establish GitHub publication or permissions.

## Intentional source edits

```sh
PYTHONPATH=src python -B -S -m unittest discover -s tests -v
python -B -S scripts/make_manifest.py
python -B -S scripts/publish.py
```

Review the selected paths and regenerated manifest. Never regenerate it merely to
silence an unexplained integrity failure. Credentials, model weights, authority
databases, live traces, experiment data, and research corpora are not release input.

## Recreate the prepared local repository

```sh
git clone recursive-reiteration-engine.bundle recursive-reiteration-engine
```

The bundle contains only the standalone `main` root. The ZIP contains the same
checked source without `.git`. Both forms can be published with the helper above.
