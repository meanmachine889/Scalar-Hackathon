# HuggingFace Spaces Deployment Guide

This guide walks you through deploying the Incident Response Environment to Hugging Face Spaces.

## Prerequisites

- HF account at [huggingface.co](https://huggingface.co)
- HF CLI installed: `pip install huggingface-hub`
- Logged in: `huggingface-cli login` (paste your HF token)

## Step 1: Prepare Your Repository

Ensure your repo has the following **required files**:

```
incident-response-env/
├── openenv.yaml              ✅ (updated with full spec)
├── Dockerfile                ✅
├── requirements.txt          ✅
├── pyproject.toml            ✅
├── baseline.py               ✅ (now saves results.json)
├── validate.py               ✅ (new validation script)
├── README.md                 ✅
├── src/
│   ├── __init__.py
│   ├── models.py
│   ├── scenarios.py
│   ├── environment.py
│   ├── graders.py
│   └── server.py
├── hackathon/                (venv — exclude from git)
└── .gitignore                (add: hackathon/, __pycache__/, *.pyc, results.json)
```

## Step 2: Test Locally

Before pushing to HF, validate everything works:

```bash
# 1. Start the environment server
uvicorn src.server:app --reload

# 2. In another terminal, run the validator
python validate.py

# 3. Run baseline (expert mode, no API key needed)
python baseline.py --expert

# 4. Check results
cat results.json
```

All should show success. If any ❌ errors, fix them before deploying.

## Step 3: Create a Hugging Face Space

1. Go to [huggingface.co/new-space](https://huggingface.co/new-space)
2. Fill in:
   - **Owner**: Your HF username
   - **Space name**: `incident-response-env` (or your preferred name)
   - **License**: `mit` (or your choice)
   - **Space SDK**: `Docker`
   - **Visibility**: `Public` (for hackathon evaluation)
3. Click **Create Space**

You'll be redirected to the Space's repository page.

## Step 4: Push Your Code to HF Spaces

Clone the Space repo and add your code:

```bash
# Clone the empty Space repo (replace YOUR_USERNAME and SPACE_NAME)
git clone https://huggingface.co/spaces/YOUR_USERNAME/incident-response-env
cd incident-response-env

# Copy your code (from local repo) into this directory
# Ensure: Dockerfile, openenv.yaml, requirements.txt, src/, baseline.py, validate.py, README.md
#         .gitignore

# Commit and push
git add .
git commit -m "Initial commit: incident response environment"
git push origin main
```

The Space will **automatically build** from your Dockerfile.

## Step 5: Wait for Build Completion

- Go back to your Space on HF
- Watch the build logs under **Build Status**
- Once green ✅ (usually 5–10 minutes), your environment is live

## Step 6: Verify Deployment

Once built, test your live Space:

```bash
# Replace with your Space URL
SPACE_URL="https://your-username-incident-response-env.hf.space"

# Test health
curl ${SPACE_URL}/health

# Test /tasks
curl ${SPACE_URL}/tasks

# Test /reset
curl -X POST ${SPACE_URL}/reset \
  -H "Content-Type: application/json" \
  -d '{"task_id": "easy_db_pool"}'
```

All should return 200 with JSON responses.

## Step 7: (Optional) Add OPENAI_API_KEY Secret

If you want to test the LLM baseline on your Space:

1. Go to **Space Settings** → **Secrets**
2. Add:
   - **Name**: `OPENAI_API_KEY`
   - **Value**: `sk-...` (your actual key)
   - **Visibility**: `Private`

Then you can run the LLM baseline on the Space (not just expert mode).

## Step 8: Finalize README for HF

Create a clear **README.md** (or update the one in your Space) with:

- Brief environment description
- Link to your GitHub repo (if applicable)
- Instructions to reset and run episodes
- Example curl commands
- Results: baseline scores

HF will display this at the top of your Space.

## Troubleshooting

### Build Failed
- Check the build logs for errors
- Common issue: missing dependencies in `requirements.txt`
- Fix and re-push: `git add . && git commit -m "Fix" && git push`

### Environment not responding
- HF Spaces has a 7-day inactivity timeout (apps get paused)
- Click **Restart** in the Space settings to wake it up
- For persistent hosting, use a more robust platform (AWS, Azure, etc.)

### OPENENV_API_KEY not working
- Double-check the secret was added to **Secrets**, not env file
- HF injects secrets at runtime; code just reads `os.getenv("OPENAI_API_KEY")`

## Pre-Submission Checklist

Before submitting your hackathon entry, verify:

- [ ] HF Space URL is live and public
- [ ] `/health` returns 200
- [ ] `/tasks` lists 3+ tasks
- [ ] `/reset` works and initializes episodes
- [ ] `/step` accepts actions and returns observations
- [ ] `/grade` returns scores between 0.0–1.0
- [ ] `baseline.py --expert` completes and creates `results.json`
- [ ] README clearly explains what the environment does
- [ ] `openenv.yaml` is spec-complete (check with `validate.py`)
- [ ] Dockerfile builds cleanly

## Support

- HF Spaces docs: https://huggingface.co/docs/hub/spaces
- OpenEnv spec: https://github.com/openenv/openenv
- For issues: check Space build logs and README validation

---

Good luck! 🚀
