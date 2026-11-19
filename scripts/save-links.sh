#!/usr/bin/env bash
# After social.py announce: commit the post links it wrote into _posts, push, and rebuild Pages.
# Pushes made with the workflow token never start a Pages build (or social.yml) on their own.
set -euo pipefail
git add _posts
if git diff --cached --quiet; then echo "No new post links."; exit 0; fi
slugs=$(git diff --cached --name-only | xargs -n1 basename | sed 's/\.html$//' | paste -sd, -)
git -c user.name='github-actions[bot]' -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
  commit -qm "Link the social posts for $slugs"
git pull -q --rebase origin master && git push -q origin HEAD:master
gh api -X POST "repos/${GITHUB_REPOSITORY}/pages/builds" --silent
