.PHONY: help deploy

help:
	@echo "make deploy   — git-pull deploy origin/main to the interview host + rebuild"
	@echo "                (override: INTERVIEW_HOST, INTERVIEW_SSH_KEY, INTERVIEW_BRANCH)"

# Deploy the current origin/main to the target host over SSH (no rsync).
deploy:
	./scripts/deploy.sh
