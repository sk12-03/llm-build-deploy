import os
import json
import pathlib
import httpx

# ---- LLM config from env ----
LLM_BASE  = os.getenv("LLM_API_BASE")   # e.g. https://api.openai.com/v1
LLM_KEY   = os.getenv("LLM_API_KEY")    # your API key
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# ---- Prompting ----
SYSTEM = (
    "You generate minimal, production-ready static web apps.\n"
    "Return a single JSON object EXACTLY like: "
    '{"files":[{"path":"index.html","content":"..."}]}\n'
    "Only return JSON — no markdown, no explanations.\n"
    "Keep JavaScript inline in index.html unless the brief clearly needs extra files.\n"
    "Prefer no external CDNs unless requested."
)

USER_TPL = (
    "Brief: {brief}\n"
    "Output requirements:\n"
    "- Must include an index.html that completes the brief.\n"
    "- You may add extra files (e.g., styles.css) if helpful.\n"
    "- The JSON you return must be parseable by json.loads()."
)

# ---- GitHub Pages workflow we write into the generated repo ----
PAGES_YML = """name: Deploy to GitHub Pages
on:
  push:
    branches: ["main"]
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: "pages"
  cancel-in-progress: true
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: .
  deploy:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
"""

async def call_llm(brief: str) -> dict:
    """
    Call an OpenAI-compatible /chat/completions endpoint and return a Python dict.
    Raises on configuration or network errors so the caller can fail loudly.
    """
    if not (LLM_BASE and LLM_KEY):
        raise RuntimeError("LLM config missing (LLM_API_BASE / LLM_API_KEY).")

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER_TPL.format(brief=brief)},
        ],
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {LLM_KEY}"}

    async with httpx.AsyncClient(base_url=LLM_BASE, headers=headers, timeout=60) as client:
        r = await client.post("/chat/completions", json=payload)
        if r.status_code != 200:
            raise RuntimeError(f"LLM call failed: {r.status_code} {r.text}")

        data = r.json()
        # Extract assistant content and parse as JSON
        content = data["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except Exception as e:
            raise RuntimeError(f"LLM returned non-JSON content: {e}\n{content[:500]}")

async def materialize_app(local_dir: str, brief: str, attachments: list):
    """
    Generate the app files using the LLM. No fallback is used.
    If the LLM does not return files[], we raise, so /task returns 500.
    Also writes the GitHub Pages workflow file.
    """
    # Ensure target dir exists
    out_dir = pathlib.Path(local_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Call the LLM
    llm = await call_llm(brief)
    files = llm.get("files")
    if not files or not isinstance(files, list):
        raise RuntimeError("LLM did not return a 'files' array.")

    # Write all files
    for f in files:
        path = f.get("path")
        content = f.get("content")
        if not path or content is None:
            raise RuntimeError("Each file must have 'path' and 'content'.")
        p = out_dir / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    # Write the GitHub Pages workflow so the repo auto-deploys
    wf_dir = out_dir / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "pages.yml").write_text(PAGES_YML, encoding="utf-8")

    workflow_dir = pathlib.Path(local_dir) / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / "pages.yml").write_text(PAGES_YML, encoding="utf-8")
