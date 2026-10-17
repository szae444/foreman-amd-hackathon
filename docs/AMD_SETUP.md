# Getting Foreman onto the AMD MI300X: the critical path

The hackathon only counts projects that run "a meaningful part of its workload on AMD infrastructure", so this step decides prize eligibility. Allow about **45 minutes**, most of it waiting for the Gemma 4 31B weights (about 60 GB) to download on the droplet.

## 1. Accounts (about 5 min, you)
1. Join the **AMD AI Developer Program** (this is where the $100 credit comes from) and sign in to **AMD Developer Cloud** with the same account.
2. In **Billing**, add a payment method if the "Create GPU Droplet" button is greyed out. Credits are used first.

## 2. SSH key (about 1 min, you; skip if you have one)
In Git Bash on this PC:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub        # copy this whole line
```

## 3. Create the droplet (about 4 min, you)
**GPU Droplets → Create GPU Droplet**
- **Plan:** MI300X × 1 (about $1.99/h)
- **Image:** vLLM Quick Start
- **Region:** whichever has capacity
- **SSH key:** paste the line from step 2

Wait until the status shows **Active**, then copy the **public IP**.

## 4. Deploy (about 35 min, mostly unattended; Claude can do this once you share the IP)
From Git Bash in `D:\foreman`:
```bash
bash deploy/push_from_laptop.sh <droplet-ip>
```
This copies the project, stops the quick-start container, starts Gemma 4 31B on `vllm/vllm-openai-rocm` (bound to localhost only), builds the app on ROCm, trains PatchCore on the GPU (printing AUROC and timing), and serves the UI on `http://<droplet-ip>:8080`.

## 5. Measure (about 10 min)
```bash
ssh root@<ip> 'cd /opt/foreman && docker compose exec foreman python -m scripts.smoke_live'
ssh root@<ip> 'cd /opt/foreman && docker compose exec foreman python -m scripts.eval_live --per-fault 3'
```
Those numbers fill the `[__]` placeholders in the deck (slides 6–7) and the README results table.

## 6. Record the demo (follow `docs/DEMO_SCRIPT.md`)
Check that the badge shows `gemma-4-31B-it`, the compute rail shows the MI300X and VRAM, and there is no yellow mock banner.

## 7. Afterwards: destroy the droplet
Billing continues even while a droplet is powered off. **Destroy** it once the video is recorded. If judges need the live URL, keep it running until judging ends and watch the credit balance.

---
**If 31B is too slow on camera:** set `FOREMAN_LLM_MODEL=google/gemma-4-26B-A4B-it` in `.env` on the droplet and run `docker compose up -d`. It's a Mixture-of-Experts model with about 4B active parameters, so it's much faster.
**If something fails:** run `docker compose logs --tail 50 vllm` (or `foreman`) on the droplet and share the output.
