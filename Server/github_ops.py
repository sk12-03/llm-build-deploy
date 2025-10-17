import os
import subprocess
from pathlib import Path
import httpx

def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v

async def enable_pages_workflow(owner: str, repo: str):
    """
    Enable GitHub Pages and set build_type=workflow (GitHub Actions).
    Works whether Pages exists or not.
    """
    token = _require_env("GITHUB_TOKEN")

    base = f"https://api.github.com/repos/{owner}/{repo}/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        # Check if Pages exists
        r = await client.get(base)
        if r.status_code == 404:
            # Create Pages site with workflow build
            r = await client.post(base, json={"build_type": "workflow"})
            if r.status_code not in (201, 202):
                raise RuntimeError(f"Enable Pages failed (create): {r.status_code} {r.text}")
        elif r.status_code == 200:
            # Update existing Pages site to workflow
            r2 = await client.put(base, json={"build_type": "workflow"})
            if r2.status_code not in (200, 204):
                raise RuntimeError(f"Enable Pages failed (update): {r2.status_code} {r2.text}")
        else:
            raise RuntimeError(f"Pages status check failed: {r.status_code} {r.text}")

def sh(cmd: str, cwd: str | None = None) -> str:
    res = subprocess.run(
        cmd,
        cwd=cwd,
        shell=True,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )
    if res.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\n{res.stdout}\n{res.stderr}")
    return res.stdout.strip()

def _create_repo_via_api(repo_name: str) -> None:
    token = _require_env("GITHUB_TOKEN")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {"name": repo_name, "private": False, "auto_init": False}
    r = httpx.post("https://api.github.com/user/repos", headers=headers, json=payload)
    # 201 = created, 422 = already exists
    if r.status_code not in (201, 422):
        raise RuntimeError(f"GitHub repo create failed ({r.status_code}): {r.text}")

def ensure_repo(repo_name: str, work_dir: str) -> None:
    """
    Make sure a remote repo exists, init a local git repo if needed,
    set the tokened remote, fetch remote main (if it exists),
    and check out local main in sync with origin/main.
    """
    user  = _require_env("GITHUB_USER")
    token = _require_env("GITHUB_TOKEN")

    os.makedirs(work_dir, exist_ok=True)

    # 1) Create remote repo via API if needed
    _create_repo_via_api(repo_name)

    # 2) Init local repo if needed & set identity
    if not Path(work_dir, ".git").exists():
        sh("git init -b main", cwd=work_dir)
        sh(f'git config user.name "{user}"', cwd=work_dir)
        sh(f'git config user.email "{user}@users.noreply.github.com"', cwd=work_dir)

    # 3) Ensure remote "origin" points to the tokened URL
    remote_url = f"https://{user}:{token}@github.com/{user}/{repo_name}.git"
    try:
        current = sh("git remote get-url origin", cwd=work_dir)
    except RuntimeError:
        current = ""

    remotes = ""
    try:
        remotes = sh("git remote", cwd=work_dir)
    except RuntimeError:
        pass

    if "origin" not in remotes:
        sh(f'git remote add origin "{remote_url}"', cwd=work_dir)
    elif remote_url not in current:
        # Replace origin if it points somewhere else
        sh("git remote remove origin", cwd=work_dir)
        sh(f'git remote add origin "{remote_url}"', cwd=work_dir)

    # 4) Sync local with remote main if it exists
    sh("git fetch origin main || true", cwd=work_dir)
    # If origin/main exists, start from it (so push can fast-forward)
    rc = subprocess.run("git rev-parse --verify origin/main", shell=True, cwd=work_dir).returncode
    if rc == 0:
        sh("git checkout -B main origin/main", cwd=work_dir)
    else:
        sh("git checkout -B main", cwd=work_dir)

def write_license_and_readme(work_dir: str, title: str, summary: str) -> None:
    Path(work_dir, "LICENSE").write_text(
        "MIT License\n\nCopyright (c) 2025\n\nPermission is hereby granted, free of charge, "
        "to any person obtaining a copy of this software and associated documentation files "
        "(the 'Software'), to deal in the Software without restriction, including without "
        "limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, "
        "and/or sell copies of the Software.\n",
        encoding="utf-8",
    )

    Path(work_dir, "README.md").write_text(
        f"# {title}\n\n{summary}\n\n## License\nMIT\n",
        encoding="utf-8",
    )

def add_pages_workflow(work_dir: str) -> None:
    wf_dir = Path(work_dir, ".github", "workflows")
    wf_dir.mkdir(parents=True, exist_ok=True)
    wf = wf_dir / "pages.yml"
    wf.write_text(
        """name: Deploy to GitHub Pages
on:
  push:
    branches: [ "main" ]
permissions:
  contents: read
  pages: write
  id-token: write
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/upload-pages-artifact@v3
        with:
          path: .
  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
""",
        encoding="utf-8",
    )

def git_push_and_get_commit(work_dir: str) -> str:
    """
    Commit changes and push. If rejected due to remote updates,
    rebase onto origin/main and push again.
    """
    sh("git add -A", cwd=work_dir)
    sh('git commit -m "auto: update" --allow-empty', cwd=work_dir)
    try:
        sh("git push -u origin main", cwd=work_dir)
    except RuntimeError:
        # Remote has new commits (e.g., from round 1). Rebase and push again.
        sh("git pull --rebase origin main || true", cwd=work_dir)
        sh("git push -u origin main", cwd=work_dir)
    return sh("git rev-parse HEAD", cwd=work_dir)

def repo_url(user: str, repo_name: str) -> str:
    return f"https://github.com/{user}/{repo_name}"

def pages_url(user: str, repo_name: str) -> str:
    return f"https://{user}.github.io/{repo_name}/"
