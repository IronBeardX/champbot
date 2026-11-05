# Merging a PR

This repo keeps a linear `main`: every merge is a fast-forward, never a merge commit or a squash. The PR's commits land on `main` exactly as written, so the commit history is the project history — anyone can read `git log --oneline main` as the story of how the codebase got here, one small, Conventional-Commits step at a time.

## Before merging

- CI is green on the PR's current head.
- The owner approved the PR in chat (not inferred from silence or from an earlier approval of a different version).
- The branch doesn't need a rebase, or it already got one (see below).

## 1. Rebase onto `main`

```sh
git fetch origin
git rebase origin/main
```

- **Clean rebase, no conflicts**: push and wait for CI again.
  ```sh
  git push --force-with-lease
  ```
- **Conflicts, or `main` moved in a file this PR also touches** (source, tests, config): resolve them, then push and get fresh owner approval before merging — a rebase can silently change what the PR does.
- **Clean rebase where the only overlap is docs** (`docs/`, `*.md`): push and wait for CI, then double-check anything position-sensitive still reads right (e.g. a decision number in `docs/decisions.md`).

## 2. Clean up the history

The PR should read as a story, one commit per logical step:

```sh
git rebase --autosquash origin/main
```

Fold any `fixup!` or stray "address review comment" commits into the step they belong to. The final tree must be identical to before the cleanup (`git diff <old-head> <new-head>` is empty) — this only reshapes history, it never changes the result. Push and wait for CI once more.

## 3. Fast-forward merge

```sh
git push origin HEAD:main
```

This only succeeds if it's a fast-forward — i.e., `main` hasn't moved since the last rebase. If it's rejected, go back to step 1 and rebase again; never force-push over `main`.

Then:

```sh
git push origin --delete <branch>
```

## Why this strategy, and not squash or merge commits

- **Squash** would throw away the commit-by-commit story the PR was reviewed as, collapsing a deliberate sequence of small steps into one opaque commit.
- **Merge commits** add a node with no content of its own, and make `git log` and `git bisect` harder to follow on a project this size, for no benefit a solo-reviewed, atomic-issue workflow needs.
- **Fast-forward** keeps `main` exactly equal to some PR branch's tip at every point in its history — there's never a "merge" state that didn't exist as a real, tested branch.

## After the merge

Every push to `main` deploys the Worker (see the root `README.md`'s Deploy section). Confirm the deploy job on the merge commit went green, then check the production URL is reachable (`/health`, and `/` if the frontend changed) before considering the issue done.
