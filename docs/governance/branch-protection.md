# Branch Protection Policy

Recommended GitHub branch protection settings for `main`.

## Required Settings

| Setting | Value | Reason |
|---------|-------|--------|
| **Require status checks to pass** | Enabled | Goblin Guardian CI must succeed before merge |
| **Required status check** | `guardian` (job name in ci.yml) | The Guardian job runs lint, format, publish validation, and tests |
| **Require branches to be up to date** | Enabled | Prevents merge conflicts and stale CI results |
| **Require pull request reviews** | At least 1 approval | Human review for all changes |
| **Dismiss stale reviews on new pushes** | Enabled | Re-review after changes |
| **Restrict force pushes** | Enabled (no force push) | History must not be rewritten on `main` |
| **Restrict deletions** | Enabled | `main` cannot be deleted |

## How to Configure

1. Go to **Settings → Branches** in the GitHub repository
2. Under **Branch protection rules**, click **Add rule**
3. Set **Branch name pattern** to `main`
4. Enable the settings above
5. Click **Create** / **Save changes**

## Notes

- The CI job name is `guardian` (defined in `.github/workflows/ci.yml` as `jobs.guardian`)
- If you rename the CI job, update the required status check name in branch protection
- Force pushes are blocked to prevent history rewriting, which could remove Guardian evidence
- These settings apply to all contributors, including repository admins (recommended)
