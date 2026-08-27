# Security recommendations

- Do NOT commit secrets (API keys, session IDs, passwords) into the repository.
- Use environment variables for secrets. Example (bash):
  export POESESSID=your_session_id
  export CURRENT_LEAGUE_ID=16

- If you accidentally committed secrets, rotate/revoke them immediately and remove them from git history (use `git filter-repo` or BFG).

- Run local scans before making the repository public:
  - gitleaks detect --source .
  - detect-secrets scan
  - bandit -r .
