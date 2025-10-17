# server/main.py

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv


from .security import verify_secret
from .generator import materialize_app
from .github_ops import (
    ensure_repo,
    write_license_and_readme,
    git_push_and_get_commit,
    pages_url,
    repo_url,
    enable_pages_workflow,
)
# If you plan to notify, keep this; otherwise you can remove it
from .notifier import post_with_backoff  # optional, currently unused

# ---------------------------------------------------------------------
# Load .env and create FastAPI app BEFORE any route decorators
# ---------------------------------------------------------------------
load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")
APP = FastAPI(title="LLM Build & Deploy")

# ---------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------
class Attachment(BaseModel):
    name: str
    url: str

class TaskRequest(BaseModel):
    email: str
    secret: str
    task: str
    round: int = Field(ge=1)
    nonce: str
    brief: str
    checks: List[str] = []
    evaluation_url: str
    attachments: List[Attachment] = []

# ---------------------------------------------------------------------
# Health & info
# ---------------------------------------------------------------------
@APP.get("/")
def root():
    return {
        "status": "ok",
        "message": "LLM Build & Deploy API. POST /task with the JSON request to trigger a build.",
        "docs": "/docs",
    }

# ---------------------------------------------------------------------
# Main task endpoint
# ---------------------------------------------------------------------
@APP.post("/task")
async def accept_task(req: TaskRequest):
    # 1) Verify secret
    if not verify_secret(req.secret):
        raise HTTPException(status_code=401, detail="Invalid secret")

    # 2) Prepare working dir/repo name
    repo_name = req.task.strip()
    if not repo_name:
        raise HTTPException(status_code=400, detail="Empty task/repo name")

    work_dir = f"/tmp/{repo_name}"

    # 3) Ensure repo exists locally & remote origin is set
    ensure_repo(repo_name, work_dir)

    # 4) Generate files with LLM (no fallback)
    await materialize_app(work_dir, req.brief, [a.model_dump() for a in req.attachments])

    # 5) Optional: LICENSE + README
    try:
        write_license_and_readme(
            work_dir,
            title=repo_name,
            summary=f"Auto-generated for task '{repo_name}' (round {req.round})."
        )
    except Exception:
        pass

    # 6) ✅ Enable Pages (workflow) BEFORE first push
    await enable_pages_workflow(os.getenv("GITHUB_USER"), repo_name)

    # 7) First push -> triggers Pages workflow
    commit_sha = git_push_and_get_commit(work_dir)

    # 8) Build URLs to return
    user = os.getenv("GITHUB_USER")
    repo = repo_url(user, repo_name)
    pages = pages_url(user, repo_name)

    # 9) (Optional) notify evaluation_url
    # try:
    #     await post_with_backoff(req.evaluation_url, {
    #         "email": req.email,
    #         "task": req.task,
    #         "round": req.round,
    #         "nonce": req.nonce,
    #         "repo_url": repo,
    #         "commit_sha": commit_sha,
    #         "pages_url": pages,
    #     })
    # except Exception:
    #     pass

    return {
        "status": "ok",
        "email": req.email,
        "task": req.task,
        "round": req.round,
        "nonce": req.nonce,
        "repo_url": repo,
        "commit_sha": commit_sha,
        "pages_url": pages,
    }
