# GitHub hardening for the public repo

Apply with `gh` (OWNER/REPO = the public repo). Idempotent.

```bash
# merge settings: squash only, auto-merge, tidy branches
gh api -X PATCH repos/OWNER/REPO -F allow_auto_merge=true -F allow_squash_merge=true \
  -F allow_merge_commit=false -F allow_rebase_merge=false -F delete_branch_on_merge=true \
  -F has_wiki=false -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=PR_BODY

# secret scanning + push protection
gh api -X PATCH repos/OWNER/REPO --input - <<'JSON'
{"security_and_analysis":{"secret_scanning":{"status":"enabled"},
 "secret_scanning_push_protection":{"status":"enabled"}}}
JSON

# Actions: read-only token, can't approve PRs
gh api -X PUT repos/OWNER/REPO/actions/permissions/workflow \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false

# main: PRs only, required checks, applies to admins too
gh api -X PUT repos/OWNER/REPO/branches/main/protection --input - <<'JSON'
{"required_status_checks":{"strict":false,"contexts":["leakguard","gitleaks","tests"]},
 "enforce_admins":true,
 "required_pull_request_reviews":{"required_approving_review_count":0},
 "restrictions":null,
 "required_linear_history":true,
 "allow_force_pushes":false,"allow_deletions":false,
 "required_conversation_resolution":true}
JSON
```

The LEAKGUARD_DENYLIST secret (Actions and Dependabot) is set by the private overlay's `bin/sync-denylist`.
